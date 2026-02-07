"""FastAPI webapp server for browsing docbot run output."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .models import DocsIndex
from .search import SearchIndex, SearchResult

logger = logging.getLogger(__name__)

app = FastAPI(title="docbot", version="0.1.0")

# Set by start_server() before uvicorn starts.
_run_dir: Path | None = None
_index_cache: DocsIndex | None = None
_search_index_cache: SearchIndex | None = None
_llm_client: object | None = None  # LLMClient, optional

# In-memory chat sessions: session_id -> list of {role, content} messages
_chat_sessions: dict[str, list[dict[str, str]]] = {}

# Cached tours (loaded from disk or generated once)
_tours_cache: list[dict] | None = None


def _load_index() -> DocsIndex:
    """Load and cache the DocsIndex from the run directory."""
    global _index_cache
    if _index_cache is not None:
        return _index_cache

    if _run_dir is None:
        raise HTTPException(status_code=503, detail="No run directory configured.")

    index_path = _run_dir / "docs_index.json"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="docs_index.json not found in run directory.")

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
    # It's optional for now (might not exist if search step failed/skipped)
    if not search_path.exists():
         # Return empty index if not found, to avoid crashing UI
        return SearchIndex()

    _search_index_cache = SearchIndex.load(search_path)
    return _search_index_cache


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.get("/api/search", response_model=list[dict])
async def search(q: str) -> list[dict]:
    """Search for symbols and files."""
    if not q:
        return []
    
    idx = _load_search_index()
    results = idx.search(q, limit=20)
    
    # Return as dicts for JSON serialization
    return [
        {
            "citation": r.citation.model_dump(),
            "score": r.score,
            "match_context": r.match_context
        }
        for r in results
    ]


@app.get("/api/index")
async def get_index() -> JSONResponse:
    """Return the full DocsIndex (top-level summary)."""
    index = _load_index()
    return JSONResponse({
        "repo_path": index.repo_path,
        "generated_at": index.generated_at,
        "languages": index.languages,
        "scope_count": len(index.scopes),
        "entrypoints": index.entrypoints,
        "env_var_count": len(index.env_vars),
        "public_api_count": len(index.public_api),
        "cross_scope_analysis": index.cross_scope_analysis or None,
    })


@app.get("/api/scopes")
async def get_scopes() -> JSONResponse:
    """Return a list of scope summaries."""
    index = _load_index()
    scopes = []
    for s in index.scopes:
        scopes.append({
            "scope_id": s.scope_id,
            "title": s.title,
            "languages": s.languages,
            "file_count": len(s.paths),
            "symbol_count": len(s.public_api),
            "env_var_count": len(s.env_vars),
            "error": s.error,
            "summary": s.summary[:300] if s.summary else None,
        })
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
    """Return scope edges and optional Mermaid graph for visualization."""
    index = _load_index()
    return JSONResponse({
        "scope_edges": [{"from": a, "to": b} for a, b in index.scope_edges],
        "mermaid_graph": index.mermaid_graph or None,
    })


@app.get("/api/files/{file_path:path}")
async def get_file(file_path: str) -> JSONResponse:
    """Read a source file from the repository."""
    if _run_dir is None:
        raise HTTPException(status_code=503, detail="No run directory configured.")

    index = _load_index()
    
    # We attempt to resolve the repo root. 
    # In a real scenario, we might want to store the resolved root in the index metadata
    # or pass it as a flag to `docbot serve`.
    # For now, we assume the index.repo_path is correct (it's absolute from the scanner).
    repo_root = Path(index.repo_path).resolve()
    
    if not repo_root.exists():
         raise HTTPException(status_code=500, detail=f"Repository root not found at {repo_root}")

    # Build absolute target path
    # file_path comes from the URL, e.g. "src/docbot/server.py"
    target_path = (repo_root / file_path).resolve()
    
    # Security check: ensure target is within repo_root
    try:
        target_path.relative_to(repo_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="File path must be within repository root.")

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    try:
        content = target_path.read_text(encoding="utf-8", errors="replace")
        return JSONResponse({"content": content, "path": file_path})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {e}")


@app.get("/api/fs")
async def get_fs() -> JSONResponse:
    """Return the repository file structure as a tree."""
    if _run_dir is None:
        raise HTTPException(status_code=503, detail="No run directory configured.")

    index = _load_index()
    repo_root = Path(index.repo_path).resolve()
    
    if not repo_root.exists():
         raise HTTPException(status_code=500, detail=f"Repository root not found at {repo_root}")

    def build_tree(path: Path) -> dict:
        name = path.name
        rel_path = str(path.relative_to(repo_root))
        if path.is_file():
            return {"name": name, "path": rel_path, "type": "file"}
        
        # Directory
        children = []
        try:
            # Sort directories first, then files
            items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            for item in items:
                # Basic filtering
                if item.name.startswith(".") and item.name != ".gitignore":
                    continue
                if item.name in ("__pycache__", "venv", "node_modules", "runs", "dist", "build"):
                    continue
                if item.is_dir() and item.name.endswith(".egg-info"):
                    continue
                    
                children.append(build_tree(item))
        except PermissionError:
            pass
            
        return {"name": name, "path": rel_path if path != repo_root else ".", "type": "directory", "children": children}

    tree = build_tree(repo_root)
    # Return the children of the root so we don't have a single "." root node if we don't want it,
    # but having a root node is fine. Let's return the root's children to be cleaner.
    return JSONResponse(tree["children"])


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

_CHAT_SYSTEM_TEMPLATE = """\
You are an expert code assistant helping a developer understand a codebase. \
You have access to the full documentation index for this repository. \
Answer questions accurately, citing specific files and line numbers when possible \
using the format `file:line`. You can generate Mermaid diagrams when useful \
by wrapping them in ```mermaid code blocks. Stay factual — only describe what \
the codebase actually contains based on the index data below.

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
        summary = (s.summary[:200] + "...") if s.summary and len(s.summary) > 200 else (s.summary or "")
        scope_lines.append(f"- [{s.scope_id}] {s.title} ({langs}, {len(s.paths)} files): {summary}")
    scope_summaries = "\n".join(scope_lines) if scope_lines else "(none)"

    api_lines = []
    for sym in index.public_api[:80]:
        doc = f" -- {sym.docstring_first_line}" if sym.docstring_first_line else ""
        api_lines.append(f"  {sym.signature}{doc}  [{sym.citation.file}:{sym.citation.line_start}]")
    api_block = "\n".join(api_lines) if api_lines else "(none)"

    env_lines = [f"  {e.name} [{e.citation.file}:{e.citation.line_start}]" for e in index.env_vars[:30]]
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


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """AI chat endpoint. Returns SSE stream with the assistant response."""
    if _llm_client is None:
        raise HTTPException(
            status_code=503,
            detail="No LLM client configured. Set OPENROUTER_KEY to enable chat.",
        )

    from .llm import LLMClient
    assert isinstance(_llm_client, LLMClient)

    index = _load_index()

    # Resolve or create session.
    session_id = req.session_id or secrets.token_hex(8)
    if session_id not in _chat_sessions:
        _chat_sessions[session_id] = []
    history = _chat_sessions[session_id]

    # Append user message.
    history.append({"role": "user", "content": req.message})

    # Build messages: system prompt + conversation history.
    system_prompt = _build_chat_system_prompt(index)
    messages = [{"role": "system", "content": system_prompt}] + history

    async def event_stream():
        yield {"event": "session", "data": json.dumps({"session_id": session_id})}

        try:
            response = await _llm_client.chat(messages)
            # Store assistant reply in session.
            history.append({"role": "assistant", "content": response})
            yield {
                "event": "message",
                "data": json.dumps({"content": response, "session_id": session_id}),
            }
        except Exception as exc:
            logger.error("Chat LLM error: %s", exc)
            yield {
                "event": "error",
                "data": json.dumps({"error": str(exc)}),
            }

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())


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
  - "explanation": 2-3 sentence explanation of what to look at and why
  - "file": repo-relative file path
  - "line_start": starting line number (integer)
  - "line_end": ending line number (integer)

Tours to generate:
1. "project-overview" — High-level architecture walkthrough (5-8 steps)
2. "getting-started" — Key files a new developer should read first (4-6 steps)
{scope_tours}

Return ONLY valid JSON — no markdown fences, no commentary."""


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
        scope_tours += f'{i}. "{s.scope_id}-deep-dive" — Deep dive into {s.title} (3-5 steps)\n'

    tour_count = 2 + min(len(index.scopes), 5)

    return _TOUR_GENERATION_PROMPT.format(
        repo_path=index.repo_path,
        languages=", ".join(index.languages) if index.languages else "unknown",
        scope_block=scope_block,
        scope_tours=scope_tours,
        tour_count=tour_count,
    )


async def _generate_tours(index: DocsIndex) -> list[dict]:
    """Generate tours via LLM or return a minimal fallback."""
    if _llm_client is None:
        # No LLM — return a basic fallback tour built from the index.
        steps = []
        for s in index.scopes[:8]:
            first_file = s.paths[0] if s.paths else ""
            steps.append({
                "title": s.title,
                "explanation": s.summary[:200] if s.summary else f"Scope covering {len(s.paths)} file(s).",
                "file": first_file,
                "line_start": 1,
                "line_end": 30,
            })
        return [{
            "tour_id": "project-overview",
            "title": "Project Overview",
            "description": "A walkthrough of the main components.",
            "steps": steps,
        }]

    from .llm import LLMClient
    assert isinstance(_llm_client, LLMClient)

    prompt = _build_tour_prompt(index)
    try:
        raw = await _llm_client.ask(prompt, json_mode=True)
        tours = json.loads(raw)
        if isinstance(tours, dict) and "tours" in tours:
            tours = tours["tours"]
        if not isinstance(tours, list):
            tours = [tours]
        return tours
    except Exception as exc:
        logger.error("Tour generation failed: %s", exc)
        # Return minimal fallback.
        return [{
            "tour_id": "project-overview",
            "title": "Project Overview",
            "description": "Auto-generated overview (LLM generation failed).",
            "steps": [{
                "title": s.title,
                "explanation": s.summary[:200] if s.summary else "",
                "file": s.paths[0] if s.paths else "",
                "line_start": 1,
                "line_end": 30,
            } for s in index.scopes[:6]],
        }]


async def _load_tours() -> list[dict]:
    """Load tours from cache, disk, or generate them."""
    global _tours_cache
    if _tours_cache is not None:
        return _tours_cache

    if _run_dir is None:
        raise HTTPException(status_code=503, detail="No run directory configured.")

    tours_path = _run_dir / "tours.json"

    # Try loading from disk first.
    if tours_path.exists():
        try:
            _tours_cache = json.loads(tours_path.read_text(encoding="utf-8"))
            return _tours_cache
        except (json.JSONDecodeError, OSError):
            pass

    # Generate and cache.
    index = _load_index()
    tours = await _generate_tours(index)

    # Persist to disk.
    try:
        tours_path.write_text(json.dumps(tours, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not cache tours to disk: %s", exc)

    _tours_cache = tours
    return _tours_cache


@app.get("/api/tours")
async def get_tours() -> JSONResponse:
    """List available guided tours."""
    tours = await _load_tours()
    # Return summaries without full steps.
    return JSONResponse([
        {
            "tour_id": t.get("tour_id", ""),
            "title": t.get("title", ""),
            "description": t.get("description", ""),
            "step_count": len(t.get("steps", [])),
        }
        for t in tours
    ])


@app.get("/api/tours/{tour_id}")
async def get_tour_detail(tour_id: str) -> JSONResponse:
    """Return a specific guided tour with all steps."""
    tours = await _load_tours()
    for t in tours:
        if t.get("tour_id") == tour_id:
            return JSONResponse(t)
    raise HTTPException(status_code=404, detail=f"Tour '{tour_id}' not found.")


# ---------------------------------------------------------------------------
# Server launcher
# ---------------------------------------------------------------------------

def start_server(
    run_dir: Path,
    host: str = "127.0.0.1",
    port: int = 8000,
    llm_client: object | None = None,
) -> None:
    """Start the webapp server pointing at a completed run directory."""
    import uvicorn

    global _run_dir, _index_cache, _search_index_cache, _llm_client, _tours_cache
    _run_dir = run_dir.resolve()
    _index_cache = None
    _search_index_cache = None
    _tours_cache = None
    _llm_client = llm_client

    uvicorn.run(app, host=host, port=port)
