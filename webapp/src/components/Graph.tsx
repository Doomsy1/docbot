import { useEffect, useState, useCallback, useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeProps,
  type EdgeProps,
  Handle,
  Position,
  useReactFlow,
  ReactFlowProvider,
  BaseEdge,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import ELK from 'elkjs/lib/elk.bundled.js';
import { IconFile, IconX } from '@tabler/icons-react';

const elk = new ELK();

const GROUP_COLORS: Record<string, string> = {
  frontend: '#3B82F6',
  backend:  '#22C55E',
  core:     '#F59E0B',
  testing:  '#EC4899',
  scripts:  '#8B5CF6',
  external: '#64748b',
};

const GROUP_BG: Record<string, string> = {
  frontend: '#EFF6FF',
  backend:  '#F0FDF4',
  core:     '#FFFBEB',
  testing:  '#FDF2F8',
  scripts:  '#F5F3FF',
  external: '#F1F5F9',
};

// Edge colors match source node group
const GROUP_EDGE_COLORS: Record<string, string> = {
  frontend: '#93C5FD',
  backend:  '#86EFAC',
  core:     '#FCD34D',
  testing:  '#F9A8D4',
  scripts:  '#C4B5FD',
  external: '#CBD5E1',
};

const GROUP_EDGE_ARROW: Record<string, string> = {
  frontend: '#3B82F6',
  backend:  '#22C55E',
  core:     '#F59E0B',
  testing:  '#EC4899',
  scripts:  '#8B5CF6',
  external: '#94A3B8',
};

interface ScopeMeta {
  scope_id: string;
  title: string;
  file_count: number;
  symbol_count: number;
  languages: string[];
  group: string;
}

interface ExternalMeta {
  id: string;
  title: string;
  icon: string;
}

interface GraphProps {
  onSelectFile?: (path: string) => void;
}

interface ScopeDetail {
  scope_id: string;
  title: string;
  summary: string;
  paths: string[];
}

const EXTERNAL_ICONS: Record<string, string> = {
  db: '\u{1F5C4}',
  cloud: '\u2601',
  ai: '\u2728',
  api: '\u{1F517}',
  auth: '\u{1F512}',
};

// Custom edge that follows ELK's computed bend points
function ElkEdge({ data, markerEnd, style }: EdgeProps) {
  const points: { x: number; y: number }[] = (data?.elkPoints as { x: number; y: number }[]) || [];

  if (points.length < 2) {
    return null;
  }

  // Build an SVG path from the ELK points
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length; i++) {
    d += ` L ${points[i].x} ${points[i].y}`;
  }

  return (
    <BaseEdge
      path={d}
      markerEnd={markerEnd}
      style={style}
    />
  );
}

function ScopeNode({ data, selected }: NodeProps) {
  const color = GROUP_COLORS[data.group as string] || GROUP_COLORS.core;
  const bg = GROUP_BG[data.group as string] || GROUP_BG.core;
  const files = data.file_count as number;
  const symbols = data.symbol_count as number;

  return (
    <>
      <Handle type="target" position={Position.Top} className="!bg-transparent !border-0 !w-3 !h-1" />
      <div
        className="px-4 py-3 rounded-lg text-center transition-shadow cursor-pointer"
        style={{
          background: bg,
          border: `2px solid ${color}`,
          boxShadow: selected ? `0 0 0 2px ${color}, 0 4px 12px rgba(0,0,0,0.15)` : '0 1px 4px rgba(0,0,0,0.08)',
          minWidth: 140,
          maxWidth: 200,
        }}
      >
        <div className="font-bold text-sm leading-tight" style={{ color: '#111' }}>
          {data.label as string}
        </div>
        <div className="text-[10px] text-gray-500 mt-1 font-mono">
          {files} file{files !== 1 ? 's' : ''} · {symbols} sym
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-transparent !border-0 !w-3 !h-1" />
    </>
  );
}

function ExternalNode({ data, selected }: NodeProps) {
  const icon = EXTERNAL_ICONS[(data.icon as string) || 'api'] || '\u{1F517}';

  return (
    <>
      <Handle type="target" position={Position.Top} className="!bg-transparent !border-0 !w-3 !h-1" />
      <div
        className="px-4 py-3 rounded-lg text-center transition-shadow cursor-pointer"
        style={{
          background: '#F8FAFC',
          border: '2px dashed #94A3B8',
          boxShadow: selected ? '0 0 0 2px #64748b, 0 4px 12px rgba(0,0,0,0.15)' : '0 1px 4px rgba(0,0,0,0.06)',
          minWidth: 120,
          maxWidth: 160,
        }}
      >
        <div className="text-lg leading-none">{icon}</div>
        <div className="font-bold text-xs text-slate-600 mt-1">{data.label as string}</div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-transparent !border-0 !w-3 !h-1" />
    </>
  );
}

