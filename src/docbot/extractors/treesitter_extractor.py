"""Tree-sitter extractor for TypeScript, JavaScript, Go, Rust, Java, Kotlin, C#, Ruby, Swift.

Uses tree-sitter grammars when available, otherwise falls back to
regex-based heuristic extraction.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..models import (
    Citation,
    EnvVar,
    FileExtraction,
    PublicSymbol,
    RaisedError,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Try importing tree-sitter; flag availability
# --------------------------------------------------------------------------

_HAS_TREE_SITTER = False
try:
    from tree_sitter import Language, Parser, Query, QueryCursor

    _HAS_TREE_SITTER = True
except ImportError:
    pass


# --------------------------------------------------------------------------
# Grammar loaders — each returns a Language or None
# --------------------------------------------------------------------------

def _load_grammar(language: str) -> "Language | None":
    """Load the tree-sitter grammar for *language*. Returns None on failure."""
    if not _HAS_TREE_SITTER:
        return None
    try:
        if language == "javascript":
            import tree_sitter_javascript
            return Language(tree_sitter_javascript.language())
        if language == "typescript":
            import tree_sitter_typescript
            return Language(tree_sitter_typescript.language_typescript())
        if language == "go":
            import tree_sitter_go
            return Language(tree_sitter_go.language())
        if language == "rust":
            import tree_sitter_rust
            return Language(tree_sitter_rust.language())
        if language == "java":
            import tree_sitter_java
            return Language(tree_sitter_java.language())
        if language == "kotlin":
            import tree_sitter_kotlin
            return Language(tree_sitter_kotlin.language())
        if language == "csharp":
            import tree_sitter_c_sharp
            return Language(tree_sitter_c_sharp.language())
        if language == "ruby":
            import tree_sitter_ruby
            return Language(tree_sitter_ruby.language())
        if language == "swift":
            import tree_sitter_swift
            return Language(tree_sitter_swift.language())
    except Exception as exc:
        logger.debug("Failed to load tree-sitter grammar for %s: %s", language, exc)
    return None


# Cache loaded grammars.
_grammar_cache: dict[str, "Language | None"] = {}


def _get_grammar(language: str) -> "Language | None":
    if language not in _grammar_cache:
        _grammar_cache[language] = _load_grammar(language)
    return _grammar_cache[language]


# --------------------------------------------------------------------------
# Per-language tree-sitter queries
# --------------------------------------------------------------------------

# Each language maps to a dict of query_name -> S-expression pattern.
# Queries use @capture names that the extractor code reads.

_TS_QUERIES: dict[str, dict[str, str]] = {
    "javascript": {
        "functions": "(function_declaration name: (identifier) @name) @func",
        "arrow_functions": "(lexical_declaration (variable_declarator name: (identifier) @name value: (arrow_function) @func))",
        "classes": "(class_declaration name: (identifier) @name) @cls",
        "imports_from": '(import_statement source: (string) @source)',
        "requires": '(call_expression function: (identifier) @fn (#eq? @fn "require") arguments: (arguments (string) @mod))',
        "env_vars": '(member_expression object: (member_expression object: (identifier) @obj (#eq? @obj "process") property: (property_identifier) @p1 (#eq? @p1 "env")) property: (property_identifier) @var)',
        "throws": "(throw_statement) @throw",
    },
    "typescript": {
        "functions": "(function_declaration name: (identifier) @name) @func",
        "arrow_functions": "(lexical_declaration (variable_declarator name: (identifier) @name value: (arrow_function) @func))",
        "classes": "(class_declaration name: (type_identifier) @name) @cls",
        "interfaces": "(interface_declaration name: (type_identifier) @name) @iface",
        "type_aliases": "(type_alias_declaration name: (type_identifier) @name) @alias",
        "imports_from": '(import_statement source: (string) @source)',
        "env_vars": '(member_expression object: (member_expression object: (identifier) @obj (#eq? @obj "process") property: (property_identifier) @p1 (#eq? @p1 "env")) property: (property_identifier) @var)',
        "throws": "(throw_statement) @throw",
    },
    "go": {
        "functions": "(function_declaration name: (identifier) @name) @func",
        "methods": "(method_declaration name: (field_identifier) @name) @func",
        "structs": '(type_declaration (type_spec name: (type_identifier) @name type: (struct_type) @body))',
        "interfaces": '(type_declaration (type_spec name: (type_identifier) @name type: (interface_type) @body))',
        "imports": '(import_spec path: (interpreted_string_literal) @path)',
        "env_vars": '(call_expression function: (selector_expression operand: (identifier) @pkg (#eq? @pkg "os") field: (field_identifier) @fn (#eq? @fn "Getenv")) arguments: (argument_list (interpreted_string_literal) @var))',
        "panics": '(call_expression function: (identifier) @fn (#eq? @fn "panic")) @panic_call',
    },
    "rust": {
        "functions": "(function_item name: (identifier) @name) @func",
        "structs": "(struct_item name: (type_identifier) @name) @item",
        "enums": "(enum_item name: (type_identifier) @name) @item",
        "traits": "(trait_item name: (type_identifier) @name) @item",
        "impl_methods": "(impl_item (declaration_list (function_item name: (identifier) @name) @func))",
        "use_decls": "(use_declaration argument: (_) @path)",
        "panics": '(macro_invocation macro: (identifier) @macro (#eq? @macro "panic")) @panic_call',
    },
    "java": {
        "classes": "(class_declaration name: (identifier) @name) @cls",
        "interfaces": "(interface_declaration name: (identifier) @name) @iface",
        "enums": "(enum_declaration name: (identifier) @name) @enm",
        "methods": "(method_declaration name: (identifier) @name) @method",
        "constructors": "(constructor_declaration name: (identifier) @name) @ctor",
        "imports": "(import_declaration (scoped_identifier) @path)",
        "env_vars": '(method_invocation object: (identifier) @obj (#eq? @obj "System") name: (identifier) @fn (#eq? @fn "getenv") arguments: (argument_list (string_literal) @var))',
        "throws": "(throw_statement) @throw",
    },
    "kotlin": {
        "functions": "(function_declaration (identifier) @name) @func",
        "classes": "(class_declaration (identifier) @name) @cls",
        "imports": "(import (qualified_identifier) @path)",
    },
    "csharp": {
        "classes": "(class_declaration name: (identifier) @name) @cls",
        "interfaces": "(interface_declaration name: (identifier) @name) @iface",
        "structs": "(struct_declaration name: (identifier) @name) @item",
        "enums": "(enum_declaration name: (identifier) @name) @enm",
        "methods": "(method_declaration name: (identifier) @name) @method",
        "imports": "(using_directive (qualified_name) @path)",
        "env_vars": '(invocation_expression function: (member_access_expression name: (identifier) @fn (#eq? @fn "GetEnvironmentVariable"))) @call',
        "throws": "(throw_statement) @throw",
    },
    "ruby": {
        "methods": "(method name: (identifier) @name) @func",
        "classes": "(class name: (constant) @name) @cls",
        "modules": "(module name: (constant) @name) @mod",
        "requires": '(call method: (identifier) @fn (#match? @fn "^require") arguments: (argument_list (string) @path))',
    },
    "swift": {
        "functions": "(function_declaration name: (simple_identifier) @name) @func",
        "classes": "(class_declaration name: (type_identifier) @name) @cls",
        "structs": "(struct_declaration name: (type_identifier) @name) @item",
        "enums": "(enum_declaration name: (type_identifier) @name) @enm",
        "protocols": "(protocol_declaration name: (type_identifier) @name) @proto",
        "imports": "(import_declaration (identifier) @path)",
    },
}


# --------------------------------------------------------------------------
# Per-language regex patterns (fallback when tree-sitter unavailable)
# --------------------------------------------------------------------------

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
    "kotlin": re.compile(
        r"^\s*(?:(?:public|private|internal|protected)\s+)?fun\s+(?P<name>\w+)\s*(?P<sig>\([^)]*\)[^{]*)",
        re.MULTILINE,
    ),
    "csharp": re.compile(
        r"^\s*(?:public|private|protected|internal)?\s*(?:static\s+)?(?:async\s+)?(?:\w+\s+)+(?P<name>\w+)\s*(?P<sig>\([^)]*\))",
        re.MULTILINE,
    ),
    "ruby": re.compile(
        r"^\s*def\s+(?P<name>\w+)(?P<sig>\([^)]*\))?",
        re.MULTILINE,
    ),
    "swift": re.compile(
        r"^\s*(?:public\s+)?func\s+(?P<name>\w+)\s*(?P<sig>\([^)]*\)[^{]*)",
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
    "kotlin": re.compile(
        r"^(?:(?:public|private|internal)\s+)?(?:data\s+)?(?:class|interface|object|enum\s+class)\s+(?P<name>\w+)",
        re.MULTILINE,
    ),
    "csharp": re.compile(
        r"^(?:public\s+)?(?:abstract\s+)?(?:class|interface|struct|enum)\s+(?P<name>\w+)",
        re.MULTILINE,
    ),
    "ruby": re.compile(
        r"^\s*class\s+(?P<name>[A-Z]\w*)",
        re.MULTILINE,
    ),
    "swift": re.compile(
        r"^(?:public\s+)?(?:class|struct|enum|protocol)\s+(?P<name>\w+)",
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
    "kotlin": re.compile(
        r"^import\s+(?P<mod>[^\s]+)",
        re.MULTILINE,
    ),
    "csharp": re.compile(
        r"^using\s+(?P<mod>[^;]+);",
        re.MULTILINE,
    ),
    "ruby": re.compile(
        r"""require(?:_relative)?\s+['"](?P<mod>[^'"]+)['"]""",
    ),
    "swift": re.compile(
        r"^import\s+(?P<mod>\w+)",
        re.MULTILINE,
    ),
}

_ENV_PATTERNS: dict[str, re.Pattern[str]] = {
    "typescript": re.compile(r"process\.env\.(?P<name>[A-Z_][A-Z0-9_]*)"),
    "javascript": re.compile(r"process\.env\.(?P<name>[A-Z_][A-Z0-9_]*)"),
    "go": re.compile(r'os\.Getenv\s*\(\s*"(?P<name>[A-Z_][A-Z0-9_]*)"'),
    "rust": re.compile(r'(?:env::var|std::env::var)\s*\(\s*"(?P<name>[A-Z_][A-Z0-9_]*)"'),
    "java": re.compile(r'System\.getenv\s*\(\s*"(?P<name>[A-Z_][A-Z0-9_]*)"'),
    "kotlin": re.compile(r'System\.getenv\s*\(\s*"(?P<name>[A-Z_][A-Z0-9_]*)"'),
    "csharp": re.compile(r'GetEnvironmentVariable\s*\(\s*"(?P<name>[A-Z_][A-Z0-9_]*)"'),
    "ruby": re.compile(r"ENV\[(?:'|\")(?P<name>[A-Z_][A-Z0-9_]*)(?:'|\")\]"),
    "swift": re.compile(r'ProcessInfo\.processInfo\.environment\[(?:"|")(?P<name>[A-Z_][A-Z0-9_]*)(?:"|")\]'),
}

_ERROR_PATTERNS: dict[str, re.Pattern[str]] = {
    "typescript": re.compile(r"^\s*throw\s+(?P<expr>.+?)$", re.MULTILINE),
    "javascript": re.compile(r"^\s*throw\s+(?P<expr>.+?)$", re.MULTILINE),
    "go": re.compile(r"(?:return\s+.*?(?:errors\.New|fmt\.Errorf)\s*\((?P<expr>[^)]+)\))", re.MULTILINE),
    "rust": re.compile(r"(?:panic!\s*\((?P<expr>[^)]+)\)|return\s+Err\((?P<expr2>[^)]+)\))", re.MULTILINE),
    "java": re.compile(r"^\s*throw\s+(?P<expr>.+?);", re.MULTILINE),
    "kotlin": re.compile(r"^\s*throw\s+(?P<expr>.+?)$", re.MULTILINE),
    "csharp": re.compile(r"^\s*throw\s+(?P<expr>.+?);", re.MULTILINE),
    "ruby": re.compile(r"^\s*raise\s+(?P<expr>.+?)$", re.MULTILINE),
    "swift": re.compile(r"^\s*throw\s+(?P<expr>.+?)$", re.MULTILINE),
}


# --------------------------------------------------------------------------
# Extractor class
# --------------------------------------------------------------------------

class TreeSitterExtractor:
    """Extract symbols from source files using tree-sitter grammars.

    Falls back to regex heuristics when a grammar is not available.
    """

    SUPPORTED: frozenset[str] = frozenset({
        "typescript", "javascript", "go", "rust", "java",
        "kotlin", "csharp", "ruby", "swift",
    })

    def extract_file(
        self, abs_path: Path, rel_path: str, language: str
    ) -> FileExtraction:
        if language not in self.SUPPORTED:
            return FileExtraction()

        source = abs_path.read_text(encoding="utf-8", errors="replace")

        grammar = _get_grammar(language)
        if grammar is not None:
            try:
                return self._extract_tree_sitter(source, rel_path, language, grammar)
            except Exception as exc:
                logger.debug("Tree-sitter extraction failed for %s, falling back to regex: %s", rel_path, exc)

        return self._extract_regex(source, rel_path, language)

    # ------------------------------------------------------------------
    # Tree-sitter extraction
    # ------------------------------------------------------------------

    def _extract_tree_sitter(
        self, source: str, rel_path: str, language: str, grammar: "Language"
    ) -> FileExtraction:
        parser = Parser(grammar)
        tree = parser.parse(source.encode("utf-8"))
        root = tree.root_node

        symbols: list[PublicSymbol] = []
        imports: list[str] = []
        env_vars: list[EnvVar] = []
        raised_errors: list[RaisedError] = []
        citations: list[Citation] = []

        queries = _TS_QUERIES.get(language, {})

        for query_name, pattern in queries.items():
            try:
                q = Query(grammar, pattern)
            except Exception as exc:
                logger.debug("Query %s failed for %s: %s", query_name, language, exc)
                continue

            cursor = QueryCursor(q)
            matches = list(cursor.matches(root))

            for _pat_id, captures in matches:
                self._process_match(
                    query_name, captures, rel_path, language,
                    symbols, imports, env_vars, raised_errors, citations,
                )

        # Supplement with regex-based env var and error detection (more reliable
        # for complex patterns that are hard to express in tree-sitter queries).
        self._supplement_regex(source, rel_path, language, env_vars, raised_errors)

        return FileExtraction(
            symbols=symbols,
            imports=imports,
            env_vars=env_vars,
            raised_errors=raised_errors,
            citations=citations,
        )

    def _process_match(
        self,
        query_name: str,
        captures: dict[str, list],
        rel_path: str,
        language: str,
        symbols: list[PublicSymbol],
        imports: list[str],
        env_vars: list[EnvVar],
        raised_errors: list[RaisedError],
        citations: list[Citation],
    ) -> None:
        """Dispatch a single query match to the right handler."""
        # --- Functions / methods ---
        if query_name in ("functions", "methods", "arrow_functions", "constructors", "impl_methods"):
            name_nodes = captures.get("name", [])
            func_nodes = captures.get("func", captures.get("method", captures.get("ctor", [])))
            for name_node in name_nodes:
                name = name_node.text.decode()
                if name.startswith("_"):
                    continue
                line = name_node.start_point[0] + 1
                end_line = line
                if func_nodes:
                    end_line = func_nodes[0].end_point[0] + 1

                sig = self._build_func_sig(name, func_nodes[0] if func_nodes else name_node, language)
                cit = Citation(file=rel_path, line_start=line, line_end=end_line, symbol=name)
                symbols.append(PublicSymbol(
                    name=name, kind="function", signature=sig, citation=cit,
                ))
                citations.append(cit)

        # --- Classes ---
        elif query_name in ("classes",):
            for name_node in captures.get("name", []):
                name = name_node.text.decode()
                if name.startswith("_"):
                    continue
                cls_node = (captures.get("cls", []) or [name_node])[0]
                line = name_node.start_point[0] + 1
                end_line = cls_node.end_point[0] + 1
                cit = Citation(file=rel_path, line_start=line, line_end=end_line, symbol=name)
                symbols.append(PublicSymbol(
                    name=name, kind="class", signature=f"class {name}", citation=cit,
                ))
                citations.append(cit)

        # --- Interfaces / protocols / traits ---
        elif query_name in ("interfaces", "protocols", "traits"):
            kind_label = {"interfaces": "interface", "protocols": "protocol", "traits": "trait"}.get(query_name, "interface")
            for name_node in captures.get("name", []):
                name = name_node.text.decode()
                container = (captures.get("iface", []) or captures.get("proto", []) or captures.get("item", []) or [name_node])[0]
                line = name_node.start_point[0] + 1
                end_line = container.end_point[0] + 1
                cit = Citation(file=rel_path, line_start=line, line_end=end_line, symbol=name)
                symbols.append(PublicSymbol(
                    name=name, kind="interface", signature=f"{kind_label} {name}", citation=cit,
                ))
                citations.append(cit)

        # --- Structs / enums / type aliases ---
        elif query_name in ("structs", "enums", "type_aliases", "modules"):
            kind_map = {"structs": "struct", "enums": "enum", "type_aliases": "type", "modules": "module"}
            kind = kind_map.get(query_name, "class")
            for name_node in captures.get("name", []):
                name = name_node.text.decode()
                container = (captures.get("item", []) or captures.get("enm", []) or captures.get("alias", []) or captures.get("mod", []) or [name_node])[0]
                line = name_node.start_point[0] + 1
                end_line = container.end_point[0] + 1
                cit = Citation(file=rel_path, line_start=line, line_end=end_line, symbol=name)
                symbols.append(PublicSymbol(
                    name=name, kind=kind, signature=f"{kind} {name}", citation=cit,
                ))
                citations.append(cit)

        # --- Imports ---
        elif query_name in ("imports", "imports_from", "requires", "use_decls"):
            for key in ("source", "mod", "path"):
                for node in captures.get(key, []):
                    text = node.text.decode().strip("'\"")
                    if text:
                        imports.append(text)

        # --- Env vars ---
        elif query_name == "env_vars":
            for node in captures.get("var", []):
                name = node.text.decode().strip("'\"")
                line = node.start_point[0] + 1
                env_vars.append(EnvVar(
                    name=name,
                    citation=Citation(file=rel_path, line_start=line, line_end=line),
                ))

        # --- Error throwing / panics ---
        elif query_name in ("throws", "panics"):
            for node in captures.get("throw", captures.get("panic_call", [])):
                text = node.text.decode()[:120]
                line = node.start_point[0] + 1
                raised_errors.append(RaisedError(
                    expression=text,
                    citation=Citation(file=rel_path, line_start=line, line_end=line),
                ))

    @staticmethod
    def _build_func_sig(name: str, node, language: str) -> str:
        """Build a human-readable function signature from a tree-sitter node."""
        text = node.text.decode()
        # Try to extract just the signature line (up to the body).
        for i, ch in enumerate(text):
            if ch == '{':
                sig = text[:i].strip()
                # For languages with keywords in the signature, include them.
                return sig if sig else name
        # No brace found — use first line.
        first_line = text.split('\n', 1)[0].rstrip()
        return first_line if first_line else name

    @staticmethod
    def _supplement_regex(
        source: str,
        rel_path: str,
        language: str,
        env_vars: list[EnvVar],
        raised_errors: list[RaisedError],
    ) -> None:
        """Use regex to catch env vars and errors that tree-sitter queries might miss."""
        seen_env = {e.name for e in env_vars}

        pat = _ENV_PATTERNS.get(language)
        if pat:
            for m in pat.finditer(source):
                name = m.group("name")
                if name not in seen_env:
                    seen_env.add(name)
                    lineno = source[:m.start()].count("\n") + 1
                    env_vars.append(EnvVar(
                        name=name,
                        citation=Citation(file=rel_path, line_start=lineno, line_end=lineno),
                    ))

    # ------------------------------------------------------------------
    # Regex fallback (used when tree-sitter grammar not available)
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
