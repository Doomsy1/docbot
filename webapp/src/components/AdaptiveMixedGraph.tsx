import { memo, useCallback, useEffect, useRef } from 'react';

export interface MixedNode {
  id: string;
  kind: 'scope' | 'module' | 'file' | 'entity';
  label: string;
  group: string;
  description?: string;
  preview?: string | null;
  scope_id?: string;
  module_id?: string;
  file_path?: string;
  entity_kind?: string;
  line_start?: number;
  file_count?: number;
  entity_count?: number;
  import_count?: number;
}

export interface MixedEdge {
  id: string;
  from: string;
  to: string;
  kind: string;
  weight: number;
  directed: boolean;
}

interface SimNode extends MixedNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

interface Props {
  nodes: MixedNode[];
  edges: MixedEdge[];
  highlightedNodeId?: string | null;
  selectedNodeId?: string | null;
  isolatedNodeId?: string | null;
  onNodeClick?: (node: MixedNode) => void;
  onNodeIsolateToggle?: (node: MixedNode) => void;
  onHoverNode?: (node: MixedNode | null) => void;
  onGraphInteract?: () => void;
  fitTargetId?: string | null;
}

const GROUP_COLORS: Record<string, string> = {
  frontend: '#3b82f6',
  backend: '#10b981',
  testing: '#f59e0b',
  scripts: '#8b5cf6',
  core: '#6b7280',
};

function baseRadius(kind: MixedNode['kind']): number {
  if (kind === 'scope') return 84;
  if (kind === 'module') return 60;
  if (kind === 'file') return 40;
  return 26;
}

function nodeRadius(n: MixedNode): number {
  return baseRadius(n.kind);
}

function edgeStyle(kind: string): { stroke: string; width: number; dashed: boolean } {
  if (kind === 'runtime_http') return { stroke: '#dc2626', width: 2.4, dashed: false };
  if (kind === 'entity_intra_file') return { stroke: '#64748b', width: 1.5, dashed: true };
  if (kind === 'entity_cross_file') return { stroke: '#1f2937', width: 2.2, dashed: false };
  if (kind === 'file_dep') return { stroke: '#334155', width: 2.0, dashed: false };
  if (kind === 'module_dep') return { stroke: '#1e293b', width: 2.6, dashed: false };
  return { stroke: '#475569', width: 2.2, dashed: false };
}

