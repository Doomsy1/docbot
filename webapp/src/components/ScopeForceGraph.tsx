import { useCallback, useEffect, useRef } from 'react';

interface ScopeNode {
  scope_id: string;
  title: string;
  file_count: number;
  symbol_count: number;
  languages: string[];
  group: string;
  description?: string;
  summary?: string;
}

interface Props {
  scopes: ScopeNode[];
  scopeEdges: Array<{ from: string; to: string }>;
  onScopeClick?: (node: { scopeId: string; title: string }) => void;
}

interface SimNode {
  scopeId: string;
  title: string;
  fileCount: number;
  symbolCount: number;
  group: string;
  description?: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

const GROUP_COLORS: Record<string, string> = {
  frontend: '#3b82f6',
  backend: '#10b981',
  testing: '#f59e0b',
  scripts: '#8b5cf6',
  core: '#6b7280',
};

export default function ScopeForceGraph({ scopes, scopeEdges, onScopeClick }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<SimNode[]>([]);
  const animRef = useRef<number>(0);
  const dragRef = useRef<{ node: SimNode; offsetX: number; offsetY: number } | null>(null);
  const hoverRef = useRef<SimNode | null>(null);
  const panRef = useRef({ x: 0, y: 0 });
  const zoomRef = useRef(1);
  const isPanningRef = useRef(false);
  const panStartRef = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const downRef = useRef<{ x: number; y: number; scopeId: string | null }>({ x: 0, y: 0, scopeId: null });

  const toWorld = useCallback((sx: number, sy: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    return {
      x: (sx - canvas.width / 2) / zoomRef.current - panRef.current.x,
      y: (sy - canvas.height / 2) / zoomRef.current - panRef.current.y,
    };
  }, []);

  function nodeRadius(n: SimNode): number {
    const score = n.fileCount + n.symbolCount * 0.6;
    return Math.max(40, Math.min(84, 30 + Math.sqrt(Math.max(1, score)) * 5.2));
  }

  useEffect(() => {
    const angle = (2 * Math.PI) / Math.max(scopes.length, 1);
    const orbit = Math.max(220, Math.min(360, scopes.length * 32));
    const nodes: SimNode[] = scopes.map((s, i) => ({
      scopeId: s.scope_id,
      title: s.title,
      fileCount: s.file_count,
      symbolCount: s.symbol_count,
      group: s.group,
      description: s.description ?? s.summary,
      x: Math.cos(angle * i) * orbit,
      y: Math.sin(angle * i) * orbit,
      vx: 0,
      vy: 0,
    }));
    nodesRef.current = nodes;
    panRef.current = { x: 0, y: 0 };
    zoomRef.current = 1;
  }, [scopes]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const canvasEl: HTMLCanvasElement = canvas;
    const context: CanvasRenderingContext2D = ctx;

    let running = true;
    let tick = 0;

    function resize() {
      const rect = canvasEl.parentElement?.getBoundingClientRect();
      if (!rect) return;
      canvasEl.width = rect.width;
      canvasEl.height = rect.height;
    }
    resize();
    const obs = new ResizeObserver(resize);
    obs.observe(canvasEl.parentElement!);

    function simulate() {
      const nodes = nodesRef.current;
      if (!nodes.length) return;
      const alpha = Math.max(0.006, 0.3 * Math.pow(0.995, tick));
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = (5600 / (dist * dist)) * alpha;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }
      }

      const nodeMap = new Map(nodes.map((n) => [n.scopeId, n]));
      for (const e of scopeEdges) {
        const a = nodeMap.get(e.from);
        const b = nodeMap.get(e.to);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const target = 220;
        const force = ((dist - target) / dist) * 0.06 * alpha;
        a.vx += dx * force;
        a.vy += dy * force;
        b.vx -= dx * force;
        b.vy -= dy * force;
      }

      for (const n of nodes) {
        n.vx -= n.x * 0.0018 * alpha;
        n.vy -= n.y * 0.0018 * alpha;
      }

      for (const n of nodes) {
        if (dragRef.current?.node === n) continue;
        n.vx *= 0.82;
        n.vy *= 0.82;
        n.x += n.vx;
        n.y += n.vy;
      }
      tick++;
    }

