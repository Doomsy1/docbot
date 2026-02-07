"""Reducer -- merge per-scope results into a global docs index."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import PurePosixPath

from .models import DocsIndex, EnvVar, PublicSymbol, ScopeResult

logger = logging.getLogger(__name__)

_ANALYSIS_SYSTEM = """\
You are a software architect analyzing a Python codebase. Base every claim \
on the structured data provided. Identify patterns and relationships. \
Be specific -- reference file names and symbol names."""

_ANALYSIS_PROMPT = """\
Analyze the following scope results from a Python repository and write a \
cross-scope architectural analysis.

Repository: {repo_path}

Scopes:
{scope_block}

Import-based dependency edges (scope -> scope):
{edges_block}

Write 3-5 paragraphs covering:
1. How the scopes relate to each other architecturally.
2. Data flow: where requests enter, how they're processed, what gets stored.
3. Shared dependencies and cross-cutting patterns (auth, config, logging).
4. Notable architectural decisions or patterns you observe.

Be specific. Reference scope names, file names, and symbols."""

_MERMAID_SYSTEM = """\
You are a software architect creating a Mermaid architecture diagram. \
Return ONLY valid Mermaid syntax starting with "graph TD". No markdown fences. \
No commentary before or after the diagram. CRITICAL: Define each node EXACTLY \
ONCE. Never redefine a node with a different label or shape."""

_MERMAID_PROMPT = """\
Create a Mermaid architecture diagram for this Python repository.

Repository: {repo_path}

Scopes and what they do:
{scope_block}

Import-based edges: {edges_block}

Entrypoints: {entrypoints}

STRICT requirements:
- Use "graph TD" (top-down layout).
- Define each node EXACTLY ONCE with its label. Never redefine or relabel nodes.
- Use scope_id as the node ID with a short descriptive label in brackets.
- Show dependency arrows using --> for direct deps and -.-> for inferred ones.
- Group related scopes with subgraphs if helpful.
- Use classDef for styling (entrypoints get thicker borders, utilities get dashed).
- Maximum 15 nodes total. Keep it simple and clean.
- DO NOT repeat any node definitions, connections, or subgraph blocks.
- DO NOT include comments explaining what you are doing (no %% lines).
- The entire output should be under 60 lines.