const nodeTypes = {
  scope: ScopeNode,
  external: ExternalNode,
};

const edgeTypes = {
  elk: ElkEdge,
};

async function getLayoutedElements(
  nodes: Node[],
  edges: Edge[],
) {
  // Build ELK graph
  const elkNodes = nodes.map((n) => ({
    id: n.id,
    width: n.data.isExternal ? 140 : 180,
    height: n.data.isExternal ? 60 : 65,
  }));

  const elkEdges = edges.map((e) => ({
    id: e.id,
    sources: [e.source],
    targets: [e.target],
  }));

  const elkGraph = await elk.layout({
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'DOWN',
      'elk.spacing.nodeNode': '80',
      'elk.layered.spacing.nodeNodeBetweenLayers': '120',
      'elk.layered.spacing.edgeNodeBetweenLayers': '60',
      'elk.spacing.edgeEdge': '30',
      'elk.spacing.edgeNode': '40',
      'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
      'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
      'elk.edgeRouting': 'ORTHOGONAL',
      'elk.layered.mergeEdges': 'false',
      'elk.layered.unnecessaryBendpoints': 'true',
    },
    children: elkNodes,
    edges: elkEdges,
  });

  // Map positions back to ReactFlow nodes
  const posMap: Record<string, { x: number; y: number; width: number; height: number }> = {};
  for (const child of elkGraph.children || []) {
    posMap[child.id] = {
      x: child.x ?? 0,
      y: child.y ?? 0,
      width: child.width ?? 0,
      height: child.height ?? 0,
    };
  }

  const layoutedNodes = nodes.map((node) => ({
    ...node,
    position: posMap[node.id] ? { x: posMap[node.id].x, y: posMap[node.id].y } : { x: 0, y: 0 },
  }));

  // Extract ELK edge bend points and store them in edge data
  const elkEdgeMap: Record<string, { x: number; y: number }[]> = {};
  for (const elkEdge of elkGraph.edges || []) {
    const sections = (elkEdge as any).sections;
    if (sections && sections.length > 0) {
      const section = sections[0];
      const points: { x: number; y: number }[] = [];
      if (section.startPoint) points.push(section.startPoint);
      if (section.bendPoints) points.push(...section.bendPoints);
      if (section.endPoint) points.push(section.endPoint);
      elkEdgeMap[elkEdge.id] = points;
    }
  }

  const layoutedEdges = edges.map((edge) => ({
    ...edge,
    type: 'elk',
    data: {
      ...edge.data,
      elkPoints: elkEdgeMap[edge.id] || [],
    },
  }));

  return { nodes: layoutedNodes, edges: layoutedEdges };
}

