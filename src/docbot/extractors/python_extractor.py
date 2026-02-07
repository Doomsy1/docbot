"""Python extractor — AST-based extraction for .py files.

All logic moved verbatim from explorer.py into a class implementing the
Extractor protocol.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path, PurePosixPath

from ..models import (
    Citation,
    EnvVar,
    FileExtraction,
    PublicSymbol,
    RaisedError,
)

# Regex to catch os.getenv / os.environ.get / os.environ[...] patterns.
_ENV_RE = re.compile(
    r"""os\.(?:getenv|environ\.get|environ\[)"""
    r"""\s*\(?\s*['"]([A-Z_][A-Z0-9_]*)['"]"""
    r"""(?:\s*,\s*['"]?([^'"\)]+)['"]?)?""",
)


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


class PythonExtractor:
    """AST-based extractor for Python source files."""

    def extract_file(
        self, abs_path: Path, rel_path: str, language: str
    ) -> FileExtraction:
        symbols: list[PublicSymbol] = []
        env_vars: list[EnvVar] = []
        raised_errors: list[RaisedError] = []
        citations: list[Citation] = []
        imports: list[str] = []

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
            return FileExtraction(
                env_vars=env_vars,
            )

        # Compute this file's package path for resolving relative imports.
        _rel_parts = PurePosixPath(rel_path).parts
        _pkg_parts = list(_rel_parts[:-1])

        for node in ast.walk(tree):
            # Import statements
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if node.level and node.level > 0:
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

        return FileExtraction(
            symbols=symbols,
            imports=imports,
            env_vars=env_vars,
            raised_errors=raised_errors,
            citations=citations,
        )
