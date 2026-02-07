import { useCallback, useEffect, useState } from 'react';
import ReactFlow, { 
  MiniMap, 
  Controls, 
  Background, 
  useNodesState, 
  useEdgesState, 
  addEdge,
  Position
} from 'reactflow';
import type { Connection, Edge, Node } from 'reactflow';
import dagre from 'dagre';
import 'reactflow/dist/style.css';
import { IconFile, IconX, IconHierarchy, IconBoxModel2 } from '@tabler/icons-react';
import Mermaid from './Mermaid';

const nodeWidth = 200;
const nodeHeight = 50;

const getLayoutedElements = (nodes: Node[], edges: Edge[], direction = 'TB') => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));

  dagreGraph.setGraph({ rankdir: direction });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      ...node,
      targetPosition: direction === 'LR' ? Position.Left : Position.Top,
      sourcePosition: direction === 'LR' ? Position.Right : Position.Bottom,
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
};

interface GraphProps {
  onSelectFile?: (path: string) => void;
}

interface ScopeDetail {
  scope_id: string;
  title: string;
  summary: string;
  paths: string[];
}

export default function Graph({ onSelectFile }: GraphProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedScopeId, setSelectedScopeId] = useState<string | null>(null);
  const [scopeDetail, setScopeDetail] = useState<ScopeDetail | null>(null);
  const [view, setView] = useState<'flow' | 'mermaid'>('flow');
  const [mermaidGraph, setMermaidGraph] = useState<string | null>(null);

  const onConnect = useCallback((params: Edge | Connection) => setEdges((eds) => addEdge(params, eds)), [setEdges]);

  // Fetch graph structure
  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch('/api/graph');
        const data = await res.json();
        setMermaidGraph(data.mermaid_graph || null);
        
        const scopeEdges: { from: string; to: string }[] = data.scope_edges || [];
        const scopeList: string[] = data.scopes || [];

        // If no scopes found in the list but we have edges, fallback to edges (safety)
        if (scopeList.length === 0 && scopeEdges.length > 0) {
          const uniqueScopes = new Set<string>();
          scopeEdges.forEach(e => {
            uniqueScopes.add(e.from);
            uniqueScopes.add(e.to);
          });
          scopeList.push(...Array.from(uniqueScopes).sort());
        }

        const initialNodes: Node[] = scopeList.map((scopeId) => ({
          id: scopeId,
          position: { x: 0, y: 0 },
          data: { label: scopeId },
          style: { 
            border: '1px solid black', 
            background: 'white', 
            borderRadius: 0, 
            width: nodeWidth, 
            textAlign: 'center',
            padding: '10px',
            fontSize: '12px',
            fontFamily: 'monospace',
            cursor: 'pointer'
          },
        }));

        const initialEdges: Edge[] = scopeEdges.map((e, i) => ({
          id: `e-${i}`,
          source: e.from,
          target: e.to,
          style: { stroke: 'black' },
          animated: true,
          type: 'smoothstep'
        }));

        const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
          initialNodes,
          initialEdges
        );

        setNodes(layoutedNodes);
        setEdges(layoutedEdges);
      } catch (err) {
        console.error("Failed to fetch graph", err);
      }
    }
    fetchData();
  }, [setNodes, setEdges]);

  // Fetch scope details when selected
  useEffect(() => {
    if (!selectedScopeId) {
      setScopeDetail(null);
      return;
    }

    async function fetchDetail() {
      try {
        const res = await fetch(`/api/scopes/${selectedScopeId}`);
        if (!res.ok) throw new Error("Failed to fetch scope");
        const data = await res.json();
        setScopeDetail(data);
      } catch (err) {
        console.error(err);
      }
    }
    fetchDetail();
  }, [selectedScopeId]);

  const onNodeClick = (_: React.MouseEvent, node: Node) => {
    setSelectedScopeId(node.id);
  };

  return (
    <div className="h-full w-full border border-black relative flex flex-col">
      {/* View Toggle */}
      <div className="p-2 border-b border-black flex gap-2 bg-gray-50">
        <button 
            onClick={() => setView('flow')}
            className={`flex items-center gap-1.5 px-3 py-1 text-xs font-bold border border-black ${view === 'flow' ? 'bg-black text-white shadow-[2px_2px_0px_0px_rgba(0,0,0,0.3)]' : 'bg-white hover:bg-gray-100'}`}
        >
            <IconHierarchy size={14} />
            DEPENDENCY FLOW
        </button>
        {mermaidGraph && (
            <button 
                onClick={() => setView('mermaid')}
                className={`flex items-center gap-1.5 px-3 py-1 text-xs font-bold border border-black ${view === 'mermaid' ? 'bg-black text-white shadow-[2px_2px_0px_0px_rgba(0,0,0,0.3)]' : 'bg-white hover:bg-gray-100'}`}
            >
                <IconBoxModel2 size={14} />
                AI ARCHITECTURE
            </button>
        )}
      </div>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 h-full relative">
            {view === 'flow' ? (
                <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={onNodeClick}
                fitView
                >
                    <Controls showInteractive={false} className="!bg-white !border !border-black !shadow-none [&>button]:!border-b [&>button]:!border-black [&>button]:!fill-black" />
                    <Background color="#000" gap={20} size={1} />
                    <MiniMap 
                        style={{ border: '1px solid black' }} 
                        maskColor="rgba(255, 255, 255, 0.8)" 
                        nodeColor="black" 
                    />
                </ReactFlow>
            ) : (
                <div className="h-full overflow-auto p-12 bg-white flex flex-col items-center">
                    <div className="max-w-4xl w-full">
                        <div className="mb-8 border-b border-black pb-4">
                            <h2 className="text-2xl font-bold font-mono uppercase tracking-tighter italic flex items-center gap-3">
                                <IconBoxModel2 size={24} className="text-blue-600" />
                                AI Generated Architecture
                            </h2>
                            <p className="text-xs text-gray-400 font-mono mt-2">
                                Derived from codebase analysis using LLM patterns.
                            </p>
                        </div>
                        <Mermaid chart={mermaidGraph!} />
                    </div>
                </div>
            )}
        </div>

        {/* Side Panel */}
        {selectedScopeId && (
          <div className="w-1/3 min-w-[300px] border-l border-black bg-white h-full overflow-auto flex flex-col transition-all duration-300">
            <div className="p-4 border-b border-black flex justify-between items-start bg-gray-50 sticky top-0">
              <div>
                <h2 className="text-lg font-bold font-mono break-all">{scopeDetail?.title || selectedScopeId}</h2>
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
                    <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500">Summary</h3>
                    <p className="text-sm leading-relaxed text-gray-800">
                      {scopeDetail.summary || "No summary available."}
                    </p>
                  </div>

                  <div className="space-y-2">
                    <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500">
                      Files ({scopeDetail.paths.length})
                    </h3>
                    <div className="space-y-1">
                      {scopeDetail.paths.map(path => (
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
