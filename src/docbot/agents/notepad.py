"""Notepad -- hierarchical key-value store for inter-agent communication."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Citation


@dataclass
class NoteEntry:
    """A single note written by an agent."""

    content: str
    author: str  # e.g., "ScopeAgent:auth" or "FileAgent:auth.py"
    timestamp: float = field(default_factory=time.time)
    citation: Citation | None = None


@dataclass
class Notepad:
    """Thread-safe hierarchical notepad for agent findings.
    
    Agents write findings under dot-notation keys (e.g., 'symbols.login',
    'patterns.auth'). Parent agents can read all findings from their subagents
    and synthesize them into higher-level documentation.
    """

    scope_id: str
    _entries: dict[str, list[NoteEntry]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _questions: list[str] = field(default_factory=list)

    async def write(
        self,
        key: str,
        content: str,
        author: str,
        citation: Citation | None = None,
    ) -> None:
        """Append a note under a key (e.g., 'symbols.login', 'patterns.auth')."""
        async with self._lock:
            if key not in self._entries:
                self._entries[key] = []
            self._entries[key].append(NoteEntry(
                content=content,
                author=author,
                citation=citation,
            ))

    async def write_question(self, question: str, author: str) -> None:
        """Record an open question for later review."""
        async with self._lock:
            self._questions.append(f"[{author}] {question}")

    async def read(self, key: str) -> list[NoteEntry]:
        """Read all notes under a key."""
        async with self._lock:
            return list(self._entries.get(key, []))

    async def read_prefix(self, prefix: str) -> dict[str, list[NoteEntry]]:
        """Read all notes under keys starting with prefix."""
        async with self._lock:
            return {
                k: list(v) for k, v in self._entries.items()
                if k.startswith(prefix)
            }

    async def read_all(self) -> dict[str, list[NoteEntry]]:
        """Read entire notepad (for parent agent synthesis)."""
        async with self._lock:
            return {k: list(v) for k, v in self._entries.items()}

    def get_questions(self) -> list[str]:
        """Get all recorded questions (sync, for final result building)."""
        return list(self._questions)

    def to_context_string(self, max_chars: int = 8000) -> str:
        """Serialize notepad to string for LLM context.
        
        Groups notes by key and truncates if exceeding max_chars.
        """
        lines: list[str] = []
        total = 0
        
        for key in sorted(self._entries.keys()):
            entries = self._entries[key]
            key_line = f"\n## {key}\n"
            if total + len(key_line) > max_chars:
                lines.append("\n... (notepad truncated)")
                break
            lines.append(key_line)
            total += len(key_line)
            
            for entry in entries:
                entry_line = f"- [{entry.author}]: {entry.content}\n"
                if total + len(entry_line) > max_chars:
                    lines.append("... (truncated)")
                    break
                lines.append(entry_line)
                total += len(entry_line)
        
        return "".join(lines) if lines else "(notepad empty)"
