"""Tools -- tool definitions and executor for exploration agents."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Awaitable

if TYPE_CHECKING:
    from ..models import ScopeResult, Citation
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

# Max file size to return (chars)
_MAX_FILE_CHARS = 12000
_MAX_SYMBOL_CHARS = 4000


class AgentToolkit:
    """Executes tool calls for exploration agents."""

    def __init__(
        self,
        notepad: Notepad,
        repo_root: Path,
        scope_result: ScopeResult,
        agent_id: str,
        max_depth: int = 2,
        current_depth: int = 0,
        llm_client: object | None = None,
    ):
        self.notepad = notepad
        self.repo_root = repo_root
        self.scope_result = scope_result
        self.agent_id = agent_id
        self.max_depth = max_depth
        self.current_depth = current_depth
        self.llm_client = llm_client
        
        # Track spawned subagents for concurrency control
        self._pending_subagents: list[Awaitable] = []

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
        # Validate path is in scope
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
            )
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
            )
            return f"SymbolAgent completed: {result[:500]}..." if len(result) > 500 else f"SymbolAgent completed: {result}"
        
        else:
            return f"Unknown agent type: {agent_type}. Use 'file' or 'symbol'."
