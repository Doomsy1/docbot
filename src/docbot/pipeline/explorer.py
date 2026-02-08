"""Explorer -- extraction for a single documentation scope.

Uses the pluggable extractor system (extractors/) to handle any language.
Falls back to a minimal file-listing if no extractor is registered for a
file's language.
"""

from __future__ import annotations

import os
import traceback
from pathlib import Path

from ..extractors import get_extractor
from ..models import (
    Citation,
    EnvVar,
    FileExtraction,
    PublicSymbol,
    RaisedError,
    ScopePlan,
    ScopeResult,
)
from .scanner import ENTRYPOINT_NAMES, LANGUAGE_EXTENSIONS

# Filenames considered "key files" when present in a scope.
_KEY_BASENAMES = {"__init__.py", "settings.py", "config.py", "conf.py"} | ENTRYPOINT_NAMES

# Max chars of source to include in the LLM context per key file.
_KEY_FILE_SNIPPET_LIMIT = 3000
# Max total chars of source context sent to LLM per scope.
_LLM_SOURCE_BUDGET = 12000

_EXPLORER_SYSTEM = """\
You are a technical documentation assistant. You produce accurate, concise \
summaries of code modules. Only describe what the code actually does \
based on the extracted signals and source snippets provided. Never invent \
functionality that is not evidenced in the data. Use plain language."""

_EXPLORER_PROMPT = """\
Summarize this documentation scope for a {languages} repository.

Scope: {title}
Files ({file_count}): {file_list}

Key files: {key_files}
Entrypoints: {entrypoints}

Public API ({api_count} symbols):
{api_block}

Environment variables: {env_block}
Raised errors ({error_count}): {error_block}

Source snippets from key files:
{source_snippets}

Write a 2-4 paragraph summary covering:
1. What this scope/module does (purpose and responsibilities).
2. Key public interfaces and how they relate.
3. Notable patterns (env var usage, error handling, entrypoints) if present.

Stay factual. Reference specific symbols and files. Do not speculate."""


def _language_for_path(rel_path: str) -> str | None:
    """Return the language for a file based on its extension, or None."""
    ext = os.path.splitext(rel_path)[1].lower()
    return LANGUAGE_EXTENSIONS.get(ext)


def explore_scope(plan: ScopePlan, repo_root: Path) -> ScopeResult:
    """Extraction for a scope using registered extractors.

    This is the CPU-bound step that runs in a thread.
    """
    symbols: list[PublicSymbol] = []
    env_vars: list[EnvVar] = []
    raised_errors: list[RaisedError] = []
    citations: list[Citation] = []
    imports: list[str] = []
    key_files: list[str] = []
    entrypoint_files: list[str] = []
    seen_languages: set[str] = set()
    file_extractions: dict[str, FileExtraction] = {}

    for rel_path in plan.paths:
        abs_path = repo_root / rel_path
        if not abs_path.is_file():
            continue

        basename = abs_path.name
        if basename in _KEY_BASENAMES:
            key_files.append(rel_path)
        if basename in ENTRYPOINT_NAMES:
            entrypoint_files.append(rel_path)

        language = _language_for_path(rel_path)
        if language:
            seen_languages.add(language)

        extractor = get_extractor(language) if language else None

        if extractor is not None:
            try:
                extraction: FileExtraction = extractor.extract_file(abs_path, rel_path, language)
                symbols.extend(extraction.symbols)
                env_vars.extend(extraction.env_vars)
                raised_errors.extend(extraction.raised_errors)
                citations.extend(extraction.citations)
                imports.extend(extraction.imports)
                file_extractions[rel_path] = extraction
            except Exception:
                citations.append(Citation(
                    file=rel_path, line_start=0, line_end=0,
                    snippet=f"EXTRACTION ERROR: {traceback.format_exc(limit=2)}",
                ))
        else:
            # No extractor available — record file as a citation so it
            # still appears in the output.
            citations.append(Citation(
                file=rel_path, line_start=0, line_end=0,
                snippet=f"No extractor for {language or 'unknown'} — file listed only.",
            ))

    # Build a basic summary from signals (used as fallback if LLM is unavailable).
    parts: list[str] = []
    parts.append(f"Scope '{plan.title}' covers {len(plan.paths)} file(s).")
    if symbols:
        parts.append(f"Exports {len(symbols)} public symbol(s).")
    if env_vars:
        names = sorted({e.name for e in env_vars})
        parts.append(f"References env var(s): {', '.join(names)}.")
    if raised_errors:
        parts.append(f"Contains {len(raised_errors)} raise statement(s).")
    summary = " ".join(parts)

    return ScopeResult(
        scope_id=plan.scope_id,
        title=plan.title,
        paths=plan.paths,
        summary=summary,
        key_files=sorted(set(key_files)),
        entrypoints=sorted(set(entrypoint_files)),
        citations=citations,
        public_api=symbols,
        env_vars=env_vars,
        raised_errors=raised_errors,
        imports=sorted(set(imports)),
        languages=sorted(seen_languages),
        file_extractions=file_extractions,
    )


