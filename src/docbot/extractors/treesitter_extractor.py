"""Tree-sitter extractor for TypeScript, JavaScript, Go, Rust, and Java.

Uses tree-sitter grammars when available, otherwise falls back to
regex-based heuristic extraction so the pipeline works even before
Dev A adds tree-sitter dependencies to pyproject.toml.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import (
    Citation,
    EnvVar,
    FileExtraction,
    PublicSymbol,
    RaisedError,
)

# --------------------------------------------------------------------------
# Try importing tree-sitter; flag availability
# --------------------------------------------------------------------------

_HAS_TREE_SITTER = False
try:
    import tree_sitter as _ts  # noqa: F401

    _HAS_TREE_SITTER = True
except ImportError:
    pass


# --------------------------------------------------------------------------
# Per-language regex patterns (fallback when tree-sitter unavailable)
# --------------------------------------------------------------------------

# Each entry: (compiled_regex, kind_str)
# The regex must have a named group 'name' and optionally 'sig'.

_FUNC_PATTERNS: dict[str, re.Pattern[str]] = {
    "typescript": re.compile(
        r"^(?:export\s+)?(?:async\s+)?function\s+(?P<name>\w+)\s*(?P<sig>\([^)]*\)[^{]*)",
        re.MULTILINE,
    ),
    "javascript": re.compile(
        r"^(?:export\s+)?(?:async\s+)?function\s+(?P<name>\w+)\s*(?P<sig>\([^)]*\)[^{]*)",
        re.MULTILINE,
    ),
    "go": re.compile(
        r"^func\s+(?:\([^)]+\)\s+)?(?P<name>\w+)\s*(?P<sig>\([^)]*\)[^{]*)",
        re.MULTILINE,
    ),
    "rust": re.compile(
        r"^(?:pub\s+)?(?:async\s+)?fn\s+(?P<name>\w+)\s*(?P<sig>\([^)]*\)[^{]*)",
        re.MULTILINE,
    ),
    "java": re.compile(
        r"^\s*(?:public|protected|private)?\s*(?:static\s+)?(?:\w+\s+)+(?P<name>\w+)\s*(?P<sig>\([^)]*\))",
        re.MULTILINE,
    ),
}

_CLASS_PATTERNS: dict[str, re.Pattern[str]] = {
    "typescript": re.compile(
        r"^(?:export\s+)?(?:abstract\s+)?class\s+(?P<name>\w+)",
        re.MULTILINE,
    ),
    "javascript": re.compile(
        r"^(?:export\s+)?class\s+(?P<name>\w+)",
        re.MULTILINE,
    ),
    "go": re.compile(
        r"^type\s+(?P<name>\w+)\s+struct\b",
        re.MULTILINE,
    ),
    "rust": re.compile(
        r"^(?:pub\s+)?(?:struct|enum|trait)\s+(?P<name>\w+)",
        re.MULTILINE,
    ),
    "java": re.compile(
        r"^(?:public\s+)?(?:abstract\s+)?(?:class|interface|enum)\s+(?P<name>\w+)",
        re.MULTILINE,
    ),
}

_INTERFACE_PATTERNS: dict[str, re.Pattern[str]] = {
    "typescript": re.compile(
        r"^(?:export\s+)?interface\s+(?P<name>\w+)",
        re.MULTILINE,
    ),
    "go": re.compile(
        r"^type\s+(?P<name>\w+)\s+interface\b",
        re.MULTILINE,
    ),
}

_IMPORT_PATTERNS: dict[str, re.Pattern[str]] = {
    "typescript": re.compile(
        r"""(?:import\s+.*?from\s+['"](?P<mod>[^'"]+)['"]|import\s+['"](?P<mod2>[^'"]+)['"])""",
    ),
    "javascript": re.compile(
        r"""(?:import\s+.*?from\s+['"](?P<mod>[^'"]+)['"]|require\s*\(\s*['"](?P<mod2>[^'"]+)['"]\s*\))""",
    ),
    "go": re.compile(
        r"""(?:"(?P<mod>[^"]+)")""",
    ),
    "rust": re.compile(
        r"^use\s+(?P<mod>[^;]+);",
        re.MULTILINE,
    ),
    "java": re.compile(
        r"^import\s+(?:static\s+)?(?P<mod>[^;]+);",
        re.MULTILINE,
    ),
}

_ENV_PATTERNS: dict[str, re.Pattern[str]] = {
    "typescript": re.compile(r"process\.env\.(?P<name>[A-Z_][A-Z0-9_]*)"),
    "javascript": re.compile(r"process\.env\.(?P<name>[A-Z_][A-Z0-9_]*)"),
    "go": re.compile(r'os\.Getenv\s*\(\s*"(?P<name>[A-Z_][A-Z0-9_]*)"'),
    "rust": re.compile(r'(?:env::var|std::env::var)\s*\(\s*"(?P<name>[A-Z_][A-Z0-9_]*)"'),
    "java": re.compile(r'System\.getenv\s*\(\s*"(?P<name>[A-Z_][A-Z0-9_]*)"'),
}