    function draw() {
      const w = canvasEl.width;
      const h = canvasEl.height;
      context.clearRect(0, 0, w, h);

      context.save();
      context.translate(w / 2, h / 2);
      context.scale(zoomRef.current, zoomRef.current);
      context.translate(panRef.current.x, panRef.current.y);

      const nodes = nodesRef.current;
      const nodeMap = new Map(nodes.map((n) => [n.scopeId, n]));
      for (const e of scopeEdges) {
        const a = nodeMap.get(e.from);
        const b = nodeMap.get(e.to);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const ux = dx / dist;
        const uy = dy / dist;
        const startX = a.x + ux * nodeRadius(a);
        const startY = a.y + uy * nodeRadius(a);
        const endX = b.x - ux * (nodeRadius(b) + 10);
        const endY = b.y - uy * (nodeRadius(b) + 10);
        context.beginPath();
        context.moveTo(startX, startY);
        context.lineTo(endX, endY);
        context.strokeStyle = '#334155';
        context.lineWidth = 2.6;
        context.globalAlpha = 0.86;
        context.stroke();
        context.globalAlpha = 1;
      }

      for (const n of nodes) {
        const hovered = hoverRef.current === n;
        const r = hovered ? nodeRadius(n) + 3 : nodeRadius(n);
        const color = GROUP_COLORS[n.group] ?? GROUP_COLORS.core;
        context.beginPath();
        context.arc(n.x, n.y, r, 0, Math.PI * 2);
        context.fillStyle = color;
        context.globalAlpha = 0.9;
        context.fill();
        context.globalAlpha = 1;
        context.strokeStyle = hovered ? '#000' : '#0f172a';
        context.lineWidth = hovered ? 2 : 1.4;
        context.stroke();

        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.fillStyle = '#e5e7eb';
        context.font = '11px ui-monospace, monospace';
        context.fillText(`${n.fileCount} files`, n.x, n.y - 4);
        context.fillText(`${n.symbolCount} entities`, n.x, n.y + 12);

        const label = n.title.length > 26 ? `${n.title.slice(0, 25)}…` : n.title;
        const ly = n.y + r + 18;
        const tw = context.measureText(label).width;
        const chipW = tw + 14;
        context.fillStyle = '#f3f4f6';
        context.globalAlpha = 0.94;
        context.beginPath();
        context.roundRect(n.x - chipW / 2, ly - 14, chipW, 18, 5);
        context.fill();
        context.globalAlpha = 1;
        context.fillStyle = '#111827';
        context.font = `${hovered ? 'bold ' : ''}12px ui-monospace, monospace`;
        context.fillText(label, n.x, ly - 5);
      }

      if (hoverRef.current) {
        const n = hoverRef.current;
        const lines = [
          n.title,
          `${n.fileCount} files, ${n.symbolCount} entities`,
          n.description || 'Scope node in the architecture graph.',
        ];
        const pad = 8;
        const lineH = 16;
        context.font = '11px ui-monospace, monospace';
        const maxW = Math.max(...lines.map((l) => context.measureText(l).width));
        const tw = maxW + pad * 2;
        const th = lines.length * lineH + pad * 2;
        const tx = n.x + nodeRadius(n) + 12;
        const ty = n.y - th / 2;
        context.fillStyle = '#111827';
        context.globalAlpha = 0.95;
        context.beginPath();
        context.roundRect(tx, ty, tw, th, 5);
        context.fill();
        context.globalAlpha = 1;
        context.fillStyle = '#f9fafb';
        context.textAlign = 'left';
        context.textBaseline = 'top';
        lines.forEach((line, i) => {
          context.font = i === 0 ? 'bold 11px ui-monospace, monospace' : '11px ui-monospace, monospace';
          context.fillText(line, tx + pad, ty + pad + i * lineH);
        });
      }

      context.restore();
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
  }, [scopeEdges, scopes]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const canvasEl: HTMLCanvasElement = canvas;

    function findNodeAt(sx: number, sy: number): SimNode | null {
      const { x: wx, y: wy } = toWorld(sx, sy);
      for (const n of nodesRef.current) {
        const dx = n.x - wx;
        const dy = n.y - wy;
        const r = nodeRadius(n);
        if (dx * dx + dy * dy < (r + 4) * (r + 4)) return n;
      }
      return null;
    }

    function onMouseDown(e: MouseEvent) {
      const rect = canvasEl.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const node = findNodeAt(sx, sy);
      downRef.current = { x: sx, y: sy, scopeId: node?.scopeId ?? null };
      if (node) {
        const { x: wx, y: wy } = toWorld(sx, sy);
        dragRef.current = { node, offsetX: node.x - wx, offsetY: node.y - wy };
      } else {
        isPanningRef.current = true;
        panStartRef.current = { x: e.clientX, y: e.clientY, panX: panRef.current.x, panY: panRef.current.y };
      }
    }

    function onMouseMove(e: MouseEvent) {
      const rect = canvasEl.getBoundingClientRect();
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
        canvasEl.style.cursor = hoverRef.current ? 'grab' : 'default';
      }
    }

    function onMouseUp(e: MouseEvent) {
      const rect = canvasEl.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const moved = Math.hypot(sx - downRef.current.x, sy - downRef.current.y);
      if (moved < 6 && downRef.current.scopeId && onScopeClick) {
        const n = nodesRef.current.find((node) => node.scopeId === downRef.current.scopeId);
        if (n) onScopeClick({ scopeId: n.scopeId, title: n.title });
      }
      dragRef.current = null;
      isPanningRef.current = false;
      downRef.current = { x: 0, y: 0, scopeId: null };
    }

    function onWheel(e: WheelEvent) {
      e.preventDefault();
      const factor = e.deltaY > 0 ? 0.92 : 1.08;
      zoomRef.current = Math.max(0.2, Math.min(5, zoomRef.current * factor));
    }

    canvasEl.addEventListener('mousedown', onMouseDown);
    canvasEl.addEventListener('mousemove', onMouseMove);
    canvasEl.addEventListener('mouseup', onMouseUp);
    canvasEl.addEventListener('mouseleave', onMouseUp);
    canvasEl.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      canvasEl.removeEventListener('mousedown', onMouseDown);
      canvasEl.removeEventListener('mousemove', onMouseMove);
      canvasEl.removeEventListener('mouseup', onMouseUp);
      canvasEl.removeEventListener('mouseleave', onMouseUp);
      canvasEl.removeEventListener('wheel', onWheel);
    };
  }, [toWorld, onScopeClick]);

  return (
    <div>
      <div className="text-xs text-gray-500 mb-1">
        {scopes.length} scopes, {scopeEdges.length} dependencies
      </div>
      <div className="border border-gray-300 bg-white" style={{ height: 520 }}>
        <canvas ref={canvasRef} className="w-full h-full" />
      </div>
    </div>
  );
}
