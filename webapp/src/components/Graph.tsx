import { useEffect, useState, useRef, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { IconFile, IconX } from '@tabler/icons-react';

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
  icon: string; // "db" | "cloud" | "ai" | "api" | "auth"
}

interface GraphNode {
  id: string;
  title: string;
  group: string;
  file_count: number;
  symbol_count: number;
  radius: number;
  isExternal?: boolean;
  externalIcon?: string;
  x?: number;
  y?: number;
}

interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  isExternal?: boolean;
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

function getNodeRadius(fileCount: number, symbolCount: number, allNodes: ScopeMeta[]): number {
  const size = fileCount + symbolCount;
  const sizes = allNodes.map(n => n.file_count + n.symbol_count);
  const maxSize = Math.max(...sizes, 1);
  const minSize = Math.min(...sizes, 0);
  const range = maxSize - minSize || 1;
  // Scale from 35 to 65
  return 35 + ((size - minSize) / range) * 30;
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
        setDimensions({ width: entry.contentRect.width, height: entry.contentRect.height });
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

        const externalNodes: ExternalMeta[] = data.external_nodes || [];
        const externalEdges: { from: string; to: string }[] = data.external_edges || [];

        const nodes: GraphNode[] = scopesMeta.map((s) => ({
          id: s.scope_id,
          title: s.title,
          group: s.group,
          file_count: s.file_count,
          symbol_count: s.symbol_count,
          radius: getNodeRadius(s.file_count, s.symbol_count, scopesMeta),
        }));

        // Add external service nodes
        for (const ext of externalNodes) {
          nodes.push({
            id: ext.id,
            title: ext.title,
            group: 'external',
            file_count: 0,
            symbol_count: 0,
            radius: 28,
            isExternal: true,
            externalIcon: ext.icon,
          });
        }

        const links: GraphLink[] = scopeEdges.map((e) => ({
          source: e.from,
          target: e.to,
        }));

        // Add external edges
        for (const e of externalEdges) {
          links.push({ source: e.from, target: e.to, isExternal: true });
        }

        setGraphData({ nodes, links });
      } catch (err) {
        console.error('Failed to fetch graph', err);
      }
    }
    fetchData();
  }, []);

  // Configure forces and zoom to fit
  useEffect(() => {
    if (graphData.nodes.length > 0 && fgRef.current) {
      fgRef.current.d3Force('charge').strength(-2500).distanceMax(1000);
      fgRef.current.d3Force('link').distance(320);
      fgRef.current.d3Force('center').strength(0.03);

      // Cluster by group
      const groupCenters: Record<string, { x: number; y: number }> = {};
      const groupOrder = ['frontend', 'core', 'backend', 'scripts', 'testing'];
      const angleStep = (2 * Math.PI) / groupOrder.length;
      const clusterRadius = 400;
      groupOrder.forEach((g, i) => {
        groupCenters[g] = {
          x: Math.cos(angleStep * i - Math.PI / 2) * clusterRadius,
          y: Math.sin(angleStep * i - Math.PI / 2) * clusterRadius,
        };
      });

      fgRef.current.d3Force('cluster', (alpha: number) => {
        for (const node of graphData.nodes) {
          const center = groupCenters[node.group];
          if (!center || node.x == null || node.y == null) continue;
          node.x += (center.x - node.x) * alpha * 0.3;
          node.y += (center.y - node.y) * alpha * 0.3;
        }
      });

      // Collision force to prevent overlap based on actual radii
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      fgRef.current.d3Force('collide', (alpha: number) => {
        const nodes = graphData.nodes;
        for (let i = 0; i < nodes.length; i++) {
          for (let j = i + 1; j < nodes.length; j++) {
            const a = nodes[i];
            const b = nodes[j];
            if (a.x == null || a.y == null || b.x == null || b.y == null) continue;
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const minDist = a.radius + b.radius + 20;
            if (dist < minDist) {
              const push = (minDist - dist) * alpha * 0.5;
              const nx = dx / dist;
              const ny = dy / dist;
              a.x -= nx * push;
              a.y -= ny * push;
              b.x += nx * push;
              b.y += ny * push;
            }
          }
        }
      });

      setTimeout(() => {
        fgRef.current?.zoomToFit(600, 100);
      }, 4500);
    }
  }, [graphData]);

  // Fetch scope details when selected
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

  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedScopeId(node.id);
  }, []);

  // Draw curved arrows with gradient color
  const linkCanvasObject = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const source = link.source as GraphNode;
      const target = link.target as GraphNode;
      if (!source.x || !source.y || !target.x || !target.y) return;

      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const nx = dx / dist;
      const ny = dy / dist;

      const srcR = source.radius || 35;
      const tgtR = target.radius || 35;
      const sx = source.x + nx * srcR;
      const sy = source.y + ny * srcR;
      const ex = target.x - nx * tgtR;
      const ey = target.y - ny * tgtR;

      // Control point for curve
      const px = -ny;
      const py = nx;
      const curvature = dist * 0.15;
      const ctrlX = (sx + ex) / 2 + px * curvature;
      const ctrlY = (sy + ey) / 2 + py * curvature;

      const isExternal = !!(link as GraphLink).isExternal;
      const lineWidth = 2 / globalScale;

      // Draw the curve as small segments with gradient color
      const steps = 32;
      const sourceColor = isExternal
        ? { r: 148, g: 163, b: 184 }  // slate-400
        : { r: 191, g: 219, b: 254 }; // blue-200
      const targetColor = isExternal
        ? { r: 71, g: 85, b: 105 }    // slate-600
        : { r: 30, g: 64, b: 175 };   // blue-800

      for (let i = 0; i < steps; i++) {
        const t0 = i / steps;
        const t1 = (i + 1) / steps;

        // Start point of segment
        const x0 = (1-t0)*(1-t0)*sx + 2*(1-t0)*t0*ctrlX + t0*t0*ex;
        const y0 = (1-t0)*(1-t0)*sy + 2*(1-t0)*t0*ctrlY + t0*t0*ey;
        // End point of segment
        const x1 = (1-t1)*(1-t1)*sx + 2*(1-t1)*t1*ctrlX + t1*t1*ex;
        const y1 = (1-t1)*(1-t1)*sy + 2*(1-t1)*t1*ctrlY + t1*t1*ey;

        // Interpolate color at midpoint of segment
        const tMid = (t0 + t1) / 2;
        const r = Math.round(sourceColor.r + (targetColor.r - sourceColor.r) * tMid);
        const g = Math.round(sourceColor.g + (targetColor.g - sourceColor.g) * tMid);
        const b = Math.round(sourceColor.b + (targetColor.b - sourceColor.b) * tMid);

        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y1);
        ctx.strokeStyle = `rgb(${r},${g},${b})`;
        ctx.lineWidth = lineWidth;
        if (isExternal) {
          ctx.setLineDash([6 / globalScale, 4 / globalScale]);
        }
        ctx.stroke();
        if (isExternal) {
          ctx.setLineDash([]);
        }
      }

      // Arrowhead aligned to curve tangent at end
      const tgx = 2 * (1-1) * (ctrlX - sx) + 2 * 1 * (ex - ctrlX);
      const tgy = 2 * (1-1) * (ctrlY - sy) + 2 * 1 * (ey - ctrlY);
      const tgl = Math.sqrt(tgx * tgx + tgy * tgy) || 1;
      const anx = tgx / tgl;
      const any_ = tgy / tgl;
      const apx = -any_;
      const apy = anx;

      const arrowLen = 12 / globalScale;
      const arrowWidth = 6 / globalScale;

      ctx.beginPath();
      ctx.moveTo(ex, ey);
      ctx.lineTo(ex - anx * arrowLen + apx * arrowWidth, ey - any_ * arrowLen + apy * arrowWidth);
      ctx.lineTo(ex - anx * arrowLen - apx * arrowWidth, ey - any_ * arrowLen - apy * arrowWidth);
      ctx.closePath();
      ctx.fillStyle = `rgb(${targetColor.r},${targetColor.g},${targetColor.b})`;
      ctx.fill();
    },
    []
  );

  // Icon symbols for external services
  const EXTERNAL_ICONS: Record<string, string> = {
    db: '\u{1F5C4}',      // file cabinet (database)
    cloud: '\u2601',       // cloud
    ai: '\u2728',          // sparkles (AI)
    api: '\u{1F517}',      // link (API)
    auth: '\u{1F512}',     // lock (auth)
  };

  const nodeCanvasObject = useCallback((node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const x = node.x || 0;
    const y = node.y || 0;
    const isSelected = node.id === selectedScopeId;
    const isHovered = node.id === hoveredNode;
    const r = node.radius;

    if (node.isExternal) {
      // External service node — rounded rect with dashed border
      const w = r * 2;
      const h = r * 1.4;
      const cornerR = 8 / globalScale;

      // Shadow
      if (isSelected || isHovered) {
        ctx.fillStyle = 'rgba(0,0,0,0.08)';
        ctx.beginPath();
        ctx.roundRect(x - w/2 + 2/globalScale, y - h/2 + 2/globalScale, w, h, cornerR);
        ctx.fill();
      }

      // Background
      ctx.beginPath();
      ctx.roundRect(x - w/2, y - h/2, w, h, cornerR);
      ctx.fillStyle = '#f1f5f9';
      ctx.fill();

      // Dashed border
      ctx.setLineDash([6 / globalScale, 4 / globalScale]);
      ctx.strokeStyle = '#64748b';
      ctx.lineWidth = (isSelected ? 2.5 : isHovered ? 2 : 1.5) / globalScale;
      ctx.stroke();
      ctx.setLineDash([]);

      // Icon
      const iconSize = Math.max(12 / globalScale, 4);
      const icon = EXTERNAL_ICONS[node.externalIcon || 'api'] || '\u{1F517}';
      ctx.font = `${iconSize}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(icon, x, y - iconSize * 0.6);

      // Title
      const fontSize = Math.max(10 / globalScale, 3);
      ctx.font = `bold ${fontSize}px sans-serif`;
      ctx.fillStyle = '#334155';
      ctx.fillText(node.title, x, y + iconSize * 0.5);

      return;
    }

    // Regular scope node
    const color = GROUP_COLORS[node.group] || GROUP_COLORS.core;
    const bg = GROUP_BG[node.group] || GROUP_BG.core;

    // Shadow
    if (isSelected || isHovered) {
      ctx.beginPath();
      ctx.arc(x + 2 / globalScale, y + 2 / globalScale, r, 0, 2 * Math.PI);
      ctx.fillStyle = 'rgba(0,0,0,0.1)';
      ctx.fill();
    }

    // Circle
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fillStyle = bg;
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = (isSelected ? 3 : isHovered ? 2.5 : 1.5) / globalScale;
    ctx.stroke();

    // Auto-size text to fit inside circle
    const maxTextWidth = r * 1.5;
    const maxTextHeight = r * 1.4;
    let fontSize = Math.max(12 / globalScale, 3);

    function wrapText(size: number): string[] {
      ctx.font = `bold ${size}px sans-serif`;
      const words = node.title.split(' ');
      const lines: string[] = [];
      let current = '';
      for (const word of words) {
        const test = current ? `${current} ${word}` : word;
        if (ctx.measureText(test).width > maxTextWidth && current) {
          lines.push(current);
          current = word;
        } else {
          current = test;
        }
      }
      if (current) lines.push(current);
      return lines;
    }

    let lines = wrapText(fontSize);
    let lineHeight = fontSize * 1.25;
    while (lines.length * lineHeight > maxTextHeight && fontSize > 2) {
      fontSize *= 0.85;
      lines = wrapText(fontSize);
      lineHeight = fontSize * 1.25;
    }

    ctx.font = `bold ${fontSize}px sans-serif`;
    ctx.fillStyle = '#111';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    const totalHeight = lines.length * lineHeight;
    const startY = y - totalHeight / 2 + lineHeight / 2;
    for (let i = 0; i < lines.length; i++) {
      ctx.fillText(lines[i], x, startY + i * lineHeight);
    }
  }, [selectedScopeId, hoveredNode]);

  const nodePointerAreaPaint = useCallback((node: GraphNode, color: string, ctx: CanvasRenderingContext2D) => {
    const x = node.x || 0;
    const y = node.y || 0;
    if (node.isExternal) {
      const w = node.radius * 2;
      const h = node.radius * 1.4;
      ctx.fillStyle = color;
      ctx.fillRect(x - w/2, y - h/2, w, h);
    } else {
      ctx.beginPath();
      ctx.arc(x, y, node.radius, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
    }
  }, []);

  const activeGroups = [...new Set(graphData.nodes.map((n) => n.group))].sort();

  return (
    <div className="h-full w-full border border-black relative flex flex-col">
      <div className="p-2 px-3 border-b border-black flex items-center justify-between bg-gray-50">
        <span className="text-xs font-bold uppercase tracking-wide">System Architecture</span>
        <div className="flex items-center gap-3">
          {activeGroups.map((group) => (
            <div key={group} className="flex items-center gap-1">
              <div className="w-2.5 h-2.5 rounded-full" style={{ background: GROUP_COLORS[group] || GROUP_COLORS.core }} />
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
            linkCanvasObject={linkCanvasObject}
            linkCanvasObjectMode={() => 'replace'}
            d3AlphaDecay={0.015}
            d3VelocityDecay={0.2}
            cooldownTime={4000}
            enableNodeDrag={true}
          />
        </div>

        {selectedScopeId && (
          <div className="w-1/3 min-w-[300px] border-l border-black bg-white h-full overflow-auto flex flex-col">
            <div className="p-4 border-b border-black flex justify-between items-start bg-gray-50 sticky top-0">
              <div>
                <h2 className="text-lg font-bold font-mono break-all">{scopeDetail?.title || selectedScopeId}</h2>
                <div className="text-xs text-gray-500 font-mono mt-1">Scope Details</div>
              </div>
              <button onClick={() => setSelectedScopeId(null)} className="p-1 hover:bg-gray-200 rounded">
                <IconX size={18} />
              </button>
            </div>
            <div className="p-4 space-y-6">
              {scopeDetail ? (
                <>
                  <div className="space-y-2">
                    <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500">Summary</h3>
                    <p className="text-sm leading-relaxed text-gray-800">{scopeDetail.summary || 'No summary available.'}</p>
                  </div>
                  <div className="space-y-2">
                    <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500">Files ({scopeDetail.paths.length})</h3>
                    <div className="space-y-1">
                      {scopeDetail.paths.map((path) => (
                        <div key={path} className="flex items-center gap-2 text-sm p-1.5 hover:bg-gray-100 cursor-pointer font-mono text-blue-600 truncate" onClick={() => onSelectFile?.(path)}>
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
