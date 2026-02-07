"""Self-contained HTML/CSS/JS for the D3.js agent visualization."""

VIZ_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>docbot – Pipeline Visualization</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0f172a;
    color: #e2e8f0;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    overflow: hidden;
    height: 100vh;
    width: 100vw;
  }
  #header {
    position: fixed; top: 0; left: 0; right: 0;
    height: 40px;
    background: #1e293b;
    border-bottom: 1px solid #334155;
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 16px;
    z-index: 10;
    font-size: 13px;
  }
  #header .title { font-weight: 600; color: #38bdf8; }
  #header .stats { color: #94a3b8; }
  #canvas { position: absolute; top: 40px; left: 0; right: 0; bottom: 0; }
  svg { width: 100%; height: 100%; }

  /* Legend */
  #legend {
    position: fixed; bottom: 16px; right: 16px;
    background: #1e293bdd;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 12px;
    z-index: 10;
  }
  #legend .row { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
  #legend .swatch {
    width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0;
  }

  /* Pulse animation for running nodes */
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }
  .node-running rect { animation: pulse 1.4s ease-in-out infinite; }
</style>
</head>
<body>
<div id="header">
  <span class="title">docbot pipeline</span>
  <span class="stats" id="stats">connecting…</span>
</div>
<div id="canvas"></div>
<div id="legend">
  <div class="row"><span class="swatch" style="background:#64748b"></span> Pending</div>
  <div class="row"><span class="swatch" style="background:#eab308"></span> Waiting</div>
  <div class="row"><span class="swatch" style="background:#3b82f6"></span> Running</div>
  <div class="row"><span class="swatch" style="background:#22c55e"></span> Done</div>
  <div class="row"><span class="swatch" style="background:#ef4444"></span> Error</div>
</div>

<script type="module">
import * as d3 from "https://cdn.jsdelivr.net/npm/d3@7/+esm";

const STATE_COLORS = {
  pending:  "#64748b",
  waiting:  "#eab308",
  running:  "#3b82f6",
  done:     "#22c55e",
  error:    "#ef4444",
};

const NODE_W = 150, NODE_H = 44, NODE_R = 8;

const svg = d3.select("#canvas").append("svg");
const gRoot = svg.append("g");

// zoom / pan
const zoom = d3.zoom().scaleExtent([0.2, 3]).on("zoom", (e) => {
  gRoot.attr("transform", e.transform);
});
svg.call(zoom);

const gLinks = gRoot.append("g").attr("class", "links");
const gNodes = gRoot.append("g").attr("class", "nodes");

let prevNodeCount = 0;

function buildHierarchy(data) {
  if (!data.root || !data.nodes.length) return null;
  const map = {};
  data.nodes.forEach(n => { map[n.id] = { ...n, children: [] }; });
  data.nodes.forEach(n => {
    if (n.parent && map[n.parent]) {
      map[n.parent].children.push(map[n.id]);
    }
  });
  return map[data.root] || null;
}

function render(data) {
  const rootData = buildHierarchy(data);
  if (!rootData) return;

  const root = d3.hierarchy(rootData);
  const treeLayout = d3.tree().nodeSize([NODE_W + 30, NODE_H + 50]);
  treeLayout(root);

  // update stats
  const total = data.nodes.length;
  const done = data.nodes.filter(n => n.state === "done").length;
  const running = data.nodes.filter(n => n.state === "running").length;
  const errors = data.nodes.filter(n => n.state === "error").length;
  let statsText = `${done}/${total} done, ${running} running`;
  if (errors) statsText += `, ${errors} error(s)`;
  document.getElementById("stats").textContent = statsText;

  // --- Links ---
  const linkGen = d3.linkVertical().x(d => d.x).y(d => d.y);
  const links = gLinks.selectAll("path.link").data(root.links(), d => d.source.data.id + "-" + d.target.data.id);
  links.enter()
    .append("path").attr("class", "link")
    .attr("fill", "none").attr("stroke", "#475569").attr("stroke-width", 1.5)
    .attr("d", linkGen)
    .attr("opacity", 0)
    .transition().duration(300).attr("opacity", 1);
  links.transition().duration(300).attr("d", linkGen);
  links.exit().transition().duration(200).attr("opacity", 0).remove();

  // --- Nodes ---
  const nodeData = root.descendants();
  const nodes = gNodes.selectAll("g.node").data(nodeData, d => d.data.id);

  // enter
  const enter = nodes.enter().append("g")
    .attr("class", d => "node node-" + d.data.state)
    .attr("transform", d => `translate(${d.x},${d.y})`);

  enter.append("rect")
    .attr("x", -NODE_W / 2).attr("y", -NODE_H / 2)
    .attr("width", NODE_W).attr("height", NODE_H)
    .attr("rx", NODE_R).attr("ry", NODE_R)
    .attr("fill", d => STATE_COLORS[d.data.state] || "#64748b")
    .attr("opacity", 0.9);

  enter.append("text")
    .attr("text-anchor", "middle").attr("dy", "-0.15em")
    .attr("fill", "#f8fafc").attr("font-size", "12px").attr("font-weight", "600")
    .text(d => d.data.name.length > 18 ? d.data.name.slice(0, 16) + "…" : d.data.name);

  enter.append("text")
    .attr("class", "elapsed")
    .attr("text-anchor", "middle").attr("dy", "1.2em")
    .attr("fill", "#cbd5e1").attr("font-size", "10px")
    .text(d => d.data.elapsed > 0 ? d.data.elapsed + "s" : "");

  // update
  const merged = enter.merge(nodes);
  merged
    .attr("class", d => "node node-" + d.data.state)
    .transition().duration(300)
    .attr("transform", d => `translate(${d.x},${d.y})`);

  merged.select("rect")
    .transition().duration(300)
    .attr("fill", d => STATE_COLORS[d.data.state] || "#64748b");

  merged.select("text.elapsed")
    .text(d => d.data.elapsed > 0 ? d.data.elapsed + "s" : "");

  nodes.exit().transition().duration(200).attr("opacity", 0).remove();

  // auto-fit when new nodes appear
  if (nodeData.length !== prevNodeCount) {
    prevNodeCount = nodeData.length;
    autoFit(root);
  }
}

function autoFit(root) {
  const nodes = root.descendants();
  if (!nodes.length) return;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  nodes.forEach(n => {
    minX = Math.min(minX, n.x - NODE_W / 2);
    maxX = Math.max(maxX, n.x + NODE_W / 2);
    minY = Math.min(minY, n.y - NODE_H / 2);
    maxY = Math.max(maxY, n.y + NODE_H / 2);
  });
  const pad = 60;
  const w = maxX - minX + pad * 2;
  const h = maxY - minY + pad * 2;
  const svgEl = svg.node();
  const sw = svgEl.clientWidth;
  const sh = svgEl.clientHeight;
  const scale = Math.min(sw / w, sh / h, 1.5);
  const tx = sw / 2 - (minX + maxX) / 2 * scale;
  const ty = sh / 2 - (minY + maxY) / 2 * scale;
  svg.transition().duration(400).call(
    zoom.transform,
    d3.zoomIdentity.translate(tx, ty).scale(scale)
  );
}

async function poll() {
  try {
    const resp = await fetch("/state");
    if (resp.ok) {
      const data = await resp.json();
      render(data);
    }
  } catch { /* server not ready yet */ }
}

setInterval(poll, 400);
poll();
</script>
</body>
</html>
"""
