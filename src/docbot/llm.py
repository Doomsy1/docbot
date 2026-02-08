"""LLM client -- async wrapper around Backboard.io's unified API."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

BACKBOARD_BASE_URL = "https://app.backboard.io/api"
DEFAULT_MODEL = "openai/gpt-4o-mini"


def _split_model(model: str) -> tuple[str, str]:
    """Map model id to Backboard (llm_provider, model_name).

    Backboard accepts canonical providers (openai/anthropic/google/...) with
    short model names, but OpenRouter-style model ids (e.g. `vendor/model`)
    must be sent as `llm_provider=openrouter` and full `model_name`.
    """
    known_providers = {
        "openai",
        "anthropic",
        "google",
        "meta",
        "mistral",
        "cohere",
        "xai",
        "deepseek",
        "groq",
        "openrouter",
    }
    if "/" not in model:
        return "openai", model
    provider, name = model.split("/", 1)
    if provider.lower() in known_providers:
        return provider, name
    # Treat unknown-prefixed IDs as OpenRouter catalog IDs.
    return "openrouter", model


# ---------------------------------------------------------------------------
# Streaming data types
# ---------------------------------------------------------------------------


@dataclass
class StreamDelta:
    """A single chunk from an SSE stream."""

    content: str | None = None
    finish_reason: str | None = None


@dataclass
class LLMClient:
    """Minimal async-friendly Backboard.io client using stdlib only."""

    api_key: str
    model: str = DEFAULT_MODEL
    max_tokens: int = 8192
    temperature: float = 0.3
    backoff_enabled: bool = True
    max_retries: int = 4
    base_backoff_seconds: float = 0.05
    adaptive_reduction_factor: float = 0.6
    max_concurrency: int = 6
    _sem: asyncio.Semaphore = field(init=False, repr=False)
    _failure_streak: int = field(default=0, init=False, repr=False)
    _stats_lock: asyncio.Lock = field(init=False, repr=False)
    _total_calls: int = field(default=0, init=False, repr=False)
    _retry_count: int = field(default=0, init=False, repr=False)
    # Backboard-specific
    _assistant_id: str | None = field(default=None, init=False, repr=False)
    _init_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self._sem = asyncio.Semaphore(max(1, self.max_concurrency))
        self._stats_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Header helpers
    # ------------------------------------------------------------------

    def _json_headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key, "Content-Type": "application/json"}

    def _form_headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    def _extract_supported_models(self, error_body: str) -> list[str]:
        """Parse Backboard unsupported-model errors into model ids."""
        text = error_body or ""
        if "Supported models:" not in text:
            return []
        match = re.search(r"Supported models:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
        if not match:
            return []
        tail = match.group(1).strip()
        # keep the first line only; API sometimes appends extra context
        tail = tail.splitlines()[0]
        candidates = [c.strip() for c in tail.split(",") if c.strip()]
        return candidates

    def _switch_to_supported_model(self, error_body: str) -> bool:
        """Switch self.model to a supported fallback if available."""
        supported = self._extract_supported_models(error_body)
        if not supported:
            return False
        fallback = next((m for m in supported if m != self.model), None)
        if fallback is None:
            # If parsing yields only the current (still failing) model, use safe default.
            fallback = DEFAULT_MODEL
        if fallback == self.model:
            return False
        old = self.model
        self.model = fallback
        # assistant is model-bound; force recreate with fallback model
        self._assistant_id = None
        logger.warning("Backboard model '%s' unsupported; falling back to '%s'.", old, fallback)
        return True

    def _switch_to_default_model(self, reason: str) -> bool:
        """Fallback to a known-good default model."""
        if self.model == DEFAULT_MODEL:
            return False
        old = self.model
        self.model = DEFAULT_MODEL
        self._assistant_id = None
        logger.warning("Backboard model '%s' failed (%s); falling back to '%s'.", old, reason, DEFAULT_MODEL)
        return True

    # ------------------------------------------------------------------
    # Backboard resource management
    # ------------------------------------------------------------------

    def _ensure_assistant_sync(self) -> str:
        """Lazily create a Backboard assistant on first use. Thread-safe."""
        with self._init_lock:
            if self._assistant_id:
                return self._assistant_id
            attempted_fallback = False
            while True:
                provider, model_name = _split_model(self.model)
                body = json.dumps({
                    "name": "docbot",
                    "description": "Documentation generator assistant",
                    "llm_provider": provider,
                    "llm_model_name": model_name,
                    "tools": [],
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"{BACKBOARD_BASE_URL}/assistants",
                    data=body,
                    headers=self._json_headers(),
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    self._assistant_id = data["assistant_id"]
                    return self._assistant_id
                except urllib.error.HTTPError as exc:
                    error_body = exc.read().decode("utf-8", errors="replace")
                    can_retry = (
                        not attempted_fallback
                        and (
                            ("not supported" in error_body.lower() and self._switch_to_supported_model(error_body))
                            or ("not a valid model id" in error_body.lower() and self._switch_to_default_model("invalid model id"))
                        )
                    )
                    if can_retry:
                        attempted_fallback = True
                        continue
                    raise RuntimeError(
                        f"Backboard assistant creation failed ({exc.code}): {error_body}"
                    ) from exc

    def _create_thread_sync(self) -> str:
        """Create a new Backboard thread."""
        assistant_id = self._ensure_assistant_sync()
        req = urllib.request.Request(
            f"{BACKBOARD_BASE_URL}/assistants/{assistant_id}/threads",
            data=b"{}",
            headers=self._json_headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Backboard thread creation failed ({exc.code}): {error_body}"
            ) from exc
        return data["thread_id"]

    def _send_message_sync(
        self,
        thread_id: str,
        content: str,
        *,
        memory: str = "off",
        send_to_llm: bool = True,
    ) -> str:
        """Send a message to a Backboard thread (form-encoded). Blocking."""
        attempted_fallback = False
        while True:
            provider, model_name = _split_model(self.model)
            form_data = urllib.parse.urlencode({
                "content": content,
                "stream": "false",
                "memory": memory,
                "send_to_llm": str(send_to_llm).lower(),
                "llm_provider": provider,
                "model_name": model_name,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{BACKBOARD_BASE_URL}/threads/{thread_id}/messages",
                data=form_data,
                headers=self._form_headers(),
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                # Backboard may return API-level errors in a 200 payload.
                response_text = str(data.get("content", "") or "")
                error_text = str(
                    data.get("error")
                    or data.get("detail")
                    or data.get("message")
                    or ""
                )
                combined = (response_text + "\n" + error_text).strip()
                if (
                    not attempted_fallback
                    and "not supported" in combined.lower()
                    and self._switch_to_supported_model(combined)
                ):
                    attempted_fallback = True
                    continue
                if (
                    not attempted_fallback
                    and "not a valid model id" in combined.lower()
                    and self._switch_to_default_model("invalid model id")
                ):
                    attempted_fallback = True
                    continue
                if error_text and not response_text:
                    raise RuntimeError(f"Backboard API error: {error_text}")
                return response_text
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                can_retry = (
                    not attempted_fallback
                    and (
                        ("not supported" in error_body.lower() and self._switch_to_supported_model(error_body))
                        or ("not a valid model id" in error_body.lower() and self._switch_to_default_model("invalid model id"))
                    )
                )
                if can_retry:
                    attempted_fallback = True
                    continue
                raise RuntimeError(
                    f"Backboard API error ({exc.code}): {error_body}"
                ) from exc

    # ------------------------------------------------------------------
    # Message flattening
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten_messages(messages: list[dict[str, str]], *, json_mode: bool = False) -> str:
        """Convert OpenAI-format messages list into a single string for Backboard."""
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            text = msg.get("content", "")
            if role == "system":
                parts.append(f"[System Instructions]\n{text}")
            elif role == "assistant":
                parts.append(f"[Previous Response]\n{text}")
            else:
                parts.append(text)
        if json_mode:
            parts.append("\nIMPORTANT: Respond with valid JSON only. No markdown fences, no explanation.")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Core call methods
    # ------------------------------------------------------------------

    def _call_sync(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
    ) -> str:
        """Blocking call via Backboard. Meant to be run via asyncio.to_thread."""
        thread_id = self._create_thread_sync()
        content = self._flatten_messages(messages, json_mode=json_mode)
        return self._send_message_sync(thread_id, content, memory="off")

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
    ) -> str:
        """Send a chat completion request asynchronously."""
        async with self._sem:
            attempt = 0
            while True:
                try:
                    result = await asyncio.to_thread(self._call_sync, messages, json_mode=json_mode)
                    async with self._stats_lock:
                        self._total_calls += 1
                        # Decay failure streak after successful request.
                        self._failure_streak = max(0, self._failure_streak - 1)
                    return result
                except Exception as exc:
                    if (
                        not self.backoff_enabled
                        or not _is_retryable(exc)
                        or attempt >= self.max_retries
                    ):
                        raise
                    async with self._stats_lock:
                        self._retry_count += 1
                        self._failure_streak += 1
                        streak = self._failure_streak
                    penalty = (1.0 / max(0.1, self.adaptive_reduction_factor)) ** min(streak, 3)
                    wait_s = ((self.base_backoff_seconds * (2 ** attempt)) * penalty) + random.uniform(0, 0.01)
                    await asyncio.sleep(wait_s)
                    attempt += 1

    async def ask(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """Convenience: single user prompt with optional system message."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages, json_mode=json_mode)

    def ask_sync(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """Synchronous version of ask() for use in threads."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self._call_sync(messages, json_mode=json_mode)

    # ------------------------------------------------------------------
    # Public thread methods (for agents / webapp)
    # ------------------------------------------------------------------

    async def create_thread(self) -> str:
        """Create a new Backboard thread (async)."""
        return await asyncio.to_thread(self._create_thread_sync)

    async def send_thread_message(
        self,
        thread_id: str,
        content: str,
        *,
        memory: str = "auto",
        send_to_llm: bool = True,
    ) -> str:
        """Send a message to an existing thread with retry/backoff."""
        async with self._sem:
            attempt = 0
            while True:
                try:
                    result = await asyncio.to_thread(
                        self._send_message_sync, thread_id, content,
                        memory=memory, send_to_llm=send_to_llm,
                    )
                    async with self._stats_lock:
                        self._total_calls += 1
                        self._failure_streak = max(0, self._failure_streak - 1)
                    return result
                except Exception as exc:
                    if not self.backoff_enabled or not _is_retryable(exc) or attempt >= self.max_retries:
                        raise
                    async with self._stats_lock:
                        self._retry_count += 1
                        self._failure_streak += 1
                        streak = self._failure_streak
                    penalty = (1.0 / max(0.1, self.adaptive_reduction_factor)) ** min(streak, 3)
                    wait_s = ((self.base_backoff_seconds * (2 ** attempt)) * penalty) + random.uniform(0, 0.01)
                    await asyncio.sleep(wait_s)
                    attempt += 1

    # ------------------------------------------------------------------
    # Streaming support
    # ------------------------------------------------------------------

    def _stream_sync(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
    ) -> Iterator[StreamDelta]:
        """Blocking SSE reader for Backboard. Yields ``StreamDelta`` objects."""
        thread_id = self._create_thread_sync()
        content = self._flatten_messages(messages)
        provider, model_name = _split_model(self.model)
        form_data = urllib.parse.urlencode({
            "content": content,
            "stream": "true",
            "memory": "off",
            "send_to_llm": "true",
            "llm_provider": provider,
            "model_name": model_name,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{BACKBOARD_BASE_URL}/threads/{thread_id}/messages",
            data=form_data,
            headers=self._form_headers(),
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=180)
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Backboard stream error ({exc.code}): {error_body}"
            ) from exc
        try:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    return
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                event_type = chunk.get("type", "")
                if event_type == "content_streaming":
                    text = chunk.get("content")
                    if text:
                        yield StreamDelta(content=text)
                elif event_type == "run_ended":
                    yield StreamDelta(finish_reason="stop")
                    return
        finally:
            resp.close()

    async def stream_chat(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamDelta]:
        """Async generator that streams deltas from Backboard.

        Uses the same concurrency semaphore as ``chat()``.
        The *tools* parameter is accepted for API compatibility but tool
        instructions must be embedded in the prompt text (Backboard has no
        native function calling).
        """
        async with self._sem:
            queue: asyncio.Queue[StreamDelta | None] = asyncio.Queue()

            def _run() -> None:
                try:
                    for delta in self._stream_sync(messages, tools=tools):
                        queue.put_nowait(delta)
                except Exception as exc:
                    queue.put_nowait(StreamDelta(finish_reason=f"__error__:{exc}"))
                finally:
                    queue.put_nowait(None)  # sentinel

            loop = asyncio.get_running_loop()
            fut = loop.run_in_executor(None, _run)

            error_msg: str | None = None
            try:
                while True:
                    delta = await queue.get()
                    if delta is None:
                        break
                    if delta.finish_reason and delta.finish_reason.startswith("__error__:"):
                        error_msg = delta.finish_reason[10:]
                        break
                    yield delta
            finally:
                await fut

            if error_msg:
                raise RuntimeError(error_msg)

            async with self._stats_lock:
                self._total_calls += 1
                self._failure_streak = max(0, self._failure_streak - 1)

    async def get_stats(self) -> dict[str, int]:
        """Get runtime LLM call stats for telemetry/persistence."""
        async with self._stats_lock:
            return {
                "total_calls": self._total_calls,
                "retries": self._retry_count,
            }


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    retry_markers = ("429", "rate limit", "timeout", "temporar", "5")
    return any(m in msg for m in retry_markers)
