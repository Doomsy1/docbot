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


# ---------------------------------------------------------------------------
# Project state & configuration (Phase 3 -- git-integrated CLI)
# ---------------------------------------------------------------------------

class ProjectState(BaseModel):
    """Persistent state tracking for the .docbot/ directory.

    Written to ``.docbot/state.json`` after every ``generate`` or ``update``.
    The ``scope_file_map`` is the key structure for incremental updates --
    it records which repo-relative files belong to which documentation scope.
    """

    last_commit: str | None = None
    """Git commit hash (HEAD) at the time of the last generate/update."""

    last_run_id: str | None = None
    """Identifier of the most recent pipeline run."""

    last_run_at: str | None = None
    """ISO-8601 timestamp of the most recent pipeline run."""

    scope_file_map: dict[str, list[str]] = Field(default_factory=dict)
    """Mapping of scope_id to the list of repo-relative file paths it covers."""


class DocbotConfig(BaseModel):
    """User configuration stored in ``.docbot/config.toml``.

    CLI flags override these values for a single invocation.
    Precedence: CLI flag > config.toml > default.
    """

    model: str = "openai/gpt-oss-20b"
    """OpenRouter model ID for LLM calls."""

    concurrency: int = 4
    """Maximum parallel explorer workers."""

    timeout: float = 120.0
    """Per-scope timeout in seconds."""

    max_scopes: int = 20
    """Maximum number of documentation scopes."""

    max_snapshots: int = 10
    """Number of history snapshots to retain."""

    no_llm: bool = False
    """Skip LLM enrichment; extraction still runs."""


# ---------------------------------------------------------------------------
# Snapshot history models (Phase 3D)
# ---------------------------------------------------------------------------

class ScopeSummary(BaseModel):
    """Compact per-scope stats captured in a snapshot."""

    file_count: int
    symbol_count: int
    summary_hash: str


class SnapshotStats(BaseModel):
    """High-level aggregate metrics stored with each snapshot."""

    total_files: int
    total_scopes: int
    total_symbols: int
    total_edges: int


class DocSnapshot(BaseModel):
    """Snapshot metadata persisted to `.docbot/history/`."""

    commit_hash: str
    run_id: str
    timestamp: str
    scope_summaries: dict[str, ScopeSummary] = Field(default_factory=dict)
    graph_digest: str
    doc_hashes: dict[str, str] = Field(default_factory=dict)
    stats: SnapshotStats


# ---------------------------------------------------------------------------
# Diff models (Phase 3E)
# ---------------------------------------------------------------------------

class GraphDelta(BaseModel):
    """Architecture graph differences between two snapshots."""

    added_edges: list[tuple[str, str]] = Field(default_factory=list)
    removed_edges: list[tuple[str, str]] = Field(default_factory=list)
    changed_nodes: list[str] = Field(default_factory=list)


class StatsDelta(BaseModel):
    """Numeric deltas from one snapshot to another."""

    total_files: int = 0
    total_scopes: int = 0
    total_symbols: int = 0


class ScopeModification(BaseModel):
    """Per-scope change summary."""

    scope_id: str
    added_files: list[str] = Field(default_factory=list)
    removed_files: list[str] = Field(default_factory=list)
    added_symbols: list[str] = Field(default_factory=list)
    removed_symbols: list[str] = Field(default_factory=list)
    summary_changed: bool = False


class DiffReport(BaseModel):
    """Top-level diff report returned by `docbot diff` and web APIs."""

    added_scopes: list[str] = Field(default_factory=list)
    removed_scopes: list[str] = Field(default_factory=list)
    modified_scopes: list[ScopeModification] = Field(default_factory=list)
    graph_changes: GraphDelta = Field(default_factory=GraphDelta)
    stats_delta: StatsDelta = Field(default_factory=StatsDelta)
