"""Extraction engine — routes files to the right extractor by language."""

from __future__ import annotations

from .base import Extractor, FileExtraction

__all__ = [
    "Extractor",
    "FileExtraction",
    "get_extractor",
    "register",
    "setup_extractors",
]

# Registry populated at startup via setup_extractors().
_REGISTRY: dict[str, Extractor] = {}


def register(language: str, extractor: Extractor) -> None:
    """Register an extractor instance for a language."""
    _REGISTRY[language] = extractor


def get_extractor(language: str) -> Extractor | None:
    """Return the extractor for *language*, or ``None`` if unsupported."""
    return _REGISTRY.get(language)


def setup_extractors(*, llm_client: object | None = None) -> None:
    """Register all built-in extractors.

    Call once at pipeline startup.  The *llm_client* is optional — when
    provided, an LLM fallback extractor is registered for languages not
    covered by AST or tree-sitter.
    """
    from .python_extractor import PythonExtractor
    from .treesitter_extractor import TreeSitterExtractor

    register("python", PythonExtractor())

    ts = TreeSitterExtractor()
    for lang in ts.SUPPORTED:
        register(lang, ts)

    if llm_client is not None:
        from .llm_extractor import LLMExtractor

        fallback = LLMExtractor(llm_client)
        # Register for any language in LANGUAGE_EXTENSIONS not already covered.
        from ..pipeline.scanner import LANGUAGE_EXTENSIONS

        for lang in set(LANGUAGE_EXTENSIONS.values()):
            if lang not in _REGISTRY:
                register(lang, fallback)
