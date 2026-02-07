"""FastAPI webapp server for browsing docbot run output."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .models import DocsIndex
from .search import SearchIndex, SearchResult

app = FastAPI(title="docbot", version="0.1.0")

# Set by start_server() before uvicorn starts.
_run_dir: Path | None = None
_index_cache: DocsIndex | None = None
_search_index_cache: SearchIndex | None = None


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
# Server launcher
# ---------------------------------------------------------------------------

def start_server(run_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the webapp server pointing at a completed run directory."""
    import uvicorn

    global _run_dir, _index_cache, _search_index_cache
    _run_dir = run_dir.resolve()
    _index_cache = None
    _search_index_cache = None

    uvicorn.run(app, host=host, port=port)
