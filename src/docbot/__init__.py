"""Docbot - Automated documentation generation."""

from .models import (  # noqa: F401 -- public re-exports
    Citation,
    DocsIndex,
    FileExtraction,
    PublicSymbol,
    ScopePlan,
    ScopeResult,
    SourceFile,
)
from .llm import LLMClient
from .pipeline import run_async, generate_async, update_async

__version__ = "0.1.0"

__all__ = [
    "LLMClient",
    "run_async",
    "generate_async",
    "update_async",
    "Citation",
    "DocsIndex",
    "FileExtraction",
    "PublicSymbol",
    "ScopePlan",
    "ScopeResult",
    "SourceFile",
]
