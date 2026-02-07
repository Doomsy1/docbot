"""Base protocol for source-file extractors."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..models import FileExtraction


@runtime_checkable
class Extractor(Protocol):
    """Interface that every language extractor must satisfy.

    Implementations:
      - PythonExtractor   (AST-based, moved from explorer.py)
      - TreeSitterExtractor (tree-sitter queries for TS/JS, Go, Rust, Java)
      - LLMExtractor      (LLM-based fallback for unsupported languages)
    """

    def extract_file(
        self, abs_path: Path, rel_path: str, language: str
    ) -> FileExtraction:
        """Extract symbols, imports, env vars, errors, and citations from a single file."""
        ...
