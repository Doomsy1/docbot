"""Snapshot history management for documentation versioning.

Provides functions to save, load, list, and prune documentation snapshots.
Each snapshot captures the state of the documentation at a specific commit.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    DocSnapshot,
    DocsIndex,
    ScopeResult,
    ScopeSummary,
    SnapshotStats,
)


def _compute_graph_digest(docs_index: DocsIndex) -> str:
    """Compute a hash of the dependency graph edges for change detection."""
    if not docs_index.architecture or not docs_index.architecture.graph:
        return ""
    
    # Sort edges for consistent hashing
    edges = sorted(
        (e.source, e.target, e.edge_type)
        for e in docs_index.architecture.graph.edges
    )
    
    edge_str = json.dumps(edges, sort_keys=True)
    return hashlib.sha256(edge_str.encode()).hexdigest()[:16]


def _compute_doc_hashes(docs_dir: Path) -> dict[str, str]:
    """Compute content hashes for all generated documentation files."""
    doc_hashes: dict[str, str] = {}
    
    if not docs_dir.exists():
        return doc_hashes
    
    for doc_file in docs_dir.rglob("*.md"):
        if doc_file.is_file():
            content = doc_file.read_bytes()
            content_hash = hashlib.sha256(content).hexdigest()[:16]
            # Store relative path from docs_dir
            rel_path = doc_file.relative_to(docs_dir).as_posix()
            doc_hashes[rel_path] = content_hash
    
    return doc_hashes


def _compute_scope_summaries(scope_results: list[ScopeResult]) -> dict[str, ScopeSummary]:
    """Build compact summaries for each scope."""
    summaries: dict[str, ScopeSummary] = {}
    
    for sr in scope_results:
        # Count symbols across all files in the scope
        total_symbols = sum(len(f.symbols) for f in sr.files)
        
        # Hash the summary text for change detection
        summary_text = sr.summary or ""
        summary_hash = hashlib.sha256(summary_text.encode()).hexdigest()[:16]
        
        summaries[sr.scope_id] = ScopeSummary(
            file_count=len(sr.files),
            symbol_count=total_symbols,
            summary_hash=summary_hash,
        )
    
    return summaries


def _compute_stats(docs_index: DocsIndex, scope_results: list[ScopeResult]) -> SnapshotStats:
    """Compute aggregate statistics for the snapshot."""
    total_files = sum(len(sr.files) for sr in scope_results)
    total_scopes = len(scope_results)
    total_symbols = sum(
        sum(len(f.symbols) for f in sr.files)
        for sr in scope_results
    )
    total_edges = (
        len(docs_index.architecture.graph.edges)
        if docs_index.architecture and docs_index.architecture.graph
        else 0
    )
    
    return SnapshotStats(
        total_files=total_files,
        total_scopes=total_scopes,
        total_symbols=total_symbols,
        total_edges=total_edges,
    )


def save_snapshot(
    docbot_dir: Path,
    docs_index: DocsIndex,
    scope_results: list[ScopeResult],
    run_id: str,
    commit: str,
) -> None:
    """Save a documentation snapshot to history.
    
    Creates:
    - `.docbot/history/<run_id>.json` - snapshot metadata
    - `.docbot/history/<run_id>/` - directory with scope results
    
    Args:
        docbot_dir: Path to .docbot/ directory
        docs_index: The documentation index
        scope_results: List of scope results from the pipeline
        run_id: Unique run identifier
        commit: Git commit hash at snapshot time
    """
    history_dir = docbot_dir / "history"
    history_dir.mkdir(exist_ok=True)
    
    # Compute snapshot components
    scope_summaries = _compute_scope_summaries(scope_results)
    graph_digest = _compute_graph_digest(docs_index)
    doc_hashes = _compute_doc_hashes(docbot_dir / "docs")
    stats = _compute_stats(docs_index, scope_results)
    
    # Create snapshot metadata
    snapshot = DocSnapshot(
        commit_hash=commit,
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        scope_summaries=scope_summaries,
        graph_digest=graph_digest,
        doc_hashes=doc_hashes,
        stats=stats,
    )
    
    # Save metadata
    metadata_path = history_dir / f"{run_id}.json"
    metadata_path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    
    # Save scope results to subdirectory
    scope_dir = history_dir / run_id
    scope_dir.mkdir(exist_ok=True)
    
    for sr in scope_results:
        scope_file = scope_dir / f"{sr.scope_id}.json"
        scope_file.write_text(sr.model_dump_json(indent=2), encoding="utf-8")


def load_snapshot(docbot_dir: Path, run_id: str) -> DocSnapshot | None:
    """Load a specific snapshot by run ID.
    
    Args:
        docbot_dir: Path to .docbot/ directory
        run_id: Run identifier to load
        
    Returns:
        DocSnapshot if found, None otherwise
    """
    metadata_path = docbot_dir / "history" / f"{run_id}.json"
    
    if not metadata_path.exists():
        return None
    
    try:
        return DocSnapshot.model_validate_json(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None


def list_snapshots(docbot_dir: Path) -> list[DocSnapshot]:
    """List all available snapshots, sorted by timestamp (newest first).
    
    Args:
        docbot_dir: Path to .docbot/ directory
        
    Returns:
        List of DocSnapshot objects, sorted newest to oldest
    """
    history_dir = docbot_dir / "history"
    
    if not history_dir.exists():
        return []
    
    snapshots: list[DocSnapshot] = []
    
    for metadata_file in history_dir.glob("*.json"):
        try:
            snapshot = DocSnapshot.model_validate_json(
                metadata_file.read_text(encoding="utf-8")
            )
            snapshots.append(snapshot)
        except (json.JSONDecodeError, ValueError):
            # Skip invalid snapshot files
            continue
    
    # Sort by timestamp, newest first
    snapshots.sort(key=lambda s: s.timestamp, reverse=True)
    
    return snapshots


def prune_snapshots(docbot_dir: Path, max_count: int) -> int:
    """Remove oldest snapshots beyond the retention limit.
    
    Keeps the most recent `max_count` snapshots and removes older ones,
    including both metadata files and scope result directories.
    
    Args:
        docbot_dir: Path to .docbot/ directory
        max_count: Maximum number of snapshots to retain
        
    Returns:
        Number of snapshots removed
    """
    snapshots = list_snapshots(docbot_dir)
    
    if len(snapshots) <= max_count:
        return 0
    
    # Identify snapshots to remove (oldest ones)
    to_remove = snapshots[max_count:]
    history_dir = docbot_dir / "history"
    removed_count = 0
    
    for snapshot in to_remove:
        # Remove metadata file
        metadata_path = history_dir / f"{snapshot.run_id}.json"
        if metadata_path.exists():
            metadata_path.unlink()
            removed_count += 1
        
        # Remove scope results directory
        scope_dir = history_dir / snapshot.run_id
        if scope_dir.exists() and scope_dir.is_dir():
            # Remove all files in the directory
            for scope_file in scope_dir.iterdir():
                if scope_file.is_file():
                    scope_file.unlink()
            # Remove the directory itself
            scope_dir.rmdir()
    
    return removed_count
