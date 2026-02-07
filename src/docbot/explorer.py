"""Explorer -- AST-based extraction for a single documentation scope."""

from __future__ import annotations

import ast
import re
import traceback
from pathlib import Path, PurePosixPath

from .models import (
    Citation,
    EnvVar,
    PublicSymbol,
    RaisedError,
    ScopePlan,
    ScopeResult,
)
from .scanner import ENTRYPOINT_NAMES

# Regex to catch os.getenv / os.environ.get / os.environ[...] patterns.
_ENV_RE = re.compile(
    r"""os\.(?:getenv|environ\.get|environ\[)"""
    r"""\s*\(?\s*['"]([A-Z_][A-Z0-9_]*)['"]"""
    r"""(?:\s*,\s*['"]?([^'"\)]+)['"]?)?""",
)

# Filenames considered "key files" when present in a scope.
_KEY_BASENAMES = {"__init__.py", "settings.py", "config.py", "conf.py"} | ENTRYPOINT_NAMES

# Max chars of source to include in the LLM context per key file.
_KEY_FILE_SNIPPET_LIMIT = 3000
# Max total chars of source context sent to LLM per scope.
_LLM_SOURCE_BUDGET = 12000

_EXPLORER_SYSTEM = """\
You are a technical documentation assistant. You produce accurate, concise \
summaries of Python code modules. Only describe what the code actually does \
based on the extracted signals and source snippets provided. Never invent \
functionality that is not evidenced in the data. Use plain language."""

_EXPLORER_PROMPT = """\
Summarize this documentation scope for a Python repository.

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


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<unparse-failed>"


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Best-effort function signature string."""
    try:
        args = ast.unparse(node.args)
    except Exception:
        args = "..."
    ret = ""
    if node.returns:
        try:
            ret = f" -> {ast.unparse(node.returns)}"
        except Exception:
            pass
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({args}){ret}"


def _first_line_docstring(node: ast.AST) -> str | None:
    """Return first non-empty line of a node's docstring, or None."""
    ds = ast.get_docstring(node)
    if not ds:
        return None
    for line in ds.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _extract_file(
    abs_path: Path,
    rel_path: str,
    symbols: list[PublicSymbol],
    env_vars: list[EnvVar],
    raised_errors: list[RaisedError],
    citations: list[Citation],
    imports: list[str],
) -> None:
    """Parse one Python file and populate the output lists."""

    source = abs_path.read_text(encoding="utf-8", errors="replace")

    # --- regex pass for env vars (works even if AST fails) ---
    for m in _ENV_RE.finditer(source):
        lineno = source[: m.start()].count("\n") + 1
        env_vars.append(EnvVar(
            name=m.group(1),
            default=m.group(2) if m.group(2) else None,
            citation=Citation(file=rel_path, line_start=lineno, line_end=lineno),
        ))

    # --- AST pass ---
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return  # skip unparseable files

    # Compute this file's package path for resolving relative imports.
    # e.g. "src/docbot/cli.py" -> ["src", "docbot"]
    _rel_parts = PurePosixPath(rel_path).parts
    _pkg_parts = list(_rel_parts[:-1])  # directory parts

    for node in ast.walk(tree):
        # Import statements -- resolve to repo-relative dotted paths.
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level and node.level > 0:
                # Relative import: go up `level` directories from this file's package.
                base = _pkg_parts[:max(0, len(_pkg_parts) - (node.level - 1))]
                resolved = ".".join(base + ([mod] if mod else []))
                if resolved:
                    imports.append(resolved)
            elif mod:
                imports.append(mod)
        # Public functions / async functions at module level
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                cit = Citation(
                    file=rel_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    symbol=node.name,
                )
                symbols.append(PublicSymbol(
                    name=node.name,
                    kind="function",
                    signature=_signature(node),
                    docstring_first_line=_first_line_docstring(node),
                    citation=cit,
                ))
                citations.append(cit)

        # Public classes at module level
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                cit = Citation(
                    file=rel_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    symbol=node.name,
                )
                # Build a minimal class signature
                bases = ", ".join(_safe_unparse(b) for b in node.bases)
                sig = f"class {node.name}({bases})" if bases else f"class {node.name}"
                symbols.append(PublicSymbol(
                    name=node.name,
                    kind="class",
                    signature=sig,
                    docstring_first_line=_first_line_docstring(node),
                    citation=cit,
                ))
                citations.append(cit)

        # Raise statements
        elif isinstance(node, ast.Raise):
            expr_str = _safe_unparse(node.exc) if node.exc else "<bare raise>"
            lineno = node.lineno
            raised_errors.append(RaisedError(
                expression=expr_str,
                citation=Citation(
                    file=rel_path,
                    line_start=lineno,
                    line_end=node.end_lineno or lineno,
                ),
            ))


def explore_scope(plan: ScopePlan, repo_root: Path) -> ScopeResult:
    """Synchronous AST extraction for a scope. Returns structured result.

    This is the CPU-bound step that runs in a thread.
    """
    symbols: list[PublicSymbol] = []
    env_vars: list[EnvVar] = []
    raised_errors: list[RaisedError] = []
    citations: list[Citation] = []
    imports: list[str] = []
    key_files: list[str] = []
    entrypoint_files: list[str] = []

    for rel_path in plan.paths:
        abs_path = repo_root / rel_path
        if not abs_path.is_file():
            continue

        basename = abs_path.name
        if basename in _KEY_BASENAMES:
            key_files.append(rel_path)
        if basename in ENTRYPOINT_NAMES:
            entrypoint_files.append(rel_path)

        try:
            _extract_file(abs_path, rel_path, symbols, env_vars, raised_errors, citations, imports)
        except Exception:
            # Per-file failures should not kill the scope.
            citations.append(Citation(
                file=rel_path, line_start=0, line_end=0,
                snippet=f"EXTRACTION ERROR: {traceback.format_exc(limit=2)}",
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
    from .llm import LLMClient
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

    prompt = _EXPLORER_PROMPT.format(
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
