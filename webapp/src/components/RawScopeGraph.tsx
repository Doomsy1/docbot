import { useEffect, useRef, useCallback } from 'react';

interface FileNode {
  id: string;
  path: string;
  scope_id: string;
  scope_title: string;
  symbol_count: number;
  import_count: number;
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

interface ContextScope {
  scope_id: string;
  title: string;
  file_count: number;
  symbol_count: number;
  languages: string[];
  group: string;
}

interface Props {
  fileNodes: FileNode[];
  fileEdges: Array<{ from: string; to: string }>;
  scopeGroups: ScopeGroup[];
  scopeEdges: Array<{ from: string; to: string }>;
  contextScopes?: ContextScope[];
  contextScopeEdges?: Array<{ from: string; to: string }>;
  onFileClick?: (node: { path: string; scopeId: string; scopeTitle: string }) => void;
  onScopeClick?: (node: { scopeId: string; scopeTitle: string }) => void;
}

interface SimNode {
  kind: 'file' | 'scope';
  id: string;
  path: string;
  scopeId: string;
  scopeTitle: string;
  fileCount: number;
  symbolCount: number;
  importCount: number;
  language: string;
  group: string;
  description?: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

const FILE_NODE_MIN_RADIUS = 10;
const FILE_NODE_MAX_RADIUS = 22;

const SCOPE_COLORS: Record<string, string> = {
  frontend: '#3b82f6',
  backend: '#10b981',
  testing: '#f59e0b',
  scripts: '#8b5cf6',
  core: '#6b7280',
};

// Per-scope distinct hues rotated from the group base color
function scopeColor(group: string, scopeIndex: number): string {
  const base = SCOPE_COLORS[group] ?? SCOPE_COLORS.core;
  if (scopeIndex === 0) return base;
  // Shift hue slightly for each additional scope in the same group
  const shift = scopeIndex * 35;
  // Parse hex -> hsl, rotate, convert back
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

export default function RawScopeGraph({
  fileNodes,
  fileEdges,
  scopeGroups,
  scopeEdges,
  contextScopes,
  contextScopeEdges,
  onFileClick,
  onScopeClick,
}: Props) {
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

  function fileNodeRadius(n: SimNode): number {
    return Math.max(FILE_NODE_MIN_RADIUS, Math.min(FILE_NODE_MAX_RADIUS, 8 + n.symbolCount * 1.1));
  }

  function scopeNodeRadius(n: SimNode): number {
    const score = Math.max(1, n.fileCount + n.symbolCount / 8);
    return Math.max(28, Math.min(52, 20 + Math.sqrt(score) * 3.2));
  }

  function nodeRadius(n: SimNode): number {
    return n.kind === 'scope' ? scopeNodeRadius(n) : fileNodeRadius(n);
  }

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
    const allScopesDetailed: ContextScope[] = contextScopes?.length
      ? contextScopes
      : scopeGroups.map((s) => ({
          scope_id: s.scope_id,
          title: s.title,
          file_count: s.file_count,
          symbol_count: 0,
          languages: [],
          group: s.group,
        }));
    const allScopes: ScopeGroup[] = allScopesDetailed.map((s) => ({
      scope_id: s.scope_id,
      title: s.title,
      file_count: s.file_count,
      group: s.group,
    }));

    // Build scope color map
    const colorMap = new Map<string, string>();
    const groupCounters: Record<string, number> = {};
    for (const sg of allScopes) {
      const idx = groupCounters[sg.group] ?? 0;
      groupCounters[sg.group] = idx + 1;
      colorMap.set(sg.scope_id, scopeColor(sg.group, idx));
    }
    scopeColorMapRef.current = colorMap;

    // Group files by scope and arrange in clusters
    const scopeFiles = new Map<string, FileNode[]>();
    for (const fn of fileNodes) {
      if (!scopeFiles.has(fn.scope_id)) scopeFiles.set(fn.scope_id, []);
      scopeFiles.get(fn.scope_id)!.push(fn);
    }

    const allScopeIds = allScopes.map((s) => s.scope_id);
    const scopeAngle = (2 * Math.PI) / Math.max(allScopeIds.length, 1);
    const clusterRadius = Math.min(430, Math.max(230, allScopeIds.length * 66));
    const centerMap = new Map<string, { x: number; y: number }>();
    allScopeIds.forEach((sid, si) => {
      centerMap.set(sid, {
        x: Math.cos(scopeAngle * si) * clusterRadius,
        y: Math.sin(scopeAngle * si) * clusterRadius,
      });
    });
    const nodes: SimNode[] = [];
    const focusedScopeIds = [...scopeFiles.keys()];
    focusedScopeIds.forEach((sid) => {
      const files = scopeFiles.get(sid)!;
      const center = centerMap.get(sid) ?? { x: 0, y: 0 };
      const cx = center.x;
      const cy = center.y;
      const fileAngle = (2 * Math.PI) / Math.max(files.length, 1);
      const fileRadius = Math.min(140, Math.max(56, files.length * 18));

      files.forEach((f, fi) => {
        nodes.push({
          kind: 'file',
          id: f.id,
          path: f.path,
          scopeId: f.scope_id,
          scopeTitle: f.scope_title,
          fileCount: 1,
          symbolCount: f.symbol_count,
          importCount: f.import_count,
          language: f.language,
          group: f.group,
          description: f.description,
          x: cx + Math.cos(fileAngle * fi) * fileRadius,
          y: cy + Math.sin(fileAngle * fi) * fileRadius,
          vx: 0,
          vy: 0,
        });
      });
    });

    // Add non-focused scopes as proper simulated context nodes.
    const focusedSet = new Set(focusedScopeIds);
    for (const s of allScopesDetailed) {
      if (focusedSet.has(s.scope_id)) continue;
      const center = centerMap.get(s.scope_id) ?? { x: 0, y: 0 };
      nodes.push({
        kind: 'scope',
        id: `scope:${s.scope_id}`,
        path: '',
        scopeId: s.scope_id,
        scopeTitle: s.title,
        fileCount: s.file_count,
        symbolCount: s.symbol_count,
        importCount: 0,
        language: s.languages.join(', '),
        group: s.group,
        description: `${s.title} scope with ${s.file_count} files and ${s.symbol_count} entities.`,
        x: center.x,
        y: center.y,
        vx: 0,
        vy: 0,
      });
    }

    nodesRef.current = nodes;
    panRef.current = { x: 0, y: 0 };
    zoomRef.current = 1;
  }, [fileNodes, scopeGroups, contextScopes]);

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

