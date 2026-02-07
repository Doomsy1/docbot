"""FastAPI webapp server for browsing docbot run output."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .llm import LLMClient
from .models import Citation, DocsIndex
from .search import SearchIndex

logger = logging.getLogger(__name__)

app = FastAPI(title="docbot", version="0.1.0")

# Set by start_server() before uvicorn starts.
_run_dir: Path | None = None
_index_cache: DocsIndex | None = None
_search_index_cache: SearchIndex | None = None
_llm_client: LLMClient | None = None
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
    """Return scope edges and optional Mermaid graph for visualization."""
    index = _load_index()
    return JSONResponse(
        {
            "scopes": [s.scope_id for s in index.scopes],
            "scope_edges": [{"from": a, "to": b} for a, b in index.scope_edges],
            "mermaid_graph": index.mermaid_graph or None,
        }
    )


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


class ChatRequest(BaseModel):
    query: str | None = None
    message: str | None = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Answer questions about the codebase using index-aware RAG."""
    question = (req.query or req.message or "").strip()
    if not question:
        return ChatResponse(answer="Please provide a query.")

    if _llm_client is None:
        raise HTTPException(
            status_code=503, detail="LLM not configured (missing OPENROUTER_KEY)."
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

    messages = [
        {"role": "system", "content": _build_chat_system_prompt(index)},
        {
            "role": "user",
            "content": f"Question:\n{question}\n\nRelevant code context:\n{context}",
        },
    ]
    try:
        answer = await _llm_client.chat(messages)
        return ChatResponse(answer=answer, citations=[r.citation for r in results])
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

    global _run_dir, _index_cache, _search_index_cache, _llm_client, _tours_cache
    _run_dir = run_dir.resolve()
    _index_cache = None
    _search_index_cache = None
    _tours_cache = None
    _llm_client = llm_client

    here = Path(__file__).parent.resolve()
    potential_dists = [
        here / "web_dist",  # Bundled package
        here.parents[1] / "webapp" / "dist",  # Editable/source checkout
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
