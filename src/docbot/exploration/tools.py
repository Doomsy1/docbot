"""Tool definitions for the LangGraph agent exploration system.

Each tool is created via the ``create_tools()`` factory, which binds runtime
state (repo root, notepad store, agent identity) into closures so that the
LangGraph ``ToolNode`` can execute them without extra wiring.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from .store import NotepadStore

logger = logging.getLogger(__name__)

# Maximum number of characters returned from a file read.
_MAX_FILE_CHARS = 12_000

# Directories to filter out of directory listings -- noise that agents
# should never need to inspect.
_NOISE_DIRS = frozenset({
    "__pycache__",
    "node_modules",
    ".git",
    "venv",
    ".venv",
    "dist",
    "build",
    ".docbot",
    ".mypy_cache",
    ".pytest_cache",
})


def create_tools(
    repo_root: Path,
    store: "NotepadStore",
    event_queue: asyncio.Queue | None = None,
    agent_id: str = "root",
    delegate_fn: Callable[[str, str, str, str], Awaitable[str]] | None = None,
    current_depth: int = 0,
    max_depth: int = 0,
) -> list:
    """Build the set of LangChain tools bound to the given runtime state.

    Parameters
    ----------
    repo_root:
        Absolute path to the repository being documented.  All file/directory
        operations are sandboxed to this root.
    store:
        The shared ``NotepadStore`` instance used for cross-agent knowledge
        sharing.
    event_queue:
        Optional async queue for pushing live visualization events.
    agent_id:
        Identity string for the agent that will use these tools.  Written as
        the ``author`` field when the agent records notepad entries.

    Returns
    -------
    list
        A list of ``@tool``-decorated functions ready to be passed to
        ``llm.bind_tools()`` and ``ToolNode()``.
    """
    from langchain_core.tools import tool

    # ------------------------------------------------------------------
    # 1. read_file
    # ------------------------------------------------------------------
    @tool
    def read_file(path: str) -> str:
        """Read a source file from the repository.

        The file path must be relative to the repository root (e.g.
        ``src/auth/login.py``).  Contents are capped at 12 000 characters;
        larger files are truncated with a marker at the end.

        Returns the file contents prefixed with the path, or an error
        message if the file does not exist.
        """
        resolved = (repo_root / path).resolve()

        # Prevent path traversal outside the repo.
        try:
            resolved.relative_to(repo_root.resolve())
        except ValueError:
            return f"Error: path '{path}' resolves outside the repository."

        if not resolved.is_file():
            return f"File not found: {path}"

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Error reading '{path}': {exc}"

        if len(content) > _MAX_FILE_CHARS:
            content = content[:_MAX_FILE_CHARS] + "\n... (truncated)"

        return f"=== {path} ===\n{content}"

    # ------------------------------------------------------------------
    # 2. list_directory
    # ------------------------------------------------------------------
    @tool
    def list_directory(path: str) -> str:
        """List the contents of a directory relative to the repository root.

        Use ``"."`` to list the top-level directory.  Hidden directories,
        build artifacts, and common noise directories (node_modules,
        __pycache__, .git, etc.) are automatically filtered out.

        Each entry is annotated with ``[dir]`` or ``[file]`` and files
        include their size in bytes.
        """
        resolved = (repo_root / path).resolve()

        try:
            resolved.relative_to(repo_root.resolve())
        except ValueError:
            return f"Error: path '{path}' resolves outside the repository."

        if not resolved.is_dir():
            return f"Directory not found: {path}"

        entries: list[str] = []
        try:
            items = sorted(
                resolved.iterdir(),
                key=lambda p: (p.is_file(), p.name.lower()),
            )
            for item in items:
                # Skip hidden entries (except .gitignore which can be useful).
                if item.name.startswith(".") and item.name not in (".gitignore",):
                    continue
                if item.name in _NOISE_DIRS:
                    continue
                if item.is_dir() and item.name.endswith(".egg-info"):
                    continue

                rel = item.relative_to(repo_root).as_posix()
                if item.is_dir():
                    entries.append(f"  [dir]  {rel}")
                else:
                    size_str = ""
                    try:
                        sz = item.stat().st_size
                        size_str = f" ({sz:,} bytes)"
                    except OSError:
                        pass
                    entries.append(f"  [file] {rel}{size_str}")
        except PermissionError:
            return f"Permission denied: {path}"

        if not entries:
            return f"Directory '{path}' is empty (or all contents were filtered out)."

        return f"Directory '{path}' ({len(entries)} items):\n" + "\n".join(entries)

    # ------------------------------------------------------------------
    # 3. read_notepad
    # ------------------------------------------------------------------
    @tool
    def read_notepad(topic: str) -> str:
        """Read all entries from a shared notepad topic.

        The notepad is shared across all agents in the exploration run.
        Use this to check what other agents have already discovered about
        a topic before duplicating work.

        Returns the concatenated entries for the topic, or a message
        indicating the topic is empty.
        """
        return store.read(topic)

    # ------------------------------------------------------------------
    # 4. write_notepad
    # ------------------------------------------------------------------
    @tool
    def write_notepad(topic: str, content: str) -> str:
        """Write an entry to a shared notepad topic.

        Use descriptive topic names with dot notation for organization
        (e.g. ``architecture.layers``, ``patterns.singleton``,
        ``dependencies.external``).  Multiple agents can write to the
        same topic; entries are appended, not overwritten.

        Returns the current contents of the topic so you can see the
        full context after your write.
        """
        return store.write(topic, content, author=agent_id)

    # ------------------------------------------------------------------
    # 5. list_topics
    # ------------------------------------------------------------------
    @tool
    def list_topics() -> str:
        """List all notepad topics that have been written to so far.

        Use this to discover what other agents have recorded and avoid
        duplicating exploration effort.

        Returns a newline-separated list of topic names, or a message
        indicating the notepad is empty.
        """
        return store.list_topics()

    # ------------------------------------------------------------------
    # 6. delegate
    # ------------------------------------------------------------------
    @tool
    async def delegate(
        target: str,
        purpose: str,
        name: str = "",
        context: str = "",
    ) -> str:
        """Spawn a child agent to explore a subdirectory or module.

        Use this when a part of the codebase is large or complex enough
        to warrant dedicated exploration by a separate agent.

        Required args:
        - target: subdirectory/module path relative to repo root.
        - purpose: what the child should focus on.
        Optional args:
        - name: child label (auto-generated when omitted).
        - context: condensed parent context for the child.
        """
        if not name:
            name = f"delegate:{target}"
        if current_depth >= max_depth:
            return (
                f"Delegation blocked: already at maximum depth "
                f"({current_depth}/{max_depth})."
            )
        if delegate_fn is None:
            return (
                f"Delegation requested for '{name}' on '{target}', but no "
                f"delegate handler is configured."
            )
        summary = await delegate_fn(target, name, purpose, context)
        return (
            f"Delegated to child agent '{name}' for '{target}'. "
            f"Child summary: {summary[:600]}"
        )

    # ------------------------------------------------------------------
    # 7. finish
    # ------------------------------------------------------------------
    @tool
    def finish(summary: str) -> str:
        """Conclude exploration and return findings to the parent agent.

        Call this tool when you have gathered enough information and
        written your key findings to the notepad.  The summary should
        be a concise but comprehensive description of what you
        discovered, including:

        - Architecture and structure
        - Key patterns and design decisions
        - Important dependencies and data flows
        - Any concerns or notable observations

        After calling finish, no further tool calls will be made.
        """
        return summary

    return [
        read_file,
        list_directory,
        read_notepad,
        write_notepad,
        list_topics,
        delegate,
        finish,
    ]
