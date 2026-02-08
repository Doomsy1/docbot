"""FastAPI webapp server for browsing docbot run output."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path, PurePosixPath

from fastapi.encoders import jsonable_encoder
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..llm import LLMClient
from ..models import Citation, DocsIndex
from .search import SearchIndex

logger = logging.getLogger(__name__)

app = FastAPI(title="docbot", version="0.1.0")

# Set by start_server() before uvicorn starts.
_run_dir: Path | None = None
_index_cache: DocsIndex | None = None
_search_index_cache: SearchIndex | None = None
_llm_client: LLMClient | None = None
_tours_cache: list[dict] | None = None
_service_details_cache: dict | None = None
_explore_graph_cache: dict | None = None


def _load_index() -> DocsIndex:
    """Load and cache the DocsIndex from the run directory."""
    global _index_cache
    if _index_cache is not None:
        return _index_cache

    if _run_dir is None:
        raise HTTPException(status_code=503, detail="No run directory configured.")

    index_path = _run_dir / "docs_index.json"
    if not index_path.exists():
        raise HTTPException(
            status_code=404, detail="docs_index.json not found in run directory."
        )

    _index_cache = DocsIndex.model_validate_json(index_path.read_text(encoding="utf-8"))
    return _index_cache


def _load_search_index() -> SearchIndex:
    """Load and cache the SearchIndex from the run directory."""
    global _search_index_cache
    if _search_index_cache is not None:
        return _search_index_cache

    if _run_dir is None:
        raise HTTPException(status_code=503, detail="No run directory configured.")

    search_path = _run_dir / "search_index.json"
    # Optional for now (might not exist if search step failed/skipped).
    if not search_path.exists():
        return SearchIndex()

    _search_index_cache = SearchIndex.load(search_path)
    return _search_index_cache


def _scope_group(scope) -> str:
    """Classify a scope into a coarse UI group."""
    group = "core"
    if scope.paths:
        first = scope.paths[0].replace("\\", "/")
        if first.startswith("webapp/") or first.startswith("frontend/"):
            group = "frontend"
        elif first.startswith("services/") or first.startswith("backend/"):
            group = "backend"
        elif first.startswith("tests/") or "test" in scope.scope_id:
            group = "testing"
        elif first.startswith("scripts/"):
            group = "scripts"
    return group


def _normalize_query_tokens(text: str) -> set[str]:
    """Lowercase + tokenize an arbitrary user query."""
    return set(re.findall(r"[a-z0-9_./-]+", text.lower()))


def _infer_graph_view(query: str) -> str:
    """Infer target graph depth from the user query."""
    q = query.lower()
    explicit_file_level = any(
        k in q
        for k in (
            "file level",
            "file-level",
            "files only",
            "on a file level",
            "per file",
            "file graph",
            "script files",
            "two script files",
        )
    )
    high_level = (
        "high level" in q
        or "overview" in q
        or "big picture" in q
        or "architecture" in q
        or "how it fits" in q
    )
    entity_level = any(
        k in q
        for k in (
            "entity",
            "entities",
            "symbol",
            "symbols",
            "function",
            "method",
            "class",
        )
    )
    file_level = any(
        k in q
        for k in (
            "file",
            "line",
            "implementation",
            "deep detail",
            "specific code",
            "debug",
        )
    )
    module_level = any(
        k in q
        for k in (
            "module",
            "directory",
            "package",
            "service",
            "component",
            "backend part",
            "subsystem",
        )
    )
    if explicit_file_level:
        return "file"
    if entity_level:
        return "entity"
    if file_level:
        return "file"
    if high_level and not module_level:
        return "scope"
    if module_level:
        return "module"
    return "module"


def _has_explicit_file_intent(query: str) -> bool:
    q = query.lower()
    return any(
        k in q
        for k in (
            "file level",
            "file-level",
            "files only",
            "on a file level",
            "per file",
            "file graph",
            "script files",
            "two script files",
        )
    )


def _infer_scope_filter(index: DocsIndex, query: str) -> set[str] | None:
    """Infer a scope filter from the query, or None for all scopes."""
    q = query.lower()
    tokens = _normalize_query_tokens(query)

    if "entire" in q or "whole codebase" in q or "all scopes" in q or "everything" in q:
        return None

    scopes_by_id = {s.scope_id: s for s in index.scopes}
    selected: set[str] = set()

    # Direct scope-id/title mention.
    for s in index.scopes:
        sid = s.scope_id.lower()
        title = s.title.lower()
        if sid in q or title in q:
            selected.add(s.scope_id)
            continue
        title_tokens = _normalize_query_tokens(title)
        if title_tokens and len(title_tokens.intersection(tokens)) >= max(1, min(2, len(title_tokens))):
            selected.add(s.scope_id)

    # Group hints.
    wanted_groups: set[str] = set()
    if any(k in q for k in ("backend", "api", "server", "service")):
        wanted_groups.add("backend")
    if any(k in q for k in ("frontend", "ui", "client", "webapp")):
        wanted_groups.add("frontend")
    if any(k in q for k in ("test", "testing", "qa")):
        wanted_groups.add("testing")
    if any(k in q for k in ("script", "cli", "tooling")):
        wanted_groups.add("scripts")

    if wanted_groups:
        for sid, s in scopes_by_id.items():
            if _scope_group(s) in wanted_groups:
                selected.add(sid)

    return selected or None


def _can_fast_route(query: str) -> bool:
    """Whether heuristics are explicit enough to skip LLM routing."""
    q = query.lower()
    explicit_depth = any(
        k in q
        for k in (
            "high level",
            "overview",
            "architecture",
            "module",
            "directory",
            "service",
            "file",
            "line",
            "entity",
            "symbol",
            "function",
            "method",
            "class",
            "implementation",
            "in detail",
            "specific",
        )
    )
    explicit_scope = any(
        k in q for k in ("backend", "frontend", "tests", "testing", "scripts", "whole project", "entire")
    )
    return explicit_depth or explicit_scope


def _file_to_scope_map(index: DocsIndex) -> dict[str, str]:
    """Map repo-relative file path -> scope_id."""
    out: dict[str, str] = {}
    for s in index.scopes:
        for p in s.paths:
            out[p] = s.scope_id
    return out


def _build_graph_rag_context(index: DocsIndex, query: str, *, max_scopes: int = 12) -> str:
    """Build compact local-RAG context for graph routing decisions."""
    file_to_scope = _file_to_scope_map(index)
    scope_by_id = {s.scope_id: s for s in index.scopes}
    scope_scores: dict[str, int] = {s.scope_id: 0 for s in index.scopes}

    hits = _load_search_index().search(query, limit=14)
    hit_lines: list[str] = []
    for h in hits:
        file = h.citation.file
        sid = file_to_scope.get(file)
        if sid:
            scope_scores[sid] = scope_scores.get(sid, 0) + 2
        hit_lines.append(
            f"- {h.match_context} @ {h.citation.file}:{h.citation.line_start} (score={h.score:.2f})"
        )

    query_tokens = _normalize_query_tokens(query)
    for s in index.scopes:
        text = f"{s.scope_id} {s.title}".lower()
        if any(tok in text for tok in query_tokens):
            scope_scores[s.scope_id] = scope_scores.get(s.scope_id, 0) + 3

    ranked_scopes = sorted(
        index.scopes,
        key=lambda s: (scope_scores.get(s.scope_id, 0), len(s.paths)),
        reverse=True,
    )[:max_scopes]

    scope_lines: list[str] = []
    for s in ranked_scopes:
        group = _scope_group(s)
        langs = ", ".join(s.languages[:3]) if s.languages else "unknown"
        summary = (s.summary or "").replace("\n", " ").strip()
        if len(summary) > 140:
            summary = summary[:137] + "..."
        scope_lines.append(
            f"- id={s.scope_id} | title={s.title} | group={group} | files={len(s.paths)} | langs={langs} | score={scope_scores.get(s.scope_id, 0)} | summary={summary or '(none)'}"
        )

    return (
        "Top scope candidates:\n"
        + ("\n".join(scope_lines) if scope_lines else "(none)")
        + "\n\nTop semantic hits:\n"
        + ("\n".join(hit_lines) if hit_lines else "(none)")
    )


def _match_scope_ids(index: DocsIndex, requested_ids: list[str]) -> set[str]:
    """Resolve requested scope identifiers/titles to known scope_ids."""
    if not requested_ids:
        return set()
    scopes = index.scopes
    by_id = {s.scope_id.lower(): s.scope_id for s in scopes}
    by_title = {s.title.lower(): s.scope_id for s in scopes}
    resolved: set[str] = set()

    for raw in requested_ids:
        key = raw.strip().lower()
        if not key:
            continue
        if key in by_id:
            resolved.add(by_id[key])
            continue
        if key in by_title:
            resolved.add(by_title[key])
            continue
        # Soft matching by containment in id/title.
        for s in scopes:
            sid = s.scope_id.lower()
            title = s.title.lower()
            if key in sid or sid in key or key in title or title in key:
                resolved.add(s.scope_id)
                break
    return resolved


async def _route_graph_with_llm(index: DocsIndex, query: str) -> tuple[str, set[str] | None, str]:
    """LLM-based routing for graph view and scope filters using local RAG context."""
    if _llm_client is None:
        view = _infer_graph_view(query)
        return view, _infer_scope_filter(index, query), "Heuristic routing (LLM unavailable)."

    rag_context = _build_graph_rag_context(index, query)
    allowed_ids = [s.scope_id for s in index.scopes]
    prompt = f"""You are routing a graph UI for code exploration.

User query:
{query}

Available scope IDs:
{", ".join(allowed_ids)}

Context:
{rag_context}

Return JSON only with this schema:
{{
  "view": "scope" | "module" | "file" | "entity",
  "scope_mode": "all" | "filtered",
  "scope_ids": ["scope_id_or_title", "..."],
  "reason": "short explanation"
}}

