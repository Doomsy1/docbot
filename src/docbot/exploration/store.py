"""NotepadStore -- thread-safe shared notepad for LangGraph agent exploration.

Agents write findings under topic keys (e.g. ``architecture.layers``,
``patterns.singleton``).  Multiple agents can append to the same topic.
The store optionally pushes events to an ``asyncio.Queue`` for live
visualization in the webapp pipeline view.

This is intentionally dependency-light: just a dict + ``threading.Lock``.
No LangGraph ``InMemoryStore`` involved.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class NoteEntry:
    """A single note written by an agent."""

    content: str
    author: str  # agent_id that wrote this
    timestamp: float  # time.time()
    topic: str


# ---------------------------------------------------------------------------
# NotepadStore
# ---------------------------------------------------------------------------

class NotepadStore:
    """Thread-safe in-memory notepad shared across all agents in a run.

    Parameters
    ----------
    event_queue:
        Optional ``asyncio.Queue`` for pushing notepad events to the live
        visualization layer.  When ``None``, no events are emitted.
    """

    def __init__(self, event_queue: asyncio.Queue | None = None) -> None:
        self._entries: dict[str, list[NoteEntry]] = {}
        self._lock = threading.Lock()
        self._event_queue = event_queue

    # -- helpers -------------------------------------------------------------

    def _emit_event(self, event: dict) -> None:
        """Best-effort push of an event onto the async queue.

        Since ``write()`` is synchronous (called from LangChain tool
        functions that are not async), we use ``put_nowait`` wrapped in a
        try/except.  If the queue is full the event is silently dropped --
        visualization events are non-critical.
        """
        try:
            from ..web import server as web_server
            web_server._update_agent_state_snapshot(event)
        except Exception:
            pass
        if self._event_queue is None:
            return
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("Event queue full; dropping notepad event")
        except Exception:  # noqa: BLE001
            # Guard against any edge case (queue closed, wrong loop, etc.)
            logger.debug("Failed to emit notepad event", exc_info=True)

    @staticmethod
    def _format_entries(entries: list[NoteEntry]) -> str:
        """Format a list of entries as ``[author] content``, one per line."""
        return "\n".join(f"[{e.author}] {e.content}" for e in entries)

    # -- public API ----------------------------------------------------------

    def write(self, topic: str, content: str, author: str) -> str:
        """Append an entry to *topic* and return the formatted topic contents.

        If this is the first entry for a topic, a ``notepad_created`` event
        is emitted before the ``notepad_write`` event.

        Parameters
        ----------
        topic:
            Dot-notation topic key (e.g. ``architecture.layers``).
        content:
            The note body.
        author:
            The ``agent_id`` of the agent writing the note.

        Returns
        -------
        str
            All current entries for the topic, formatted for display.
        """
        entry = NoteEntry(
            content=content,
            author=author,
            timestamp=time.time(),
            topic=topic,
        )

        with self._lock:
            is_new = topic not in self._entries
            if is_new:
                self._entries[topic] = []
            self._entries[topic].append(entry)
            snapshot = list(self._entries[topic])

        # Emit events outside the lock to avoid any re-entrant issues.
        if is_new:
            self._emit_event({
                "type": "notepad_created",
                "topic": topic,
                "author": author,
            })
        self._emit_event({
            "type": "notepad_write",
            "topic": topic,
            "content": content,
            "author": author,
        })

        return self._format_entries(snapshot)

    def read(self, topic: str) -> str:
        """Return formatted entries for *topic*.

        Returns
        -------
        str
            Formatted entries, or a message indicating the topic is empty.
        """
        with self._lock:
            entries = list(self._entries.get(topic, []))

        if not entries:
            return f"No entries for topic '{topic}'"

        return self._format_entries(entries)

    def list_topics(self) -> str:
        """Return a formatted list of all topics with entry counts.

        Returns
        -------
        str
            One topic per line in the form ``topic (N entries)``,
            or ``"No topics yet."`` when the notepad is empty.
        """
        with self._lock:
            topics = {k: len(v) for k, v in self._entries.items()}

        if not topics:
            return "No topics yet."

        lines = [
            f"{topic} ({count} {'entry' if count == 1 else 'entries'})"
            for topic, count in sorted(topics.items())
        ]
        return "\n".join(lines)

    def serialize(self) -> dict:
        """Export the entire notepad as a JSON-serializable dictionary.

        Returns
        -------
        dict
            Structure: ``{topic: [{content, author, timestamp}, ...]}``
        """
        with self._lock:
            return {
                topic: [
                    {
                        "content": e.content,
                        "author": e.author,
                        "timestamp": e.timestamp,
                    }
                    for e in entries
                ]
                for topic, entries in self._entries.items()
            }

    def to_context_string(self, max_chars: int = 8000) -> str:
        """Format all notepad content for inclusion in an LLM context window.

        Groups entries by topic (sorted alphabetically) and truncates the
        output if it would exceed *max_chars*.

        Parameters
        ----------
        max_chars:
            Maximum character budget for the returned string.

        Returns
        -------
        str
            The formatted notepad content, or ``"(notepad empty)"`` when
            there are no entries.
        """
        with self._lock:
            snapshot = {k: list(v) for k, v in self._entries.items()}

        if not snapshot:
            return "(notepad empty)"

        lines: list[str] = []
        total = 0

        for topic in sorted(snapshot):
            header = f"\n## {topic}\n"
            if total + len(header) > max_chars:
                lines.append("\n... (notepad truncated)")
                break
            lines.append(header)
            total += len(header)

            for entry in snapshot[topic]:
                entry_line = f"- [{entry.author}]: {entry.content}\n"
                if total + len(entry_line) > max_chars:
                    lines.append("... (truncated)")
                    total = max_chars  # force outer loop to stop too
                    break
                lines.append(entry_line)
                total += len(entry_line)

        return "".join(lines)
