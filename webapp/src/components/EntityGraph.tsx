import { useEffect, useRef, useCallback } from 'react';

interface EntityNode {
  id: string;
  name: string;
  kind: string;
  signature: string;
  file: string;
  line_start: number;
  scope_id: string;
  scope_title: string;
  module_id: string;
  language: string;
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
  entityNodes: EntityNode[];
  entityEdges: Array<{ from: string; to: string; weight: number }>;
  scopeGroups: ScopeGroup[];
}

interface SimNode {
  id: string;
  name: string;
  kind: string;
  signature: string;
  file: string;
  lineStart: number;
  scopeId: string;
  scopeTitle: string;
  moduleId: string;
  language: string;
  group: string;
  description?: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

const SCOPE_COLORS: Record<string, string> = {
  frontend: '#3b82f6',
  backend: '#10b981',
  testing: '#f59e0b',
  scripts: '#8b5cf6',
  core: '#6b7280',
};

export default function EntityGraph({ entityNodes, entityEdges, scopeGroups }: Props) {
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
  const degreeRef = useRef<Map<string, number>>(new Map());

  const toWorld = useCallback((sx: number, sy: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    return {
      x: (sx - canvas.width / 2) / zoomRef.current - panRef.current.x,
      y: (sy - canvas.height / 2) / zoomRef.current - panRef.current.y,
    };
  }, []);

  useEffect(() => {
    const colorMap = new Map<string, string>();
    for (const sg of scopeGroups) {
      colorMap.set(sg.scope_id, SCOPE_COLORS[sg.group] ?? SCOPE_COLORS.core);
    }
    scopeColorMapRef.current = colorMap;

    const byScope = new Map<string, EntityNode[]>();
    for (const en of entityNodes) {
      if (!byScope.has(en.scope_id)) byScope.set(en.scope_id, []);
      byScope.get(en.scope_id)!.push(en);
    }

    const scopeIds = [...byScope.keys()];
    const scopeAngle = (2 * Math.PI) / Math.max(scopeIds.length, 1);
    const clusterRadius = Math.min(620, Math.max(320, scopeIds.length * 110));
    const nodes: SimNode[] = [];

    scopeIds.forEach((sid, si) => {
      const ents = byScope.get(sid)!;
      const cx = Math.cos(scopeAngle * si) * clusterRadius;
      const cy = Math.sin(scopeAngle * si) * clusterRadius;
      const entAngle = (2 * Math.PI) / Math.max(ents.length, 1);
      const entRadius = Math.min(300, Math.max(110, ents.length * 14));

      ents.forEach((e, ei) => {
        nodes.push({
          id: e.id,
          name: e.name,
          kind: e.kind,
          signature: e.signature,
          file: e.file,
          lineStart: e.line_start,
          scopeId: e.scope_id,
          scopeTitle: e.scope_title,
          moduleId: e.module_id,
          language: e.language,
          group: e.group,
          description: e.description,
          x: cx + Math.cos(entAngle * ei) * entRadius,
          y: cy + Math.sin(entAngle * ei) * entRadius,
          vx: 0,
          vy: 0,
        });
      });
    });

    nodesRef.current = nodes;
    const deg = new Map<string, number>();
    for (const e of entityEdges) {
      deg.set(e.from, (deg.get(e.from) ?? 0) + 1);
      deg.set(e.to, (deg.get(e.to) ?? 0) + 1);
    }
    degreeRef.current = deg;
    panRef.current = { x: 0, y: 0 };
    zoomRef.current = 1;
  }, [entityNodes, entityEdges, scopeGroups]);

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

    function nodeRadius(n: SimNode): number {
      const base = n.kind === 'class' ? 56 : 52;
      const degreeBoost = Math.min(22, (degreeRef.current.get(n.id) ?? 0) * 2.4);
      return Math.max(46, Math.min(86, base + (n.name.length > 14 ? 6 : 0) + degreeBoost));
    }

    function simulate() {
      const nodes = nodesRef.current;
      if (nodes.length === 0) return;
      const alpha = Math.max(0.005, 0.3 * Math.pow(0.995, tick));

      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[j].x - nodes[i].x;
          const dy = nodes[j].y - nodes[i].y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const sameScope = nodes[i].scopeId === nodes[j].scopeId;
          const repulsion = sameScope ? 7200 : 12400;
          const force = (repulsion / (dist * dist)) * alpha;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          nodes[i].vx -= fx;
          nodes[i].vy -= fy;
          nodes[j].vx += fx;
          nodes[j].vy += fy;
        }
      }

      const nodeMap = new Map(nodes.map((n) => [n.id, n]));
      for (const e of entityEdges) {
        const a = nodeMap.get(e.from);
        const b = nodeMap.get(e.to);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const target = a.scopeId === b.scopeId ? 150 : 260;
        const force = ((dist - target) / dist) * Math.min(0.08, 0.03 + e.weight * 0.01) * alpha;
        a.vx += dx * force;
        a.vy += dy * force;
        b.vx -= dx * force;
        b.vy -= dy * force;
      }

