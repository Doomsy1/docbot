import { useCallback, useEffect, useState } from 'react';
import AdaptiveMixedGraph from './AdaptiveMixedGraph';
import type { MixedNode, MixedEdge } from './AdaptiveMixedGraph';
import { IconCpu } from '@tabler/icons-react';

interface DiffReport {
  from_id: string;
  to_id: string;
  added_scopes: string[];
  removed_scopes: string[];
  modified_scopes: { scope_id: string }[];
}

interface ScopeMeta {
  scope_id: string;
  title: string;
  file_count: number;
  symbol_count: number;
  group: string;
  summary?: string;
  description?: string;
}

interface ScopeEdge {
  from: string;
  to: string;
}

interface ScopeGraph {
  scopes: ScopeMeta[];
  scope_edges: ScopeEdge[];
}

interface Props {
  diff: DiffReport;
}

/**
 * Maps a change status to a visual group name used for color-coding.
 */
function diffGroup(status: 'added' | 'removed' | 'modified' | 'context'): string {
  return `diff_${status}`;
}

export default function DiffGraph({ diff }: Props) {
  const [nodes, setNodes] = useState<MixedNode[]>([]);
  const [edges, setEdges] = useState<MixedEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [isolatedNodeId, setIsolatedNodeId] = useState<string | null>(null);

  useEffect(() => {
    if (!diff) return;

    // Fetch the current (to) graph to get scope metadata + edges
    setLoading(true);
    fetch('/api/graph')
      .then(res => res.json())
      .then((graph: ScopeGraph) => {
        const addedSet = new Set(diff.added_scopes);
        const removedSet = new Set(diff.removed_scopes);
        const modifiedSet = new Set(diff.modified_scopes.map(m => m.scope_id));

        // Collect all changed scope IDs
        const changedIds = new Set([...addedSet, ...removedSet, ...modifiedSet]);

        // Find neighbor scopes connected to any changed scope
        const neighborIds = new Set<string>();
        for (const edge of graph.scope_edges) {
          if (changedIds.has(edge.from) && !changedIds.has(edge.to)) {
            neighborIds.add(edge.to);
          }
          if (changedIds.has(edge.to) && !changedIds.has(edge.from)) {
            neighborIds.add(edge.from);
          }
        }

        // The visible set is changed + neighbors
        const visibleIds = new Set([...changedIds, ...neighborIds]);

        // Build a lookup of scope metadata
        const scopeMap = new Map<string, ScopeMeta>();
        for (const s of graph.scopes) {
          scopeMap.set(s.scope_id, s);
        }

        // Build nodes
        const builtNodes: MixedNode[] = [];
        for (const id of visibleIds) {
          const meta = scopeMap.get(id);
          let status: 'added' | 'removed' | 'modified' | 'context' = 'context';
          if (addedSet.has(id)) status = 'added';
          else if (removedSet.has(id)) status = 'removed';
          else if (modifiedSet.has(id)) status = 'modified';

          builtNodes.push({
            id,
            kind: 'scope',
            label: meta?.title ?? id,
            group: diffGroup(status),
            description: meta?.description,
            scope_id: id,
            file_count: meta?.file_count ?? 0,
            entity_count: meta?.symbol_count ?? 0,
          });
        }

        // For removed scopes that might not be in the current graph,
        // ensure they still appear as nodes
        for (const id of removedSet) {
          if (!visibleIds.has(id)) {
            builtNodes.push({
              id,
              kind: 'scope',
              label: id,
              group: diffGroup('removed'),
              description: 'Removed scope',
              scope_id: id,
              file_count: 0,
              entity_count: 0,
            });
          }
        }

        // Build edges (only between visible nodes)
        const builtEdges: MixedEdge[] = [];
        const allNodeIds = new Set(builtNodes.map(n => n.id));
        for (const edge of graph.scope_edges) {
          if (allNodeIds.has(edge.from) && allNodeIds.has(edge.to)) {
            builtEdges.push({
              id: `${edge.from}->${edge.to}`,
              from: edge.from,
              to: edge.to,
              kind: 'scope_dep',
              weight: 1,
              directed: true,
            });
          }
        }

        setNodes(builtNodes);
        setEdges(builtEdges);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [diff]);

  // Escape key exits spotlight
  useEffect(() => {
    const onKeyDown = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') setIsolatedNodeId(null);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const handleNodeClick = useCallback((node: MixedNode) => {
    setSelectedNodeId(node.id);
  }, []);

  const toggleNodeIsolation = useCallback((node: MixedNode) => {
    setSelectedNodeId(node.id);
    setIsolatedNodeId((prev) => (prev === node.id ? null : node.id));
  }, []);

  if (loading) {
    return (
      <div className="h-[50vh] flex items-center justify-center">
        <IconCpu className="animate-spin text-gray-400" size={24} />
        <span className="ml-2 text-gray-400 font-mono text-sm">Loading graph...</span>
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <div className="h-[50vh] flex items-center justify-center text-gray-400 italic text-sm">
        No scope changes to visualize.
      </div>
    );
  }

  return (
    <div className="relative">
      {isolatedNodeId && (
        <div className="absolute top-2 left-3 z-10">
          <button
            onClick={() => setIsolatedNodeId(null)}
            className="inline-flex items-center justify-center h-7 px-3 border border-black bg-amber-100 text-black hover:bg-amber-200 text-xs font-mono"
            title="Exit spotlight (Esc)"
          >
            Exit Spotlight
          </button>
        </div>
      )}
      <AdaptiveMixedGraph
        nodes={nodes}
        edges={edges}
        selectedNodeId={selectedNodeId}
        isolatedNodeId={isolatedNodeId}
        onNodeClick={handleNodeClick}
        onNodeIsolateToggle={toggleNodeIsolation}
      />
      {/* Legend */}
      <div className="absolute bottom-3 left-3 bg-white/90 border border-black px-3 py-2 text-xs font-mono flex gap-4">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-green-500 inline-block" /> Added
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-red-500 inline-block" /> Removed
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-yellow-500 inline-block" /> Modified
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-gray-400 inline-block" /> Neighbor
        </span>
      </div>
    </div>
  );
}
