"""Pydantic models for docbot's data pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------

class Citation(BaseModel):
    """Points back to a specific region in the source tree."""

    file: str
    line_start: int
    line_end: int
    symbol: str | None = None
    snippet: str | None = None


class PublicSymbol(BaseModel):
    """A public function or class extracted from the AST."""

    name: str
    kind: str  # "function" | "class"
    signature: str
    docstring_first_line: str | None = None
    citation: Citation


class EnvVar(BaseModel):
    """An environment-variable reference found via regex/AST."""

    name: str
    default: str | None = None
    citation: Citation


class RaisedError(BaseModel):
    """A ``raise`` statement captured from AST."""

    expression: str
    citation: Citation


class TourStep(BaseModel):
    """A single step in a guided walkthrough."""

    title: str
    description: str
    citation: Citation | None = None


class Tour(BaseModel):
    """A collection of steps making up a guided tour of the codebase."""

    tour_id: str
    title: str
    description: str
    steps: list[TourStep]


# ---------------------------------------------------------------------------
# Multi-language support (Phase 0 contracts)
# ---------------------------------------------------------------------------

class SourceFile(BaseModel):
    """A discovered source file in the repository."""

    path: str       # repo-relative path (forward slashes)
    language: str   # "python", "typescript", "go", "rust", "java", etc.


class FileExtraction(BaseModel):
    """Output from any extractor (AST, tree-sitter, or LLM)."""

    symbols: list[PublicSymbol] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    env_vars: list[EnvVar] = Field(default_factory=list)
    raised_errors: list[RaisedError] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Scope-level models (explorer input / output)
# ---------------------------------------------------------------------------

class ScopePlan(BaseModel):
    """Describes one documentation scope before exploration."""

    scope_id: str
    title: str
    paths: list[str]
    notes: str = ""


class ScopeResult(BaseModel):
    """Output produced by an explorer for a single scope."""

    scope_id: str
    title: str
    paths: list[str]
    summary: str = ""
    key_files: list[str] = Field(default_factory=list)
    entrypoints: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    public_api: list[PublicSymbol] = Field(default_factory=list)
    env_vars: list[EnvVar] = Field(default_factory=list)
    raised_errors: list[RaisedError] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)

    # If exploration failed, store the reason here.
    error: str | None = None


# ---------------------------------------------------------------------------
# Reducer output
# ---------------------------------------------------------------------------

class DocsIndex(BaseModel):
    """Global merged index produced by the reducer."""

    repo_path: str
    generated_at: str
    scopes: list[ScopeResult]
    env_vars: list[EnvVar] = Field(default_factory=list)
    public_api: list[PublicSymbol] = Field(default_factory=list)
    entrypoints: list[str] = Field(default_factory=list)
    scope_edges: list[tuple[str, str]] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    cross_scope_analysis: str = ""
    mermaid_graph: str = ""
    tours: list[Tour] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Run metadata
# ---------------------------------------------------------------------------

class RunMeta(BaseModel):
    """Metadata for a single docbot run."""

    run_id: str
    repo_path: str
    started_at: str
    finished_at: str | None = None
    scope_count: int = 0
    succeeded: int = 0
    failed: int = 0