function GraphInner({ onSelectFile }: GraphProps) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedScopeId, setSelectedScopeId] = useState<string | null>(null);
  const [scopeDetail, setScopeDetail] = useState<ScopeDetail | null>(null);
  const { fitView } = useReactFlow();

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch('/api/graph');
        const data = await res.json();
        const scopesMeta: ScopeMeta[] = data.scopes || [];
        const scopeEdges: { from: string; to: string }[] = data.scope_edges || [];
        const externalNodes: ExternalMeta[] = data.external_nodes || [];
        const externalEdges: { from: string; to: string }[] = data.external_edges || [];

        // Build group lookup
        const nodeGroupMap: Record<string, string> = {};
        for (const s of scopesMeta) nodeGroupMap[s.scope_id] = s.group;
        for (const ext of externalNodes) nodeGroupMap[ext.id] = 'external';

        const rfNodes: Node[] = scopesMeta.map((s) => ({
          id: s.scope_id,
          type: 'scope',
          position: { x: 0, y: 0 },
          data: {
            label: s.title,
            group: s.group,
            file_count: s.file_count,
            symbol_count: s.symbol_count,
            isExternal: false,
          },
        }));

        for (const ext of externalNodes) {
          rfNodes.push({
            id: ext.id,
            type: 'external',
            position: { x: 0, y: 0 },
            data: {
              label: ext.title,
              icon: ext.icon,
              isExternal: true,
            },
          });
        }

        const rfEdges: Edge[] = scopeEdges.map((e, i) => {
          const srcGroup = nodeGroupMap[e.from] || 'core';
          return {
            id: `e-${i}`,
            source: e.from,
            target: e.to,
            type: 'elk',
            style: {
              stroke: GROUP_EDGE_COLORS[srcGroup] || '#93C5FD',
              strokeWidth: 2,
            },
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: GROUP_EDGE_ARROW[srcGroup] || '#3B82F6',
              width: 16,
              height: 16,
            },
          };
        });

        externalEdges.forEach((e, i) => {
          const srcGroup = nodeGroupMap[e.from] || 'external';
          rfEdges.push({
            id: `ext-${i}`,
            source: e.from,
            target: e.to,
            type: 'elk',
            style: {
              stroke: GROUP_EDGE_COLORS[srcGroup] || '#CBD5E1',
              strokeWidth: 1.5,
              strokeDasharray: '6 4',
            },
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: GROUP_EDGE_ARROW[srcGroup] || '#94A3B8',
              width: 14,
              height: 14,
            },
          });
        });

        const { nodes: layoutedNodes, edges: layoutedEdges } =
          await getLayoutedElements(rfNodes, rfEdges);

        setNodes(layoutedNodes);
        setEdges(layoutedEdges);

        setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 100);
      } catch (err) {
        console.error('Failed to fetch graph', err);
      }
    }
    fetchData();
  }, [fitView]);

  useEffect(() => {
    if (!selectedScopeId) { setScopeDetail(null); return; }
    async function fetchDetail() {
      try {
        const res = await fetch(`/api/scopes/${selectedScopeId}`);
        if (!res.ok) throw new Error('Failed to fetch scope');
        setScopeDetail(await res.json());
      } catch (err) { console.error(err); }
    }
    fetchDetail();
  }, [selectedScopeId]);

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedScopeId(node.id);
  }, []);

  const activeGroups = useMemo(() => {
    const groups = new Set(
      nodes
        .map((n) => (n.data.group as string) || (n.data.isExternal ? 'external' : ''))
        .filter(Boolean),
    );
    return [...groups].sort();
  }, [nodes]);

  return (
    <div className="h-full w-full border border-black relative flex flex-col">
      <div className="p-2 px-3 border-b border-black flex items-center justify-between bg-gray-50">
        <span className="text-xs font-bold uppercase tracking-wide">System Architecture</span>
        <div className="flex items-center gap-3">
          {activeGroups.map((group) => (
            <div key={group} className="flex items-center gap-1">
              <div
                className="w-2.5 h-2.5 rounded-full"
                style={{ background: GROUP_COLORS[group] || GROUP_COLORS.core }}
              />
              <span className="text-[10px] uppercase tracking-wide text-gray-500">{group}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 h-full relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodeClick={onNodeClick}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            minZoom={0.1}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
            nodesDraggable={true}
            nodesConnectable={false}
            elementsSelectable={true}
          >
            <Background color="#e5e7eb" gap={20} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>

        {selectedScopeId && (
          <div className="w-1/3 min-w-[300px] border-l border-black bg-white h-full overflow-auto flex flex-col">
            <div className="p-4 border-b border-black flex justify-between items-start bg-gray-50 sticky top-0">
              <div>
                <h2 className="text-lg font-bold font-mono break-all">
                  {scopeDetail?.title || selectedScopeId}
                </h2>
                <div className="text-xs text-gray-500 font-mono mt-1">Scope Details</div>
              </div>
              <button
                onClick={() => setSelectedScopeId(null)}
                className="p-1 hover:bg-gray-200 rounded"
              >
                <IconX size={18} />
              </button>
            </div>
            <div className="p-4 space-y-6">
              {scopeDetail ? (
                <>
                  <div className="space-y-2">
                    <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500">
                      Summary
                    </h3>
                    <p className="text-sm leading-relaxed text-gray-800">
                      {scopeDetail.summary || 'No summary available.'}
                    </p>
                  </div>
                  <div className="space-y-2">
                    <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500">
                      Files ({scopeDetail.paths.length})
                    </h3>
                    <div className="space-y-1">
                      {scopeDetail.paths.map((path) => (
                        <div
                          key={path}
                          className="flex items-center gap-2 text-sm p-1.5 hover:bg-gray-100 cursor-pointer font-mono text-blue-600 truncate"
                          onClick={() => onSelectFile?.(path)}
                        >
                          <IconFile size={14} className="shrink-0 text-gray-400" />
                          <span className="truncate">{path}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <div className="flex items-center justify-center p-8">
                  <span className="animate-pulse text-gray-400 font-mono">Loading details...</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Graph({ onSelectFile }: GraphProps) {
  return (
    <ReactFlowProvider>
      <GraphInner onSelectFile={onSelectFile} />
    </ReactFlowProvider>
  );
}