def _build_source_snippets(result: ScopeResult, repo_root: Path) -> str:
    """Read truncated source from key files to feed the LLM."""
    snippets: list[str] = []
    budget = _LLM_SOURCE_BUDGET

    targets = result.key_files or result.paths[:5]
    for rel_path in targets:
        if budget <= 0:
            break
        abs_path = repo_root / rel_path
        if not abs_path.is_file():
            continue
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        chunk = text[:min(_KEY_FILE_SNIPPET_LIMIT, budget)]
        if len(text) > len(chunk):
            chunk += "\n... (truncated)"
        snippets.append(f"--- {rel_path} ---\n{chunk}")
        budget -= len(chunk)

    return "\n\n".join(snippets) if snippets else "(none available)"


async def enrich_scope_with_llm(
    result: ScopeResult,
    repo_root: Path,
    llm_client: object,  # docbot.llm.LLMClient
) -> ScopeResult:
    """Call the LLM to produce a richer summary for an already-extracted scope."""
    from ..llm import LLMClient
    assert isinstance(llm_client, LLMClient)

    api_lines = []
    for sym in result.public_api[:40]:  # cap to avoid huge prompts
        doc = f" -- {sym.docstring_first_line}" if sym.docstring_first_line else ""
        api_lines.append(f"  {sym.signature}{doc}  [{sym.citation.file}:{sym.citation.line_start}]")
    api_block = "\n".join(api_lines) if api_lines else "(none)"

    env_block = ", ".join(f"{e.name}" for e in result.env_vars) if result.env_vars else "(none)"

    error_lines = [f"  {e.expression} [{e.citation.file}:{e.citation.line_start}]" for e in result.raised_errors[:20]]
    error_block = "\n".join(error_lines) if error_lines else "(none)"

    source_snippets = _build_source_snippets(result, repo_root)

    languages = ", ".join(result.languages) if result.languages else "unknown"

    prompt = _EXPLORER_PROMPT.format(
        languages=languages,
        title=result.title,
        file_count=len(result.paths),
        file_list=", ".join(result.paths[:30]) + ("..." if len(result.paths) > 30 else ""),
        key_files=", ".join(result.key_files) if result.key_files else "(none)",
        entrypoints=", ".join(result.entrypoints) if result.entrypoints else "(none)",
        api_count=len(result.public_api),
        api_block=api_block,
        env_block=env_block,
        error_count=len(result.raised_errors),
        error_block=error_block,
        source_snippets=source_snippets,
    )

    try:
        llm_summary = await llm_client.ask(prompt, system=_EXPLORER_SYSTEM)
        result.summary = llm_summary
    except Exception as exc:
        # Keep the fallback summary; note the failure in open_questions.
        result.open_questions.append(f"LLM summary generation failed: {exc}")

    return result