Rules:
- Choose "scope" for big-picture architecture.
- Choose "module" for component/directory/service-level exploration.
- Choose "file" for implementation-level/debugging.
- Choose "entity" for function/class/method-level relationships.
- If user asks whole project, use scope_mode="all".
- If user asks backend/frontend/tests/scripts or specific subsystem, use scope_mode="filtered" and include relevant scope IDs.
- Keep reason under 18 words.
"""
    try:
        # Keep routing fast; fall back if model is slow/unavailable.
        raw = await asyncio.wait_for(_llm_client.ask(prompt, json_mode=True), timeout=7.0)
        data = json.loads(raw)
        view = data.get("view", "module")
        if view not in {"scope", "module", "file", "entity"}:
            view = "module"
        scope_mode = data.get("scope_mode", "filtered")
        requested = data.get("scope_ids") or []
        if not isinstance(requested, list):
            requested = []
        matched = _match_scope_ids(index, [str(x) for x in requested])
        if scope_mode == "all":
            scope_filter = None
        else:
            scope_filter = matched or _infer_scope_filter(index, query)
        reason = str(data.get("reason") or "LLM-routed using docbot local context.")
        return view, scope_filter, reason
    except Exception as exc:
        logger.warning("Graph LLM routing failed, falling back to heuristics: %s", exc)
        view = _infer_graph_view(query)
        return view, _infer_scope_filter(index, query), "Heuristic fallback (LLM route timed out/failed)."


def _build_scope_graph(index: DocsIndex, include_scopes: set[str] | None = None) -> dict:
    """Build scope-level graph payload."""
    scopes_meta = []
    for s in index.scopes:
        if include_scopes is not None and s.scope_id not in include_scopes:
            continue
        scopes_meta.append(
            {
                "scope_id": s.scope_id,
                "title": s.title,
                "file_count": len(s.paths),
                "symbol_count": len(s.public_api),
                "languages": s.languages,
                "group": _scope_group(s),
                "summary": s.summary,
                "description": (
                    s.summary
                    or f"{s.title} contains {len(s.paths)} files across {', '.join(s.languages) if s.languages else 'unknown languages'}."
                ),
            }
        )
    edge_items = []
    for a, b in index.scope_edges:
        if include_scopes is not None and (a not in include_scopes or b not in include_scopes):
            continue
        edge_items.append({"from": a, "to": b})
    return {
        "scopes": scopes_meta,
        "scope_edges": edge_items,
        "mermaid_graph": index.mermaid_graph or None,
    }


def _build_file_graph(index: DocsIndex, include_scopes: set[str] | None = None) -> dict:
    """Build file-level graph payload."""
    path_to_file: dict[str, str] = {}
    prefix_to_file: dict[str, str] = {}
    source_exts = frozenset(
        {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".go",
            ".rs",
            ".java",
            ".kt",
            ".cs",
            ".swift",
            ".rb",
            ".cpp",
            ".c",
            ".h",
            ".hpp",
        }
    )
    lang_exts: dict[str, str] = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin",
        ".cs": "csharp",
        ".swift": "swift",
        ".rb": "ruby",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "c",
        ".hpp": "cpp",
    }

    for s in index.scopes:
        if include_scopes is not None and s.scope_id not in include_scopes:
            continue
        for p in s.paths:
            stem, _ext = os.path.splitext(p)
            path_to_file[stem] = p
            path_to_file[PurePosixPath(stem).name] = p
            parts = PurePosixPath(p).parts
            for i in range(1, len(parts) + 1):
                segment = list(parts[:i])
                base, ext2 = os.path.splitext(segment[-1])
                if ext2 in source_exts:
                    segment[-1] = base
                prefix_to_file[".".join(segment)] = p

    file_nodes: list[dict] = []
    file_edges: list[dict] = []
    for s in index.scopes:
        if include_scopes is not None and s.scope_id not in include_scopes:
            continue
        group = _scope_group(s)
        for p in s.paths:
            ext = os.path.splitext(p)[1].lower()
            language = lang_exts.get(ext, "unknown")
            fe = s.file_extractions.get(p)
            file_nodes.append(
                {
                    "id": p,
                    "path": p,
                    "scope_id": s.scope_id,
                    "scope_title": s.title,
                    "symbol_count": len(fe.symbols) if fe else 0,
                    "import_count": len(fe.imports) if fe else 0,
                    "language": language,
                    "group": group,
                    "description": (
                        f"File {p} in {s.title}. "
                        f"Contains {len(fe.symbols) if fe else 0} entities and {len(fe.imports) if fe else 0} imports."
                    ),
                }
            )
            if fe:
                for imp in fe.imports:
                    target_file = _resolve_import_to_file(imp, path_to_file, prefix_to_file, source_exts)
                    if target_file and target_file != p:
                        file_edges.append({"from": p, "to": target_file})

    scope_groups = []
    for s in index.scopes:
        if include_scopes is not None and s.scope_id not in include_scopes:
            continue
        scope_groups.append(
            {
                "scope_id": s.scope_id,
                "title": s.title,
                "file_count": len(s.paths),
                "group": _scope_group(s),
            }
        )
    scope_edges = []
    for a, b in index.scope_edges:
        if include_scopes is not None and (a not in include_scopes or b not in include_scopes):
            continue
        scope_edges.append({"from": a, "to": b})

    return {
        "file_nodes": file_nodes,
        "file_edges": file_edges,
        "scope_groups": scope_groups,
        "scope_edges": scope_edges,
    }


def _build_module_graph(index: DocsIndex, include_scopes: set[str] | None = None) -> dict:
    """Build module-level graph payload (directory nodes + weighted edges)."""
    path_to_file: dict[str, str] = {}
    prefix_to_file: dict[str, str] = {}
    source_exts = frozenset(
        {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".go",
            ".rs",
            ".java",
            ".kt",
            ".cs",
            ".swift",
            ".rb",
            ".cpp",
            ".c",
            ".h",
            ".hpp",
        }
    )
    lang_exts: dict[str, str] = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin",
        ".cs": "csharp",
        ".swift": "swift",
        ".rb": "ruby",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "c",
        ".hpp": "cpp",
    }

    for s in index.scopes:
        if include_scopes is not None and s.scope_id not in include_scopes:
            continue
        for p in s.paths:
            stem, _ext = os.path.splitext(p)
            path_to_file[stem] = p
            path_to_file[PurePosixPath(stem).name] = p
            parts = PurePosixPath(p).parts
            for i in range(1, len(parts) + 1):
                segment = list(parts[:i])
                base, ext2 = os.path.splitext(segment[-1])
                if ext2 in source_exts:
                    segment[-1] = base
                prefix_to_file[".".join(segment)] = p

    file_to_module: dict[str, str] = {}
    module_stats: dict[str, dict] = {}
    for s in index.scopes:
        if include_scopes is not None and s.scope_id not in include_scopes:
            continue
        group = _scope_group(s)
        for p in s.paths:
            module_id = os.path.dirname(p).replace("\\", "/") or "."
            file_to_module[p] = module_id
            fe = s.file_extractions.get(p)
            symbol_count = len(fe.symbols) if fe else 0
            import_count = len(fe.imports) if fe else 0
            language = lang_exts.get(os.path.splitext(p)[1].lower(), "unknown")
            if module_id not in module_stats:
                module_stats[module_id] = {
                    "id": module_id,
                    "label": os.path.basename(module_id) if module_id != "." else "(root)",
                    "scope_id": s.scope_id,
                    "scope_title": s.title,
                    "file_count": 0,
                    "symbol_count": 0,
                    "import_count": 0,
                    "languages": set(),
                    "group": group,
                    "paths": [],
                    "symbol_names": set(),
                }
            st = module_stats[module_id]
            st["file_count"] += 1
            st["symbol_count"] += symbol_count
            st["import_count"] += import_count
            st["paths"].append(p)
            if language != "unknown":
                st["languages"].add(language)
            if fe:
                for sym in fe.symbols[:12]:
                    st["symbol_names"].add(sym.name)

    module_nodes = []
    for m in module_stats.values():
        symbol_preview = ", ".join(sorted(m["symbol_names"])[:4]) or "no named entities extracted"
        module_nodes.append(
            {
                "id": m["id"],
                "label": m["label"],
                "scope_id": m["scope_id"],
                "scope_title": m["scope_title"],
                "file_count": m["file_count"],
                "symbol_count": m["symbol_count"],
                "import_count": m["import_count"],
                "languages": sorted(m["languages"]),
                "group": m["group"],
                "description": (
                    f"Module {m['id']} in {m['scope_title']}. "
                    f"Contains {m['file_count']} files, {m['symbol_count']} entities, {m['import_count']} imports. "
                    f"Examples: {symbol_preview}."
                ),
            }
        )

    edge_counts: dict[tuple[str, str], int] = {}
    for s in index.scopes:
        if include_scopes is not None and s.scope_id not in include_scopes:
            continue
        for p in s.paths:
            fe = s.file_extractions.get(p)
            if not fe:
                continue
            src_module = file_to_module.get(p)
            if not src_module:
                continue
            for imp in fe.imports:
                target_file = _resolve_import_to_file(imp, path_to_file, prefix_to_file, source_exts)
                if not target_file or target_file == p:
                    continue
                dst_module = file_to_module.get(target_file)
                if not dst_module or dst_module == src_module:
                    continue
                key = (src_module, dst_module)
                edge_counts[key] = edge_counts.get(key, 0) + 1
    module_edges = [{"from": a, "to": b, "weight": w} for (a, b), w in edge_counts.items()]

    scope_groups = []
    for s in index.scopes:
        if include_scopes is not None and s.scope_id not in include_scopes:
            continue
        scope_groups.append(
            {
                "scope_id": s.scope_id,
                "title": s.title,
                "file_count": len(s.paths),
                "group": _scope_group(s),
            }
        )
    return {
        "module_nodes": module_nodes,
        "module_edges": module_edges,
        "scope_groups": scope_groups,
    }


def _build_entity_graph(
    index: DocsIndex,
    include_scopes: set[str] | None = None,
    *,
    query: str | None = None,
    connected_only: bool = True,
) -> dict:
    """Build entity-level graph payload from extracted symbols and import-derived dependencies."""
    source_exts = frozenset(
        {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".go",
            ".rs",
            ".java",
            ".kt",
            ".cs",
            ".swift",
            ".rb",
            ".cpp",
            ".c",
            ".h",
            ".hpp",
        }
    )
    lang_exts: dict[str, str] = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin",
        ".cs": "csharp",
        ".swift": "swift",
        ".rb": "ruby",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "c",
        ".hpp": "cpp",
    }

    path_to_file: dict[str, str] = {}
    prefix_to_file: dict[str, str] = {}
    for s in index.scopes:
        if include_scopes is not None and s.scope_id not in include_scopes:
            continue
        for p in s.paths:
            stem, _ext = os.path.splitext(p)
            path_to_file[stem] = p
            path_to_file[PurePosixPath(stem).name] = p
            parts = PurePosixPath(p).parts
            for i in range(1, len(parts) + 1):
                segment = list(parts[:i])
                base, ext2 = os.path.splitext(segment[-1])
                if ext2 in source_exts:
                    segment[-1] = base
                prefix_to_file[".".join(segment)] = p

    # Build entity nodes.
    entity_nodes: list[dict] = []
    file_entities: dict[str, list[str]] = {}
    for s in index.scopes:
        if include_scopes is not None and s.scope_id not in include_scopes:
            continue
        group = _scope_group(s)
        for p in s.paths:
            fe = s.file_extractions.get(p)
            language = lang_exts.get(os.path.splitext(p)[1].lower(), "unknown")
            if not fe or not fe.symbols:
                continue
            kept_symbol_ids: list[str] = []
            for sym in fe.symbols[:8]:
                eid = f"{sym.citation.file}:{sym.citation.line_start}:{sym.name}"
                kept_symbol_ids.append(eid)
                entity_nodes.append(
                    {
                        "id": eid,
                        "name": sym.name,
                        "kind": sym.kind,
                        "signature": sym.signature,
                        "file": sym.citation.file,
                        "line_start": sym.citation.line_start,
                        "scope_id": s.scope_id,
                        "scope_title": s.title,
                        "module_id": os.path.dirname(sym.citation.file).replace("\\", "/") or ".",
                        "language": language,
                        "group": group,
                        "description": (
                            sym.docstring_first_line
                            or f"{sym.kind.title()} `{sym.name}` defined in {sym.citation.file}:{sym.citation.line_start}."
                        ),
                    }
                )
            if kept_symbol_ids:
                file_entities[p] = kept_symbol_ids

    # Cap node count for browser performance before edge construction.
    max_nodes = 260
    if len(entity_nodes) > max_nodes:
        kept_ids = {n["id"] for n in entity_nodes[:max_nodes]}
        entity_nodes = entity_nodes[:max_nodes]
        file_entities = {k: [eid for eid in v if eid in kept_ids] for k, v in file_entities.items()}

    # Build entity edges by lifting file import dependencies.
    edge_counts: dict[tuple[str, str], int] = {}
    for s in index.scopes:
        if include_scopes is not None and s.scope_id not in include_scopes:
            continue
        for p in s.paths:
            fe = s.file_extractions.get(p)
            if not fe:
                continue
            src_entities = file_entities.get(p, [])
            if not src_entities:
                continue
            for imp in fe.imports:
                target_file = _resolve_import_to_file(imp, path_to_file, prefix_to_file, source_exts)
                if not target_file or target_file == p:
                    continue
                dst_entities = file_entities.get(target_file, [])
                if not dst_entities:
                    continue
                for src_eid in src_entities[:3]:
                    for dst_eid in dst_entities[:3]:
                        key = (src_eid, dst_eid)
                        edge_counts[key] = edge_counts.get(key, 0) + 1

    entity_edges = [{"from": a, "to": b, "weight": w} for (a, b), w in edge_counts.items()]

    # Keep connected entities by default for readability; preserve query matches if provided.
    if connected_only and entity_nodes:
        connected_ids: set[str] = set()
        for e in entity_edges:
            connected_ids.add(e["from"])
            connected_ids.add(e["to"])

        query_tokens = _normalize_query_tokens(query or "")
        query_ids: set[str] = set()
        if query_tokens:
            for n in entity_nodes:
                hay = f"{n['name']} {n['signature']} {n['file']} {n['module_id']}".lower()
                if any(tok in hay for tok in query_tokens):
                    query_ids.add(n["id"])

        keep_ids = connected_ids | query_ids
        if keep_ids:
            entity_nodes = [n for n in entity_nodes if n["id"] in keep_ids]
            keep_set = {n["id"] for n in entity_nodes}
            entity_edges = [e for e in entity_edges if e["from"] in keep_set and e["to"] in keep_set]

    # Final cap after filtering (keeps densest part by edge participation).
    if len(entity_nodes) > 140:
        degree: dict[str, int] = {}
        for e in entity_edges:
            degree[e["from"]] = degree.get(e["from"], 0) + 1
            degree[e["to"]] = degree.get(e["to"], 0) + 1
        ranked_ids = [n["id"] for n in sorted(entity_nodes, key=lambda n: degree.get(n["id"], 0), reverse=True)]
        keep_ids = set(ranked_ids[:140])
        entity_nodes = [n for n in entity_nodes if n["id"] in keep_ids]
        entity_edges = [e for e in entity_edges if e["from"] in keep_ids and e["to"] in keep_ids]

    scope_groups = []
    for s in index.scopes:
        if include_scopes is not None and s.scope_id not in include_scopes:
            continue
        scope_groups.append(
            {
                "scope_id": s.scope_id,
                "title": s.title,
                "file_count": len(s.paths),
                "group": _scope_group(s),
            }
        )

    return {
        "entity_nodes": entity_nodes,
        "entity_edges": entity_edges,
        "scope_groups": scope_groups,
    }


def _excerpt_for_file(file_path: str, *, line_start: int | None = None, radius: int = 5) -> str | None:
    """Return a small code excerpt for hover cards."""
    index = _load_index()
    repo_root = Path(index.repo_path).resolve()
    target = (repo_root / file_path).resolve()
    try:
        target.relative_to(repo_root)
    except ValueError:
        return None
    if not target.exists() or not target.is_file():
        return None
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None
    if not lines:
        return None
    if line_start is None:
        line_start = 1
    start = max(1, line_start - radius)
    end = min(len(lines), line_start + radius)
    excerpt = "\n".join(f"{i:>4} | {lines[i - 1]}" for i in range(start, end + 1))
    return excerpt[:2000]


def _build_explore_catalog(index: DocsIndex) -> dict:
    """Build and cache full graph primitives used by adaptive mixed-depth rendering."""
    global _explore_graph_cache
    cache_key = f"{index.repo_path}:{index.generated_at}:{len(index.scopes)}"
    if _explore_graph_cache and _explore_graph_cache.get("key") == cache_key:
        return _explore_graph_cache["data"]

    source_exts = frozenset(
        {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".go",
            ".rs",
            ".java",
            ".kt",
            ".cs",
            ".swift",
            ".rb",
            ".cpp",
            ".c",
            ".h",
            ".hpp",
        }
    )

    scopes: dict[str, dict] = {}
    modules: dict[str, dict] = {}
    files: dict[str, dict] = {}
    entities: dict[str, dict] = {}
    file_to_scope: dict[str, str] = {}
    file_to_module: dict[str, str] = {}
    file_entities: dict[str, list[str]] = {}

    path_to_file: dict[str, str] = {}
    prefix_to_file: dict[str, str] = {}
    for s in index.scopes:
        scopes[s.scope_id] = {
            "id": f"scope:{s.scope_id}",
            "scope_id": s.scope_id,
            "label": s.title,
            "kind": "scope",
            "group": _scope_group(s),
            "file_count": len(s.paths),
            "entity_count": sum(len(s.file_extractions.get(p).symbols) if s.file_extractions.get(p) else 0 for p in s.paths),
            "description": s.summary or f"{s.title} scope",
            "preview": None,
        }
        for p in s.paths:
            stem, _ext = os.path.splitext(p)
            path_to_file[stem] = p
            path_to_file[PurePosixPath(stem).name] = p
            parts = PurePosixPath(p).parts
            for i in range(1, len(parts) + 1):
                segment = list(parts[:i])
                base, ext2 = os.path.splitext(segment[-1])
                if ext2 in source_exts:
                    segment[-1] = base
                prefix_to_file[".".join(segment)] = p

    for s in index.scopes:
        group = _scope_group(s)
        for p in s.paths:
            module_path = os.path.dirname(p).replace("\\", "/") or "."
            module_key = f"module:{s.scope_id}:{module_path}"
            file_key = f"file:{p}"
            file_to_scope[p] = s.scope_id
            file_to_module[p] = module_key
            fe = s.file_extractions.get(p)
            symbols = fe.symbols if fe else []
            imports = fe.imports if fe else []

            if module_key not in modules:
                modules[module_key] = {
                    "id": module_key,
                    "module_path": module_path,
                    "scope_id": s.scope_id,
                    "kind": "module",
                    "label": os.path.basename(module_path) if module_path != "." else "(root)",
                    "group": group,
                    "file_count": 0,
                    "entity_count": 0,
                    "import_count": 0,
                    "description": f"{module_path} module in {s.title}",
                    "preview": None,
                }
            modules[module_key]["file_count"] += 1
            modules[module_key]["entity_count"] += len(symbols)
            modules[module_key]["import_count"] += len(imports)

            files[file_key] = {
                "id": file_key,
                "file_path": p,
                "scope_id": s.scope_id,
                "module_id": module_key,
                "kind": "file",
                "label": os.path.basename(p),
                "group": group,
                "file_count": 1,
                "entity_count": len(symbols),
                "import_count": len(imports),
                "description": f"{p} with {len(symbols)} entities and {len(imports)} imports",
                "preview": _excerpt_for_file(p, line_start=1, radius=6),
            }

            entity_ids: list[str] = []
            for sym in symbols[:16]:
                entity_key = f"entity:{sym.citation.file}:{sym.citation.line_start}:{sym.name}"
                entity_ids.append(entity_key)
                entities[entity_key] = {
                    "id": entity_key,
                    "entity_name": sym.name,
                    "entity_kind": sym.kind,
                    "line_start": sym.citation.line_start,
                    "file_path": sym.citation.file,
                    "scope_id": s.scope_id,
                    "module_id": module_key,
                    "kind": "entity",
                    "label": sym.name,
                    "group": group,
                    "file_count": 1,
                    "entity_count": 1,
                    "import_count": 0,
                    "description": sym.docstring_first_line or f"{sym.kind} in {sym.citation.file}:{sym.citation.line_start}",
                    "preview": _excerpt_for_file(sym.citation.file, line_start=sym.citation.line_start, radius=7),
                }
            file_entities[p] = entity_ids

    scope_edges = [{"from": f"scope:{a}", "to": f"scope:{b}", "kind": "scope_dep", "weight": 1} for a, b in index.scope_edges]
    module_edge_counts: dict[tuple[str, str], int] = {}
    file_edges: list[dict] = []
    entity_cross_counts: dict[tuple[str, str], int] = {}
    entity_intra_edges: list[dict] = []

    for s in index.scopes:
        for p in s.paths:
            fe = s.file_extractions.get(p)
            if not fe:
                continue
            src_file_key = f"file:{p}"
            src_module_key = file_to_module.get(p)
            for imp in fe.imports:
                target_file = _resolve_import_to_file(imp, path_to_file, prefix_to_file, source_exts)
                if not target_file or target_file == p:
                    continue
                dst_file_key = f"file:{target_file}"
                dst_module_key = file_to_module.get(target_file)
                if src_module_key and dst_module_key and src_module_key != dst_module_key:
                    k = (src_module_key, dst_module_key)
                    module_edge_counts[k] = module_edge_counts.get(k, 0) + 1
                file_edges.append(
                    {
                        "from": src_file_key,
                        "to": dst_file_key,
                        "kind": "file_dep",
                        "weight": 1,
                    }
                )
                src_entities = file_entities.get(p, [])[:3]
                dst_entities = file_entities.get(target_file, [])[:3]
                for a in src_entities:
                    for b in dst_entities:
                        k2 = (a, b)
                        entity_cross_counts[k2] = entity_cross_counts.get(k2, 0) + 1

            # in-file relationship chain for visual distinction
            eids = file_entities.get(p, [])
            for i in range(len(eids) - 1):
                entity_intra_edges.append(
                    {
                        "from": eids[i],
                        "to": eids[i + 1],
                        "kind": "entity_intra_file",
                        "weight": 1,
                    }
                )

    module_edges = [{"from": a, "to": b, "kind": "module_dep", "weight": w} for (a, b), w in module_edge_counts.items()]
    entity_edges = (
        [{"from": a, "to": b, "kind": "entity_cross_file", "weight": w} for (a, b), w in entity_cross_counts.items()]
        + entity_intra_edges
    )

    out = {
        "scopes": scopes,
        "modules": modules,
        "files": files,
        "entities": entities,
        "file_to_scope": file_to_scope,
        "file_to_module": file_to_module,
        "file_entities": file_entities,
        "scope_edges": scope_edges,
        "module_edges": module_edges,
        "file_edges": file_edges,
        "entity_edges": entity_edges,
    }
    _explore_graph_cache = {"key": cache_key, "data": out}
    return out


def _collect_one_hop_entities(catalog: dict, focused_file_path: str, *, limit: int = 120) -> set[str]:
    """Keep focused file entities plus 1-hop neighbors."""
    focus_ids = set(catalog["file_entities"].get(focused_file_path, []))
    if not focus_ids:
        return set()
    keep = set(focus_ids)
    for e in catalog["entity_edges"]:
        a = e["from"]
        b = e["to"]
        if a in focus_ids or b in focus_ids:
            keep.add(a)
            keep.add(b)
        if len(keep) >= limit:
            break
    return keep


def _resolve_view_depth(view: str) -> int:
    return {"scope": 0, "module": 1, "file": 2, "entity": 3}.get(view, 0)


def _build_explore_scene(
    index: DocsIndex,
    *,
    view: str,
    focus_scope_id: str | None,
    focus_module_id: str | None,
    focus_file_id: str | None,
    highlighted_node_id: str | None = None,
) -> dict:
    """Build a single-canvas mixed-depth graph scene."""
    catalog = _build_explore_catalog(index)
    depth = _resolve_view_depth(view)

    nodes: dict[str, dict] = {}
    visible_module_ids: set[str] = set()
    visible_file_ids: set[str] = set()
    visible_entity_ids: set[str] = set()

    # scope baseline
    for sid, s in catalog["scopes"].items():
        if depth >= 1 and focus_scope_id and sid == focus_scope_id:
            continue
        nodes[s["id"]] = dict(s)

    # scope -> module expansion
    if depth >= 1 and focus_scope_id:
        for mid, m in catalog["modules"].items():
            if m["scope_id"] != focus_scope_id:
                continue
            if depth >= 2 and focus_module_id and mid == focus_module_id:
                continue
            nodes[mid] = dict(m)
            visible_module_ids.add(mid)

    # module -> file expansion
    if depth >= 2 and focus_module_id:
        for fid, f in catalog["files"].items():
            if f["module_id"] != focus_module_id:
                continue
            if depth >= 3 and focus_file_id and fid == focus_file_id:
                continue
            nodes[fid] = dict(f)
            visible_file_ids.add(fid)

    # file -> entity expansion
    if depth >= 3 and focus_file_id:
        file_path = focus_file_id.removeprefix("file:")
        keep_entity_ids = _collect_one_hop_entities(catalog, file_path)
        for eid in keep_entity_ids:
            en = catalog["entities"].get(eid)
            if not en:
                continue
            nodes[eid] = dict(en)
            visible_entity_ids.add(eid)

    def rep_for_file(file_path: str) -> str | None:
        fid = f"file:{file_path}"
        mid = catalog["file_to_module"].get(file_path)
        sid = catalog["file_to_scope"].get(file_path)
        if depth >= 3 and focus_file_id and fid == focus_file_id:
            return None  # represented by entity nodes
        if depth >= 2 and focus_module_id and mid == focus_module_id:
            return fid if fid in nodes else None
        if depth >= 1 and focus_scope_id and sid == focus_scope_id:
            return mid if mid in nodes else None
        return f"scope:{sid}" if sid else None

    edges: dict[str, dict] = {}

    def add_edge(frm: str, to: str, kind: str, weight: int = 1):
        if frm == to or frm not in nodes or to not in nodes:
            return
        key = f"{frm}|{to}|{kind}"
        if key not in edges:
            edges[key] = {"id": key, "from": frm, "to": to, "kind": kind, "weight": weight, "directed": True}
        else:
            edges[key]["weight"] += weight

    # Mixed-level dependency edges mapped from file dependencies.
    for e in catalog["file_edges"]:
        src_fp = e["from"].removeprefix("file:")
        dst_fp = e["to"].removeprefix("file:")
        a = rep_for_file(src_fp)
        b = rep_for_file(dst_fp)
        if not a or not b:
            continue
        mapped_kind = "dep"
        if a.startswith("scope:") and b.startswith("scope:"):
            mapped_kind = "scope_dep"
        elif a.startswith("module:") or b.startswith("module:"):
            mapped_kind = "module_dep"
        elif a.startswith("file:") or b.startswith("file:"):
            mapped_kind = "file_dep"
        add_edge(a, b, mapped_kind, 1)

    # Focused entity edges.
    if depth >= 3 and visible_entity_ids:
        for e in catalog["entity_edges"]:
            a = e["from"]
            b = e["to"]
            if a in visible_entity_ids and b in visible_entity_ids:
                add_edge(a, b, e["kind"], e.get("weight", 1))

    node_list = [jsonable_encoder(v) for v in nodes.values()]
    edge_list = [jsonable_encoder(v) for v in edges.values()]

    return {
        "state": {
            "view": view,
            "focus_scope_id": focus_scope_id,
            "focus_module_id": focus_module_id,
            "focus_file_id": focus_file_id,
        },
        "nodes": node_list,
        "edges": edge_list,
        "highlighted_node_id": highlighted_node_id,
        "metrics": {
            "node_count": len(node_list),
            "edge_count": len(edge_list),
            "scope_nodes": sum(1 for n in node_list if n.get("kind") == "scope"),
            "module_nodes": sum(1 for n in node_list if n.get("kind") == "module"),
            "file_nodes": sum(1 for n in node_list if n.get("kind") == "file"),
            "entity_nodes": sum(1 for n in node_list if n.get("kind") == "entity"),
        },
    }


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@app.get("/api/search", response_model=list[dict])
async def search(q: str) -> list[dict]:
    """Search for symbols and files."""
    if not q:
        return []

    results = _load_search_index().search(q, limit=20)
    return [
        {
            "citation": r.citation.model_dump(),
            "score": r.score,
            "match_context": r.match_context,
        }
        for r in results
    ]


@app.get("/api/index")
async def get_index() -> JSONResponse:
    """Return the full DocsIndex (top-level summary)."""
    index = _load_index()
    # Build scope summaries for the dashboard
    scopes_summary = []
    for s in index.scopes:
        scopes_summary.append(
            {
                "scope_id": s.scope_id,
                "title": s.title,
                "file_count": len(s.paths),
                "symbol_count": len(s.public_api),
                "languages": s.languages,
            }
        )

    # Build public API grouped by scope
    public_api_by_scope: dict[str, list[dict]] = {}
    for s in index.scopes:
        if s.public_api:
            items = []
            for sym in s.public_api:
                items.append(
                    {
                        "name": sym.name,
                        "kind": sym.kind,
                        "signature": sym.signature,
                        "docstring": sym.docstring_first_line,
                        "file": sym.citation.file,
                        "line": sym.citation.line_start,
                    }
                )
            public_api_by_scope[s.title] = items

    # Build entrypoints grouped by language/directory
    entrypoint_groups: dict[str, list[str]] = {}
    for ep in index.entrypoints:
        # Group by top-level directory or root
        parts = ep.replace("\\", "/").split("/")
        group = parts[0] if len(parts) > 1 else "root"
        entrypoint_groups.setdefault(group, []).append(ep)

    return JSONResponse(
        {
            "repo_path": index.repo_path,
            "generated_at": index.generated_at,
            "languages": index.languages,
            "scope_count": len(index.scopes),
            "entrypoints": index.entrypoints,
            "env_var_count": len(index.env_vars),
            "public_api_count": len(index.public_api),
            "cross_scope_analysis": index.cross_scope_analysis or None,
            "scopes": scopes_summary,
            "public_api_by_scope": public_api_by_scope,
            "entrypoint_groups": entrypoint_groups,
        }
    )


@app.get("/api/scopes")
async def get_scopes() -> JSONResponse:
    """Return a list of scope summaries."""
    index = _load_index()
    scopes = []
    for s in index.scopes:
        scopes.append(
            {
                "scope_id": s.scope_id,
                "title": s.title,
                "languages": s.languages,
                "file_count": len(s.paths),
                "symbol_count": len(s.public_api),
                "env_var_count": len(s.env_vars),
                "error": s.error,
                "summary": s.summary[:300] if s.summary else None,
            }
        )
    return JSONResponse({"scopes": scopes})


@app.get("/api/scopes/{scope_id}")
async def get_scope_detail(scope_id: str) -> JSONResponse:
    """Return full detail for a single scope."""
    index = _load_index()
    for s in index.scopes:
        if s.scope_id == scope_id:
            return JSONResponse(s.model_dump())
    raise HTTPException(status_code=404, detail=f"Scope '{scope_id}' not found.")


@app.get("/api/graph")
async def get_graph() -> JSONResponse:
    """Return scope edges and scope metadata for visualization."""
    index = _load_index()
    return JSONResponse(_build_scope_graph(index))


@app.get("/api/graph/detailed")
async def get_graph_detailed() -> JSONResponse:
    """Return file-level graph data: file nodes grouped by scope, file-to-file edges."""
    index = _load_index()
    return JSONResponse(_build_file_graph(index))


@app.get("/api/graph/modules")
async def get_graph_modules() -> JSONResponse:
    """Return module-level graph data: directory-based nodes grouped by scope, module-to-module edges."""
    index = _load_index()
    return JSONResponse(_build_module_graph(index))


@app.get("/api/graph/entities")
async def get_graph_entities() -> JSONResponse:
    """Return entity-level graph data: symbol nodes and import-derived entity edges."""
    index = _load_index()
    return JSONResponse(_build_entity_graph(index, connected_only=True))


class DynamicGraphRequest(BaseModel):
    query: str
    view: str | None = None
    scope_filter: list[str] | None = None


@app.post("/api/graph/dynamic")
async def get_graph_dynamic(req: DynamicGraphRequest) -> JSONResponse:
    """Return an adaptive graph payload based on query intent (depth + scope)."""
    index = _load_index()
    query = (req.query or "").strip()
    forced_view = (req.view or "").strip().lower() or None
    if forced_view not in {"scope", "module", "file", "entity"}:
        forced_view = None
    forced_scope_filter = None
    if req.scope_filter is not None:
        forced_scope_filter = _match_scope_ids(index, [str(x) for x in req.scope_filter if str(x).strip()])

    explicit_file_intent = _has_explicit_file_intent(query)
    if not query:
        default_view = forced_view or "module"
        default_scopes = forced_scope_filter if forced_scope_filter is not None else None
        if default_view == "scope":
            default_graph = _build_scope_graph(index, default_scopes)
        elif default_view == "file":
            default_graph = _build_file_graph(index, default_scopes)
        elif default_view == "entity":
            default_graph = _build_entity_graph(index, default_scopes, query="", connected_only=True)
        else:
            default_graph = _build_module_graph(index, default_scopes)
        return JSONResponse(
            {
                "view": default_view,
                "reason": "No query provided; default graph view.",
                "router": "forced" if (forced_view or forced_scope_filter is not None) else "default",
                "scope_filter": sorted(default_scopes) if default_scopes else [],
                "graph": default_graph,
            }
        )

    if forced_view is not None or forced_scope_filter is not None:
        view = forced_view or _infer_graph_view(query)
        scope_filter = forced_scope_filter
        route_reason = "Forced route from client drilldown."
        router_name = "forced"
    elif _can_fast_route(query):
        view = _infer_graph_view(query)
        scope_filter = _infer_scope_filter(index, query)
        route_reason = "Fast heuristic route (explicit depth/scope intent)."
        router_name = "heuristic-fast"
    else:
        view, scope_filter, route_reason = await _route_graph_with_llm(index, query)
        router_name = "llm" if _llm_client is not None else "heuristic"
    if view == "scope":
        graph_payload = _build_scope_graph(index, scope_filter)
        # A single scope node is usually not informative; auto-expand depth.
        if len(graph_payload.get("scopes", [])) <= 1:
            view = "module"
            graph_payload = _build_module_graph(index, scope_filter)
    elif view == "entity":
        graph_payload = _build_entity_graph(index, scope_filter, query=query, connected_only=True)
    elif view == "file":
        graph_payload = _build_file_graph(index, scope_filter)
    else:
        graph_payload = _build_module_graph(index, scope_filter)

    # If module view is still too sparse, expand to file-level.
    if view == "module" and len(graph_payload.get("module_nodes", [])) <= 2:
        view = "file"
        graph_payload = _build_file_graph(index, scope_filter)
    if view == "file" and len(graph_payload.get("file_nodes", [])) == 0:
        view = "entity"
        graph_payload = _build_entity_graph(index, scope_filter, query=query, connected_only=True)
    if view == "entity" and explicit_file_intent:
        view = "file"
        graph_payload = _build_file_graph(index, scope_filter)
    if view == "entity" and len(graph_payload.get("entity_nodes", [])) <= 1:
        view = "file"
        graph_payload = _build_file_graph(index, scope_filter)

    context_graph = None
    composite_mode = "single"
    if scope_filter and view in {"module", "file", "entity"}:
        context_graph = _build_scope_graph(index, None)
        composite_mode = "focus+context"

    reason_bits = [route_reason, f"graph={view}"]
    if scope_filter:
        reason_bits.append(f"filtered={len(scope_filter)} scope(s)")
    else:
        reason_bits.append("filtered=all")

    payload = {
        "view": view,
        "reason": "; ".join(reason_bits) + ".",
        "router": router_name,
        "scope_filter": sorted(scope_filter) if scope_filter else [],
        "graph": graph_payload,
        "context_graph": context_graph,
        "composite_mode": composite_mode,
    }
    return JSONResponse(jsonable_encoder(payload))


class ExploreState(BaseModel):
    view: str = "scope"
    focus_scope_id: str | None = None
    focus_module_id: str | None = None
    focus_file_id: str | None = None


class ExploreRequest(BaseModel):
    query: str
    state: ExploreState | None = None


class GraphTransitionRequest(BaseModel):
    state: ExploreState
    node_id: str
    node_kind: str


def _pick_focus_scope_id(index: DocsIndex, scope_filter: set[str] | None, query: str) -> str | None:
    """Pick the most relevant scope to expand for mixed-depth scenes."""
    candidates = [s for s in index.scopes if scope_filter is None or s.scope_id in scope_filter]
    if not candidates:
        return None
    q = query.lower()
    tokens = _normalize_query_tokens(query)

    def score_scope(s) -> tuple[int, int]:
        sid = s.scope_id.lower()
        title = s.title.lower()
        group = _scope_group(s)
        score = 0
        if sid in q or title in q:
            score += 6
        if any(tok and (tok in sid or tok in title) for tok in tokens):
            score += 3
        if "service" in q and ("service" in sid or "service" in title):
            score += 5
        if "backend" in q and group == "backend":
            score += 4
        if "frontend" in q and group == "frontend":
            score += 4
        if "script" in q and group == "scripts":
            score += 4
        return score, len(s.paths)

    best = max(candidates, key=score_scope)
    return best.scope_id


def _pick_focus_module_id(catalog: dict, scope_id: str | None, query: str) -> str | None:
    if not scope_id:
        return None
    q = query.lower()
    tokens = _normalize_query_tokens(query)
    candidates = [m for m in catalog["modules"].values() if m["scope_id"] == scope_id]
    if not candidates:
        return None

    def score_module(m: dict) -> tuple[int, int, int]:
        mp = str(m["module_path"]).lower()
        label = str(m["label"]).lower()
        score = 0
        if mp in q or label in q:
            score += 6
        if any(tok and (tok in mp or tok in label) for tok in tokens):
            score += 3
        if "service" in q and "service" in mp:
            score += 4
        return score, int(m.get("entity_count", 0)), int(m.get("file_count", 0))

    return max(candidates, key=score_module)["id"]


def _heuristic_explore_plan(
    index: DocsIndex,
    catalog: dict,
    query: str,
    prev_state: ExploreState,
) -> tuple[str, str | None, str | None, str | None, str]:
    """Deterministic fallback route for /api/explore when LLM output is unavailable."""
    view = _infer_graph_view(query)
    scope_filter = _infer_scope_filter(index, query)
    focus_scope_id = _pick_focus_scope_id(index, scope_filter, query)
    focus_module_id = _pick_focus_module_id(catalog, focus_scope_id, query)
    focus_file_id = _match_file_id(catalog, query, focus_module_id) or _match_file_id(catalog, query, None)

    if view == "scope":
        focus_scope_id = None
        focus_module_id = None
        focus_file_id = None
    elif view == "module":
        focus_module_id = None
        focus_file_id = None
    elif view == "file":
        if focus_file_id and not focus_module_id:
            focus_module_id = catalog["files"][focus_file_id]["module_id"]
        if focus_module_id and not focus_scope_id:
            focus_scope_id = catalog["modules"][focus_module_id]["scope_id"]
        focus_file_id = None
    else:  # entity
        if not focus_file_id:
            # Fall back to file-level detail when no concrete file target exists.
            view = "file"
            focus_file_id = None
        else:
            if not focus_module_id:
                focus_module_id = catalog["files"][focus_file_id]["module_id"]
            if not focus_scope_id:
                focus_scope_id = catalog["files"][focus_file_id]["scope_id"]

    # Keep continuity if heuristic cannot identify anything specific.
    if view in {"module", "file", "entity"} and not focus_scope_id:
        focus_scope_id = prev_state.focus_scope_id
    if view in {"file", "entity"} and not focus_module_id:
        focus_module_id = prev_state.focus_module_id

    reason = "Heuristic fallback route (LLM unavailable/malformed)."
    return view, focus_scope_id, focus_module_id, focus_file_id, reason


def _heuristic_fallback_answer(index: DocsIndex, query: str, *, max_items: int = 4) -> str:
    """Short answer when LLM output is unavailable."""
    hits = _load_search_index().search(query, limit=max_items)
    if not hits:
        return "Could not use the LLM for this turn. Graph still updated using heuristic routing."
    lines = ["LLM failed this turn, but here are likely relevant files:"]
    used: set[str] = set()
    for h in hits:
        key = f"{h.citation.file}:{h.citation.line_start}"
        if key in used:
            continue
        used.add(key)
        lines.append(f"- `{key}`")
    return "\n".join(lines[: max_items + 1])


def _match_module_id(catalog: dict, raw: str | None, scope_id: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower()
    modules = catalog["modules"]
    for mid, m in modules.items():
        if scope_id and m["scope_id"] != scope_id:
            continue
        if key == mid.lower() or key == m["module_path"].lower() or key == m["label"].lower():
            return mid
        if key in mid.lower() or key in m["module_path"].lower():
            return mid
    return None


def _match_file_id(catalog: dict, raw: str | None, module_id: str | None = None) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower()
    for fid, f in catalog["files"].items():
        if module_id and f["module_id"] != module_id:
            continue
        fp = f["file_path"].lower()
        if key == fid.lower() or key == fp or key == os.path.basename(fp):
            return fid
        if key in fp:
            return fid
    return None


def _build_explore_system_prompt(index: DocsIndex) -> str:
    return (
        "You are a codebase exploration copilot. "
        "Return concise, high-signal markdown and an exact graph routing plan. "
        "Do not over-explain. Prefer concrete architecture relationships."
    )


def _build_explore_user_prompt(
    index: DocsIndex,
    query: str,
    *,
    state: ExploreState | None,
) -> str:
    catalog = _build_explore_catalog(index)
    hits = _load_search_index().search(query, limit=10)
    hit_lines = []
    for h in hits:
        hit_lines.append(f"- {h.citation.file}:{h.citation.line_start} :: {h.match_context}")
    if not hit_lines:
        hit_lines.append("- (no semantic hits)")

    scope_lines = []
    for s in index.scopes:
        scope_lines.append(f"- {s.scope_id}: {s.title} ({len(s.paths)} files)")

    module_lines = []
    for m in list(catalog["modules"].values())[:80]:
        module_lines.append(f"- {m['id']} [{m['scope_id']}]")

    file_lines = []
    for f in list(catalog["files"].values())[:160]:
        file_lines.append(f"- file:{f['file_path']} [{f['scope_id']}] [{f['module_id']}]")

    state_block = json.dumps(state.model_dump() if state else ExploreState().model_dump())
    return f"""
