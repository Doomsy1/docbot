"""Tools -- tool definitions and executor for exploration agents."""

from __future__ import annotations

import json
import logging
import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Awaitable

if TYPE_CHECKING:
    from ..models import ScopeResult, ScopePlan, Citation
    from .notepad import Notepad

logger = logging.getLogger(__name__)

# Tool definitions for LLM function calling
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read source code from a file in the current scope. Returns the file contents (may be truncated for large files).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repo-relative path to the file (e.g., 'src/auth.py')"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_symbol",
            "description": "Read a specific function or class definition by name from a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Repo-relative path to the file"
                    },
                    "symbol": {
                        "type": "string",
                        "description": "Name of the function or class to read"
                    }
                },
                "required": ["file", "symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_notepad",
            "description": "Record a finding to the shared notepad. Use dot notation for keys (e.g., 'patterns.singleton', 'dependencies.external').",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Key path for the note (dot notation)"
                    },
                    "content": {
                        "type": "string",
                        "description": "The finding or observation to record"
                    }
                },
                "required": ["key", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": "Spawn a specialized subagent for deeper analysis of a file or symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_type": {
                        "type": "string",
                        "enum": ["file", "symbol"],
                        "description": "Type of subagent to spawn"
                    },
                    "target": {
                        "type": "string",
                        "description": "Target for analysis (file path or 'file:symbol' for symbol agent)"
                    },
                    "task": {
                        "type": "string",
                        "description": "Specific analysis task for the subagent"
                    }
                },
                "required": ["agent_type", "target", "task"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Complete analysis and return the final summary. Call this when you have gathered enough information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Comprehensive summary of your findings"
                    }
                },
                "required": ["summary"]
            }
        }
    }
]

# Tool definitions for root agent (repo-level exploration)
ROOT_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and subdirectories in a repo directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repo-relative dir path ('.' for root)"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_folder",
            "description": "Delegate a folder/module to a subagent for deep analysis and documentation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "Repo-relative folder path (e.g. 'src/auth')"
                    },
                    "name": {
                        "type": "string",
                        "description": "Descriptive human-readable name for this module (e.g. 'User Authentication')"
                    },
                    "task": {
                        "type": "string",
                        "description": "What to analyze and document about this module"
                    }
                },
                "required": ["folder_path", "name", "task"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read source code from a file in the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repo-relative path to the file"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_notepad",
            "description": "Record a finding to the shared notepad. Use dot notation for keys.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Key path for the note (dot notation)"
                    },
                    "content": {
                        "type": "string",
                        "description": "The finding or observation to record"
                    }
                },
                "required": ["key", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Complete analysis and return the final summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Comprehensive architectural summary of your findings"
                    }
                },
                "required": ["summary"]
            }
        }
    }
]

# Max file size to return (chars)
_MAX_FILE_CHARS = 12000
_MAX_SYMBOL_CHARS = 4000


