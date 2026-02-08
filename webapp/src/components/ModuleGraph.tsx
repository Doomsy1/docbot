import { useEffect, useRef, useCallback } from 'react';

interface ModuleNode {
  id: string;
  label: string;
  scope_id: string;
  scope_title: string;
  file_count: number;
  symbol_count: number;
  import_count: number;
  languages: string[];
  group: string;
  description?: string;
}

interface ScopeGroup {
  scope_id: string;
  title: string;
  file_count: number;
  group: string;
}

interface Props {
  moduleNodes: ModuleNode[];
  moduleEdges: Array<{ from: string; to: string; weight: number }>;
  scopeGroups: ScopeGroup[];
  onModuleClick?: (node: { id: string; label: string; scopeId: string; scopeTitle: string }) => void;
}

interface SimNode {
  id: string;
  label: string;
  scopeId: string;
  scopeTitle: string;
  fileCount: number;
  symbolCount: number;
  importCount: number;
  languages: string[];
  group: string;
  description?: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

const MODULE_NODE_MIN_RADIUS = 16;
const MODULE_NODE_MAX_RADIUS = 38;

const SCOPE_COLORS: Record<string, string> = {
  frontend: '#3b82f6',
  backend: '#10b981',
  testing: '#f59e0b',
  scripts: '#8b5cf6',
  core: '#6b7280',
};

function scopeColor(group: string, scopeIndex: number): string {
  const base = SCOPE_COLORS[group] ?? SCOPE_COLORS.core;
  if (scopeIndex === 0) return base;
  const shift = scopeIndex * 35;
  const r = parseInt(base.slice(1, 3), 16) / 255;
  const g = parseInt(base.slice(3, 5), 16) / 255;
  const b = parseInt(base.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const l = (max + min) / 2;
  let h = 0, s = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) * 60;
    else if (max === g) h = ((b - r) / d + 2) * 60;
    else h = ((r - g) / d + 4) * 60;
  }
  h = (h + shift) % 360;
  return `hsl(${h}, ${Math.round(s * 70 + 20)}%, ${Math.round(l * 100)}%)`;
}