_ERROR_PATTERNS: dict[str, re.Pattern[str]] = {
    "typescript": re.compile(r"^\s*throw\s+(?P<expr>.+?)$", re.MULTILINE),
    "javascript": re.compile(r"^\s*throw\s+(?P<expr>.+?)$", re.MULTILINE),
    "go": re.compile(r"(?:return\s+.*?(?:errors\.New|fmt\.Errorf)\s*\((?P<expr>[^)]+)\))", re.MULTILINE),
    "rust": re.compile(r"(?:panic!\s*\((?P<expr>[^)]+)\)|return\s+Err\((?P<expr2>[^)]+)\))", re.MULTILINE),
    "java": re.compile(r"^\s*throw\s+(?P<expr>.+?);", re.MULTILINE),
}


# --------------------------------------------------------------------------
# Extractor class
# --------------------------------------------------------------------------

class TreeSitterExtractor:
    """Extract symbols from TypeScript, JavaScript, Go, Rust, and Java files.

    Uses tree-sitter when available, otherwise regex heuristics.
    """

    # Languages this extractor handles.
    SUPPORTED: frozenset[str] = frozenset(
        {"typescript", "javascript", "go", "rust", "java"}
    )

    def extract_file(
        self, abs_path: Path, rel_path: str, language: str
    ) -> FileExtraction:
        if language not in self.SUPPORTED:
            return FileExtraction()

        source = abs_path.read_text(encoding="utf-8", errors="replace")

        if _HAS_TREE_SITTER:
            return self._extract_tree_sitter(source, rel_path, language)

        return self._extract_regex(source, rel_path, language)

    # ------------------------------------------------------------------
    # Regex fallback
    # ------------------------------------------------------------------

    def _extract_regex(
        self, source: str, rel_path: str, language: str
    ) -> FileExtraction:
        symbols: list[PublicSymbol] = []
        imports: list[str] = []
        env_vars: list[EnvVar] = []
        raised_errors: list[RaisedError] = []
        citations: list[Citation] = []

        # Functions
        pat = _FUNC_PATTERNS.get(language)
        if pat:
            for m in pat.finditer(source):
                name = m.group("name")
                sig_text = m.group("sig").strip() if m.group("sig") else "()"
                lineno = source[: m.start()].count("\n") + 1
                cit = Citation(file=rel_path, line_start=lineno, line_end=lineno, symbol=name)
                symbols.append(PublicSymbol(
                    name=name,
                    kind="function",
                    signature=f"{name}{sig_text}",
                    citation=cit,
                ))
                citations.append(cit)

        # Classes / structs / traits
        pat = _CLASS_PATTERNS.get(language)
        if pat:
            for m in pat.finditer(source):
                name = m.group("name")
                lineno = source[: m.start()].count("\n") + 1
                cit = Citation(file=rel_path, line_start=lineno, line_end=lineno, symbol=name)
                symbols.append(PublicSymbol(
                    name=name,
                    kind="class",
                    signature=f"class {name}",
                    citation=cit,
                ))
                citations.append(cit)

        # Interfaces (TS, Go)
        pat = _INTERFACE_PATTERNS.get(language)
        if pat:
            for m in pat.finditer(source):
                name = m.group("name")
                lineno = source[: m.start()].count("\n") + 1
                cit = Citation(file=rel_path, line_start=lineno, line_end=lineno, symbol=name)
                symbols.append(PublicSymbol(
                    name=name,
                    kind="class",
                    signature=f"interface {name}",
                    citation=cit,
                ))
                citations.append(cit)

        # Imports
        pat = _IMPORT_PATTERNS.get(language)
        if pat:
            for m in pat.finditer(source):
                mod = m.group("mod") or m.groupdict().get("mod2") or ""
                mod = mod.strip()
                if mod:
                    imports.append(mod)

        # Env vars
        pat = _ENV_PATTERNS.get(language)
        if pat:
            for m in pat.finditer(source):
                name = m.group("name")
                lineno = source[: m.start()].count("\n") + 1
                env_vars.append(EnvVar(
                    name=name,
                    citation=Citation(file=rel_path, line_start=lineno, line_end=lineno),
                ))

        # Error throwing
        pat = _ERROR_PATTERNS.get(language)
        if pat:
            for m in pat.finditer(source):
                expr = m.group("expr") or m.groupdict().get("expr2") or ""
                expr = expr.strip()[:120]
                lineno = source[: m.start()].count("\n") + 1
                raised_errors.append(RaisedError(
                    expression=expr,
                    citation=Citation(file=rel_path, line_start=lineno, line_end=lineno),
                ))

        return FileExtraction(
            symbols=symbols,
            imports=imports,
            env_vars=env_vars,
            raised_errors=raised_errors,
            citations=citations,
        )

    # ------------------------------------------------------------------
    # Tree-sitter (used when dependency is available)
    # ------------------------------------------------------------------

    def _extract_tree_sitter(
        self, source: str, rel_path: str, language: str
    ) -> FileExtraction:
        # Placeholder — will be filled in when tree-sitter grammars are
        # added by Dev A.  For now, delegate to the regex path.
        return self._extract_regex(source, rel_path, language)
