import { useCallback } from 'react';
import ReactFlow, { 
  MiniMap, 
  Controls, 
  Background, 
  useNodesState, 
  useEdgesState, 
  addEdge,
} from 'reactflow';
import type { Connection, Edge } from 'reactflow';
import 'reactflow/dist/style.css';

const initialNodes = [
  { id: '1', position: { x: 0, y: 0 }, data: { label: 'docbot' }, style: { border: '1px solid black', background: 'white', borderRadius: 0 } },
  { id: '2', position: { x: 0, y: 100 }, data: { label: 'scanner.py' }, style: { border: '1px solid black', background: 'white', borderRadius: 0 } },
];
const initialEdges = [{ id: 'e1-2', source: '1', target: '2', style: { stroke: 'black' }, animated: false }];

export default function Graph() {
  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const onConnect = useCallback((params: Edge | Connection) => setEdges((eds) => addEdge(params, eds)), [setEdges]);

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
