"""LLM client -- async wrapper around OpenRouter's chat completions API."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash-lite-preview-09-2025"


@dataclass
class LLMClient:
    """Minimal async-friendly OpenRouter client using stdlib only."""

    api_key: str
    model: str = DEFAULT_MODEL
    max_tokens: int = 4096
    temperature: float = 0.3

    def _call_sync(self, messages: list[dict[str, str]]) -> str:
        """Blocking HTTP call to OpenRouter. Meant to be run via asyncio.to_thread."""
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }).encode("utf-8")

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

        # Extract the assistant message text.
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Unexpected OpenRouter response shape: {body}") from exc

    async def chat(self, messages: list[dict[str, str]]) -> str:
        """Send a chat completion request asynchronously."""
        return await asyncio.to_thread(self._call_sync, messages)

    async def ask(self, prompt: str, *, system: str | None = None) -> str:
        """Convenience: single user prompt with optional system message."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages)
