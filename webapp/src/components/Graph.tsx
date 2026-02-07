import { useCallback, useEffect } from 'react';
import ReactFlow, { 
  MiniMap, 
  Controls, 
  Background, 
  useNodesState, 
  useEdgesState, 
  addEdge,
} from 'reactflow';
import type { Connection, Edge, Node } from 'reactflow';
import 'reactflow/dist/style.css';

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

        // 2. Create Nodes with simple grid layout
        const COLS = 3;
        const X_GAP = 250;
        const Y_GAP = 100;
        
        const newNodes: Node[] = scopeList.map((scopeId, i) => ({
          id: scopeId,
          position: { 
            x: (i % COLS) * X_GAP, 
            y: Math.floor(i / COLS) * Y_GAP 
          },
          data: { label: scopeId },
          style: { 
            border: '1px solid black', 
            background: 'white', 
            borderRadius: 0, 
            width: 200, 
            textAlign: 'center',
            padding: '10px'
          },
        }));

        // 3. Create Edges
        const newEdges: Edge[] = scopeEdges.map((e, i) => ({
          id: `e-${i}`,
          source: e.from,
          target: e.to,
          style: { stroke: 'black' },
          animated: true,
          type: 'smoothstep'
        }));

        setNodes(newNodes);
        setEdges(newEdges);
      } catch (err) {
        console.error("Failed to fetch graph", err);
      }
    }
    fetchData();
  }, [setNodes, setEdges]);


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
        <MiniMap style={{ border: '1px solid black' }} maskColor="rgba(255, 255, 255, 0.8)" nodeColor="black" />
      </ReactFlow>
    </div>
  );
}
