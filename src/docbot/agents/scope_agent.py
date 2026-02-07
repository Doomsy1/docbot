"""Scope agent -- top-level agent for exploring a documentation scope."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm import LLMClient
    from ..models import ScopePlan, ScopeResult

from .loop import run_agent_loop
from .notepad import Notepad
from .tools import AgentToolkit

logger = logging.getLogger(__name__)


SCOPE_AGENT_SYSTEM = """\
You are a senior software documentation agent analyzing a code scope (module/package).

Your goal is to produce thorough, accurate documentation by systematically exploring the codebase.

## Strategy

1. **Orientation**: Review the provided extraction data to understand the scope's overall structure
2. **Key Files**: Read 1-2 of the most important files (entrypoints, main modules)
3. **SPAWN SUBAGENTS**: For ANY file with more than ~100 lines OR multiple functions/classes, you MUST spawn a FileAgent. This is critical for thorough analysis.
4. **Patterns**: Identify architectural patterns, dependencies, and design decisions
5. **Record**: Write key findings to the notepad (patterns.X, architecture.X, etc.)
6. **Synthesize**: Call 'finish' with comprehensive summary

## IMPORTANT: Subagent Usage

You MUST spawn FileAgents for complex files. Use:
```json
{"tool": "spawn_subagent", "args": {"agent_type": "file", "target": "path/to/file.py", "task": "Analyze this module's API and patterns"}}
```

Spawn at least 2-3 FileAgents for any scope with more than 3 files. Do NOT try to read and analyze all files yourself - delegate to subagents.

## Guidelines

- Be factual. Reference specific files, functions, and line numbers.
- Don't speculate about functionality not evidenced in the code.
- Note uncertainties under 'questions' key in notepad.
- Prioritize depth via subagents over shallow breadth.
"""


def _build_scope_context(plan: ScopePlan, result: ScopeResult) -> str:
    """Build initial context for the scope agent from extraction data."""
    lines = [
        f"# Scope: {plan.title}",
        f"Scope ID: {plan.scope_id}",
        "",
        f"## Files ({len(result.paths)})",
    ]
    
    # List files, highlighting key files
    for path in result.paths[:30]:
        marker = " [KEY]" if path in result.key_files else ""
        marker += " [ENTRY]" if path in result.entrypoints else ""
        lines.append(f"  - {path}{marker}")
    if len(result.paths) > 30:
        lines.append(f"  ... and {len(result.paths) - 30} more")
    
    lines.append("")
    lines.append(f"## Languages: {', '.join(result.languages) or 'unknown'}")
    
    # Public API summary
    if result.public_api:
        lines.append(f"\n## Public API ({len(result.public_api)} symbols)")
        for sym in result.public_api[:25]:
            doc = f" - {sym.docstring_first_line}" if sym.docstring_first_line else ""
            lines.append(f"  - {sym.kind} `{sym.name}`: {sym.signature[:80]}{doc}")
        if len(result.public_api) > 25:
            lines.append(f"  ... and {len(result.public_api) - 25} more symbols")
    
    # Environment variables
    if result.env_vars:
        lines.append(f"\n## Environment Variables ({len(result.env_vars)})")
        for ev in result.env_vars[:10]:
            default = f" (default: {ev.default})" if ev.default else ""
            lines.append(f"  - {ev.name}{default}")
    
    # Imports
    if result.imports:
        lines.append(f"\n## Key Imports ({len(result.imports)})")
        for imp in result.imports[:15]:
            lines.append(f"  - {imp}")
    
    # Planner notes
    if plan.notes:
        lines.append(f"\n## Planner Notes\n{plan.notes}")
    
    lines.append("\n---")
    lines.append("Begin your analysis. Use tools to read files and record findings.")
    
    return "\n".join(lines)


async def run_scope_agent(
    plan: ScopePlan,
    scope_result: ScopeResult,
    repo_root: Path,
    llm_client: LLMClient,
    max_depth: int = 2,
) -> ScopeResult:
    """Run hierarchical agent exploration for a scope.
    
    Args:
        plan: The scope plan from the planner
        scope_result: Pre-extracted scope data (symbols, imports, etc.)
        repo_root: Path to repository root
        llm_client: LLM client for agent calls
        max_depth: Maximum subagent recursion depth (1=file, 2=symbol)
    
    Returns:
        Enriched ScopeResult with agent-generated summary
    """
    agent_id = f"ScopeAgent:{plan.scope_id}"
    logger.info("[%s] Starting scope agent exploration (depth=%d)", agent_id, max_depth)
    
    # Create notepad for this scope
    notepad = Notepad(scope_id=plan.scope_id)
    
    # Create toolkit
    toolkit = AgentToolkit(
        notepad=notepad,
        repo_root=repo_root,
        scope_result=scope_result,
        agent_id=agent_id,
        max_depth=max_depth,
        current_depth=0,
        llm_client=llm_client,
    )
    
    # Build initial context
    context = _build_scope_context(plan, scope_result)
    
    # Run agent loop
    try:
        summary = await run_agent_loop(
            llm_client=llm_client,
            system_prompt=SCOPE_AGENT_SYSTEM,
            initial_context=context,
            toolkit=toolkit,
            max_steps=15,
            agent_id=agent_id,
        )
        
        # Enrich result
        scope_result.summary = summary
        scope_result.open_questions = notepad.get_questions()
        
        logger.info("[%s] Scope agent completed successfully", agent_id)
        
    except Exception as e:
        logger.error("[%s] Scope agent failed: %s", agent_id, e)
        scope_result.open_questions.append(f"Agent exploration failed: {e}")
    
    return scope_result
