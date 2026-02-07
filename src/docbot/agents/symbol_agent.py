"""Symbol agent -- leaf-level agent for function/class analysis."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm import LLMClient
    from ..models import ScopeResult

from .notepad import Notepad

logger = logging.getLogger(__name__)


SYMBOL_AGENT_SYSTEM = """\
You are analyzing a specific function or class in detail.

Document comprehensively:
1. Purpose and high-level behavior
2. Parameters and return value (with types if available)
3. Side effects (I/O, state mutations, external calls)
4. Error handling and edge cases
5. Dependencies and how they're used
6. Any notable implementation patterns

Be thorough but concise. This is the deepest level of analysis.
"""


async def run_symbol_agent(
    file_path: str,
    symbol_name: str,
    task: str,
    notepad: Notepad,
    repo_root: Path,
    llm_client: LLMClient,
    scope_result: ScopeResult,
) -> str:
    """Analyze a specific symbol and write findings to notepad.
    
    This is a leaf agent - it doesn't spawn subagents.
    It uses a simpler single-shot analysis rather than a full agent loop.
    
    Args:
        file_path: Repo-relative file path
        symbol_name: Name of the function/class
        task: Specific analysis task
        notepad: Shared notepad
        repo_root: Repository root
        llm_client: LLM client
        scope_result: Scope extraction data
    
    Returns:
        Analysis summary
    """
    agent_id = f"SymbolAgent:{file_path}:{symbol_name}"
    logger.debug("[%s] Starting symbol agent", agent_id)
    
    # Find symbol in extraction data
    symbol_info = None
    for sym in scope_result.public_api:
        if sym.citation.file == file_path and sym.name == symbol_name:
            symbol_info = sym
            break
    
    # Read symbol source code
    source = "(source not available)"
    if symbol_info:
        abs_path = repo_root / file_path
        if abs_path.is_file():
            try:
                lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
                start = max(0, symbol_info.citation.line_start - 1)
                end = min(len(lines), symbol_info.citation.line_end)
                source = "\n".join(lines[start:end])
                if len(source) > 4000:
                    source = source[:4000] + "\n... (truncated)"
            except Exception:
                pass
    
    # Build prompt
    prompt = f"""# Symbol Analysis: {symbol_name}

**File**: {file_path}
**Kind**: {symbol_info.kind if symbol_info else "unknown"}
**Signature**: {symbol_info.signature if symbol_info else "unknown"}
**Task**: {task}

## Source Code
```
{source}
```

Analyze this {symbol_info.kind if symbol_info else "symbol"} thoroughly. Cover:
1. Purpose and behavior
2. Parameters and return value
3. Side effects
4. Error handling
5. Notable patterns

Provide a comprehensive but concise analysis."""

    try:
        # Single-shot analysis (no loop needed for leaf agent)
        analysis = await llm_client.ask(prompt, system=SYMBOL_AGENT_SYSTEM)
        
        # Record to notepad
        key = f"symbols.{symbol_name}"
        await notepad.write(key, analysis, agent_id)
        
        logger.debug("[%s] Symbol analysis complete", agent_id)
        return analysis
        
    except Exception as e:
        logger.warning("[%s] Symbol analysis failed: %s", agent_id, e)
        return f"(Symbol analysis failed: {e})"