Return ONLY the Mermaid code. Start with "graph TD". No fences. No commentary."""


def _compute_scope_edges(scope_results: list[ScopeResult]) -> list[tuple[str, str]]:
    """Infer directed edges (from_scope -> to_scope) based on import statements."""
    prefix_to_scope: dict[str, str] = {}
    for sr in scope_results:
        for p in sr.paths:
            parts = PurePosixPath(p).parts
            for i in range(1, len(parts) + 1):
                segment = list(parts[:i])
                if segment[-1].endswith(".py"):
                    segment[-1] = segment[-1][:-3]
                dotted = ".".join(segment)
                prefix_to_scope[dotted] = sr.scope_id

    edges: set[tuple[str, str]] = set()
    for sr in scope_results:
        for imp in sr.imports:
            parts = imp.split(".")
            for i in range(len(parts), 0, -1):
                candidate = ".".join(parts[:i])
                target = prefix_to_scope.get(candidate)
                if target and target != sr.scope_id:
                    edges.add((sr.scope_id, target))
                    break

    return sorted(edges)


def _build_scope_block(scope_results: list[ScopeResult]) -> str:
    parts = []
    for sr in scope_results:
        status = "[FAILED]" if sr.error else ""
        parts.append(f"### {sr.title} (scope_id: {sr.scope_id}) {status}")
        parts.append(f"  Files: {len(sr.paths)}, Public symbols: {len(sr.public_api)}, "
                      f"Env vars: {len(sr.env_vars)}, Errors raised: {len(sr.raised_errors)}")
        if sr.entrypoints:
            parts.append(f"  Entrypoints: {', '.join(sr.entrypoints)}")
        if sr.summary:
            # First 500 chars of the summary
            parts.append(f"  Summary: {sr.summary[:500]}")
        parts.append("")
    return "\n".join(parts)


def reduce(
    scope_results: list[ScopeResult],
    repo_path: str,
) -> DocsIndex:
    """Merge all scope results into a single :class:`DocsIndex` (no LLM)."""
    all_env: list[EnvVar] = []
    all_api: list[PublicSymbol] = []
    all_entrypoints: list[str] = []
    seen_env: set[str] = set()
    seen_sym: set[str] = set()
    seen_ep: set[str] = set()

    for sr in scope_results:
        for ev in sr.env_vars:
            key = (ev.name, ev.citation.file)
            if key not in seen_env:
                seen_env.add(key)
                all_env.append(ev)
        for sym in sr.public_api:
            key = f"{sym.citation.file}::{sym.name}"
            if key not in seen_sym:
                seen_sym.add(key)
                all_api.append(sym)
        for ep in sr.entrypoints:
            if ep not in seen_ep:
                seen_ep.add(ep)
                all_entrypoints.append(ep)

    all_env.sort(key=lambda e: e.name)
    all_api.sort(key=lambda s: (s.citation.file, s.name))
    all_entrypoints.sort()

    scope_edges = _compute_scope_edges(scope_results)

    return DocsIndex(
        repo_path=repo_path,
        generated_at=datetime.now(timezone.utc).isoformat(),
        scopes=scope_results,
        env_vars=all_env,
        public_api=all_api,
        entrypoints=all_entrypoints,
        scope_edges=scope_edges,
    )


def _dedupe_mermaid(mermaid: str) -> str:
    """Remove duplicate lines from LLM-generated Mermaid to prevent parse errors."""
    seen: set[str] = set()
    out: list[str] = []
    for line in mermaid.splitlines():
        stripped = line.strip()
        # Always keep structural lines (graph, subgraph, end, empty, classDef)
        if stripped in ("", "end") or stripped.startswith(("graph ", "subgraph ", "classDef ", "class ")):
            # For subgraph/classDef/class, dedupe them too
            if stripped.startswith(("subgraph ", "classDef ", "class ")):
                if stripped in seen:
                    continue
                seen.add(stripped)
            out.append(line)
        else:
            if stripped in seen:
                continue
            seen.add(stripped)
            out.append(line)
    return "\n".join(out)


async def reduce_with_llm(
    scope_results: list[ScopeResult],
    repo_path: str,
    llm_client: object,
) -> DocsIndex:
    """Merge scope results and use LLM for cross-scope analysis + Mermaid graph."""
    from .llm import LLMClient
    assert isinstance(llm_client, LLMClient)

    # First do the mechanical merge.
    index = reduce(scope_results, repo_path)

    scope_block = _build_scope_block(scope_results)
    edges_block = ", ".join(f"{a} -> {b}" for a, b in index.scope_edges) or "(none detected)"
    ep_block = ", ".join(index.entrypoints) or "(none)"

    # Run cross-scope analysis and Mermaid generation in parallel.
    async def _analysis_task() -> str | None:
        try:
            return await llm_client.ask(
                _ANALYSIS_PROMPT.format(
                    repo_path=repo_path,
                    scope_block=scope_block,
                    edges_block=edges_block,
                ),
                system=_ANALYSIS_SYSTEM,
            )
        except Exception as exc:
            logger.warning("LLM cross-scope analysis failed: %s", exc)
            return None

    async def _mermaid_task() -> str | None:
        try:
            mermaid_raw = await llm_client.ask(
                _MERMAID_PROMPT.format(
                    repo_path=repo_path,
                    scope_block=scope_block,
                    edges_block=edges_block,
                    entrypoints=ep_block,
                ),
                system=_MERMAID_SYSTEM,
            )
            mermaid = mermaid_raw.strip()
            if mermaid.startswith("```"):
                mermaid = mermaid.split("\n", 1)[1]
            if mermaid.endswith("```"):
                mermaid = mermaid.rsplit("```", 1)[0]
            mermaid = mermaid.strip()
            if mermaid.startswith("graph"):
                return _dedupe_mermaid(mermaid)
            return None
        except Exception as exc:
            logger.warning("LLM Mermaid generation failed: %s", exc)
            return None

    analysis, mermaid = await asyncio.gather(_analysis_task(), _mermaid_task())
    if analysis:
        index.cross_scope_analysis = analysis
    if mermaid:
        index.mermaid_graph = mermaid

    return index
