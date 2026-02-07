"""FastAPI webapp server for browsing docbot run output."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .models import DocsIndex

app = FastAPI(title="docbot", version="0.1.0")

# Set by start_server() before uvicorn starts.
_run_dir: Path | None = None
_index_cache: DocsIndex | None = None


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


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Server launcher
# ---------------------------------------------------------------------------

def start_server(run_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the webapp server pointing at a completed run directory."""
    import uvicorn

    global _run_dir, _index_cache
    _run_dir = run_dir.resolve()
    _index_cache = None

    uvicorn.run(app, host=host, port=port)
