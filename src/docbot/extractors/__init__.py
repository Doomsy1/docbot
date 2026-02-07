"""Extraction engine — routes files to the right extractor by language."""

from __future__ import annotations

from .base import Extractor, FileExtraction

__all__ = ["Extractor", "FileExtraction", "get_extractor"]

# Registry populated as extractor modules are implemented.
_REGISTRY: dict[str, Extractor] = {}


def register(language: str, extractor: Extractor) -> None:
    """Register an extractor instance for a language."""
    _REGISTRY[language] = extractor


def get_extractor(language: str) -> Extractor | None:
    """Return the extractor for *language*, or ``None`` if unsupported."""
    return _REGISTRY.get(language)
