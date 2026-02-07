"""Snapshot comparison and diff computation.

Provides functions to compare two documentation snapshots and generate
detailed reports of what changed between them.
"""

from __future__ import annotations

from .models import (
    DiffReport,
    DocSnapshot,
    GraphDelta,
    ScopeModification,
    StatsDelta,
)


def compute_diff(snapshot_from: DocSnapshot, snapshot_to: DocSnapshot) -> DiffReport:
    """Compare two snapshots and generate a detailed diff report.
    
    Args:
        snapshot_from: The earlier snapshot (baseline)
        snapshot_to: The later snapshot (current)
        
    Returns:
        DiffReport containing all changes between the snapshots
    """
    # Compare scope lists
    from_scopes = set(snapshot_from.scope_summaries.keys())
    to_scopes = set(snapshot_to.scope_summaries.keys())
    
    added_scopes = sorted(to_scopes - from_scopes)
    removed_scopes = sorted(from_scopes - to_scopes)
    common_scopes = from_scopes & to_scopes
    
    # Compare modified scopes
    modified_scopes: list[ScopeModification] = []
    
    for scope_id in sorted(common_scopes):
        from_summary = snapshot_from.scope_summaries[scope_id]
        to_summary = snapshot_to.scope_summaries[scope_id]
        
        # Check if summary changed
        summary_changed = from_summary.summary_hash != to_summary.summary_hash
        
        # For now, we don't have file-level or symbol-level tracking in the snapshot
        # So we'll just mark if the scope changed at all
        if (from_summary.file_count != to_summary.file_count or
            from_summary.symbol_count != to_summary.symbol_count or
            summary_changed):
            
            modification = ScopeModification(
                scope_id=scope_id,
                added_files=[],  # Would need scope results to compute
                removed_files=[],  # Would need scope results to compute
                added_symbols=[],  # Would need scope results to compute
                removed_symbols=[],  # Would need scope results to compute
                summary_changed=summary_changed,
            )
            modified_scopes.append(modification)
    
    # Compare graph changes
    graph_changes = _compute_graph_delta(snapshot_from, snapshot_to)
    
    # Compute stats deltas
    stats_delta = StatsDelta(
        total_files=snapshot_to.stats.total_files - snapshot_from.stats.total_files,
        total_scopes=snapshot_to.stats.total_scopes - snapshot_from.stats.total_scopes,
        total_symbols=snapshot_to.stats.total_symbols - snapshot_from.stats.total_symbols,
    )
    
    return DiffReport(
        added_scopes=added_scopes,
        removed_scopes=removed_scopes,
        modified_scopes=modified_scopes,
        graph_changes=graph_changes,
        stats_delta=stats_delta,
    )


def _compute_graph_delta(snapshot_from: DocSnapshot, snapshot_to: DocSnapshot) -> GraphDelta:
    """Compare graph digests and detect changes.
    
    Note: Since we only store a digest hash, we can only detect if the graph
    changed, not the specific edges that were added/removed. For detailed
    edge-level diffs, we would need to store the full edge list in the snapshot.
    """
    graph_changed = snapshot_from.graph_digest != snapshot_to.graph_digest
    
    if graph_changed:
        # Graph changed, but we don't have detailed edge information
        # Return empty lists with a changed_nodes indicator
        return GraphDelta(
            added_edges=[],
            removed_edges=[],
            changed_nodes=["<graph structure changed>"],
        )
    else:
        # No changes
        return GraphDelta(
            added_edges=[],
            removed_edges=[],
            changed_nodes=[],
        )


def compute_detailed_scope_diff(
    scope_id: str,
    from_scope_result: dict,
    to_scope_result: dict,
) -> ScopeModification:
    """Compare two scope results and generate detailed file/symbol diffs.
    
    This is a helper function for when you have the full scope results loaded
    (from .docbot/history/<run_id>/<scope_id>.json) and want detailed diffs.
    
    Args:
        scope_id: The scope identifier
        from_scope_result: Earlier scope result as dict
        to_scope_result: Later scope result as dict
        
    Returns:
        ScopeModification with detailed file and symbol changes
    """
    # Extract file paths
    from_files = set(f["path"] for f in from_scope_result.get("files", []))
    to_files = set(f["path"] for f in to_scope_result.get("files", []))
    
    added_files = sorted(to_files - from_files)
    removed_files = sorted(from_files - to_files)
    
    # Extract symbols from all files
    from_symbols = set()
    for f in from_scope_result.get("files", []):
        for sym in f.get("symbols", []):
            from_symbols.add(f"{sym.get('kind', '')}:{sym.get('name', '')}")
    
    to_symbols = set()
    for f in to_scope_result.get("files", []):
        for sym in f.get("symbols", []):
            to_symbols.add(f"{sym.get('kind', '')}:{sym.get('name', '')}")
    
    added_symbols = sorted(to_symbols - from_symbols)
    removed_symbols = sorted(from_symbols - to_symbols)
    
    # Check if summary changed
    from_summary = from_scope_result.get("summary", "")
    to_summary = to_scope_result.get("summary", "")
    summary_changed = from_summary != to_summary
    
    return ScopeModification(
        scope_id=scope_id,
        added_files=added_files,
        removed_files=removed_files,
        added_symbols=added_symbols,
        removed_symbols=removed_symbols,
        summary_changed=summary_changed,
    )