User query:
{query}

Current graph state:
{state_block}

Available scopes:
{chr(10).join(scope_lines)}

Available modules (ids):
{chr(10).join(module_lines)}

Available files (ids):
{chr(10).join(file_lines)}

Relevant code hits:
{chr(10).join(hit_lines)}

Return JSON ONLY:
{{
  "answer_markdown": "short but useful response",
  "graph": {{
    "view": "scope|module|file|entity",
    "focus_scope_id": "scope id or null",
    "focus_module_id": "module id or null",
    "focus_file_id": "file:<path> or null",
    "highlighted_node_id": "node id or null",
    "reason": "brief routing explanation"
  }}
}}

Rules:
- Default to scope view only when user asks big-picture architecture.
- For flow questions, prefer module view.
- Only use entity view if user explicitly asks for functions/classes/entities.
- Keep answer concise and skimmable.
- Trust the user's requested focus area; keep scope tight.
"""


@app.post("/api/explore")
async def explore(req: ExploreRequest) -> JSONResponse:
    """One-call endpoint: LLM answer + graph routing plan + built graph scene."""
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required.")
    if _llm_client is None:
        raise HTTPException(status_code=503, detail="LLM not configured (missing BACKBOARD_API_KEY).")

    index = _load_index()
    prev_state = req.state or ExploreState()
    catalog = _build_explore_catalog(index)

    t0 = time.perf_counter()
    llm_raw = ""
    try:
        llm_raw = await asyncio.wait_for(
            _llm_client.chat(
                [
                    {"role": "system", "content": _build_explore_system_prompt(index)},
                    {"role": "user", "content": _build_explore_user_prompt(index, query, state=prev_state)},
                ],
                json_mode=True,
            ),
            timeout=14.0,
        )
        raw_text = llm_raw.strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)
        data = json.loads(raw_text)
        answer = str(data.get("answer_markdown") or "").strip() or "No answer generated."
        g = data.get("graph") or {}
        view = str(g.get("view") or "scope").strip().lower()
        if view not in {"scope", "module", "file", "entity"}:
            view = prev_state.view

        focus_scope = _match_scope_ids(index, [str(g.get("focus_scope_id") or "")])
        focus_scope_id = sorted(focus_scope)[0] if focus_scope else prev_state.focus_scope_id
        if view == "scope":
            # If LLM provides a focused scope while requesting scope view,
            # expand one level to modules so the graph actually changes.
            if focus_scope_id:
                view = "module"
            else:
                focus_scope_id = None

        focus_module_id = _match_module_id(catalog, str(g.get("focus_module_id") or ""), focus_scope_id)
        if view in {"scope", "module"}:
            focus_module_id = None if view == "scope" else focus_module_id

        focus_file_id = _match_file_id(catalog, str(g.get("focus_file_id") or ""), focus_module_id)
        if view != "entity":
            focus_file_id = None if view in {"scope", "module"} else focus_file_id

        # ensure coherent focus chain
        if focus_module_id and not focus_scope_id:
            focus_scope_id = catalog["modules"][focus_module_id]["scope_id"]
        if focus_file_id and not focus_module_id:
            focus_module_id = catalog["files"][focus_file_id]["module_id"]
        if focus_module_id and not focus_scope_id:
            focus_scope_id = catalog["modules"][focus_module_id]["scope_id"]

        route_reason = str(g.get("reason") or "LLM route")
        ql = query.lower()
        if (
            view == "scope"
            and not any(k in ql for k in ("architecture", "overview", "big picture", "high level"))
            and any(k in ql for k in ("service", "services", "backend", "flow", "worker", ".py"))
        ):
            view = "module"
            if not focus_scope_id:
                focus_scope_id = _pick_focus_scope_id(index, _infer_scope_filter(index, query), query)
            focus_module_id = None
            focus_file_id = None
            route_reason = "LLM route adjusted to module view for actionable service-level intent."
        highlighted_node_id = str(g.get("highlighted_node_id") or "") or None
        scene = _build_explore_scene(
            index,
            view=view,
            focus_scope_id=focus_scope_id,
            focus_module_id=focus_module_id,
            focus_file_id=focus_file_id,
            highlighted_node_id=highlighted_node_id,
        )
        elapsed = int((time.perf_counter() - t0) * 1000)
        return JSONResponse(
            jsonable_encoder(
                {
                    "answer_markdown": answer,
                    "scene": scene,
                    "routing": {
                        "router": "llm",
                        "reason": route_reason,
                        "latency_ms": elapsed,
                        "query": query,
                    },
                    "debug": {
                        "llm_raw_excerpt": llm_raw[:1200],
                        "catalog_scopes": len(catalog["scopes"]),
                        "catalog_modules": len(catalog["modules"]),
                        "catalog_files": len(catalog["files"]),
                        "catalog_entities": len(catalog["entities"]),
                    },
                }
            )
        )
    except Exception as exc:
        logger.warning("Explore failed; applying heuristic fallback: %s", exc)
        view, focus_scope_id, focus_module_id, focus_file_id, reason = _heuristic_explore_plan(
            index, catalog, query, prev_state
        )
        scene = _build_explore_scene(
            index,
            view=view,
            focus_scope_id=focus_scope_id,
            focus_module_id=focus_module_id,
            focus_file_id=focus_file_id,
        )
        answer = _heuristic_fallback_answer(index, query)
        return JSONResponse(
            jsonable_encoder(
                {
                    "answer_markdown": answer,
                    "scene": scene,
                    "routing": {
                        "router": "heuristic-fallback",
                        "reason": reason,
                        "latency_ms": int((time.perf_counter() - t0) * 1000),
                        "query": query,
                    },
                    "debug": {"error": str(exc), "llm_raw_excerpt": llm_raw[:1200]},
                }
            )
        )


@app.post("/api/graph/transition")
async def graph_transition(req: GraphTransitionRequest) -> JSONResponse:
    """Deterministic click transitions: scope->module->file->entity."""
    index = _load_index()
    catalog = _build_explore_catalog(index)
    state = req.state
    node_id = req.node_id
    node_kind = req.node_kind

    view = state.view
    focus_scope_id = state.focus_scope_id
    focus_module_id = state.focus_module_id
    focus_file_id = state.focus_file_id
    reason = "No transition."

    if node_kind == "scope":
        sid = node_id.removeprefix("scope:")
        if sid in catalog["scopes"]:
            view = "module"
            focus_scope_id = sid
            focus_module_id = None
            focus_file_id = None
            reason = f"Scope {sid} expanded to modules."
    elif node_kind == "module":
        if node_id in catalog["modules"]:
            view = "file"
            focus_module_id = node_id
            focus_scope_id = catalog["modules"][node_id]["scope_id"]
            focus_file_id = None
            reason = f"Module {catalog['modules'][node_id]['module_path']} expanded to files."
    elif node_kind == "file":
        if node_id in catalog["files"]:
            view = "entity"
            focus_file_id = node_id
            focus_module_id = catalog["files"][node_id]["module_id"]
            focus_scope_id = catalog["files"][node_id]["scope_id"]
            reason = f"File {catalog['files'][node_id]['file_path']} expanded to entities."
    elif node_kind == "entity":
        reason = "Entity is deepest level."

    scene = _build_explore_scene(
        index,
        view=view,
        focus_scope_id=focus_scope_id,
        focus_module_id=focus_module_id,
        focus_file_id=focus_file_id,
        highlighted_node_id=node_id,
    )
    return JSONResponse(
        jsonable_encoder(
            {
                "scene": scene,
                "routing": {"router": "transition", "reason": reason, "latency_ms": 0},
            }
        )
    )


@app.get("/api/graph/initial")
async def graph_initial() -> JSONResponse:
    """Initial graph state: full-scope overview with physics-ready node payload."""
    index = _load_index()
    scene = _build_explore_scene(
        index,
        view="scope",
        focus_scope_id=None,
        focus_module_id=None,
        focus_file_id=None,
    )
    return JSONResponse(
        jsonable_encoder(
            {
                "scene": scene,
                "routing": {"router": "default", "reason": "Initial high-level scope view.", "latency_ms": 0},
            }
        )
    )


def _resolve_import_to_file(
    imp: str,
    path_to_file: dict[str, str],
    prefix_to_file: dict[str, str],
    source_exts: frozenset[str],
) -> str | None:
    """Resolve an import string to a repo-relative file path, or None."""
    # Strategy 1: path-based matching
    normalised = imp.lstrip("./").replace("\\", "/")
    stem, ext = os.path.splitext(normalised)
    if ext in source_exts:
        normalised = stem
    target = path_to_file.get(normalised)
    if target:
        return target

    # Strategy 2: dotted-prefix matching
    parts = imp.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        target = prefix_to_file.get(candidate)
        if target:
            return target

    return None


@app.get("/api/service-details")
async def get_service_details() -> JSONResponse:
    """Return LLM-generated usage descriptions for each external service per scope."""
    global _service_details_cache
    if _service_details_cache is not None:
        return JSONResponse(_service_details_cache)

    index = _load_index()
    external_nodes, external_edges = _detect_external_services(index)

    if not external_nodes:
        _service_details_cache = {}
        return JSONResponse({})

    scope_summaries: dict[str, str] = {}
    for s in index.scopes:
        scope_summaries[s.scope_id] = s.summary or s.title

    service_contexts: list[str] = []
    for node in external_nodes:
        edges = [e for e in external_edges if e["to"] == node["id"]]
        scope_parts = []
        for edge in edges:
            scope_id = edge["from"]
            imports = edge.get("imports", [])
            summary = scope_summaries.get(scope_id, scope_id)
            scope_parts.append(
                f'  - scope "{scope_id}": imports {imports}. Scope summary: "{summary}"'
            )
        service_contexts.append(
            f'Service: {node["title"]} (id: {node["id"]})\n'
            + "\n".join(scope_parts)
        )

    prompt = (
        "You are a technical documentation writer. For each external service and scope pair below, "
        "write a 1-2 sentence explanation of HOW and WHY that scope uses the service. "
        "Be specific — reference the actual libraries/imports and what they enable. "
        "Use the scope summary to understand the scope's purpose.\n\n"
        + "\n\n".join(service_contexts)
        + '\n\nRespond with JSON: {"<service_id>": {"<scope_id>": "<explanation>", ...}, ...}\n'
        "Only include the JSON object, no other text."
    )

    if _llm_client is None:
        _service_details_cache = {}
        return JSONResponse({})

    try:
        raw = await _llm_client.ask(prompt, json_mode=True)
        result = json.loads(raw)
        _service_details_cache = result
        return JSONResponse(result)
    except Exception as exc:
        logger.warning("Failed to generate service details: %s", exc)
        _service_details_cache = {}
        return JSONResponse({})


@app.get("/api/files/{file_path:path}")
async def get_file(file_path: str) -> JSONResponse:
    """Read a source file from the repository."""
    if _run_dir is None:
        raise HTTPException(status_code=503, detail="No run directory configured.")

    index = _load_index()
    repo_root = Path(index.repo_path).resolve()

    if not repo_root.exists():
        raise HTTPException(
            status_code=500, detail=f"Repository root not found at {repo_root}"
        )

    target_path = (repo_root / file_path).resolve()

    try:
        target_path.relative_to(repo_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=403, detail="File path must be within repository root."
        ) from exc

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    try:
        content = target_path.read_text(encoding="utf-8", errors="replace")
        return JSONResponse({"content": content, "path": file_path})
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error reading file: {exc}"
        ) from exc


@app.get("/api/fs")
async def get_fs() -> JSONResponse:
    """Return the repository file structure as a tree."""
    if _run_dir is None:
        raise HTTPException(status_code=503, detail="No run directory configured.")

    repo_root = Path(_load_index().repo_path).resolve()
    if not repo_root.exists():
        raise HTTPException(
            status_code=500, detail=f"Repository root not found at {repo_root}"
        )

    def build_tree(path: Path) -> dict:
        name = path.name
        rel_path = str(path.relative_to(repo_root))
        if path.is_file():
            return {"name": name, "path": rel_path, "type": "file"}

        children = []
        try:
            items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            for item in items:
                if item.name.startswith(".") and item.name != ".gitignore":
                    continue
                if item.name in (
                    "__pycache__",
                    "venv",
                    "node_modules",
                    "runs",
                    "dist",
                    "build",
                ):
                    continue
                if item.is_dir() and item.name.endswith(".egg-info"):
                    continue
                children.append(build_tree(item))
        except PermissionError:
            pass

        return {
            "name": name,
            "path": rel_path if path != repo_root else ".",
            "type": "directory",
            "children": children,
        }

    return JSONResponse(build_tree(repo_root)["children"])


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

_CHAT_SYSTEM_TEMPLATE = """\
You are an expert code assistant helping a developer understand a codebase. \
You have access to the full documentation index for this repository. \
Answer questions accurately, citing specific files and line numbers when possible \
using the format `file:line`. You can generate Mermaid diagrams when useful \
by wrapping them in ```mermaid code blocks. Stay factual and only describe what \
the codebase contains based on the index data below.

Repository: {repo_path}
Languages: {languages}
Scopes ({scope_count}):
{scope_summaries}

Key public API ({api_count} symbols):
{api_block}

Environment variables ({env_count}):
{env_block}

Dependency edges:
{edge_block}

Cross-scope analysis:
{cross_scope_analysis}
"""


def _build_chat_system_prompt(index: DocsIndex) -> str:
    """Build the system prompt for chat from the DocsIndex."""
    scope_lines = []
    for s in index.scopes:
        langs = ", ".join(s.languages) if s.languages else "unknown"
        summary = (
            (s.summary[:200] + "...")
            if s.summary and len(s.summary) > 200
            else (s.summary or "")
        )
        scope_lines.append(
            f"- [{s.scope_id}] {s.title} ({langs}, {len(s.paths)} files): {summary}"
        )
    scope_summaries = "\n".join(scope_lines) if scope_lines else "(none)"

    api_lines = []
    for sym in index.public_api[:80]:
        doc = f" -- {sym.docstring_first_line}" if sym.docstring_first_line else ""
        api_lines.append(
            f"  {sym.signature}{doc}  [{sym.citation.file}:{sym.citation.line_start}]"
        )
    api_block = "\n".join(api_lines) if api_lines else "(none)"

    env_lines = [
        f"  {e.name} [{e.citation.file}:{e.citation.line_start}]"
        for e in index.env_vars[:30]
    ]
    env_block = "\n".join(env_lines) if env_lines else "(none)"

    edge_lines = [f"  {a} -> {b}" for a, b in index.scope_edges[:50]]
    edge_block = "\n".join(edge_lines) if edge_lines else "(none)"

    return _CHAT_SYSTEM_TEMPLATE.format(
        repo_path=index.repo_path,
        languages=", ".join(index.languages) if index.languages else "unknown",
        scope_count=len(index.scopes),
        scope_summaries=scope_summaries,
        api_count=len(index.public_api),
        api_block=api_block,
        env_count=len(index.env_vars),
        env_block=env_block,
        edge_block=edge_block,
        cross_scope_analysis=index.cross_scope_analysis or "(none)",
    )


def _truncate_words(text: str, max_words: int) -> str:
    """Hard word cap for concise mode to prevent overly long responses."""
    words = text.split()
    if len(words) <= max_words:
        return text
    clipped = " ".join(words[:max_words]).rstrip()
    # Try to end at a sentence boundary for readability.
    for punct in (". ", "! ", "? "):
        idx = clipped.rfind(punct)
        if idx > max(40, int(len(clipped) * 0.55)):
            clipped = clipped[: idx + 1]
            break
    return clipped + "..."


def _make_scannable_markdown(text: str) -> str:
    """Normalize compact prose into easier-to-skim markdown."""
    # Convert inline dash bullets into real line bullets.
    text = re.sub(r"\s+-\s+", "\n- ", text.strip())
    # Convert inline numbered sections into real lines.
    text = re.sub(r"\s+(\d+\.)\s+", r"\n\1 ", text)

    has_list = "\n- " in text or re.search(r"\n\d+\.\s", text) is not None
    if has_list:
        return text

    # If no list structure exists, force a compact summary + bullets shape.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return text
    summary = sentences[0]
    bullets = "\n".join(f"- {s}" for s in sentences[1:6])
    if bullets:
        return f"**Summary**\n{summary}\n\n**Key Points**\n{bullets}"
    return f"**Summary**\n{summary}"


class ChatRequest(BaseModel):
    query: str | None = None
    message: str | None = None
    concise: bool = False
    max_words: int | None = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class DiffChatRequest(BaseModel):
    question: str
    diff_context: dict  # The current diff report from /api/changes


def _build_diff_system_prompt() -> str:
    """Build system prompt for diff-aware chat."""
    return """You are a helpful assistant that explains code and documentation changes between two snapshots of a codebase.

You will receive:
1. A diff report showing what changed (added scopes, removed scopes, modified scopes, stats delta)
2. A user question about those changes

Your job is to:
- Explain the changes clearly and concisely
- Reference specific scope names when relevant
- Summarize the impact of changes when asked
- Help users understand what was added, removed, or modified

Be concise and focus on the actual data provided. If you don't have enough information to answer, say so.
Format your response using markdown with headers and bullets for readability."""


@app.post("/api/diff-chat")
async def diff_chat(req: DiffChatRequest):
    """Answer questions about diff changes between snapshots."""
    if not req.question.strip():
        return {"answer": "Please provide a question."}

    if _llm_client is None:
        raise HTTPException(
            status_code=503, detail="LLM not configured (missing OPENROUTER_KEY)."
        )

    # Format diff context for the LLM
    ctx = req.diff_context
    diff_summary = []

    if ctx.get("added_scopes"):
        diff_summary.append(f"**Added Scopes ({len(ctx['added_scopes'])}):** {', '.join(ctx['added_scopes'])}")
    if ctx.get("removed_scopes"):
        diff_summary.append(f"**Removed Scopes ({len(ctx['removed_scopes'])}):** {', '.join(ctx['removed_scopes'])}")
    if ctx.get("modified_scopes"):
        mods = []
        for m in ctx["modified_scopes"]:
            details = []
            if m.get("added_files"):
                details.append(f"+{len(m['added_files'])} files")
            if m.get("removed_files"):
                details.append(f"-{len(m['removed_files'])} files")
            if m.get("summary_changed"):
                details.append("summary changed")
            mod_str = f"{m['scope_id']}"
            if details:
                mod_str += f" ({', '.join(details)})"
            mods.append(mod_str)
        diff_summary.append(f"**Modified Scopes ({len(ctx['modified_scopes'])}):** {'; '.join(mods)}")
    
    stats = ctx.get("stats_delta", {})
    if any(stats.get(k, 0) != 0 for k in ["total_files", "total_scopes", "total_symbols"]):
        stats_str = f"Files: {stats.get('total_files', 0):+d}, Scopes: {stats.get('total_scopes', 0):+d}, Symbols: {stats.get('total_symbols', 0):+d}"
        diff_summary.append(f"**Stats Delta:** {stats_str}")

    if ctx.get("graph_changed"):
        diff_summary.append("**Graph:** Architecture dependencies changed")

    context_text = "\n".join(diff_summary) if diff_summary else "No changes detected between these snapshots."

    messages = [
        {"role": "system", "content": _build_diff_system_prompt()},
        {
            "role": "user",
            "content": f"## Diff Report\n{context_text}\n\n## Question\n{req.question}",
        },
    ]

    try:
        answer = await _llm_client.chat(messages)
        return {"answer": answer}
    except Exception as exc:
        logger.error("Diff chat LLM error: %s", exc)
        raise HTTPException(status_code=500, detail=f"LLM Error: {exc}") from exc


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Answer questions about the codebase using index-aware RAG."""
    question = (req.query or req.message or "").strip()
    if not question:
        return ChatResponse(answer="Please provide a query.")

    if _llm_client is None:
        raise HTTPException(
            status_code=503, detail="LLM not configured (missing BACKBOARD_API_KEY)."
        )

    index = _load_index()
    results = _load_search_index().search(question, limit=10)

    if results:
        context_blocks = []
        for r in results:
            block = f"File: {r.citation.file}:{r.citation.line_start}-{r.citation.line_end}\n"
            if r.citation.symbol:
                block += f"Symbol: {r.citation.symbol}\n"
            block += f"Snippet: {r.match_context}\n"
            context_blocks.append(block)
        context = "\n---\n".join(context_blocks)
    else:
        context = "No direct code matches were found in the index."

    brevity_hint = ""
    if req.concise:
        target = req.max_words or 220
        brevity_hint = (
            f"\n\nResponse style constraint:\n"
            f"- Keep the answer concise (target <= {target} words).\n"
            "- Use markdown headings and short bullets; no long paragraphs.\n"
            "- Preferred format:\n"
            "  1) **What It Is** (1-2 lines)\n"
            "  2) **Flow** (4-6 bullets)\n"
            "  3) **Key Files** (max 4 bullets with file:line)\n"
            "- Include only the most relevant details unless asked to expand."
        )

    messages = [
        {"role": "system", "content": _build_chat_system_prompt(index)},
        {
            "role": "user",
            "content": (
                f"Question:\n{question}\n\nRelevant code context:\n{context}"
                f"{brevity_hint}"
            ),
        },
    ]
    try:
        answer = await _llm_client.chat(messages)
        if req.concise:
            answer = _make_scannable_markdown(answer)
            answer = _truncate_words(answer, req.max_words or 180)

        # Generate follow-up suggestions
        suggestions: list[str] = []
        try:
            scope_titles = [s.title for s in index.scopes[:10]]
            followup_prompt = (
                f"The user asked: \"{question}\"\n"
                f"The answer discussed: {answer[:300]}...\n\n"
                f"Available scopes in this codebase: {', '.join(scope_titles)}\n\n"
                "Generate exactly 3 diverse follow-up questions the user might ask next. "
                "Mix different question types:\n"
                "- How/why something works\n"
                "- Comparison or relationship between components\n"
                "- Debugging or troubleshooting\n"
                "- Architecture or design decisions\n"
                "- Code location or file structure\n"
                "- Data flow or request lifecycle\n\n"
                'Respond with ONLY a JSON array of 3 strings. Example: ["question 1", "question 2", "question 3"]'
            )
            raw = await _llm_client.ask(followup_prompt)
            # Extract JSON array from response (model may wrap in markdown)
            cleaned = raw.strip()
            if "```" in cleaned:
                # Strip markdown code fences
                cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
                cleaned = cleaned.replace("```", "").strip()
            # Find the JSON array in the response
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start != -1 and end != -1:
                parsed = json.loads(cleaned[start : end + 1])
                if isinstance(parsed, list):
                    suggestions = [str(s) for s in parsed[:3]]
        except Exception:
            pass

        return ChatResponse(answer=answer, citations=[r.citation for r in results], suggestions=suggestions)
    except Exception as exc:
        logger.error("Chat LLM error: %s", exc)
        raise HTTPException(status_code=500, detail=f"LLM Error: {exc}") from exc