      // Collision avoidance.
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const minDist = nodeRadius(a) + nodeRadius(b) + 34;
          if (dist >= minDist) continue;
          const overlap = (minDist - dist) / dist;
          const push = overlap * 0.52 * alpha;
          a.vx -= dx * push;
          a.vy -= dy * push;
          b.vx += dx * push;
          b.vy += dy * push;
        }
      }

      for (const n of nodes) {
        n.vx -= n.x * 0.0016 * alpha;
        n.vy -= n.y * 0.0016 * alpha;
      }

      for (const n of nodes) {
        if (dragRef.current?.node === n) continue;
        n.vx *= 0.78;
        n.vy *= 0.78;
        n.x += n.vx;
        n.y += n.vy;
      }
      tick++;
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

      for (const e of entityEdges) {
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
        const endX = b.x - ux * (rB + 8);
        const endY = b.y - uy * (rB + 8);

        ctx.beginPath();
        ctx.moveTo(startX, startY);
        ctx.lineTo(endX, endY);
        ctx.strokeStyle = a.scopeId === b.scopeId ? '#64748b' : '#1e293b';
        ctx.lineWidth = Math.min(4, 1.4 + e.weight * 0.6);
        ctx.globalAlpha = 0.78;
        ctx.stroke();
        ctx.globalAlpha = 1;

        const arrowLen = Math.min(16, 9 + e.weight);
        const arrowAngle = Math.PI / 6;
        const angle = Math.atan2(endY - startY, endX - startX);
        ctx.beginPath();
        ctx.moveTo(endX, endY);
        ctx.lineTo(endX - arrowLen * Math.cos(angle - arrowAngle), endY - arrowLen * Math.sin(angle - arrowAngle));
        ctx.lineTo(endX - arrowLen * Math.cos(angle + arrowAngle), endY - arrowLen * Math.sin(angle + arrowAngle));
        ctx.closePath();
        ctx.fillStyle = '#1e293b';
        ctx.globalAlpha = 0.9;
        ctx.fill();
        ctx.globalAlpha = 1;
      }

      for (const n of nodes) {
        const isHovered = hoverRef.current === n;
        const r = isHovered ? nodeRadius(n) + 3 : nodeRadius(n);
        const color = scopeColorMapRef.current.get(n.scopeId) ?? '#6b7280';
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.9;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = isHovered ? '#000' : color;
        ctx.lineWidth = isHovered ? 2 : 1;
        ctx.stroke();

        const label = n.name.length > 24 ? `${n.name.slice(0, 23)}…` : n.name;
        // Keep text size stable across depth changes; only node radius scales with graph granularity.
        ctx.font = '13px ui-monospace, monospace';
        ctx.fillStyle = '#eef2ff';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(n.kind, n.x, n.y - 2);
        ctx.font = '12px ui-monospace, monospace';
        ctx.globalAlpha = 0.95;
        ctx.fillText(`${degreeRef.current.get(n.id) ?? 0} connections`, n.x, n.y + 14);
        ctx.globalAlpha = 1;

        // External black label chip for readability.
        const labelY = n.y + r + 20;
        const tw = ctx.measureText(label).width;
        const chipW = tw + 16;
        const chipH = 20;
        ctx.fillStyle = '#f3f4f6';
        ctx.globalAlpha = 0.94;
        ctx.beginPath();
        ctx.roundRect(n.x - chipW / 2, labelY - 16, chipW, chipH, 5);
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.font = `${isHovered ? 'bold ' : ''}13px ui-monospace, monospace`;
        ctx.fillStyle = '#111827';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(label, n.x, labelY - 7);
      }

      const hovered = hoverRef.current;
      if (hovered) {
        const lines = [
          hovered.name,
          hovered.signature || hovered.kind,
          `${hovered.file}:${hovered.lineStart}`,
          hovered.description || 'Entity node in the dependency graph.',
        ];
        const lineH = 16;
        const pad = 8;
        ctx.font = '11px ui-monospace, monospace';
        const maxW = Math.max(...lines.map((l) => ctx.measureText(l).width));
        const tooltipW = maxW + pad * 2;
        const tooltipH = lines.length * lineH + pad * 2;
        const tx = hovered.x + nodeRadius(hovered) + 12;
        const ty = hovered.y - tooltipH / 2;
        ctx.fillStyle = '#111827';
        ctx.globalAlpha = 0.95;
        ctx.beginPath();
        ctx.roundRect(tx, ty, tooltipW, tooltipH, 5);
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
  }, [entityNodes, entityEdges, scopeGroups]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const canvasEl = canvas;

    function nodeRadius(n: SimNode): number {
      const base = n.kind === 'class' ? 56 : 52;
      const degreeBoost = Math.min(22, (degreeRef.current.get(n.id) ?? 0) * 2.4);
      return Math.max(46, Math.min(86, base + (n.name.length > 14 ? 6 : 0) + degreeBoost));
    }

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

    function onMouseUp() {
      dragRef.current = null;
      isPanningRef.current = false;
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
  }, [toWorld]);

  return (
    <div>
      <div className="text-xs text-gray-500 mb-1">
        {entityNodes.length} entities, {entityEdges.length} edges, {scopeGroups.length} scopes
      </div>
      <div className="border border-gray-300 bg-white" style={{ height: 500 }}>
        <canvas ref={canvasRef} className="w-full h-full" />
      </div>
    </div>
  );
}
