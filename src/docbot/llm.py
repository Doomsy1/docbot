"""LLM client -- async wrapper around OpenRouter's chat completions API."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import urllib.request
import urllib.error
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-20b"


# ---------------------------------------------------------------------------
# Streaming data types
# ---------------------------------------------------------------------------


@dataclass
class StreamDelta:
    """A single chunk from an SSE stream."""

    content: str | None = None
    tool_index: int | None = None
    tool_name: str | None = None
    tool_args_chunk: str | None = None
    finish_reason: str | None = None


@dataclass
class StreamedToolCall:
    """Accumulates partial tool-call deltas into a complete invocation."""

    index: int
    id: str = ""
    name: str = ""
    arguments_json: str = ""

    def try_parse(self) -> dict | None:
        """Return parsed args dict if JSON is complete, else None."""
        try:
            return json.loads(self.arguments_json)
        except json.JSONDecodeError:
            return None


@dataclass
class LLMClient:
    """Minimal async-friendly OpenRouter client using stdlib only."""

    api_key: str
    model: str = DEFAULT_MODEL
    max_tokens: int = 8192
    temperature: float = 0.3
    backoff_enabled: bool = True
    max_retries: int = 6
    base_backoff_seconds: float = 2.0
    adaptive_reduction_factor: float = 0.6
    max_concurrency: int = 6
    _sem: asyncio.Semaphore = field(init=False, repr=False)
    _failure_streak: int = field(default=0, init=False, repr=False)
    _stats_lock: asyncio.Lock = field(init=False, repr=False)
    _total_calls: int = field(default=0, init=False, repr=False)
    _retry_count: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._sem = asyncio.Semaphore(max(1, self.max_concurrency))
        self._stats_lock = asyncio.Lock()

    def _call_sync(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
    ) -> str:
        """Blocking HTTP call to OpenRouter. Meant to be run via asyncio.to_thread."""
        body: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        payload = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(
            OPENROUTER_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/docbot",
                "X-Title": "docbot",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logger.error("OpenRouter HTTP %s: %s", exc.code, error_body)
            raise RuntimeError(f"OpenRouter API error ({exc.code}): {error_body}") from exc
        except urllib.error.URLError as exc:
            logger.error("OpenRouter connection error: %s", exc.reason)
            raise RuntimeError(f"OpenRouter connection error: {exc.reason}") from exc
        except (TimeoutError, OSError) as exc:
            logger.error("OpenRouter network error: %s", exc)
            raise RuntimeError(f"OpenRouter network error: {exc}") from exc

        # Extract the assistant message text.
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Unexpected OpenRouter response shape: {body}") from exc

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

    # ------------------------------------------------------------------
    # Streaming support
    # ------------------------------------------------------------------

    def _stream_sync(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
    ) -> Iterator[StreamDelta]:
        """Blocking SSE reader. Yields ``StreamDelta`` objects.

        Meant to be called inside a thread (via ``asyncio.to_thread``).
        """
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        payload = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(
            OPENROUTER_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "HTTP-Referer": "https://github.com/docbot",
                "X-Title": "docbot",
            },
            method="POST",
        )

        try:
            resp = urllib.request.urlopen(req, timeout=180)
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logger.error("OpenRouter stream HTTP %s: %s", exc.code, error_body)
            raise RuntimeError(
                f"OpenRouter API error ({exc.code}): {error_body}"
            ) from exc
        except urllib.error.URLError as exc:
            logger.error("OpenRouter stream connection error: %s", exc.reason)
            raise RuntimeError(
                f"OpenRouter connection error: {exc.reason}"
            ) from exc
        except (TimeoutError, OSError) as exc:
            logger.error("OpenRouter stream network error: %s", exc)
            raise RuntimeError(f"OpenRouter network error: {exc}") from exc

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

                choices = chunk.get("choices")
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                finish = choices[0].get("finish_reason")

                # Content delta
                content = delta.get("content")

                # Tool call deltas
                tc_list = delta.get("tool_calls")
                if tc_list:
                    for tc in tc_list:
                        idx = tc.get("index", 0)
                        func = tc.get("function", {})
                        yield StreamDelta(
                            tool_index=idx,
                            tool_name=func.get("name"),
                            tool_args_chunk=func.get("arguments"),
                        )
                elif content:
                    yield StreamDelta(content=content)

                if finish:
                    yield StreamDelta(finish_reason=finish)
        finally:
            resp.close()

    async def stream_chat(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamDelta]:
        """Async generator that streams deltas from OpenRouter.

        Uses the same concurrency semaphore and retry logic as ``chat()``.
        """
        async with self._sem:
            attempt = 0
            while True:
                queue: asyncio.Queue[StreamDelta | None] = asyncio.Queue()

                def _run() -> None:
                    try:
                        for delta in self._stream_sync(messages, tools=tools):
                            queue.put_nowait(delta)
                    except Exception as exc:
                        # Signal error via a special delta
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
                    # Make sure the thread finishes
                    await fut

                if error_msg:
                    exc = RuntimeError(error_msg)
                    if (
                        not self.backoff_enabled
                        or not _is_retryable(exc)
                        or attempt >= self.max_retries
                    ):
                        raise exc
                    async with self._stats_lock:
                        self._retry_count += 1
                        self._failure_streak += 1
                        streak = self._failure_streak
                    penalty = (1.0 / max(0.1, self.adaptive_reduction_factor)) ** min(streak, 3)
                    wait_s = ((self.base_backoff_seconds * (2 ** attempt)) * penalty) + random.uniform(0, 0.01)
                    await asyncio.sleep(wait_s)
                    attempt += 1
                    continue

                # Success path
                async with self._stats_lock:
                    self._total_calls += 1
                    self._failure_streak = max(0, self._failure_streak - 1)
                return

    async def get_stats(self) -> dict[str, int]:
        """Get runtime LLM call stats for telemetry/persistence."""
        async with self._stats_lock:
            return {
                "total_calls": self._total_calls,
                "retries": self._retry_count,
            }


def _is_retryable(exc: Exception) -> bool:
    """Determine if an LLM call error is worth retrying.

    Retries on: rate limits (429), server errors (5xx), timeouts,
    temporary failures, and connection errors.
    """
    msg = str(exc).lower()
    retry_markers = (
        "429", "rate limit", "rate_limit",
        "500", "502", "503", "504", "server error",
        "timeout", "timed out",
        "temporar",
        "connection error", "connection reset", "connection refused",
        "connection closed", "connection aborted",
        "network error", "urlopen error",
        "broken pipe", "eof",
    )
    return any(m in msg for m in retry_markers)
