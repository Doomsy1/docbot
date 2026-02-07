import { useCallback, useEffect } from 'react';
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
      // We are shifting the dagre node position (anchor=center center) to the top left
      // so it matches the React Flow node anchor point (top left).
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
};

export default function Graph() {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const onConnect = useCallback((params: Edge | Connection) => setEdges((eds) => addEdge(params, eds)), [setEdges]);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch('/api/graph');
        const data = await res.json();
        const scopeEdges: { from: string; to: string }[] = data.scope_edges || [];

        // 1. Identify unique nodes
        const uniqueScopes = new Set<string>();
        scopeEdges.forEach(e => {
          uniqueScopes.add(e.from);
          uniqueScopes.add(e.to);
        });
        const scopeList = Array.from(uniqueScopes).sort();

        // 2. Create Initial Nodes (position doesn't matter, dagre will fix it)
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
            fontFamily: 'monospace'
          },
        }));

        // 3. Create Edges
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
  }, [setNodes, setEdges]); // Ensure dependency array is correct

  return (
    <div className="h-full w-full border border-black">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
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
    </div>
  );
}
