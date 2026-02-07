"""docbot -- parallel repo documentation generator."""

__version__ = "0.1.0"

from .models import (  # noqa: F401 -- public re-exports
    Citation,
    DocsIndex,
    FileExtraction,
    PublicSymbol,
    ScopePlan,
    ScopeResult,
    SourceFile,
)