# ---------------------------------------------------------------------------
# Tours
# ---------------------------------------------------------------------------

_TOUR_GENERATION_PROMPT = """\
You are generating guided tours for a developer onboarding onto a codebase.

Repository: {repo_path}
Languages: {languages}

Scopes:
{scope_block}

Generate {tour_count} guided tours as a JSON array. Each tour has:
- "tour_id": short kebab-case id
- "title": human-readable title
- "description": 1-sentence description
- "steps": array of step objects, each with:
  - "title": step title
  - "description": 2-3 sentence explanation of what to look at and why
  - "citation": object with:
    - "file": repo-relative file path
    - "line_start": starting line number (integer)
    - "line_end": ending line number (integer)

Tours to generate:
1. "project-overview" - High-level architecture walkthrough (5-8 steps)
2. "getting-started" - Key files a new developer should read first (4-6 steps)
{scope_tours}

Return ONLY valid JSON - no markdown fences, no commentary."""


def _build_tour_prompt(index: DocsIndex) -> str:
    scope_lines = []
    for s in index.scopes:
        files = ", ".join(s.paths[:10])
        if len(s.paths) > 10:
            files += f" ... (+{len(s.paths) - 10} more)"
        scope_lines.append(f"- {s.title}: {files}")
    scope_block = "\n".join(scope_lines)

    scope_tours = ""
    for i, s in enumerate(index.scopes[:5], start=3):
        scope_tours += (
            f'{i}. "{s.scope_id}-deep-dive" - Deep dive into {s.title} (3-5 steps)\n'
        )

    tour_count = 2 + min(len(index.scopes), 5)

    return _TOUR_GENERATION_PROMPT.format(
        repo_path=index.repo_path,
        languages=", ".join(index.languages) if index.languages else "unknown",
        scope_block=scope_block,
        scope_tours=scope_tours,
        tour_count=tour_count,
    )