class AgentToolkit:
    """Executes tool calls for exploration agents."""

    def __init__(
        self,
        notepad: Notepad,
        repo_root: Path,
        scope_result: ScopeResult | None = None,
        agent_id: str = "",
        max_depth: int = 2,
        current_depth: int = 0,
        llm_client: object | None = None,
        tracker: object | None = None,  # NoOpTracker or PipelineTracker
        parent_tracker_id: str | None = None,  # Parent node ID for subagent tree
        max_parallel_subagents: int = 8,
        agent_role: str = "scope",  # "scope" | "root"
        scan_result: object | None = None,  # ScanResult (for root agent)
        on_scope_result: Callable | None = None,  # callback(ScopeResult) for root agent
    ):
        self.notepad = notepad
        self.repo_root = repo_root
        self.scope_result = scope_result
        self.agent_id = agent_id
        self.max_depth = max_depth
        self.current_depth = current_depth
        self.llm_client = llm_client
        self.tracker = tracker
        self.parent_tracker_id = parent_tracker_id
        self._subagent_sem = asyncio.Semaphore(max_parallel_subagents)
        self.agent_role = agent_role
        self.scan_result = scan_result
        self.on_scope_result = on_scope_result

        # Track spawned subagents for concurrency control
        self._pending_subagents: list[asyncio.Task] = []
        self._subagent_counter = 0
        # Collect ScopeResults produced by delegate_folder
        self.scope_results: list[ScopeResult] = []

    async def execute(self, tool_name: str, args: dict) -> str:
        """Execute a tool call and return result string."""
        try:
            if tool_name == "read_file":
                return await self._read_file(args["path"])
            elif tool_name == "read_symbol":
                return await self._read_symbol(args["file"], args["symbol"])
            elif tool_name == "write_notepad":
                return await self._write_notepad(args["key"], args["content"])
            elif tool_name == "spawn_subagent":
                return await self._spawn_subagent(
                    args["agent_type"], args["target"], args["task"]
                )
            elif tool_name == "list_directory":
                return await self._list_directory(args["path"])
            elif tool_name == "delegate_folder":
                return await self._delegate_folder(
                    args["folder_path"], args["name"], args["task"]
                )
            elif tool_name == "finish":
                # finish is handled in the loop, not here
                return "Finishing..."
            else:
                return f"Unknown tool: {tool_name}"
        except Exception as e:
            logger.warning("Tool %s failed: %s", tool_name, e)
            return f"Error executing {tool_name}: {e}"

    async def _read_file(self, path: str) -> str:
        """Read a file from the repository."""
        # Validate path is in scope (skip check for root agent)
        if self.agent_role != "root" and self.scope_result is not None:
            if path not in self.scope_result.paths:
                return f"File '{path}' is not in the current scope. Available files: {', '.join(self.scope_result.paths[:10])}..."

        abs_path = self.repo_root / path
        if not abs_path.is_file():
            return f"File not found: {path}"

        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            if len(content) > _MAX_FILE_CHARS:
                content = content[:_MAX_FILE_CHARS] + "\n... (truncated)"
            return f"=== {path} ===\n{content}"
        except Exception as e:
            return f"Error reading file: {e}"

    async def _read_symbol(self, file: str, symbol: str) -> str:
        """Read a specific symbol from a file."""
        # Find symbol in extracted public_api
        for sym in self.scope_result.public_api:
            if sym.citation.file == file and sym.name == symbol:
                # Read the symbol's source from file
                abs_path = self.repo_root / file
                if not abs_path.is_file():
                    return f"File not found: {file}"
                
                try:
                    lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    start = max(0, sym.citation.line_start - 1)
                    end = min(len(lines), sym.citation.line_end)
                    source = "\n".join(lines[start:end])
                    if len(source) > _MAX_SYMBOL_CHARS:
                        source = source[:_MAX_SYMBOL_CHARS] + "\n... (truncated)"
                    
                    result = f"=== {symbol} ({sym.kind}) in {file} ===\n"
                    result += f"Signature: {sym.signature}\n"
                    if sym.docstring_first_line:
                        result += f"Doc: {sym.docstring_first_line}\n"
                    result += f"\n{source}"
                    return result
                except Exception as e:
                    return f"Error reading symbol: {e}"
        
        return f"Symbol '{symbol}' not found in {file}. Available symbols: {', '.join(s.name for s in self.scope_result.public_api if s.citation.file == file)}"

    async def _write_notepad(self, key: str, content: str) -> str:
        """Write a finding to the notepad."""
        from ..models import Citation
        
        await self.notepad.write(key, content, self.agent_id)
        return f"Recorded note under '{key}'"

    async def _spawn_subagent(self, agent_type: str, target: str, task: str) -> str:
        """Spawn a subagent for deeper analysis."""
        if self.current_depth >= self.max_depth:
            return f"Cannot spawn subagent: max depth ({self.max_depth}) reached. Analyze directly instead."
        
        if self.llm_client is None:
            return "Cannot spawn subagent: no LLM client available."
        
        # Generate unique subagent ID for tracker
        self._subagent_counter += 1
        short_target = target.split("/")[-1] if "/" in target else target.split("\\")[-1] if "\\" in target else target
        subagent_node_id = f"{self.parent_tracker_id or self.agent_id}.{agent_type}{self._subagent_counter}"
        subagent_name = f"{agent_type.title()}: {short_target[:20]}"
        
        # Register with tracker
        if self.tracker:
            from ..pipeline.tracker import AgentState
            self.tracker.add_node(
                subagent_node_id, subagent_name,
                self.parent_tracker_id or self.agent_id.replace(":", "_"),
                agent_type=agent_type,
            )
            self.tracker.set_state(subagent_node_id, AgentState.running)
        
        async def _run_subagent() -> str:
            try:
                async with self._subagent_sem:
                    return await _do_run()
            except Exception:
                if self.tracker:
                    from ..pipeline.tracker import AgentState
                    self.tracker.set_state(subagent_node_id, AgentState.error)
                raise

        async def _do_run() -> str:
            if agent_type == "file":
                from .file_agent import run_file_agent
                result = await run_file_agent(
                    file_path=target,
                    task=task,
                    notepad=self.notepad,
                    repo_root=self.repo_root,
                    llm_client=self.llm_client,
                    scope_result=self.scope_result,
                    max_depth=self.max_depth,
                    current_depth=self.current_depth + 1,
                    tracker=self.tracker,
                    parent_tracker_id=subagent_node_id,
                )
                if self.tracker:
                    self.tracker.set_state(subagent_node_id, AgentState.done)
                return f"FileAgent completed: {result[:500]}..." if len(result) > 500 else f"FileAgent completed: {result}"
            
            elif agent_type == "symbol":
                # Parse target as "file:symbol"
                if ":" not in target:
                    return "For symbol agent, target must be 'file:symbol' format"
                file_path, symbol_name = target.rsplit(":", 1)
                
                from .symbol_agent import run_symbol_agent
                result = await run_symbol_agent(
                    file_path=file_path,
                    symbol_name=symbol_name,
                    task=task,
                    notepad=self.notepad,
                    repo_root=self.repo_root,
                    llm_client=self.llm_client,
                    scope_result=self.scope_result,
                    tracker=self.tracker,
                    parent_tracker_id=subagent_node_id,
                )
                if self.tracker:
                    self.tracker.set_state(subagent_node_id, AgentState.done)
                return f"SymbolAgent completed: {result[:500]}..." if len(result) > 500 else f"SymbolAgent completed: {result}"
            
            else:
                return f"Unknown agent type: {agent_type}. Use 'file' or 'symbol'."
        task_obj = asyncio.create_task(_run_subagent())
        self._pending_subagents.append(task_obj)
        return f"Scheduled {agent_type} subagent for {target}"

    async def _list_directory(self, path: str) -> str:
        """List files and subdirectories in a repo directory (root agent tool)."""
        target = self.repo_root / path
        if not target.is_dir():
            return f"Directory not found: {path}"

        entries: list[str] = []
        try:
            items = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            for item in items:
                if item.name.startswith(".") and item.name not in (".gitignore",):
                    continue
                if item.name in ("__pycache__", "node_modules", "venv", ".git", "dist", "build", ".docbot"):
                    continue
                if item.is_dir() and item.name.endswith(".egg-info"):
                    continue
                rel = item.relative_to(self.repo_root).as_posix()
                kind = "dir" if item.is_dir() else "file"
                size = ""
                if item.is_file():
                    try:
                        sz = item.stat().st_size
                        size = f" ({sz:,} bytes)"
                    except OSError:
                        pass
                entries.append(f"  [{kind}] {rel}{size}")
        except PermissionError:
            return f"Permission denied: {path}"

        if not entries:
            return f"Directory '{path}' is empty (or all contents are filtered)."

        return f"Directory '{path}' ({len(entries)} items):\n" + "\n".join(entries)

    async def _delegate_folder(self, folder_path: str, name: str, task: str) -> str:
        """Delegate a folder to a subagent for analysis (root agent tool).

        Creates a ScopePlan from the folder, runs extraction + scope agent as
        an async task. The result is collected when ``flush_subagents()`` runs.
        """
        if self.llm_client is None:
            return "Cannot delegate: no LLM client available."

        target = self.repo_root / folder_path
        if not target.is_dir():
            return f"Directory not found: {folder_path}"

        # Collect source files in the folder from scan_result if available
        folder_prefix = folder_path.replace("\\", "/").rstrip("/") + "/"
        if self.scan_result is not None:
            from ..pipeline.scanner import ScanResult
            sr: ScanResult = self.scan_result  # type: ignore[assignment]
            paths = [sf.path for sf in sr.source_files if sf.path.startswith(folder_prefix) or sf.path == folder_path]
        else:
            # Fallback: walk the directory
            paths = []
            for root, _dirs, files in os.walk(target):
                for f in files:
                    fp = Path(root) / f
                    rel = fp.relative_to(self.repo_root).as_posix()
                    paths.append(rel)

        if not paths:
            return f"No source files found in '{folder_path}'."

        # Create scope plan
        from ..models import ScopePlan
        scope_id = folder_path.replace("/", "_").replace("\\", "_").strip("_")
        plan = ScopePlan(
            scope_id=scope_id,
            title=name,
            paths=paths,
            notes=task,
        )

        # Unique tracker node
        self._subagent_counter += 1
        node_id = f"{self.parent_tracker_id or self.agent_id}.scope{self._subagent_counter}"

        if self.tracker:
            from ..pipeline.tracker import AgentState
            self.tracker.add_node(
                node_id, name, self.parent_tracker_id or self.agent_id,
                agent_type="scope",
            )
            self.tracker.set_state(node_id, AgentState.running)

        async def _run_delegate() -> ScopeResult:
            try:
                async with self._subagent_sem:
                    return await _do_delegate()
            except Exception:
                if self.tracker:
                    from ..pipeline.tracker import AgentState
                    self.tracker.set_state(node_id, AgentState.error)
                raise

        async def _do_delegate() -> ScopeResult:
            from ..pipeline.explorer import explore_scope
            from ..agents.scope_agent import run_scope_agent

            # CPU extraction
            result = await asyncio.to_thread(explore_scope, plan, self.repo_root)

            # Agent exploration
            result = await run_scope_agent(
                plan, result, self.repo_root, self.llm_client,
                max_depth=max(1, self.max_depth - 1),
                tracker=self.tracker,
                parent_tracker_id=node_id,
                max_parallel_subagents=8,
            )

            if self.tracker:
                from ..pipeline.tracker import AgentState
                self.tracker.set_state(node_id, AgentState.done)

            self.scope_results.append(result)
            if self.on_scope_result:
                self.on_scope_result(result)
            return result

        task_obj = asyncio.create_task(_run_delegate())
        self._pending_subagents.append(task_obj)
        return f"Delegated '{name}' ({len(paths)} files in {folder_path})"

    async def flush_subagents(self) -> str:
        """Wait for all scheduled subagents and return a compact status."""
        if not self._pending_subagents:
            return "No pending subagents."
        pending = self._pending_subagents
        self._pending_subagents = []
        results = await asyncio.gather(*pending, return_exceptions=True)
        failures = 0
        for res in results:
            if isinstance(res, Exception):
                failures += 1
        if failures:
            return f"Completed {len(results)} subagents with {failures} failure(s)."
        return f"Completed {len(results)} subagents."
