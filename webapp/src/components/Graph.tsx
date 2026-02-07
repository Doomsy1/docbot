import { useEffect, useState, useRef, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { IconFile, IconX } from '@tabler/icons-react';

const GROUP_COLORS: Record<string, string> = {
  frontend: '#3B82F6',
  backend:  '#22C55E',
  core:     '#F59E0B',
  testing:  '#EC4899',
  scripts:  '#8B5CF6',
};

const GROUP_BG: Record<string, string> = {
  frontend: '#EFF6FF',
  backend:  '#F0FDF4',
  core:     '#FFFBEB',
  testing:  '#FDF2F8',
  scripts:  '#F5F3FF',
};

interface ScopeMeta {
  scope_id: string;
  title: string;
  file_count: number;
  symbol_count: number;
  languages: string[];
  group: string;
}

interface GraphNode {
  id: string;
  title: string;
  group: string;
  file_count: number;
  symbol_count: number;
  x?: number;
  y?: number;
}

interface GraphLink {
  source: string;
  target: string;
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

export default function Graph({ onSelectFile }: GraphProps) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [graphData, setGraphData] = useState<{ nodes: GraphNode[]; links: GraphLink[] }>({ nodes: [], links: [] });
  const [selectedScopeId, setSelectedScopeId] = useState<string | null>(null);
  const [scopeDetail, setScopeDetail] = useState<ScopeDetail | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  // Track container size
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Fetch graph data
  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch('/api/graph');
        const data = await res.json();

        const scopesMeta: ScopeMeta[] = data.scopes || [];
        const scopeEdges: { from: string; to: string }[] = data.scope_edges || [];

        const nodes: GraphNode[] = scopesMeta.map((s) => ({
          id: s.scope_id,
          title: s.title,
          group: s.group,
          file_count: s.file_count,
          symbol_count: s.symbol_count,
        }));

        const links: GraphLink[] = scopeEdges.map((e) => ({
          source: e.from,
          target: e.to,
        }));

        setGraphData({ nodes, links });
      } catch (err) {
        console.error('Failed to fetch graph', err);
      }
    }
    fetchData();
  }, []);

  // Configure forces and zoom to fit after data loads
  useEffect(() => {
    if (graphData.nodes.length > 0 && fgRef.current) {
      // Strong repulsion to keep nodes well-separated
      fgRef.current.d3Force('charge').strength(-1500).distanceMax(800);
      // Long link distance for breathing room
      fgRef.current.d3Force('link').distance(250);
      // Gentle center pull to keep the graph compact
      fgRef.current.d3Force('center').strength(0.03);

      // Group nodes by cluster using a custom force
      const groupCenters: Record<string, { x: number; y: number }> = {};
      const groupOrder = ['frontend', 'core', 'backend', 'scripts', 'testing'];
      const angleStep = (2 * Math.PI) / groupOrder.length;
      const radius = 300;
      groupOrder.forEach((g, i) => {
        groupCenters[g] = {
          x: Math.cos(angleStep * i - Math.PI / 2) * radius,
          y: Math.sin(angleStep * i - Math.PI / 2) * radius,
        };
      });

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      fgRef.current.d3Force('cluster', (alpha: number) => {
        for (const node of graphData.nodes) {
          const center = groupCenters[node.group];
          if (!center || node.x == null || node.y == null) continue;
          node.x += (center.x - node.x) * alpha * 0.3;
          node.y += (center.y - node.y) * alpha * 0.3;
        }
      });

      setTimeout(() => {
        fgRef.current?.zoomToFit(600, 100);
      }, 4500);
    }
  }, [graphData]);

  // Fetch scope details when selected
  useEffect(() => {
    if (!selectedScopeId) {
      setScopeDetail(null);
      return;
    }
    async function fetchDetail() {
      try {
        const res = await fetch(`/api/scopes/${selectedScopeId}`);
        if (!res.ok) throw new Error('Failed to fetch scope');
        setScopeDetail(await res.json());
      } catch (err) {
        console.error(err);
      }
    }
    fetchDetail();
  }, [selectedScopeId]);

  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedScopeId(node.id);
  }, []);

  const NODE_RADIUS = 28;

  const nodeCanvasObject = useCallback((node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const x = node.x || 0;
    const y = node.y || 0;
    const color = GROUP_COLORS[node.group] || GROUP_COLORS.core;
    const bg = GROUP_BG[node.group] || GROUP_BG.core;
    const isSelected = node.id === selectedScopeId;
    const isHovered = node.id === hoveredNode;
    const r = NODE_RADIUS;

    // Shadow
    if (isSelected || isHovered) {
      ctx.beginPath();
      ctx.arc(x + 2 / globalScale, y + 2 / globalScale, r, 0, 2 * Math.PI);
      ctx.fillStyle = 'rgba(0,0,0,0.1)';
      ctx.fill();
    }

    // Circle background
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fillStyle = bg;
    ctx.fill();

    // Circle border
    ctx.strokeStyle = color;
    ctx.lineWidth = (isSelected ? 3 : isHovered ? 2.5 : 1.5) / globalScale;
    ctx.stroke();

    // Title text (inside circle)
    const fontSize = Math.max(9 / globalScale, 2.5);
    ctx.fillStyle = '#111';
    ctx.font = `bold ${fontSize}px sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    // Wrap title to fit in circle
    const maxWidth = r * 1.6;
    const words = node.title.split(' ');
    const lines: string[] = [];
    let currentLine = '';
    for (const word of words) {
      const test = currentLine ? `${currentLine} ${word}` : word;
      if (ctx.measureText(test).width > maxWidth && currentLine) {
        lines.push(currentLine);
        currentLine = word;
      } else {
        currentLine = test;
      }
    }
    if (currentLine) lines.push(currentLine);

    const lineHeight = fontSize * 1.3;
    const totalHeight = lines.length * lineHeight;
    const startY = y - totalHeight / 2 + lineHeight / 2;

    for (let i = 0; i < lines.length; i++) {
      ctx.fillText(lines[i], x, startY + i * lineHeight);
    }
  }, [selectedScopeId, hoveredNode]);

  const nodePointerAreaPaint = useCallback((node: GraphNode, color: string, ctx: CanvasRenderingContext2D) => {
    const x = node.x || 0;
    const y = node.y || 0;
    ctx.beginPath();
    ctx.arc(x, y, NODE_RADIUS, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();
  }, []);

  // Build legend from active groups
  const activeGroups = [...new Set(graphData.nodes.map((n) => n.group))].sort();

  return (
    <div className="h-full w-full border border-black relative flex flex-col">
      {/* Header */}
      <div className="p-2 px-3 border-b border-black flex items-center justify-between bg-gray-50">
        <span className="text-xs font-bold uppercase tracking-wide">System Architecture</span>
        <div className="flex items-center gap-3">
          {activeGroups.map((group) => (
            <div key={group} className="flex items-center gap-1">
              <div
                className="w-2.5 h-2.5 rounded-sm"
                style={{ background: GROUP_COLORS[group] || GROUP_COLORS.core }}
              />
              <span className="text-[10px] uppercase tracking-wide text-gray-500">{group}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 h-full relative" ref={containerRef}>
          <ForceGraph2D
            ref={fgRef}
            graphData={graphData}
            width={selectedScopeId ? dimensions.width * 0.67 : dimensions.width}
            height={dimensions.height}
            nodeCanvasObject={nodeCanvasObject}
            nodePointerAreaPaint={nodePointerAreaPaint}
            onNodeClick={handleNodeClick}
            onNodeHover={(node) => setHoveredNode(node ? (node as GraphNode).id : null)}
            linkColor={() => '#64748b'}
            linkWidth={1.5}
            linkDirectionalArrowLength={8}
            linkDirectionalArrowRelPos={0.85}
            linkDirectionalArrowColor={() => '#475569'}
            linkCurvature={0.2}
            nodeRelSize={NODE_RADIUS}
            d3AlphaDecay={0.015}
            d3VelocityDecay={0.2}
            cooldownTime={4000}
            enableNodeDrag={true}
          />
        </div>

        {/* Side Panel */}
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
                    <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500">Summary</h3>
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