def _normalize_tours(raw_tours: list[dict]) -> list[dict]:
    """Normalize tours into the API shape expected by the webapp."""
    normalized: list[dict] = []
    for i, tour in enumerate(raw_tours):
        steps_out = []
        for step in tour.get("steps", []):
            citation = step.get("citation")
            if not isinstance(citation, dict):
                citation = {
                    "file": step.get("file", ""),
                    "line_start": int(step.get("line_start", 1) or 1),
                    "line_end": int(step.get("line_end", 1) or 1),
                }
            steps_out.append(
                {
                    "title": step.get("title", "Step"),
                    "description": step.get("description", step.get("explanation", "")),
                    "citation": citation,
                }
            )

        normalized.append(
            {
                "tour_id": tour.get("tour_id", f"tour-{i + 1}"),
                "title": tour.get("title", f"Tour {i + 1}"),
                "description": tour.get("description", ""),
                "steps": steps_out,
            }
        )
    return normalized


async def _generate_tours(index: DocsIndex) -> list[dict]:
    """Generate tours via LLM or return a minimal fallback."""
    if _llm_client is None:
        steps = []
        for s in index.scopes[:8]:
            first_file = s.paths[0] if s.paths else ""
            steps.append(
                {
                    "title": s.title,
                    "description": s.summary[:200]
                    if s.summary
                    else f"Scope covering {len(s.paths)} file(s).",
                    "citation": {"file": first_file, "line_start": 1, "line_end": 30},
                }
            )
        return [
            {
                "tour_id": "project-overview",
                "title": "Project Overview",
                "description": "A walkthrough of the main components.",
                "steps": steps,
            }
        ]

    prompt = _build_tour_prompt(index)
    try:
        raw = await _llm_client.ask(prompt, json_mode=True)
        tours = json.loads(raw)
        if isinstance(tours, dict) and "tours" in tours:
            tours = tours["tours"]
        if not isinstance(tours, list):
            tours = [tours]
        return _normalize_tours(tours)
    except Exception as exc:
        logger.error("Tour generation failed: %s", exc)
        return [
            {
                "tour_id": "project-overview",
                "title": "Project Overview",
                "description": "Auto-generated overview (LLM generation failed).",
                "steps": [
                    {
                        "title": s.title,
                        "description": s.summary[:200] if s.summary else "",
                        "citation": {
                            "file": s.paths[0] if s.paths else "",
                            "line_start": 1,
                            "line_end": 30,
                        },
                    }
                    for s in index.scopes[:6]
                ],
            }
        ]


