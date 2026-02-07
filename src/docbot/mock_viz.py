"""Mock data and stubs for --mock-viz mode.

Provides fake ScanResult, ScopePlans, and an async explore stub so the
real orchestrator pipeline can run end-to-end without file I/O or LLM
calls.  All timing/structure constants live here; tracker logic stays
in the orchestrator.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .models import DocsIndex, ScopePlan, ScopeResult, SourceFile
from .scanner import ScanResult

# -- Mock scope definitions ---------------------------------------------------

SCOPES: list[tuple[str, str, list[str]]] = [
    ("api_routes",  "API Routes",      ["api/routes.py", "api/views.py", "api/middleware.py"]),
    ("db_models",   "Database Models", ["db/models.py", "db/migrations.py", "db/session.py"]),
    ("auth",        "Authentication",  ["auth/jwt.py", "auth/oauth.py", "auth/permissions.py"]),
    ("cli",         "CLI Interface",   ["cli/main.py", "cli/commands.py"]),
    ("core_utils",  "Core Utils",      ["core/utils.py", "core/config.py", "core/logging.py"]),
    ("task_queue",  "Task Queue",      ["tasks/queue.py", "tasks/worker.py", "tasks/scheduler.py"]),
]

# Per-scope explore sleep durations.  "core_utils" intentionally exceeds
# MOCK_TIMEOUT so the real _explore_one timeout handler fires.
EXPLORE_DURATIONS: dict[str, float] = {
    "api_routes": 2.0,
    "db_models":  3.0,
    "auth":       1.8,
    "cli":        2.5,
    "core_utils": 5.0,   # will exceed MOCK_TIMEOUT -> error
    "task_queue":  3.0,
}

MOCK_TIMEOUT: float = 3.5  # short timeout so core_utils triggers an error

# -- Factories ----------------------------------------------------------------

_ALL_FILES = [f for _, _, files in SCOPES for f in files]


def mock_scan(repo_path: Path) -> ScanResult:
    """Return a fake ScanResult with realistic file counts."""
    return ScanResult(
        root=repo_path,
        py_files=list(_ALL_FILES),
        source_files=[SourceFile(path=f, language="python") for f in _ALL_FILES],
        packages=["api", "db", "auth", "cli", "core", "tasks"],
        entrypoints=["cli/main.py"],
        languages=["python"],
    )


def mock_plans() -> list[ScopePlan]:
    """Return mock ScopePlans matching SCOPES."""
    return [
        ScopePlan(scope_id=sid, title=title, paths=paths)
        for sid, title, paths in SCOPES
    ]


async def mock_explore_work(plan: ScopePlan) -> ScopeResult:
    """Sleep for a predetermined duration, then return a stub ScopeResult.

    Designed to be passed as ``_work_fn`` to ``_explore_one`` so the real
    semaphore/timeout/tracker logic still applies.
    """
    dur = EXPLORE_DURATIONS.get(plan.scope_id, 2.0)
    await asyncio.sleep(dur)
    return ScopeResult(scope_id=plan.scope_id, title=plan.title, paths=plan.paths)


def mock_docs_index(scope_results: list[ScopeResult], repo_path: str) -> DocsIndex:
    """Return a minimal DocsIndex from the given scope results."""
    from datetime import datetime, timezone

    return DocsIndex(
        repo_path=repo_path,
        generated_at=datetime.now(timezone.utc).isoformat(),
        scopes=scope_results,
    )
