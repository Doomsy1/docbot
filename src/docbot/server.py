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


def _get_docbot_dir() -> Path:
    """Get the .docbot directory from the run directory."""
    if _run_dir is None:
        raise HTTPException(status_code=503, detail="No run directory configured.")

    index = _load_index()
    repo_root = Path(index.repo_path).resolve()
    docbot_dir = repo_root / ".docbot"

    if not docbot_dir.exists():
        raise HTTPException(
            status_code=404, detail=".docbot directory not found in repository."
        )

    return docbot_dir


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


# Known external service patterns detected from env vars and imports.
_EXTERNAL_SERVICES: dict[str, dict] = {
    # Databases
    "mongodb": {"title": "MongoDB", "icon": "db",
                "env_keywords": ["mongo", "mongodb"],
                "import_keywords": ["pymongo", "motor", "mongoengine", "mongoclient"]},
    "postgres": {"title": "PostgreSQL", "icon": "db",
                 "env_keywords": ["postgres", "pghost", "pg_", "database_url"],
                 "import_keywords": ["psycopg", "asyncpg", "sqlalchemy"]},
    "redis": {"title": "Redis", "icon": "db",
              "env_keywords": ["redis"],
              "import_keywords": ["redis", "aioredis"]},
    "mysql": {"title": "MySQL", "icon": "db",
              "env_keywords": ["mysql"],
              "import_keywords": ["mysql", "pymysql", "aiomysql"]},
    "firebase": {"title": "Firebase", "icon": "cloud",
                 "env_keywords": ["firebase"],
                 "import_keywords": ["firebase", "firebase_admin"]},
    "supabase": {"title": "Supabase", "icon": "cloud",
                 "env_keywords": ["supabase"],
                 "import_keywords": ["supabase"]},
    # Cloud / storage
    "aws_s3": {"title": "AWS S3", "icon": "cloud",
               "env_keywords": ["aws_", "s3_", "s3bucket"],
               "import_keywords": ["boto3", "botocore", "s3"]},
    "digitalocean": {"title": "DigitalOcean", "icon": "cloud",
                     "env_keywords": ["digitalocean", "do_space", "spaces"],
                     "import_keywords": ["digitalocean"]},
    "gcs": {"title": "Google Cloud Storage", "icon": "cloud",
            "env_keywords": ["gcs_", "google_cloud", "gcloud"],
            "import_keywords": ["google.cloud.storage"]},
    # AI / LLM
    "openai": {"title": "OpenAI", "icon": "ai",
               "env_keywords": ["openai"],
               "import_keywords": ["openai"]},
    "gemini": {"title": "Google Gemini", "icon": "ai",
               "env_keywords": ["gemini", "google_ai"],
               "import_keywords": ["google.generativeai", "genai", "gemini"]},
    "anthropic": {"title": "Anthropic", "icon": "ai",
                  "env_keywords": ["anthropic", "claude"],
                  "import_keywords": ["anthropic"]},
    "openrouter": {"title": "OpenRouter", "icon": "ai",
                   "env_keywords": ["openrouter"],
                   "import_keywords": ["openrouter"]},
    # Auth
    "auth0": {"title": "Auth0", "icon": "auth",
              "env_keywords": ["auth0"],
              "import_keywords": ["auth0"]},
    "clerk": {"title": "Clerk", "icon": "auth",
              "env_keywords": ["clerk"],
              "import_keywords": ["clerk"]},
    # Messaging / APIs
    "stripe": {"title": "Stripe", "icon": "api",
               "env_keywords": ["stripe"],
               "import_keywords": ["stripe"]},
    "twilio": {"title": "Twilio", "icon": "api",
               "env_keywords": ["twilio"],
               "import_keywords": ["twilio"]},
    "sendgrid": {"title": "SendGrid", "icon": "api",
                 "env_keywords": ["sendgrid"],
                 "import_keywords": ["sendgrid"]},
    "selenium": {"title": "Selenium", "icon": "api",
                 "env_keywords": ["selenium"],
                 "import_keywords": ["selenium"]},
    "playwright": {"title": "Playwright", "icon": "api",
                   "env_keywords": ["playwright"],
                   "import_keywords": ["playwright"]},
    "ffmpeg": {"title": "FFmpeg", "icon": "api",
               "env_keywords": ["ffmpeg"],
               "import_keywords": ["ffmpeg", "ffprobe", "moviepy"]},
    "greenhouse": {"title": "Greenhouse", "icon": "api",
                   "env_keywords": ["greenhouse"],
                   "import_keywords": ["greenhouse"]},
}


