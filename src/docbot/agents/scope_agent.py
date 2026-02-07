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
You are a documentation agent analyzing a code scope (module/package).

## Strategy
1. Review the extraction data to understand structure, symbols, and imports.
2. Read 1-2 key files directly (entrypoints, config, __init__.py) to orient yourself.
3. Delegate complex files to FileAgents. Use your judgment:
   - Spawn a FileAgent for files with rich logic, multiple classes, or non-obvious \
behavior.
   - Read simple files (constants, thin wrappers, config) yourself -- no subagent needed.
4. Record patterns and findings to the notepad (keys: patterns.X, architecture.X, api.X).
5. Call `finish` with a structured summary.

## When to Spawn vs. Read Directly
Spawn a FileAgent when:
- The file has 3+ public functions/classes
- The file is an entrypoint or orchestrator with complex control flow
- You need to understand internal implementation details for documentation

Read directly when:
- The file is short and its purpose is obvious from the extraction data
- It is a config, constants, or re-export module
- The extraction data already captures its full public API

## Finish Summary Structure
Your finish summary MUST cover these sections in order:
1. **Purpose**: What this module does and why it exists (1-2 sentences).
2. **Key interfaces**: The main classes/functions a consumer would use.
3. **Internal flow**: How the pieces connect (data flow, call chains).
4. **Dependencies**: What this module imports and what imports it.
5. **Patterns**: Notable design decisions, error handling, concurrency, etc.
6. **Open questions**: Anything unclear or potentially outdated.

## Rules
- Be factual. Reference specific files and symbols.
- Do NOT speculate about functionality not evidenced in the code.
- Note uncertainties under the 'questions' notepad key.
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
    tracker: object | None = None,
    parent_tracker_id: str | None = None,
    max_parallel_subagents: int = 8,
) -> ScopeResult:
    """Run hierarchical agent exploration for a scope.
    
    Args:
        plan: The scope plan from the planner
        scope_result: Pre-extracted scope data (symbols, imports, etc.)
        repo_root: Path to repository root
        llm_client: LLM client for agent calls
        max_depth: Maximum subagent recursion depth (1=file, 2=symbol)
        tracker: Optional pipeline tracker for visualization
        parent_tracker_id: Parent node ID for this scope agent
        max_parallel_subagents: Maximum number of concurrent subagents within this scope
    
    Returns:
        Enriched ScopeResult with agent-generated summary
    """
    agent_id = f"ScopeAgent:{plan.scope_id}"
    logger.info("[%s] Starting scope agent exploration (depth=%d)", agent_id, max_depth)
    
    # Create notepad for this scope
    notepad = Notepad(scope_id=plan.scope_id)
    
    # Create toolkit with tracker for subagent visualization
    toolkit = AgentToolkit(
        notepad=notepad,
        repo_root=repo_root,
        scope_result=scope_result,
        agent_id=agent_id,
        max_depth=max_depth,
        current_depth=0,
        llm_client=llm_client,
        tracker=tracker,
        parent_tracker_id=parent_tracker_id or f"explorer.{plan.scope_id}",
        max_parallel_subagents=max_parallel_subagents,
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
            tracker=tracker,
            tracker_node_id=parent_tracker_id or f"explorer.{plan.scope_id}",
        )
        
        # Enrich result
        scope_result.summary = summary
        scope_result.open_questions = notepad.get_questions()
        
        logger.info("[%s] Scope agent completed successfully", agent_id)
        
    except Exception as e:
        logger.error("[%s] Scope agent failed: %s", agent_id, e)
        scope_result.open_questions.append(f"Agent exploration failed: {e}")
    
    return scope_result
