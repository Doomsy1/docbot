import { useState } from 'react';

interface ScopeNode {
  scope_id: string;
  title: string;
  file_count: number;
  symbol_count: number;
  languages: string[];
  group: string;
  summary?: string;
  description?: string;
}

interface ScopeEdge {
  from: string;
  to: string;
}

interface ScopeGraphProps {
  scopes: ScopeNode[];
  scopeEdges: ScopeEdge[];
}

const GROUP_COLORS: Record<string, string> = {
  frontend: '#3b82f6',
  backend: '#10b981',
  testing: '#f59e0b',
  scripts: '#8b5cf6',
  core: '#6b7280',
};

export default function ScopeGraph({ scopes, scopeEdges }: ScopeGraphProps) {
  const width = 900;
  const height = 520;
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.max(210, Math.min(320, scopes.length * 22));
  const edgeGap = 14; // keep arrows outside circles
  const positions = new Map<string, { x: number; y: number }>();
  const [hovered, setHovered] = useState<ScopeNode | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null);

  scopes.forEach((s, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, scopes.length);
    positions.set(s.scope_id, {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    });
  });

  const radiusFor = (s: ScopeNode) => {
    // Weight files and entities so larger scopes read as larger nodes.
    const score = s.file_count + s.symbol_count * 0.35;
    return Math.max(36, Math.min(70, 30 + Math.sqrt(score) * 5));
  };

  type LabelPlacement = {
    x: number;
    y: number;
    anchor: 'start' | 'middle' | 'end';
  };

  const scopeById = new Map(scopes.map((s) => [s.scope_id, s]));
  const labelPlacement = new Map<string, LabelPlacement>();

  const distPointToSegment = (
    px: number,
    py: number,
    x1: number,
    y1: number,
    x2: number,
    y2: number,
  ) => {
    const dx = x2 - x1;
    const dy = y2 - y1;
    const len2 = dx * dx + dy * dy;
    if (len2 === 0) return Math.hypot(px - x1, py - y1);
    const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / len2));
    const cx = x1 + t * dx;
    const cy = y1 + t * dy;
    return Math.hypot(px - cx, py - cy);
  };

  // Precompute edge geometry for scoring label positions.
  const edgeSegments = scopeEdges
    .map((e) => {
      const a = positions.get(e.from);
      const b = positions.get(e.to);
      const fromScope = scopeById.get(e.from);
      const toScope = scopeById.get(e.to);
      if (!a || !b || !fromScope || !toScope) return null;
      const rFrom = radiusFor(fromScope);
      const rTo = radiusFor(toScope);
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const ux = dx / dist;
      const uy = dy / dist;
      return {
        from: e.from,
        to: e.to,
        x1: a.x + ux * (rFrom + 2),
        y1: a.y + uy * (rFrom + 2),
        x2: b.x - ux * (rTo + edgeGap),
        y2: b.y - uy * (rTo + edgeGap),
      };
    })
    .filter(Boolean) as Array<{
    from: string;
    to: string;
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  }>;

  // Choose one of 4 label positions per node to avoid arrow overlap.
  for (const s of scopes) {
    const p = positions.get(s.scope_id);
    if (!p) continue;
    const r = radiusFor(s);
    const gap = 24;
    const candidates: LabelPlacement[] = [
      { x: p.x, y: p.y + r + gap, anchor: 'middle' }, // down
      { x: p.x, y: p.y - r - gap + 2, anchor: 'middle' }, // up
      { x: p.x + r + gap, y: p.y + 4, anchor: 'start' }, // right
      { x: p.x - r - gap, y: p.y + 4, anchor: 'end' }, // left
    ];

    let best = candidates[0];
    let bestScore = Number.POSITIVE_INFINITY;

    for (const c of candidates) {
      let score = 0;

      // Penalize proximity to edges.
      for (const seg of edgeSegments) {
        const d = distPointToSegment(c.x, c.y, seg.x1, seg.y1, seg.x2, seg.y2);
        if (d < 20) score += 120;
        else if (d < 36) score += 35;
      }

      // Penalize overlap with other nodes.
      for (const other of scopes) {
        if (other.scope_id === s.scope_id) continue;
        const op = positions.get(other.scope_id);
        if (!op) continue;
        const rr = radiusFor(other) + 14;
        const d = Math.hypot(c.x - op.x, c.y - op.y);
        if (d < rr) score += 90;
      }

      if (score < bestScore) {
        bestScore = score;
        best = c;
      }
    }

    labelPlacement.set(s.scope_id, best);
  }

  return (
    <div>
      <div className="text-xs text-gray-500 mb-2">
        {scopes.length} scopes, {scopeEdges.length} dependencies
      </div>
      <div className="border border-gray-300 bg-white overflow-auto relative">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-[520px]">
          <defs>
            <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" fill="#334155" />
            </marker>
          </defs>

          {edgeSegments.map((seg, i) => {
            return (
              <line
                key={`${seg.from}-${seg.to}-${i}`}
                x1={seg.x1}
                y1={seg.y1}
                x2={seg.x2}
                y2={seg.y2}
                stroke="#334155"
                strokeWidth={2.6}
                markerEnd="url(#arrow)"
                opacity={0.9}
              />
            );
          })}

          {scopes.map((s) => {
            const p = positions.get(s.scope_id);
            if (!p) return null;
            const color = GROUP_COLORS[s.group] || GROUP_COLORS.core;
            const label = s.title.length > 26 ? `${s.title.slice(0, 25)}…` : s.title;
            const stats = `${s.file_count} files`;
            const stats2 = `${s.symbol_count} entities`;
            const nodeRadius = radiusFor(s);
            const lp = labelPlacement.get(s.scope_id) ?? {
              x: p.x,
              y: p.y + nodeRadius + 18,
              anchor: 'middle' as const,
            };
            return (
              <g key={s.scope_id}>
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={nodeRadius + 12}
                  fill="transparent"
                  onMouseMove={(e) => {
                    setHovered(s);
                    setHoverPos({ x: e.clientX, y: e.clientY });
                  }}
                  onMouseEnter={(e) => {
                    setHovered(s);
                    setHoverPos({ x: e.clientX, y: e.clientY });
                  }}
                  onMouseLeave={() => {
                    setHovered(null);
                    setHoverPos(null);
                  }}
                />
                <circle cx={p.x} cy={p.y} r={nodeRadius} fill={color} opacity={0.95} stroke="#0f172a" strokeWidth={1.6} />
                <text x={p.x} y={p.y - 2} textAnchor="middle" fill="#e5e7eb" fontSize="11">
                  {stats}
                </text>
                <text x={p.x} y={p.y + 14} textAnchor="middle" fill="#e5e7eb" fontSize="11">
                  {stats2}
                </text>
                <rect
                  x={lp.anchor === 'middle' ? lp.x - 82 : lp.anchor === 'start' ? lp.x - 4 : lp.x - 160}
                  y={lp.y - 16}
                  width={164}
                  height={22}
                  rx={5}
                  fill="#f3f4f6"
                  opacity={0.94}
                />
                <text
                  x={lp.x}
                  y={lp.y}
                  textAnchor={lp.anchor}
                  fill="#111827"
                  fontSize="15"
                  fontWeight="700"
                >
                  {label}
                </text>
              </g>
            );
          })}
        </svg>
        {hovered && hoverPos && (
          <div
            className="absolute z-20 pointer-events-none max-w-[360px] text-xs bg-gray-900 text-white border border-gray-700 rounded px-3 py-2 shadow-lg"
            style={{ left: 12, bottom: 12 }}
          >
            <div className="font-semibold mb-1">{hovered.title}</div>
            <div>{hovered.description || hovered.summary || 'Scope node in the architecture graph.'}</div>
          </div>
        )}
      </div>
    </div>
  );
}
