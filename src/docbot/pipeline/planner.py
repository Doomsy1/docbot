"""Planner -- partition scanned files into documentation scopes."""

from __future__ import annotations

import json
import logging
import re
from pathlib import PurePosixPath

from ..models import ScopePlan
from .scanner import ScanResult

logger = logging.getLogger(__name__)

# Keywords (in path segments or filename stems) that mark cross-cutting concerns.
_CROSSCUTTING_RE = re.compile(
    r"(config|settings|conf|log|logging|auth|middleware|errors|exceptions"
    r"|security|permissions|utils|helpers|common|shared|types|models)",
    re.IGNORECASE,
)

_PLANNER_SYSTEM = """\
You are a documentation architect. You receive a draft documentation plan for \
a software repository and improve it. Return ONLY valid JSON -- no markdown \
fences, no commentary."""

_PLANNER_PROMPT = """\
A tool auto-generated the following documentation plan for a repository.

Languages detected: {languages}

Repository file listing ({file_count} source files):
{file_listing}

Packages detected: {packages}
Entrypoints detected: {entrypoints}

Draft scopes:
{draft_scopes}

Improve this plan by:
1. Giving each scope a clear, descriptive title (not just the directory name).
2. Writing a short "notes" field explaining what each scope covers and why it matters.
3. Merging or splitting scopes if it would produce better documentation groupings.
4. Keeping scope_id values as simple slug strings (lowercase, underscores).

Return a JSON array of objects, each with: scope_id, title, paths (array of file paths), notes.
Keep every file from the original plan assigned to exactly one scope.
Maximum {max_scopes} scopes.
Return ONLY the JSON array, nothing else."""


def _top_level_key(rel_path: str) -> str:
    parts = PurePosixPath(rel_path).parts
    if len(parts) <= 1:
        return "<root>"
    if parts[0] == "src" and len(parts) > 2:
        return f"src/{parts[1]}"
    return parts[0]


def _is_crosscutting(rel_path: str) -> bool:
    stem = PurePosixPath(rel_path).stem
    return bool(_CROSSCUTTING_RE.search(stem)) or bool(_CROSSCUTTING_RE.search(rel_path))


def build_plan(scan: ScanResult, max_scopes: int = 20) -> list[ScopePlan]:
    """Create up to *max_scopes* scope plans from the scan result (no LLM)."""

    # Use source_files when available, fall back to py_files for compat.
    all_paths = [sf.path for sf in scan.source_files] if scan.source_files else scan.py_files

    entrypoint_set = set(scan.entrypoints)
    crosscutting_files: list[str] = []
    entrypoint_files: list[str] = []
    group_files: dict[str, list[str]] = {}

    for p in all_paths:
        if p in entrypoint_set:
            entrypoint_files.append(p)
        if _is_crosscutting(p):
            crosscutting_files.append(p)
            continue
        key = _top_level_key(p)
        group_files.setdefault(key, []).append(p)

    scopes: list[ScopePlan] = []

    if entrypoint_files:
        scopes.append(ScopePlan(
            scope_id="entrypoints",
            title="Entrypoints",
            paths=sorted(set(entrypoint_files)),
            notes="Application entrypoint files detected by naming convention.",
        ))

    if crosscutting_files:
        scopes.append(ScopePlan(
            scope_id="crosscutting",
            title="Cross-cutting concerns",
            paths=sorted(set(crosscutting_files)),
            notes="Config, logging, auth, middleware, error-handling, and shared utility modules.",
        ))

    for key in sorted(group_files):
        sid = key.replace("/", "_").replace("<", "").replace(">", "").replace(" ", "_")
        scopes.append(ScopePlan(
            scope_id=sid,
            title=key if key != "<root>" else "Root-level modules",
            paths=sorted(group_files[key]),
        ))

    if len(scopes) > max_scopes:
        reserved = [s for s in scopes if s.scope_id in ("entrypoints", "crosscutting")]
        rest = [s for s in scopes if s.scope_id not in ("entrypoints", "crosscutting")]
        rest.sort(key=lambda s: len(s.paths), reverse=True)
        budget = max_scopes - len(reserved)
        scopes = reserved + rest[:budget]

    return scopes


async def refine_plan_with_llm(
    scopes: list[ScopePlan],
    scan: ScanResult,
    max_scopes: int,
    llm_client: object,
) -> list[ScopePlan]:
    """Have the LLM refine the auto-generated scope plan."""
    from ..llm import LLMClient
    assert isinstance(llm_client, LLMClient)

    all_paths = [sf.path for sf in scan.source_files] if scan.source_files else scan.py_files
    languages = ", ".join(scan.languages) if scan.languages else "Python"

    draft = json.dumps([s.model_dump() for s in scopes], indent=2)
    file_listing = "\n".join(f"  {f}" for f in all_paths[:200])
    if len(all_paths) > 200:
        file_listing += f"\n  ... and {len(all_paths) - 200} more"

    prompt = _PLANNER_PROMPT.format(
        languages=languages,
        file_count=len(all_paths),
        file_listing=file_listing,
        packages=", ".join(scan.packages[:30]) or "(none)",
        entrypoints=", ".join(scan.entrypoints) or "(none)",
        draft_scopes=draft,
        max_scopes=max_scopes,
    )

    try:
        raw = await llm_client.ask(prompt, system=_PLANNER_SYSTEM)
        # Strip markdown fences if the LLM wrapped it anyway.
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        parsed = json.loads(cleaned)
        refined = [ScopePlan(**item) for item in parsed]
        if refined:
            return refined
    except Exception as exc:
        logger.warning("LLM plan refinement failed, using draft plan: %s", exc)

    return scopes
