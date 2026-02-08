import { useRef, useEffect, useCallback, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { useAgentStream } from './useAgentStream';
import AgentDetail from './AgentDetail';
import NotepadViewer from './NotepadViewer';
import type { GraphNode } from './types';

const STATUS_COLORS: Record<string, string> = {
  running: '#22c55e',
  done: '#9ca3af',
  error: '#ef4444',
};

function AgentExplorer() {
  const {
    agents,
    graphNodes,
    graphLinks,
    notepads,
    selectedAgent,
    setSelectedAgent,
    isConnected,
    isDone,
  } = useAgentStream();

  const graphRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  // Track container size with ResizeObserver.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setDimensions({ width: Math.floor(width), height: Math.floor(height) });
        }
      }
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // Auto-zoom to fit whenever graph data changes.
  useEffect(() => {
    if (graphRef.current && graphNodes.length > 0) {
      const timer = setTimeout(() => {
        graphRef.current?.zoomToFit(400, 40);
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [graphNodes.length]);

  const handleNodeClick = useCallback(
    (node: any) => {
      if (node?.id) {
        setSelectedAgent(node.id as string);
      }
    },
    [setSelectedAgent],
  );

  const paintNode = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const gn = node as GraphNode & { x: number; y: number };
      const radius = Math.sqrt(gn.val || 4) * 2;
      const color = STATUS_COLORS[gn.status] || STATUS_COLORS.done;

      // Circle fill.
      ctx.beginPath();
      ctx.arc(gn.x, gn.y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();

      // Highlight ring for selected node.
      if (selectedAgent === gn.id) {
        ctx.strokeStyle = '#000';
        ctx.lineWidth = 1.5 / globalScale;
        ctx.stroke();
      }

      // Label below the node.
      const fontSize = Math.max(10 / globalScale, 2);
      ctx.font = `${fontSize}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = '#111';
      const label =
        gn.name.length > 20 ? gn.name.slice(0, 20) + '...' : gn.name;
      ctx.fillText(label, gn.x, gn.y + radius + 2);
    },
    [selectedAgent],
  );

  const runningCount = graphNodes.filter((n) => n.status === 'running').length;

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Status bar */}
      <div className="flex items-center gap-4 px-4 py-2 border-b border-black bg-gray-50">
        <div className="flex items-center gap-1.5">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              isConnected ? 'bg-green-500' : 'bg-red-500'
            }`}
          />
          <span className="text-xs font-mono text-gray-600">
            {isConnected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
        <span className="text-xs font-mono text-gray-500">
          Agents: {agents.size}
        </span>
        {runningCount > 0 && (
          <span className="text-xs font-mono text-green-700">
            Running: {runningCount}
          </span>
        )}
        <span
          className={`text-xs font-bold uppercase tracking-wide ${
            isDone ? 'text-gray-500' : 'text-green-600'
          }`}
        >
          {isDone ? 'Done' : 'In Progress'}
        </span>
      </div>

      {/* Main content: graph + detail panel */}
      <div className="flex-1 flex min-h-0">
        {/* Force graph area */}
        <div className="flex-1 relative" ref={containerRef}>
          {graphNodes.length === 0 ? (
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-sm font-mono text-gray-400 animate-pulse">
                Waiting for agents...
              </span>
            </div>
          ) : (
            <ForceGraph2D
              ref={graphRef}
              graphData={{ nodes: graphNodes, links: graphLinks }}
              width={dimensions.width}
              height={dimensions.height}
              backgroundColor="#fafafa"
              nodeCanvasObject={paintNode}
              nodePointerAreaPaint={(node: any, color: string, ctx: CanvasRenderingContext2D) => {
                const radius = Math.sqrt((node as GraphNode).val || 4) * 2 + 4;
                ctx.beginPath();
                ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
                ctx.fillStyle = color;
                ctx.fill();
              }}
              onNodeClick={handleNodeClick}
              linkDirectionalParticles={2}
              linkDirectionalParticleSpeed={0.005}
              linkColor={() => '#d1d5db'}
              linkWidth={1.5}
              cooldownTicks={80}
            />
          )}
        </div>

        {/* Detail panel */}
        {selectedAgent && agents.has(selectedAgent) && (
          <div className="w-96 border-l border-black bg-white overflow-auto">
            <AgentDetail
              agent={agents.get(selectedAgent)!}
              onClose={() => setSelectedAgent(null)}
            />
          </div>
        )}
      </div>

      {/* Notepad strip */}
      {notepads.size > 0 && (
        <div className="border-t border-black">
          <NotepadViewer notepads={notepads} />
        </div>
      )}
    </div>
  );
}

export default AgentExplorer;