def _detect_external_services(index: "DocsIndex") -> tuple[list[dict], list[dict]]:
    """Detect external services from env vars and imports across all scopes.

    Returns (external_nodes, external_edges).
    """
    # Collect all env var names and imports per scope
    scope_env: dict[str, set[str]] = {}
    scope_imp: dict[str, set[str]] = {}
    for s in index.scopes:
        env_names = {e.name.lower() for e in s.env_vars}
        imp_names = {i.lower() for i in s.imports}
        scope_env[s.scope_id] = env_names
        scope_imp[s.scope_id] = imp_names

    # Also check global env vars
    global_env = {e.name.lower() for e in index.env_vars}

    found_services: dict[str, set[str]] = {}  # service_id -> set of scope_ids

    for svc_id, svc in _EXTERNAL_SERVICES.items():
        imp_kws = svc["import_keywords"]

        for s in index.scopes:
            # Only match on direct imports — env vars are too indirect
            # (config files define env vars but don't actually call the service)
            for imp in scope_imp[s.scope_id]:
                if any(kw in imp for kw in imp_kws):
                    found_services.setdefault(svc_id, set()).add(s.scope_id)
                    break

    external_nodes = []
    external_edges = []
    for svc_id, scope_ids in found_services.items():
        svc = _EXTERNAL_SERVICES[svc_id]
        external_nodes.append({
            "id": f"ext_{svc_id}",
            "title": svc["title"],
            "icon": svc["icon"],
        })
        for sid in scope_ids:
            external_edges.append({"from": sid, "to": f"ext_{svc_id}"})

    return external_nodes, external_edges


