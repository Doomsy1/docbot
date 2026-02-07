"""Reducer -- merge per-scope results into a global docs index."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import PurePosixPath

from .models import DocsIndex, EnvVar, PublicSymbol, ScopeResult

logger = logging.getLogger(__name__)

_ANALYSIS_SYSTEM = """\
You are a technical writer explaining how a software project works to a new \
developer. Write clearly and concisely. Focus on the big picture -- what the \
program does and how it works -- not on individual files or symbols."""

_ANALYSIS_PROMPT = """\
Based on the scope data below, write a high-level overview of how this \
{languages} program works.

Repository: {repo_path}

Scopes:
{scope_block}

Dependency edges (scope -> scope):
{edges_block}

Write a clear, readable overview using markdown formatting (headings, bullets, \
bold). Structure it as:

## What it does
One paragraph: what is this program and what problem does it solve?

## How it works
Describe the main user/data flow from start to finish. Use a numbered list \
or short paragraphs. Focus on what happens when someone uses the program, \
not internal implementation details.

## Key components
A short bullet list of the major parts and what each one is responsible for. \
Use plain language, not scope IDs.

## Tech stack
One-liner or short bullet list of languages, frameworks, and key technologies.

Keep the total length under 300 words. No file paths or symbol names -- just \
describe the system at a level that helps someone quickly understand the project."""

_MERMAID_SYSTEM = """\
You are a software architect creating a Mermaid architecture diagram. \
Return ONLY valid Mermaid syntax starting with "graph TD". No markdown fences. \
No commentary before or after the diagram. CRITICAL: Define each node EXACTLY \
ONCE. Never redefine a node with a different label or shape."""

_MERMAID_PROMPT = """\
Create a Mermaid architecture diagram for this {languages} repository.

STRICT requirements:
- Use "graph TD" (top-down layout).
- Use simple alpha-numeric IDs (s1, s2, etc).
- CRITICAL: Wrap all labels in double quotes (e.g. id1["Main Logic"]).
- Return ONLY the Mermaid code. No markdown fences. No commentary.

Scopes:
{scope_block}

Edges: {edges_block}
"""


# Common source-file extensions to strip when building path-based scope lookups.
_SOURCE_EXTS = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java",
    ".kt", ".cs", ".swift", ".rb", ".cpp", ".c", ".h", ".hpp",
})


def _compute_scope_edges(scope_results: list[ScopeResult]) -> list[tuple[str, str]]:
    """Infer directed edges (from_scope -> to_scope) based on import statements.

    Uses two strategies:
      1. File-path-based matching (works for any language).
      2. Dotted-prefix matching (works for Python-style imports).
    """
    # Strategy 1: map each file path (minus extension) to its scope.
    path_to_scope: dict[str, str] = {}
    for sr in scope_results:
        for p in sr.paths:
            # Store full path without extension: "src/docbot/cli" -> scope_id
            stem, ext = os.path.splitext(p)
            path_to_scope[stem] = sr.scope_id
            # Also store the basename alone for short imports
            path_to_scope[PurePosixPath(stem).name] = sr.scope_id

    # Strategy 2: dotted prefix map (original Python approach).
    prefix_to_scope: dict[str, str] = {}
    for sr in scope_results:
        for p in sr.paths:
            parts = PurePosixPath(p).parts
            for i in range(1, len(parts) + 1):
                segment = list(parts[:i])
                base, ext = os.path.splitext(segment[-1])
                if ext in _SOURCE_EXTS:
                    segment[-1] = base
                dotted = ".".join(segment)
                prefix_to_scope[dotted] = sr.scope_id

    edges: set[tuple[str, str]] = set()
    for sr in scope_results:
        for imp in sr.imports:
            found = False

            # Try file-path matching first (handles "./foo", "../bar", "@scope/pkg").
            # Normalise common path-style imports.
            normalised = imp.lstrip("./").replace("\\", "/")
            stem, ext = os.path.splitext(normalised)
            if ext in _SOURCE_EXTS:
                normalised = stem
            target = path_to_scope.get(normalised)
            if target and target != sr.scope_id:
                edges.add((sr.scope_id, target))
                found = True

            # Fall back to dotted-prefix matching.
            if not found:
                parts = imp.split(".")
                for i in range(len(parts), 0, -1):
                    candidate = ".".join(parts[:i])
                    target = prefix_to_scope.get(candidate)
                    if target and target != sr.scope_id:
                        edges.add((sr.scope_id, target))
                        break

    # Connect orphan scopes by shared directory prefix so nothing floats alone.
    connected = {sid for pair in edges for sid in pair}
    all_ids = {sr.scope_id for sr in scope_results}
    orphans = all_ids - connected

    if orphans:
        # Build scope -> primary directory mapping
        scope_dirs: dict[str, str] = {}
        for sr in scope_results:
            if sr.paths:
                first = sr.paths[0].replace("\\", "/")
                parts = first.split("/")
                scope_dirs[sr.scope_id] = "/".join(parts[:2]) if len(parts) > 1 else parts[0]

        for orphan in orphans:
            orphan_dir = scope_dirs.get(orphan, "")
            best_match: str | None = None
            best_len = 0
            for sid in connected:
                sid_dir = scope_dirs.get(sid, "")
                # Find the connected scope sharing the longest directory prefix
                common = os.path.commonprefix([orphan_dir, sid_dir])
                if len(common) > best_len:
                    best_len = len(common)
                    best_match = sid
            if best_match:
                edges.add((orphan, best_match))

    return sorted(edges)


def _build_scope_block(scope_results: list[ScopeResult]) -> str:
    parts = []
    for sr in scope_results:
        status = "[FAILED]" if sr.error else ""
        langs = f" [{', '.join(sr.languages)}]" if sr.languages else ""
        parts.append(f"### {sr.title} (scope_id: {sr.scope_id}){langs} {status}")
        parts.append(f"  Files: {len(sr.paths)}, Public symbols: {len(sr.public_api)}, "
                      f"Env vars: {len(sr.env_vars)}, Errors raised: {len(sr.raised_errors)}")
        if sr.entrypoints:
            parts.append(f"  Entrypoints: {', '.join(sr.entrypoints)}")
        if sr.summary:
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
    all_languages: set[str] = set()
    seen_env: set[str] = set()
    seen_sym: set[str] = set()
    seen_ep: set[str] = set()

    for sr in scope_results:
        all_languages.update(sr.languages)
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
        languages=sorted(all_languages),
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

    languages = ", ".join(index.languages) if index.languages else "software"
    scope_block = _build_scope_block(scope_results)
    edges_block = ", ".join(f"{a} -> {b}" for a, b in index.scope_edges) or "(none detected)"
    ep_block = ", ".join(index.entrypoints) or "(none)"

    # Run cross-scope analysis and Mermaid generation in parallel.
    async def _analysis_task() -> str | None:
        try:
            return await llm_client.ask(
                _ANALYSIS_PROMPT.format(
                    languages=languages,
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
                    languages=languages,
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
