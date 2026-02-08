"""Callback handler bridging LangGraph events to the SSE event stream.

The ``AgentEventCallback`` is an ``AsyncCallbackHandler`` that pushes
events to an ``asyncio.Queue`` whenever the LLM produces tokens or
tools are invoked.  The webapp's SSE endpoint drains this queue and
forwards the events to connected browsers.

Agent lifecycle events (``agent_spawned``, ``agent_finished``,
``agent_error``) are emitted directly from ``run_agent_exploration()``
and the ``delegate`` tool -- not from these callbacks.

Notepad events (``notepad_created``, ``notepad_write``) are emitted
from ``NotepadStore.write()``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler

logger = logging.getLogger(__name__)


class AgentEventCallback(AsyncCallbackHandler):
    """Bridges LangGraph callback events to an asyncio queue for SSE streaming.

    Parameters
    ----------
    queue:
        The event queue shared with the SSE endpoint.  ``None`` disables
        all event emission.
    agent_id:
        Identity of the agent instance this callback is tracking.
    """

    def __init__(
        self,
        queue: asyncio.Queue | None,
        agent_id: str,
    ) -> None:
        super().__init__()
        self.queue = queue
        self.agent_id = agent_id

    async def _put(self, event: dict) -> None:
        """Best-effort push onto the event queue."""
        if self.queue is None:
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("Event queue full; dropping event for %s", self.agent_id)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to emit callback event", exc_info=True)

    # -- LLM token streaming -------------------------------------------------

    async def on_llm_new_token(
        self,
        token: str,
        **kwargs: Any,
    ) -> None:
        """Called for each token the LLM streams back."""
        if not token:
            return
        await self._put({
            "type": "llm_token",
            "agent_id": self.agent_id,
            "token": token,
        })

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        **kwargs: Any,
    ) -> None:
        """Called when a chat model run starts.

        AsyncCallbackHandler defaults can raise NotImplementedError when this
        hook is unimplemented; treat as a no-op for our event stream.
        """
        return None

    # -- Tool events ----------------------------------------------------------

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Called when a tool begins execution."""
        tool_name = serialized.get("name", "unknown")
        await self._put({
            "type": "tool_start",
            "agent_id": self.agent_id,
            "tool": tool_name,
            "input": input_str[:500],
        })

    async def on_tool_end(
        self,
        output: str,
        **kwargs: Any,
    ) -> None:
        """Called when a tool finishes execution."""
        # Truncate long outputs for the event stream.
        preview = str(output)[:500]
        await self._put({
            "type": "tool_end",
            "agent_id": self.agent_id,
            "output": preview,
        })

    async def on_tool_error(
        self,
        error: BaseException,
        **kwargs: Any,
    ) -> None:
        """Called when a tool raises an exception."""
        await self._put({
            "type": "tool_error",
            "agent_id": self.agent_id,
            "error": str(error)[:300],
        })