@app.get("/api/graph")
async def get_graph() -> JSONResponse:
    """Return scope edges and scope metadata for visualization."""
    index = _load_index()

    scopes_meta = []
    for s in index.scopes:
        # Determine a logical group from the first file path
        group = "core"
        if s.paths:
            first = s.paths[0].replace("\\", "/")
            if first.startswith("webapp/") or first.startswith("frontend/"):
                group = "frontend"
            elif first.startswith("services/") or first.startswith("backend/"):
                group = "backend"
            elif first.startswith("tests/") or "test" in s.scope_id:
                group = "testing"
            elif first.startswith("scripts/"):
                group = "scripts"
        scopes_meta.append(
            {
                "scope_id": s.scope_id,
                "title": s.title,
                "file_count": len(s.paths),
                "symbol_count": len(s.public_api),
                "languages": s.languages,
                "group": group,
            }
        )

    external_nodes, external_edges = _detect_external_services(index)

    return JSONResponse(
        {
            "scopes": scopes_meta,
            "scope_edges": [{"from": a, "to": b} for a, b in index.scope_edges],
            "external_nodes": external_nodes,
            "external_edges": external_edges,
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


def _build_chat_system_prompt(index: DocsIndex, diff_report: dict | None = None) -> str:
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

    # Add recent changes section if available
    changes_section = ""
    if diff_report:
        changes_lines = []
        if diff_report.get("added_scopes"):
            changes_lines.append(
                f"Added scopes: {', '.join(diff_report['added_scopes'])}"
            )
        if diff_report.get("removed_scopes"):
            changes_lines.append(
                f"Removed scopes: {', '.join(diff_report['removed_scopes'])}"
            )
        if diff_report.get("modified_scopes"):
            changes_lines.append(
                f"Modified scopes: {len(diff_report['modified_scopes'])}"
            )

        stats = diff_report.get("stats_delta", {})
        if any(stats.values()):
            changes_lines.append(
                f"Stats delta: {stats.get('total_files', 0):+d} files, "
                f"{stats.get('total_scopes', 0):+d} scopes, "
                f"{stats.get('total_symbols', 0):+d} symbols"
            )

        if changes_lines:
            changes_section = (
                "\n\nRecent changes (since last snapshot):\n" + "\n".join(changes_lines)
            )

    return (
        _CHAT_SYSTEM_TEMPLATE.format(
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
        + changes_section
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

    # Try to load recent changes
    diff_report = None
    try:
        from .git.diff import compute_diff
        from .git.history import list_snapshots

        docbot_dir = _get_docbot_dir()
        snapshots = list_snapshots(docbot_dir)

        if len(snapshots) >= 2:
            diff = compute_diff(snapshots[-2], snapshots[-1])
            diff_report = {
                "added_scopes": diff.added_scopes,
                "removed_scopes": diff.removed_scopes,
                "modified_scopes": diff.modified_scopes,
                "stats_delta": {
                    "total_files": diff.stats_delta.total_files,
                    "total_scopes": diff.stats_delta.total_scopes,
                    "total_symbols": diff.stats_delta.total_symbols,
                },
            }
    except Exception:
        # If we can't load changes, just continue without them
        pass

    messages = [
        {"role": "system", "content": _build_chat_system_prompt(index, diff_report)},
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
# History & Changes
# ---------------------------------------------------------------------------


@app.get("/api/history")
async def get_history() -> JSONResponse:
    """List all available snapshots with metadata."""
    from .git.history import list_snapshots

    docbot_dir = _get_docbot_dir()
    snapshots = list_snapshots(docbot_dir)

    # Convert to JSON-serializable format
    snapshots_data = []
    for snap in snapshots:
        snapshots_data.append(
            {
                "run_id": snap.run_id,
                "commit_hash": snap.commit_hash,
                "timestamp": snap.timestamp,
                "stats": {
                    "total_files": snap.stats.total_files,
                    "total_scopes": snap.stats.total_scopes,
                    "total_symbols": snap.stats.total_symbols,
                },
                "scope_count": len(snap.scope_summaries),
            }
        )

    return JSONResponse({"snapshots": snapshots_data})


@app.get("/api/history/{run_id}")
async def get_snapshot_detail(run_id: str) -> JSONResponse:
    """Return detailed information for a specific snapshot."""
    from .git.history import load_snapshot

    docbot_dir = _get_docbot_dir()
    snapshot = load_snapshot(docbot_dir, run_id)

    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot '{run_id}' not found.")

    # Convert to JSON-serializable format
    return JSONResponse(
        {
            "run_id": snapshot.run_id,
            "commit_hash": snapshot.commit_hash,
            "timestamp": snapshot.timestamp,
            "graph_digest": snapshot.graph_digest,
            "stats": {
                "total_files": snapshot.stats.total_files,
                "total_scopes": snapshot.stats.total_scopes,
                "total_symbols": snapshot.stats.total_symbols,
            },
            "scope_summaries": {
                scope_id: {
                    "file_count": summary.file_count,
                    "symbol_count": summary.symbol_count,
                    "summary_hash": summary.summary_hash,
                }
                for scope_id, summary in snapshot.scope_summaries.items()
            },
            "doc_hashes": snapshot.doc_hashes,
        }
    )


@app.get("/api/changes")
async def get_changes(
    from_snapshot: str | None = None,
    to_snapshot: str | None = None,
) -> JSONResponse:
    """Compare two snapshots and return a diff report.

    Query params:
    - from: Source snapshot run_id (default: second-to-last)
    - to: Target snapshot run_id (default: latest)
    """
    from .git.diff import compute_diff
    from .git.history import list_snapshots, load_snapshot

    docbot_dir = _get_docbot_dir()
    snapshots = list_snapshots(docbot_dir)

    if len(snapshots) < 1:
        raise HTTPException(status_code=404, detail="No snapshots available.")

    # Determine source snapshot
    if from_snapshot:
        from_snap = load_snapshot(docbot_dir, from_snapshot)
        if not from_snap:
            raise HTTPException(
                status_code=404, detail=f"Snapshot '{from_snapshot}' not found."
            )
    else:
        # Default: use second-to-last snapshot
        if len(snapshots) < 2:
            raise HTTPException(
                status_code=400,
                detail="Need at least 2 snapshots to compare. Only 1 snapshot available.",
            )
        from_snap = snapshots[-2]

    # Determine target snapshot
    if to_snapshot:
        to_snap = load_snapshot(docbot_dir, to_snapshot)
        if not to_snap:
            raise HTTPException(
                status_code=404, detail=f"Snapshot '{to_snapshot}' not found."
            )
    else:
        # Default: use latest snapshot
        to_snap = snapshots[-1]

    # Compute diff
    diff_report = compute_diff(from_snap, to_snap)

    # Convert to JSON-serializable format
    return JSONResponse(
        {
            "from_snapshot": {
                "run_id": from_snap.run_id,
                "commit_hash": from_snap.commit_hash,
                "timestamp": from_snap.timestamp,
            },
            "to_snapshot": {
                "run_id": to_snap.run_id,
                "commit_hash": to_snap.commit_hash,
                "timestamp": to_snap.timestamp,
            },
            "added_scopes": diff_report.added_scopes,
            "removed_scopes": diff_report.removed_scopes,
            "modified_scopes": [
                {
                    "scope_id": mod.scope_id,
                    "added_files": mod.added_files,
                    "removed_files": mod.removed_files,
                    "added_symbols": mod.added_symbols,
                    "removed_symbols": mod.removed_symbols,
                    "summary_changed": mod.summary_changed,
                }
                for mod in diff_report.modified_scopes
            ],
            "graph_changes": {
                "added_edges": diff_report.graph_changes.added_edges,
                "removed_edges": diff_report.graph_changes.removed_edges,
                "changed_nodes": diff_report.graph_changes.changed_nodes,
            },
            "stats_delta": {
                "total_files": diff_report.stats_delta.total_files,
                "total_scopes": diff_report.stats_delta.total_scopes,
                "total_symbols": diff_report.stats_delta.total_symbols,
            },
        }
    )


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