async def _load_tours() -> list[dict]:
    """Load tours from cache, disk, docs index, or generate them."""
    global _tours_cache
    if _tours_cache is not None:
        return _tours_cache

    if _run_dir is None:
        raise HTTPException(status_code=503, detail="No run directory configured.")

    tours_path = _run_dir / "tours.json"

    if tours_path.exists():
        try:
            loaded = json.loads(tours_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                loaded = [loaded]
            _tours_cache = _normalize_tours(loaded)
            return _tours_cache
        except (json.JSONDecodeError, OSError):
            pass

    index = _load_index()
    if index.tours:
        _tours_cache = _normalize_tours([t.model_dump() for t in index.tours])
        return _tours_cache

    tours = await _generate_tours(index)

    try:
        tours_path.write_text(json.dumps(tours, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not cache tours to disk: %s", exc)

    _tours_cache = tours
    return _tours_cache


@app.get("/api/tours")
async def list_tours() -> JSONResponse:
    """List available guided tours."""
    return JSONResponse(await _load_tours())


@app.get("/api/tours/{tour_id}")
async def get_tour_detail(tour_id: str) -> JSONResponse:
    """Return a specific guided tour with all steps."""
    tours = await _load_tours()
    for t in tours:
        if t.get("tour_id") == tour_id:
            return JSONResponse(t)
    raise HTTPException(status_code=404, detail=f"Tour '{tour_id}' not found.")


# ---------------------------------------------------------------------------
# History / Diff
# ---------------------------------------------------------------------------


@app.get("/api/history")
def get_history():
    """Return list of documentation snapshots, newest first."""
    from ..git.history import list_snapshots
    
    if _run_dir is None:
        raise HTTPException(status_code=503, detail="No run directory configured.")
    
    # Look for .docbot directory relative to repo root
    index = _load_index()
    docbot_dir = Path(index.repo_path) / ".docbot"
    
    if not docbot_dir.exists():
        return []
    
    snapshots = list_snapshots(docbot_dir)
    return [
        {
            "run_id": s.run_id,
            "timestamp": s.timestamp,
            "commit_sha": s.commit_hash,
            "commit_msg": None,  # Not stored in snapshot; could lookup via git
            "scope_count": s.stats.total_scopes,
            "symbol_count": s.stats.total_symbols,
            "entrypoint_count": 0,  # Not tracked in snapshot stats
        }
        for s in snapshots
    ]


@app.get("/api/changes")
def get_changes(from_id: str | None = None, to_id: str | None = None):
    """Compare two snapshots and return the diff report."""
    from ..git.history import list_snapshots, load_snapshot
    from ..git.diff import compute_diff
    
    if _run_dir is None:
        raise HTTPException(status_code=503, detail="No run directory configured.")
    
    index = _load_index()
    docbot_dir = Path(index.repo_path) / ".docbot"
    
    if not docbot_dir.exists():
        raise HTTPException(status_code=404, detail="No .docbot directory found.")
    
    snapshots = list_snapshots(docbot_dir)
    if len(snapshots) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 snapshots to compare.")
    
    # Default: compare latest two
    if from_id is None:
        from_id = snapshots[1].run_id  # Second newest
    if to_id is None:
        to_id = snapshots[0].run_id  # Newest
    
    from_snap = load_snapshot(docbot_dir, from_id)
    to_snap = load_snapshot(docbot_dir, to_id)
    
    if from_snap is None:
        raise HTTPException(status_code=404, detail=f"Snapshot '{from_id}' not found.")
    if to_snap is None:
        raise HTTPException(status_code=404, detail=f"Snapshot '{to_id}' not found.")
    
    diff_report = compute_diff(from_snap, to_snap)
    
    return {
        "from_id": from_id,
        "to_id": to_id,
        "from_timestamp": from_snap.timestamp,
        "to_timestamp": to_snap.timestamp,
        "added_scopes": diff_report.added_scopes,
        "removed_scopes": diff_report.removed_scopes,
        "modified_scopes": [
            {
                "scope_id": m.scope_id,
                "added_files": m.added_files,
                "removed_files": m.removed_files,
                "added_symbols": m.added_symbols,
                "removed_symbols": m.removed_symbols,
                "summary_changed": m.summary_changed,
            }
            for m in diff_report.modified_scopes
        ],
        "graph_changed": bool(diff_report.graph_changes.changed_nodes),
        "stats_delta": {
            "total_files": diff_report.stats_delta.total_files,
            "total_scopes": diff_report.stats_delta.total_scopes,
            "total_symbols": diff_report.stats_delta.total_symbols,
        },
    }


# ---------------------------------------------------------------------------
# Server launcher
# ---------------------------------------------------------------------------


def start_server(
    run_dir: Path,
    host: str = "127.0.0.1",
    port: int = 8000,
    llm_client: LLMClient | None = None,
) -> None:
    """Start the webapp server pointing at a completed run directory."""
    import uvicorn
    from fastapi.staticfiles import StaticFiles

    global _run_dir, _index_cache, _search_index_cache, _llm_client, _tours_cache, _service_details_cache, _explore_graph_cache
    _run_dir = run_dir.resolve()
    _index_cache = None
    _search_index_cache = None
    _tours_cache = None
    _service_details_cache = None
    _explore_graph_cache = None
    _llm_client = llm_client

    here = Path(__file__).parent.resolve()
    potential_dists = [
        here / "web_dist",  # Bundled package
        here.parents[2] / "webapp" / "dist",  # Editable/source checkout (src/docbot/web -> repo root)
    ]

    dist_dir = None
    for p in potential_dists:
        if p.exists() and (p / "index.html").exists():
            dist_dir = p
            break

    if dist_dir:
        if not any(getattr(route, "name", None) == "static" for route in app.routes):
            app.mount(
                "/", StaticFiles(directory=str(dist_dir), html=True), name="static"
            )
        print(f"Serving static assets from {dist_dir}")

    uvicorn.run(app, host=host, port=port)
