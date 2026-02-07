"""File agent -- subagent for deep file analysis."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm import LLMClient
    from ..models import ScopeResult

from .loop import run_agent_loop
from .notepad import Notepad
from .tools import AgentToolkit

logger = logging.getLogger(__name__)


FILE_AGENT_SYSTEM = """\
You are a code analysis agent focusing on a single source file.

Your goal is to understand this file deeply and document:
1. The file's purpose and responsibilities
2. Key functions/classes and their relationships
3. Dependencies and how they're used
4. Notable patterns or implementation details
5. Any edge cases, gotchas, or important considerations

## Guidelines

- Read the file carefully before making observations
- For complex functions/classes, spawn a SymbolAgent for detailed analysis
- Write all findings to the notepad with appropriate keys
- Be specific - reference line numbers and exact code when relevant
- Call 'finish' with a summary when done
"""


async def run_file_agent(
    file_path: str,
    task: str,
    notepad: Notepad,
    repo_root: Path,
    llm_client: LLMClient,
    scope_result: ScopeResult,
    max_depth: int,
    current_depth: int,
) -> str:
    """Analyze a single file and write findings to notepad.
    
    Args:
        file_path: Repo-relative path to the file
        task: Specific analysis task from parent agent
        notepad: Shared notepad for recording findings
        repo_root: Repository root path
        llm_client: LLM client for agent calls
        scope_result: Scope extraction data
        max_depth: Maximum recursion depth
        current_depth: Current depth level
    
    Returns:
        Summary of file analysis
    """
    agent_id = f"FileAgent:{file_path}"
    logger.debug("[%s] Starting file agent (depth=%d)", agent_id, current_depth)
    
    # Create toolkit for this file agent
    toolkit = AgentToolkit(
        notepad=notepad,
        repo_root=repo_root,
        scope_result=scope_result,
        agent_id=agent_id,
        max_depth=max_depth,
        current_depth=current_depth,
        llm_client=llm_client,
    )
    
    # Build context for file analysis
    context = _build_file_context(file_path, task, scope_result)
    
    try:
        summary = await run_agent_loop(
            llm_client=llm_client,
            system_prompt=FILE_AGENT_SYSTEM,
            initial_context=context,
            toolkit=toolkit,
            max_steps=10,
            agent_id=agent_id,
        )
        
        # Record summary to notepad
        await notepad.write(f"files.{_safe_key(file_path)}", summary, agent_id)
        
        return summary
        
    except Exception as e:
        logger.warning("[%s] File agent failed: %s", agent_id, e)
        return f"(File analysis failed: {e})"


def _build_file_context(file_path: str, task: str, scope_result: ScopeResult) -> str:
    """Build initial context for file agent."""
    lines = [
        f"# File Analysis: {file_path}",
        "",
        f"## Task",
        task,
        "",
    ]
    
    # Find symbols in this file
    file_symbols = [s for s in scope_result.public_api if s.citation.file == file_path]
    if file_symbols:
        lines.append(f"## Symbols in this file ({len(file_symbols)})")
        for sym in file_symbols:
            lines.append(f"  - {sym.kind} `{sym.name}`: {sym.signature[:60]}")
    
    # Find env vars in this file
    file_envs = [e for e in scope_result.env_vars if e.citation.file == file_path]
    if file_envs:
        lines.append(f"\n## Environment Variables")
        for ev in file_envs:
            lines.append(f"  - {ev.name}")
    
    lines.append("\n---")
    lines.append("Start by reading the file with `read_file`, then analyze and record your findings.")
    
    return "\n".join(lines)


def _safe_key(path: str) -> str:
    """Convert file path to safe notepad key."""
    return path.replace("/", "_").replace("\\", "_").replace(".", "_")