export default function ModuleGraph({ moduleNodes, moduleEdges, scopeGroups, onModuleClick }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<SimNode[]>([]);
  const animRef = useRef<number>(0);
  const dragRef = useRef<{ node: SimNode; offsetX: number; offsetY: number } | null>(null);
  const hoverRef = useRef<SimNode | null>(null);
  const panRef = useRef({ x: 0, y: 0 });
  const zoomRef = useRef(1);
  const isPanningRef = useRef(false);
  const panStartRef = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const scopeColorMapRef = useRef<Map<string, string>>(new Map());
  const downRef = useRef<{ x: number; y: number; nodeId: string | null }>({ x: 0, y: 0, nodeId: null });

  const toWorld = useCallback((sx: number, sy: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    return {
      x: (sx - canvas.width / 2) / zoomRef.current - panRef.current.x,
      y: (sy - canvas.height / 2) / zoomRef.current - panRef.current.y,
    };
  }, []);

  // Initialize nodes
  useEffect(() => {
    const colorMap = new Map<string, string>();
    const groupCounters: Record<string, number> = {};
    for (const sg of scopeGroups) {
      const idx = groupCounters[sg.group] ?? 0;
      groupCounters[sg.group] = idx + 1;
      colorMap.set(sg.scope_id, scopeColor(sg.group, idx));
    }
    scopeColorMapRef.current = colorMap;

    // Group modules by scope and arrange in clusters
    const scopeModules = new Map<string, ModuleNode[]>();
    for (const mn of moduleNodes) {
      if (!scopeModules.has(mn.scope_id)) scopeModules.set(mn.scope_id, []);
      scopeModules.get(mn.scope_id)!.push(mn);
    }

    const scopeIds = [...scopeModules.keys()];
    const scopeAngle = (2 * Math.PI) / Math.max(scopeIds.length, 1);
    const clusterRadius = Math.min(460, Math.max(240, scopeIds.length * 74));

    const nodes: SimNode[] = [];

    scopeIds.forEach((sid, si) => {
      const modules = scopeModules.get(sid)!;
      const cx = Math.cos(scopeAngle * si) * clusterRadius;
      const cy = Math.sin(scopeAngle * si) * clusterRadius;
      const modAngle = (2 * Math.PI) / Math.max(modules.length, 1);
      const modRadius = Math.min(170, Math.max(70, modules.length * 34));

      modules.forEach((m, mi) => {
        nodes.push({
          id: m.id,
          label: m.label,
          scopeId: m.scope_id,
          scopeTitle: m.scope_title,
          fileCount: m.file_count,
          symbolCount: m.symbol_count,
          importCount: m.import_count,
          languages: m.languages,
          group: m.group,
          description: m.description,
          x: cx + Math.cos(modAngle * mi) * modRadius,
          y: cy + Math.sin(modAngle * mi) * modRadius,
          vx: 0,
          vy: 0,
        });
      });
    });

    nodesRef.current = nodes;
    panRef.current = { x: 0, y: 0 };
    zoomRef.current = 1;
  }, [moduleNodes, scopeGroups]);

  // Simulation + render loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let running = true;
    let tick = 0;

    function resize() {
      if (!canvas) return;
      const rect = canvas.parentElement?.getBoundingClientRect();
      if (rect) {
        canvas.width = rect.width;
        canvas.height = rect.height;
      }
    }
    resize();
    const obs = new ResizeObserver(resize);
    obs.observe(canvas.parentElement!);

    function getScopeCentroids(): Map<string, { cx: number; cy: number; count: number }> {
      const centroids = new Map<string, { cx: number; cy: number; count: number }>();
      for (const n of nodesRef.current) {
        const c = centroids.get(n.scopeId);
        if (c) {
          c.cx += n.x;
          c.cy += n.y;
          c.count++;
        } else {
          centroids.set(n.scopeId, { cx: n.x, cy: n.y, count: 1 });
        }
      }
      for (const c of centroids.values()) {
        c.cx /= c.count;
        c.cy /= c.count;
      }
      return centroids;
    }

    function simulate() {
      const nodes = nodesRef.current;
      if (nodes.length === 0) return;
      const alpha = Math.max(0.005, 0.3 * Math.pow(0.995, tick));

      // Repulsion between all pairs
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[j].x - nodes[i].x;
          const dy = nodes[j].y - nodes[i].y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const sameScope = nodes[i].scopeId === nodes[j].scopeId;
          const repulsion = sameScope ? 1700 : 3200;
          const force = (repulsion / (dist * dist)) * alpha;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          nodes[i].vx -= fx;
          nodes[i].vy -= fy;
          nodes[j].vx += fx;
          nodes[j].vy += fy;
        }
      }

      // Spring forces on module edges
      const nodeMap = new Map(nodes.map((n) => [n.id, n]));
      for (const e of moduleEdges) {
        const a = nodeMap.get(e.from);
        const b = nodeMap.get(e.to);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const target = a.scopeId === b.scopeId ? 130 : 250;
        const strength = Math.min(0.08, 0.03 + e.weight * 0.008);
        const force = ((dist - target) / dist) * strength * alpha;
        a.vx += dx * force;
        a.vy += dy * force;
        b.vx -= dx * force;
        b.vy -= dy * force;
      }

      // Collision avoidance to prevent overlap.
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const minDist = nodeRadius(a) + nodeRadius(b) + 22;
          if (dist >= minDist) continue;
          const overlap = (minDist - dist) / dist;
          const push = overlap * 0.34 * alpha;
          const fx = dx * push;
          const fy = dy * push;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }
      }

      // Cluster cohesion
      const centroids = getScopeCentroids();
      for (const n of nodes) {
        const c = centroids.get(n.scopeId);
        if (!c) continue;
        const dx = c.cx - n.x;
        const dy = c.cy - n.y;
        n.vx += dx * 0.008 * alpha;
        n.vy += dy * 0.008 * alpha;
      }

      // Gravity toward center
      for (const n of nodes) {
        n.vx -= n.x * 0.0016 * alpha;
        n.vy -= n.y * 0.0016 * alpha;
      }

      // Integrate
      for (const n of nodes) {
        if (dragRef.current?.node === n) continue;
        n.vx *= 0.8;
        n.vy *= 0.8;
        n.x += n.vx;
        n.y += n.vy;
      }

      tick++;
    }

    function nodeRadius(n: SimNode): number {
      return Math.max(MODULE_NODE_MIN_RADIUS, Math.min(MODULE_NODE_MAX_RADIUS, 16 + n.fileCount * 3.8));
    }

    function draw() {
      if (!ctx || !canvas) return;
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);

      ctx.save();
      ctx.translate(w / 2, h / 2);
      ctx.scale(zoomRef.current, zoomRef.current);
      ctx.translate(panRef.current.x, panRef.current.y);

      const nodes = nodesRef.current;
      const nodeMap = new Map(nodes.map((n) => [n.id, n]));
      const colorMap = scopeColorMapRef.current;

      // Draw scope cluster hulls
      const scopeNodes = new Map<string, SimNode[]>();
      for (const n of nodes) {
        if (!scopeNodes.has(n.scopeId)) scopeNodes.set(n.scopeId, []);
        scopeNodes.get(n.scopeId)!.push(n);
      }

      for (const [scopeId, sns] of scopeNodes) {
        if (sns.length < 1) continue;
        const color = colorMap.get(scopeId) ?? '#6b7280';

        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (const n of sns) {
          const r = nodeRadius(n);
          if (n.x - r < minX) minX = n.x - r;
          if (n.y - r < minY) minY = n.y - r;
          if (n.x + r > maxX) maxX = n.x + r;
          if (n.y + r > maxY) maxY = n.y + r;
        }
        const pad = 35;
        const rx = 12;

        ctx.fillStyle = color;
        ctx.globalAlpha = 0.08;
        ctx.beginPath();
        ctx.roundRect(minX - pad, minY - pad, maxX - minX + pad * 2, maxY - minY + pad * 2, rx);
        ctx.fill();
        ctx.globalAlpha = 0.3;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.globalAlpha = 1;

        // Scope label
        const sg = scopeGroups.find(s => s.scope_id === scopeId);
        if (sg) {
          ctx.font = 'bold 11px ui-monospace, monospace';
          ctx.fillStyle = color;
          ctx.globalAlpha = 0.7;
          ctx.textAlign = 'left';
          ctx.textBaseline = 'top';
          ctx.fillText(sg.title, minX - pad + 8, minY - pad + 6);
          ctx.globalAlpha = 1;
        }
      }

      // Draw module-to-module edges
      for (const e of moduleEdges) {
        const a = nodeMap.get(e.from);
        const b = nodeMap.get(e.to);
        if (!a || !b) continue;

        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const ux = dx / dist;
        const uy = dy / dist;

        const rA = nodeRadius(a);
        const rB = nodeRadius(b);
        const startX = a.x + ux * rA;
        const startY = a.y + uy * rA;
        const endX = b.x - ux * (rB + 6);
        const endY = b.y - uy * (rB + 6);

        const crossScope = a.scopeId !== b.scopeId;
        const lineWidth = Math.min(6, 1.6 + e.weight * 0.7);

        ctx.beginPath();
        ctx.moveTo(startX, startY);
        ctx.lineTo(endX, endY);
        ctx.strokeStyle = crossScope ? '#1e293b' : '#64748b';
        ctx.lineWidth = lineWidth;
        ctx.globalAlpha = crossScope ? 0.9 : 0.75;
        ctx.stroke();
        ctx.globalAlpha = 1;

        // Arrowhead
        const arrowLen = Math.min(14, 8 + e.weight * 1.4);
        const arrowAngle = Math.PI / 6;
        const angle = Math.atan2(endY - startY, endX - startX);
        ctx.beginPath();
        ctx.moveTo(endX, endY);
        ctx.lineTo(
          endX - arrowLen * Math.cos(angle - arrowAngle),
          endY - arrowLen * Math.sin(angle - arrowAngle),
        );
        ctx.lineTo(
          endX - arrowLen * Math.cos(angle + arrowAngle),
          endY - arrowLen * Math.sin(angle + arrowAngle),
        );
        ctx.closePath();
        ctx.fillStyle = crossScope ? '#1e293b' : '#64748b';
        ctx.globalAlpha = crossScope ? 0.95 : 0.85;
        ctx.fill();
        ctx.globalAlpha = 1;

        // Weight label on cross-scope edges with weight > 1
        if (crossScope && e.weight > 1) {
          const mx = (startX + endX) / 2;
          const my = (startY + endY) / 2;
          ctx.font = '9px ui-monospace, monospace';
          ctx.fillStyle = '#0f172a';
          ctx.globalAlpha = 0.85;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(String(e.weight), mx, my - 6);
          ctx.globalAlpha = 1;
        }
      }

      // Draw module nodes
      for (const n of nodes) {
        const isHovered = hoverRef.current === n;
        const r = nodeRadius(n);
        const drawR = isHovered ? r + 3 : r;
        const color = colorMap.get(n.scopeId) ?? '#6b7280';

        ctx.beginPath();
        ctx.arc(n.x, n.y, drawR, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.globalAlpha = isHovered ? 1 : 0.85;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = isHovered ? '#000' : color;
        ctx.lineWidth = isHovered ? 2 : 1;
        ctx.stroke();

        // Keep dense metrics inside; render title outside for readability.
        const stats = `${n.fileCount} files`;
        const stats2 = `${n.symbolCount} entities`;
        ctx.textAlign = 'center';
        ctx.fillStyle = '#fff';
        if (drawR >= 16) {
          ctx.textBaseline = 'middle';
          // Keep text size stable across zoom/depth changes; only node radius should vary.
          ctx.font = '11px ui-monospace, monospace';
          ctx.fillText(stats, n.x, n.y - 4);
          ctx.font = '10px ui-monospace, monospace';
          ctx.globalAlpha = 0.95;
          ctx.fillText(stats2, n.x, n.y + 8);
          ctx.globalAlpha = 1;
        } else {
          ctx.textBaseline = 'middle';
          ctx.font = 'bold 8px ui-monospace, monospace';
          ctx.fillText(String(n.fileCount), n.x, n.y);
        }

        // Label outside node with chip to avoid overlap with edges.
        const labelBelow = n.label.length > 22 ? `${n.label.slice(0, 21)}…` : n.label;
        const labelY = n.y + drawR + 18;
        const textW = ctx.measureText(labelBelow).width;
        const chipW = textW + 14;
        const chipH = 18;
        ctx.fillStyle = '#f3f4f6';
        ctx.globalAlpha = 0.94;
        ctx.beginPath();
        ctx.roundRect(n.x - chipW / 2, labelY - 14, chipW, chipH, 5);
        ctx.fill();
        ctx.globalAlpha = 1;

        ctx.font = `${isHovered ? 'bold ' : ''}12px ui-monospace, monospace`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#111827';
        ctx.fillText(labelBelow, n.x, labelY - 5);
      }

      // Tooltip for hovered node
      const hovered = hoverRef.current;
      if (hovered) {
        const lines = [
          hovered.id,
          `scope: ${hovered.scopeTitle}`,
          `${hovered.fileCount} files, ${hovered.symbolCount} entities`,
          `${hovered.importCount} imports`,
          hovered.languages.join(', ') || 'unknown',
          hovered.description || '',
        ].filter(Boolean);
        const lineH = 16;
        const pad = 8;
        ctx.font = '11px ui-monospace, monospace';
        const maxW = Math.max(...lines.map((l) => ctx.measureText(l).width));
        const tooltipW = maxW + pad * 2;
        const tooltipH = lines.length * lineH + pad * 2;
        const tx = hovered.x + nodeRadius(hovered) + 12;
        const ty = hovered.y - tooltipH / 2;

        ctx.fillStyle = '#1f2937';
        ctx.globalAlpha = 0.92;
        ctx.beginPath();
        ctx.roundRect(tx, ty, tooltipW, tooltipH, 4);
        ctx.fill();
        ctx.globalAlpha = 1;

        ctx.fillStyle = '#f9fafb';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        lines.forEach((line, i) => {
          ctx.font = i === 0 ? 'bold 11px ui-monospace, monospace' : '11px ui-monospace, monospace';
          ctx.fillText(line, tx + pad, ty + pad + i * lineH);
        });
      }

      ctx.restore();
    }

    function loop() {
      if (!running) return;
      simulate();
      draw();
      animRef.current = requestAnimationFrame(loop);
    }
    loop();

    return () => {
      running = false;
      cancelAnimationFrame(animRef.current);
      obs.disconnect();
    };
  }, [moduleNodes, moduleEdges, scopeGroups]);

  // Mouse interactions
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    function findNodeAt(sx: number, sy: number): SimNode | null {
      const { x: wx, y: wy } = toWorld(sx, sy);
      for (const n of nodesRef.current) {
        const dx = n.x - wx;
        const dy = n.y - wy;
        const r = Math.max(MODULE_NODE_MIN_RADIUS, Math.min(MODULE_NODE_MAX_RADIUS, 16 + n.fileCount * 3.8));
        if (dx * dx + dy * dy < (r + 4) * (r + 4)) return n;
      }
      return null;
    }

    function onMouseDown(e: MouseEvent) {
      const rect = canvas!.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const node = findNodeAt(sx, sy);
      downRef.current = { x: sx, y: sy, nodeId: node?.id ?? null };
      if (node) {
        const { x: wx, y: wy } = toWorld(sx, sy);
        dragRef.current = { node, offsetX: node.x - wx, offsetY: node.y - wy };
      } else {
        isPanningRef.current = true;
        panStartRef.current = { x: e.clientX, y: e.clientY, panX: panRef.current.x, panY: panRef.current.y };
      }
    }

    function onMouseMove(e: MouseEvent) {
      const rect = canvas!.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;

      if (dragRef.current) {
        const { x: wx, y: wy } = toWorld(sx, sy);
        dragRef.current.node.x = wx + dragRef.current.offsetX;
        dragRef.current.node.y = wy + dragRef.current.offsetY;
        dragRef.current.node.vx = 0;
        dragRef.current.node.vy = 0;
      } else if (isPanningRef.current) {
        const dx = (e.clientX - panStartRef.current.x) / zoomRef.current;
        const dy = (e.clientY - panStartRef.current.y) / zoomRef.current;
        panRef.current.x = panStartRef.current.panX + dx;
        panRef.current.y = panStartRef.current.panY + dy;
      } else {
        hoverRef.current = findNodeAt(sx, sy);
        canvas!.style.cursor = hoverRef.current ? 'grab' : 'default';
      }
    }

    function onMouseUp(e: MouseEvent) {
      const rect = canvas!.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const moved = Math.hypot(sx - downRef.current.x, sy - downRef.current.y);
      if (moved < 6 && downRef.current.nodeId) {
        const node = nodesRef.current.find((n) => n.id === downRef.current.nodeId);
        if (node && onModuleClick) {
          onModuleClick({
            id: node.id,
            label: node.label,
            scopeId: node.scopeId,
            scopeTitle: node.scopeTitle,
          });
        }
      }
      dragRef.current = null;
      isPanningRef.current = false;
      downRef.current = { x: 0, y: 0, nodeId: null };
    }

    function onWheel(e: WheelEvent) {
      e.preventDefault();
      const factor = e.deltaY > 0 ? 0.92 : 1.08;
      zoomRef.current = Math.max(0.2, Math.min(5, zoomRef.current * factor));
    }

    canvas.addEventListener('mousedown', onMouseDown);
    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseup', onMouseUp);
    canvas.addEventListener('mouseleave', onMouseUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });

    return () => {
      canvas.removeEventListener('mousedown', onMouseDown);
      canvas.removeEventListener('mousemove', onMouseMove);
      canvas.removeEventListener('mouseup', onMouseUp);
      canvas.removeEventListener('mouseleave', onMouseUp);
      canvas.removeEventListener('wheel', onWheel);
    };
  }, [toWorld, onModuleClick]);

  // Legend
  const legendItems: Array<{ label: string; color: string }> = [];
  for (const sg of scopeGroups) {
    legendItems.push({
      label: sg.title,
      color: scopeColorMapRef.current.get(sg.scope_id) ?? SCOPE_COLORS[sg.group] ?? SCOPE_COLORS.core,
    });
  }

  return (
    <div>
      <div className="flex flex-wrap gap-3 mb-2 text-xs">
        {legendItems.map((item) => (
          <span key={item.label} className="flex items-center gap-1">
            <span
              className="inline-block w-3 h-3 rounded-full"
              style={{ backgroundColor: item.color }}
            />
            {item.label}
          </span>
        ))}
        <span className="text-gray-400 ml-auto">drag nodes / scroll to zoom / drag bg to pan</span>
      </div>
      <div className="text-xs text-gray-500 mb-1">
        {moduleNodes.length} modules, {moduleEdges.length} edges, {scopeGroups.length} scopes
        {' \u00b7 '}node size = file count{' \u00b7 '}edge thickness = import weight
      </div>
      <div className="border border-gray-300 bg-white" style={{ height: 500 }}>
        <canvas ref={canvasRef} className="w-full h-full" />
      </div>
    </div>
  );
}