    // Pre-compute scope centroids for cluster forces
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

      // Repulsion between all pairs (weaker for nodes in same scope)
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[j].x - nodes[i].x;
          const dy = nodes[j].y - nodes[i].y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const sameScope = nodes[i].scopeId === nodes[j].scopeId;
          const hasScopeNode = nodes[i].kind === 'scope' || nodes[j].kind === 'scope';
          const repulsion = hasScopeNode ? (sameScope ? 1200 : 2600) : (sameScope ? 880 : 1900);
          const force = (repulsion / (dist * dist)) * alpha;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          nodes[i].vx -= fx;
          nodes[i].vy -= fy;
          nodes[j].vx += fx;
          nodes[j].vy += fy;
        }
      }

      // Spring forces on file edges
      const nodeMap = new Map(nodes.map((n) => [n.id, n]));
      for (const e of fileEdges) {
        const a = nodeMap.get(e.from);
        const b = nodeMap.get(e.to);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const target = a.scopeId === b.scopeId ? 90 : 190;
        const force = ((dist - target) / dist) * 0.058 * alpha;
        a.vx += dx * force;
        a.vy += dy * force;
        b.vx -= dx * force;
        b.vy -= dy * force;
      }

      // Scope edge forces between context scope nodes.
      const scopeNodeByScope = new Map<string, SimNode>();
      for (const n of nodes) {
        if (n.kind === 'scope') scopeNodeByScope.set(n.scopeId, n);
      }
      const scopeEdgeSet = contextScopeEdges ?? scopeEdges;
      for (const e of scopeEdgeSet) {
        const a = scopeNodeByScope.get(e.from);
        const b = scopeNodeByScope.get(e.to);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const target = 240;
        const force = ((dist - target) / dist) * 0.04 * alpha;
        a.vx += dx * force;
        a.vy += dy * force;
        b.vx -= dx * force;
        b.vy -= dy * force;
      }

      // Collision avoidance for file nodes.
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const ar = nodeRadius(a);
          const br = nodeRadius(b);
          const minDist = ar + br + 12;
          if (dist >= minDist) continue;
          const overlap = (minDist - dist) / dist;
          const push = overlap * 0.28 * alpha;
          const fx = dx * push;
          const fy = dy * push;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }
      }

      // Cluster cohesion: pull nodes toward their scope centroid
      const centroids = getScopeCentroids();
      for (const n of nodes) {
        if (n.kind === 'scope') continue;
        const c = centroids.get(n.scopeId);
        if (!c) continue;
        const dx = c.cx - n.x;
        const dy = c.cy - n.y;
        n.vx += dx * 0.006 * alpha;
        n.vy += dy * 0.006 * alpha;
      }

      // Gravity toward center
      for (const n of nodes) {
        n.vx -= n.x * 0.0015 * alpha;
        n.vy -= n.y * 0.0015 * alpha;
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
        if (sns.length < 2) continue;
        const color = colorMap.get(scopeId) ?? '#6b7280';

        // Compute bounding box with padding
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (const n of sns) {
          if (n.x < minX) minX = n.x;
          if (n.y < minY) minY = n.y;
          if (n.x > maxX) maxX = n.x;
          if (n.y > maxY) maxY = n.y;
        }
        const pad = 30;
        const rx = 10;

        ctx.fillStyle = color;
        ctx.globalAlpha = 0.07;
        ctx.beginPath();
        ctx.roundRect(minX - pad, minY - pad, maxX - minX + pad * 2, maxY - minY + pad * 2, rx);
        ctx.fill();
        ctx.globalAlpha = 0.25;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.globalAlpha = 1;

        // Scope label
        const sg = scopeGroups.find(s => s.scope_id === scopeId);
        if (sg) {
          ctx.font = 'bold 10px ui-monospace, monospace';
          ctx.fillStyle = color;
          ctx.globalAlpha = 0.6;
          ctx.textAlign = 'left';
          ctx.textBaseline = 'top';
          ctx.fillText(sg.title, minX - pad + 6, minY - pad + 4);
          ctx.globalAlpha = 1;
        }
      }

      // Draw scope-level edges (thick, faded)
      const scopeEdgeSet = contextScopeEdges ?? scopeEdges;
      for (const e of scopeEdgeSet) {
        const fromNodes = scopeNodes.get(e.from);
        const toNodes = scopeNodes.get(e.to);
        if (!fromNodes?.length || !toNodes?.length) continue;
        const ax = fromNodes.reduce((s, n) => s + n.x, 0) / fromNodes.length;
        const ay = fromNodes.reduce((s, n) => s + n.y, 0) / fromNodes.length;
        const bx = toNodes.reduce((s, n) => s + n.x, 0) / toNodes.length;
        const by = toNodes.reduce((s, n) => s + n.y, 0) / toNodes.length;

        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
        ctx.strokeStyle = '#cbd5e1';
        ctx.lineWidth = 3;
        ctx.globalAlpha = 0.3;
        ctx.stroke();
        ctx.globalAlpha = 1;
      }

      // Draw file-to-file edges
      for (const e of fileEdges) {
        const a = nodeMap.get(e.from);
        const b = nodeMap.get(e.to);
        if (!a || !b) continue;

        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const ux = dx / dist;
        const uy = dy / dist;

        const r = Math.max(FILE_NODE_MIN_RADIUS, Math.min(FILE_NODE_MAX_RADIUS, 8 + a.symbolCount * 1.1));
        const startX = a.x + ux * r;
        const startY = a.y + uy * r;
        const endR = Math.max(FILE_NODE_MIN_RADIUS, Math.min(FILE_NODE_MAX_RADIUS, 8 + b.symbolCount * 1.1));
        const endX = b.x - ux * (endR + 8);
        const endY = b.y - uy * (endR + 8);

        const crossScope = a.scopeId !== b.scopeId;
        ctx.beginPath();
        ctx.moveTo(startX, startY);
        ctx.lineTo(endX, endY);
        ctx.strokeStyle = crossScope ? '#334155' : '#64748b';
        ctx.lineWidth = crossScope ? 2.2 : 1.6;
        ctx.globalAlpha = crossScope ? 0.85 : 0.72;
        ctx.stroke();
        ctx.globalAlpha = 1;

        // Arrowhead
        const arrowLen = crossScope ? 10 : 8;
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
        ctx.fillStyle = crossScope ? '#334155' : '#64748b';
        ctx.globalAlpha = crossScope ? 0.88 : 0.75;
        ctx.fill();
        ctx.globalAlpha = 1;
      }

      // Draw nodes (files and context scopes)
      for (const n of nodes) {
        const isHovered = hoverRef.current === n;
        const baseR = nodeRadius(n);
        const r = isHovered ? baseR + 3 : baseR;
        const color = colorMap.get(n.scopeId) ?? '#6b7280';

        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.globalAlpha = n.kind === 'scope' ? (isHovered ? 0.48 : 0.28) : (isHovered ? 1 : 0.8);
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = isHovered ? '#000' : color;
        ctx.lineWidth = n.kind === 'scope' ? (isHovered ? 2.2 : 1.6) : (isHovered ? 1.5 : 0.5);
        ctx.stroke();

        if (n.kind === 'scope') {
          const stats = `${n.fileCount} files`;
          const stats2 = `${n.symbolCount} entities`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillStyle = '#111827';
          ctx.font = '11px ui-monospace, monospace';
          ctx.fillText(stats, n.x, n.y - 3);
          ctx.globalAlpha = 0.9;
          ctx.fillText(stats2, n.x, n.y + 11);
          ctx.globalAlpha = 1;

          const short = n.scopeTitle.length > 22 ? `${n.scopeTitle.slice(0, 21)}…` : n.scopeTitle;
          const labelY = n.y + r + 16;
          const tw = ctx.measureText(short).width;
          const chipW = tw + 12;
          const chipH = 16;
          ctx.fillStyle = '#f3f4f6';
          ctx.globalAlpha = 0.92;
          ctx.beginPath();
          ctx.roundRect(n.x - chipW / 2, labelY - 13, chipW, chipH, 4);
          ctx.fill();
          ctx.globalAlpha = 1;
          ctx.font = `${isHovered ? 'bold ' : ''}11px ui-monospace, monospace`;
          ctx.fillStyle = '#111827';
          ctx.fillText(short, n.x, labelY - 5);
        } else {
          const parts = n.path.split('/');
          const basename = parts.length >= 2 ? parts.slice(-2).join('/') : n.path;
          const short = basename.length > 26 ? `${basename.slice(0, 25)}…` : basename;
          const labelY = n.y + r + 16;
          const tw = ctx.measureText(short).width;
          const chipW = tw + 12;
          const chipH = 16;
          ctx.fillStyle = '#f3f4f6';
          ctx.globalAlpha = 0.92;
          ctx.beginPath();
          ctx.roundRect(n.x - chipW / 2, labelY - 13, chipW, chipH, 4);
          ctx.fill();
          ctx.globalAlpha = 1;

          ctx.font = `${isHovered ? 'bold ' : ''}10px ui-monospace, monospace`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillStyle = '#111827';
          ctx.fillText(short, n.x, labelY - 5);
        }
      }

      // Tooltip for hovered node
      const hovered = hoverRef.current;
      if (hovered) {
        const lines = hovered.kind === 'scope'
          ? [
              hovered.scopeTitle,
              `scope: ${hovered.scopeTitle}`,
              `${hovered.fileCount} files, ${hovered.symbolCount} entities`,
              hovered.description || '',
            ].filter(Boolean)
          : [
              hovered.path,
              `scope: ${hovered.scopeTitle}`,
              `${hovered.symbolCount} entities, ${hovered.importCount} imports`,
              hovered.language,
              hovered.description || '',
            ].filter(Boolean);
        const lineH = 16;
        const pad = 8;
        ctx.font = '11px ui-monospace, monospace';
        const maxW = Math.max(...lines.map((l) => ctx.measureText(l).width));
        const tooltipW = maxW + pad * 2;
        const tooltipH = lines.length * lineH + pad * 2;
        const tx = hovered.x + 18;
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
  }, [fileNodes, fileEdges, scopeGroups, scopeEdges, contextScopes, contextScopeEdges]);

  // Mouse interactions
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

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
        if (node) {
          if (node.kind === 'file' && onFileClick) {
            onFileClick({ path: node.path, scopeId: node.scopeId, scopeTitle: node.scopeTitle });
          } else if (node.kind === 'scope' && onScopeClick) {
            onScopeClick({ scopeId: node.scopeId, scopeTitle: node.scopeTitle });
          }
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
  }, [toWorld, onFileClick, onScopeClick]);

  // Legend: show scope colors
  const legendItems: Array<{ label: string; color: string }> = [];
  const legendScopes: ScopeGroup[] = contextScopes?.length
    ? contextScopes.map((s) => ({
        scope_id: s.scope_id,
        title: s.title,
        file_count: s.file_count,
        group: s.group,
      }))
    : scopeGroups;
  for (const sg of legendScopes) {
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
        {fileNodes.length} focused files, {fileEdges.length} import edges, {legendScopes.length} scopes
      </div>
      <div className="border border-gray-300 bg-white" style={{ height: 500 }}>
        <canvas ref={canvasRef} className="w-full h-full" />
      </div>
    </div>
  );
}