function cleanTooltipText(text: string): string {
  return text
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/_([^_]+)_/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

function compressTooltipBody(title: string, raw: string, maxChars: number, maxLines: number): string {
  const clean = cleanTooltipText(raw);
  if (!clean) return '';

  let text = clean;
  const escapedTitle = title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const leadPatterns = [
    new RegExp(`^the\\s+["']?${escapedTitle}["']?\\s+(module|scope|file|component)\\s+is\\s+(designed|responsible|used)\\s+to\\s+`, 'i'),
    new RegExp(`^the\\s+["']?${escapedTitle}["']?\\s+(module|scope|file|component)\\s+`, 'i'),
    /^this\s+(module|scope|file|component)\s+is\s+(designed|responsible|used)\s+to\s+/i,
    /^this\s+(module|scope|file|component)\s+/i,
  ];
  for (const p of leadPatterns) {
    text = text.replace(p, '');
  }
  text = text.replace(/^(facilitates?|handles?|manages?)\s+/i, '').replace(/^[,:;\-\s]+/, '').trim();

  const charBudget = maxChars * maxLines;
  const sentences = text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (!sentences.length) return text.slice(0, charBudget).trim();

  let out = '';
  for (const s of sentences) {
    const next = out ? `${out} ${s}` : s;
    if (next.length > charBudget) break;
    out = next;
  }
  if (!out) out = sentences[0].slice(0, charBudget).trim();
  return out;
}

function AdaptiveMixedGraph({
  nodes,
  edges,
  highlightedNodeId,
  selectedNodeId,
  isolatedNodeId,
  onNodeClick,
  onNodeIsolateToggle,
  onHoverNode,
  onGraphInteract,
  fitTargetId,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<SimNode[]>([]);
  const panRef = useRef({ x: 0, y: 0 });
  const zoomRef = useRef(1);
  const dragRef = useRef<{ node: SimNode; offsetX: number; offsetY: number } | null>(null);
  const panningRef = useRef(false);
  const panStartRef = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const hoverNodeRef = useRef<SimNode | null>(null);
  const downRef = useRef<{ x: number; y: number; id: string | null }>({ x: 0, y: 0, id: null });
  const edgeListRef = useRef<MixedEdge[]>(edges);
  const connectedToIsolatedRef = useRef<Set<string>>(new Set());
  const highlightedNodeIdRef = useRef<string | null>(highlightedNodeId ?? null);
  const selectedNodeIdRef = useRef<string | null>(selectedNodeId ?? null);
  const isolatedNodeIdRef = useRef<string | null>(isolatedNodeId ?? null);
  const onNodeClickRef = useRef<Props['onNodeClick']>(onNodeClick);
  const onNodeIsolateToggleRef = useRef<Props['onNodeIsolateToggle']>(onNodeIsolateToggle);
  const onHoverNodeRef = useRef<Props['onHoverNode']>(onHoverNode);
  const onGraphInteractRef = useRef<Props['onGraphInteract']>(onGraphInteract);

  useEffect(() => {
    edgeListRef.current = edges;
    const isolated = isolatedNodeId ?? null;
    isolatedNodeIdRef.current = isolated;
    const out = new Set<string>();
    if (isolated) {
      for (const e of edges) {
        if (e.from === isolated) out.add(e.to);
        if (e.to === isolated) out.add(e.from);
      }
    }
    connectedToIsolatedRef.current = out;
  }, [edges, isolatedNodeId]);

  useEffect(() => {
    highlightedNodeIdRef.current = highlightedNodeId ?? null;
  }, [highlightedNodeId]);

  useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId ?? null;
  }, [selectedNodeId]);

  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
    onNodeIsolateToggleRef.current = onNodeIsolateToggle;
    onHoverNodeRef.current = onHoverNode;
    onGraphInteractRef.current = onGraphInteract;
  }, [onNodeClick, onNodeIsolateToggle, onHoverNode, onGraphInteract]);

  const toWorld = useCallback((sx: number, sy: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    return {
      x: (sx - canvas.width / 2) / zoomRef.current - panRef.current.x,
      y: (sy - canvas.height / 2) / zoomRef.current - panRef.current.y,
    };
  }, []);

  useEffect(() => {
    const grouped = new Map<string, MixedNode[]>();
    for (const n of nodes) {
      const key = n.scope_id ?? '__root__';
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key)!.push(n);
    }
    const keys = [...grouped.keys()];
    const angle = (2 * Math.PI) / Math.max(1, keys.length);
    const orbit = Math.max(180, Math.min(340, 120 + keys.length * 34));
    const next: SimNode[] = [];
    keys.forEach((k, i) => {
      const groupNodes = grouped.get(k)!;
      const cx = Math.cos(i * angle) * orbit;
      const cy = Math.sin(i * angle) * orbit;
      const gAngle = (2 * Math.PI) / Math.max(1, groupNodes.length);
      const gr = Math.max(62, Math.min(180, groupNodes.length * 14));
      groupNodes.forEach((n, j) => {
        next.push({
          ...n,
          x: cx + Math.cos(j * gAngle) * gr,
          y: cy + Math.sin(j * gAngle) * gr,
          vx: 0,
          vy: 0,
        });
      });
    });
    nodesRef.current = next;
  }, [nodes, fitTargetId, highlightedNodeId, selectedNodeId]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    let frame = 0;
    let running = true;

    const resize = () => {
      const rect = canvas.parentElement?.getBoundingClientRect();
      if (!rect) return;
      canvas.width = rect.width;
      canvas.height = rect.height;
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas.parentElement!);

    const tick = () => {
      if (!running) return;
      const n = nodesRef.current;
      const alpha = Math.max(0.008, 0.28 * Math.pow(0.996, frame));

      for (let i = 0; i < n.length; i++) {
        for (let j = i + 1; j < n.length; j++) {
          const a = n[i];
          const b = n[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const repulsion = 10200;
          const f = (repulsion / (dist * dist)) * alpha;
          const fx = (dx / dist) * f;
          const fy = (dy / dist) * f;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }
      }

      const map = new Map(n.map((x) => [x.id, x]));
      for (const e of edgeListRef.current) {
        const a = map.get(e.from);
        const b = map.get(e.to);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const target = a.kind === b.kind ? 250 : 290;
        const force = ((dist - target) / dist) * 0.038 * alpha * Math.min(2.2, 1 + (e.weight || 1) * 0.22);
        a.vx += dx * force;
        a.vy += dy * force;
        b.vx -= dx * force;
        b.vy -= dy * force;
      }

      for (let i = 0; i < n.length; i++) {
        for (let j = i + 1; j < n.length; j++) {
          const a = n[i];
          const b = n[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const minD = nodeRadius(a) + nodeRadius(b) + 44;
          if (dist >= minD) continue;
          const overlap = (minD - dist) / dist;
          const push = overlap * 0.5 * alpha;
          a.vx -= dx * push;
          a.vy -= dy * push;
          b.vx += dx * push;
          b.vy += dy * push;
        }
      }

      for (const x of n) {
        x.vx -= x.x * 0.0012 * alpha;
        x.vy -= x.y * 0.0012 * alpha;
      }
      for (const x of n) {
        if (dragRef.current?.node === x) continue;
        x.vx *= 0.84;
        x.vy *= 0.84;
        x.x += x.vx;
        x.y += x.vy;
      }
      frame += 1;
    };

    const draw = () => {
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      ctx.save();
      ctx.translate(w / 2, h / 2);
      ctx.scale(zoomRef.current, zoomRef.current);
      ctx.translate(panRef.current.x, panRef.current.y);

      const map = new Map(nodesRef.current.map((x) => [x.id, x]));
      const isolatedNodeId = isolatedNodeIdRef.current;
      const connectedToIsolated = connectedToIsolatedRef.current;
      const selectedNodeId = selectedNodeIdRef.current;
      const highlightedNodeId = highlightedNodeIdRef.current;
      for (const e of edgeListRef.current) {
        if (isolatedNodeId && e.from !== isolatedNodeId && e.to !== isolatedNodeId) {
          continue;
        }
        const a = map.get(e.from);
        const b = map.get(e.to);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const ux = dx / dist;
        const uy = dy / dist;
        const ar = nodeRadius(a);
        const br = nodeRadius(b);
        const sx = a.x + ux * ar;
        const sy = a.y + uy * ar;
        const ex = b.x - ux * (br + 12);
        const ey = b.y - uy * (br + 12);
        const style = edgeStyle(e.kind);

        ctx.beginPath();
        ctx.setLineDash(style.dashed ? [8, 6] : []);
        ctx.moveTo(sx, sy);
        ctx.lineTo(ex, ey);
        ctx.strokeStyle = style.stroke;
        ctx.lineWidth = Math.min(5, style.width + (e.weight || 1) * 0.16);
        ctx.globalAlpha = 0.88;
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;

        if (e.directed) {
          const aLen = 12;
          const aAng = Math.PI / 7;
          const ang = Math.atan2(ey - sy, ex - sx);
          ctx.beginPath();
          ctx.moveTo(ex, ey);
          ctx.lineTo(ex - aLen * Math.cos(ang - aAng), ey - aLen * Math.sin(ang - aAng));
          ctx.lineTo(ex - aLen * Math.cos(ang + aAng), ey - aLen * Math.sin(ang + aAng));
          ctx.closePath();
          ctx.fillStyle = style.stroke;
          ctx.globalAlpha = 0.94;
          ctx.fill();
          ctx.globalAlpha = 1;
        }
      }

      for (const n of nodesRef.current) {
        const r = nodeRadius(n);
        const color = GROUP_COLORS[n.group] ?? GROUP_COLORS.core;
        const hovered = hoverNodeRef.current?.id === n.id;
        const selected = selectedNodeId === n.id;
        const highlighted = highlightedNodeId === n.id;
        const isIsolated = isolatedNodeId && n.id === isolatedNodeId;
        const isConnected = !!isolatedNodeId && connectedToIsolated.has(n.id);
        let nodeAlpha = 0.9;
        if (isolatedNodeId) {
          if (isIsolated) {
            nodeAlpha = 1;
          } else if (isConnected) {
            nodeAlpha = hovered ? 1 : 0.55;
          } else {
            nodeAlpha = 0.14;
          }
        }

        if (isIsolated) {
          // Mild spotlight halo to make the isolated node immediately obvious.
          ctx.beginPath();
          ctx.arc(n.x, n.y, r + 10, 0, Math.PI * 2);
          ctx.fillStyle = '#f59e0b';
          ctx.globalAlpha = 0.2;
          ctx.fill();
          ctx.globalAlpha = 1;
        }

        ctx.beginPath();
        ctx.arc(n.x, n.y, hovered ? r + 2 : r, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.globalAlpha = nodeAlpha;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = selected ? '#000' : highlighted ? '#111827' : '#1f2937';
        ctx.lineWidth = selected ? 3 : highlighted ? 2.4 : 1.8;
        ctx.stroke();

        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#f8fafc';
        ctx.font = '13px ui-monospace, monospace';
        if (nodeAlpha >= 0.24) {
          if (n.kind === 'scope' || n.kind === 'module') {
            ctx.fillText(`${n.file_count ?? 0} files`, n.x, n.y - 6);
            ctx.fillText(`${n.entity_count ?? 0} entities`, n.x, n.y + 11);
          } else if (n.kind === 'file') {
            ctx.fillText(`${n.entity_count ?? 0} entities`, n.x, n.y - 3);
          } else {
            const raw = n.entity_kind ?? 'entity';
            const maxW = Math.max(20, r * 1.55);
            let size = 13;
            let text = raw;
            ctx.font = `${size}px ui-monospace, monospace`;
            while (ctx.measureText(text).width > maxW && size > 8) {
              size -= 1;
              ctx.font = `${size}px ui-monospace, monospace`;
            }
            if (ctx.measureText(text).width > maxW) {
              while (text.length > 1 && ctx.measureText(`${text}...`).width > maxW) {
                text = text.slice(0, -1);
              }
              text = `${text}...`;
            }
            ctx.fillText(text, n.x, n.y - 3);
          }
        }

        const label = n.label.length > 36 ? `${n.label.slice(0, 35)}...` : n.label;
        if (nodeAlpha >= 0.34) {
          ctx.font = 'bold 15px ui-monospace, monospace';
          const tw = ctx.measureText(label).width;
          const chipW = tw + 14;
          const chipH = 24;
          const ly = n.y + r + 24;
          ctx.fillStyle = '#f3f4f6';
          ctx.globalAlpha = 0.97;
          ctx.beginPath();
          ctx.roundRect(n.x - chipW / 2, ly - chipH + 2, chipW, chipH, 5);
          ctx.fill();
          ctx.globalAlpha = 1;
          ctx.strokeStyle = '#d1d5db';
          ctx.lineWidth = 1;
          ctx.stroke();
          ctx.fillStyle = '#111827';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(label, n.x, ly - 10);
        }
      }

      ctx.restore();

      const activeNode =
        hoverNodeRef.current ??
        (selectedNodeIdRef.current ? nodesRef.current.find((n) => n.id === selectedNodeIdRef.current) ?? null : null);
      const canShowActiveNode =
        !!activeNode && (!isolatedNodeId || activeNode.id === isolatedNodeId || connectedToIsolated.has(activeNode.id));
      if (activeNode && canShowActiveNode) {
        const wx = activeNode.x;
        const wy = activeNode.y;
        const sx = (wx + panRef.current.x) * zoomRef.current + w / 2;
        const sy = (wy + panRef.current.y) * zoomRef.current + h / 2;
        const sr = nodeRadius(activeNode) * zoomRef.current;

        const title = activeNode.kind === 'file' ? (activeNode.file_path ?? activeNode.label) : activeNode.label;
        const subtitle =
          activeNode.kind === 'entity'
            ? `${activeNode.entity_kind ?? 'entity'} ${activeNode.file_path ?? ''}${activeNode.line_start ? `:${activeNode.line_start}` : ''}`
            : `${activeNode.file_count ?? 0} files · ${activeNode.entity_count ?? 0} entities`;
        const body = compressTooltipBody(activeNode.label, activeNode.description || '', 56, 4);

        const wrap = (text: string, maxChars: number): string[] => {
          const words = text.split(/\s+/).filter(Boolean);
          if (!words.length) return [];
          const out: string[] = [];
          let line = '';
          for (const w2 of words) {
            const next = line ? `${line} ${w2}` : w2;
            if (next.length <= maxChars) line = next;
            else {
              if (line) out.push(line);
              line = w2;
            }
          }
          if (line) out.push(line);
          return out;
        };

        const bodyWrapped = wrap(body, 56);
        const bodyLines = bodyWrapped.slice(0, 4);
        const lines = [title, subtitle, ...bodyLines].filter(Boolean);

        ctx.font = '13px ui-monospace, monospace';
        const textW = Math.max(...lines.map((l) => ctx.measureText(l).width), 320);
        const boxW = Math.min(520, textW + 20);
        const boxH = 14 + lines.length * 18;
        let tx = sx + sr + 14;
        let ty = sy - boxH / 2;
        if (tx + boxW > w - 8) tx = sx - sr - boxW - 14;
        if (tx < 8) tx = 8;
        if (ty < 8) ty = 8;
        if (ty + boxH > h - 8) ty = h - boxH - 8;

        ctx.fillStyle = '#ffffff';
        ctx.globalAlpha = 0.99;
        ctx.beginPath();
        ctx.roundRect(tx, ty, boxW, boxH, 7);
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = '#111827';
        ctx.lineWidth = 1.4;
        ctx.stroke();

        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        lines.forEach((line, i) => {
          if (i === 0) ctx.font = 'bold 13px ui-monospace, monospace';
          else if (i === 1) ctx.font = '12px ui-monospace, monospace';
          else ctx.font = '12px ui-monospace, monospace';
          ctx.fillStyle = i === 0 ? '#111827' : i === 1 ? '#374151' : '#4b5563';
          ctx.fillText(line, tx + 10, ty + 7 + i * 18, boxW - 18);
        });
      }
    };

    const animate = () => {
      tick();
      draw();
      requestAnimationFrame(animate);
    };
    animate();

    const onMouseDown = (ev: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;
      const w = toWorld(x, y);
      downRef.current = { x, y, id: null };
      for (const n of nodesRef.current) {
        const r = nodeRadius(n);
        const dx = w.x - n.x;
        const dy = w.y - n.y;
        if (dx * dx + dy * dy <= r * r) {
          onGraphInteractRef.current?.();
          dragRef.current = { node: n, offsetX: w.x - n.x, offsetY: w.y - n.y };
          downRef.current.id = n.id;
          return;
        }
      }
      panningRef.current = true;
      panStartRef.current = { x, y, panX: panRef.current.x, panY: panRef.current.y };
    };

    const onMouseMove = (ev: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;
      const w = toWorld(x, y);

      if (dragRef.current) {
        dragRef.current.node.x = w.x - dragRef.current.offsetX;
        dragRef.current.node.y = w.y - dragRef.current.offsetY;
        dragRef.current.node.vx = 0;
        dragRef.current.node.vy = 0;
        return;
      }
      if (panningRef.current) {
        const dx = x - panStartRef.current.x;
        const dy = y - panStartRef.current.y;
        panRef.current.x = panStartRef.current.panX + dx / zoomRef.current;
        panRef.current.y = panStartRef.current.panY + dy / zoomRef.current;
        return;
      }

      let hovered: SimNode | null = null;
      const isolatedNodeId = isolatedNodeIdRef.current;
      const connectedToIsolated = connectedToIsolatedRef.current;
      for (let i = nodesRef.current.length - 1; i >= 0; i--) {
        const n = nodesRef.current[i];
        if (isolatedNodeId && n.id !== isolatedNodeId && !connectedToIsolated.has(n.id)) {
          continue;
        }
        const r = nodeRadius(n);
        const dx = w.x - n.x;
        const dy = w.y - n.y;
        if (dx * dx + dy * dy <= r * r) {
          hovered = n;
          break;
        }
      }
      if (hovered?.id === hoverNodeRef.current?.id) return;
      hoverNodeRef.current = hovered;
      onHoverNodeRef.current?.(hovered);
    };

    const onMouseUp = (ev: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;
      const moved = Math.hypot(x - downRef.current.x, y - downRef.current.y);
      const clickId = dragRef.current?.node.id ?? downRef.current.id;
      if (dragRef.current && moved < 6 && clickId) {
        const node = nodesRef.current.find((n) => n.id === clickId);
        if (node && ev.altKey && onNodeIsolateToggleRef.current) {
          onNodeIsolateToggleRef.current(node);
        } else if (node && onNodeClickRef.current) {
          const isNonExpandableFile = node.kind === 'file' && (node.entity_count ?? 0) <= 0;
          if (!isNonExpandableFile) onNodeClickRef.current(node);
        }
      }
      dragRef.current = null;
      panningRef.current = false;
    };

    const onWheel = (ev: WheelEvent) => {
      onGraphInteractRef.current?.();
      ev.preventDefault();
      const factor = ev.deltaY > 0 ? 0.9 : 1.1;
      zoomRef.current = Math.max(0.25, Math.min(1.8, zoomRef.current * factor));
    };

    canvas.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });

    return () => {
      running = false;
      ro.disconnect();
      canvas.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      canvas.removeEventListener('wheel', onWheel);
    };
  }, [toWorld]);

  return (
    <div className="border border-gray-300 bg-gray-100 h-[74vh] relative">
      <canvas ref={canvasRef} className="w-full h-full" />
      <div className="absolute top-2 right-3 text-[11px] text-gray-500">click drill-down / option+click isolate / drag nodes / scroll zoom / drag background pan</div>
    </div>
  );
}

export default memo(AdaptiveMixedGraph);
