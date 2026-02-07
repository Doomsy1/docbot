"""Legacy D3/HTML template for pipeline visualization. DEPRECATED in favor of React/ReactFlow."""

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
    width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0;
  }

  /* Pulse animation for running nodes */
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.55; }
  }
  .node-running circle { animation: pulse 1.4s ease-in-out infinite; }
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

// Radii for the circles: root is larger
const ROOT_R = 30;
const NODE_R = 20;
const LEAF_R = 15;

function nodeRadius(d) {
  if (!d.parent) return ROOT_R;
  return d.children && d.children.length ? NODE_R : LEAF_R;
}

// Radial projection: angle x, radius y → cartesian
function radialPoint(x, y) {
  return [y * Math.cos(x - Math.PI / 2), y * Math.sin(x - Math.PI / 2)];
}

const svg = d3.select("#canvas").append("svg");
const gRoot = svg.append("g");

// zoom / pan
const zoom = d3.zoom().scaleExtent([0.15, 4]).on("zoom", (e) => {
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
  const nodeCount = root.descendants().length;

  // Scale the radius based on how many nodes we have
  const baseRadius = Math.max(140, nodeCount * 18);
  const treeLayout = d3.tree()
    .size([2 * Math.PI, baseRadius])
    .separation((a, b) => (a.parent === b.parent ? 1 : 2) / a.depth || 1);
  treeLayout(root);

  // Pin root at center
  root.x = 0;
  root.y = 0;

  // update stats
  const total = data.nodes.length;
  const done = data.nodes.filter(n => n.state === "done").length;
  const running = data.nodes.filter(n => n.state === "running").length;
  const errors = data.nodes.filter(n => n.state === "error").length;
  let statsText = `${done}/${total} done, ${running} running`;
  if (errors) statsText += `, ${errors} error(s)`;
  document.getElementById("stats").textContent = statsText;

  // --- Links ---
  const linkGen = d3.linkRadial().angle(d => d.x).radius(d => d.y);
  const links = gLinks.selectAll("path.link")
    .data(root.links(), d => d.source.data.id + "-" + d.target.data.id);

  links.enter()
    .append("path").attr("class", "link")
    .attr("fill", "none").attr("stroke", "#475569").attr("stroke-width", 1.5)
    .attr("d", linkGen)
    .attr("opacity", 0)
    .transition().duration(300).attr("opacity", 0.7);

  links.transition().duration(300).attr("d", linkGen);
  links.exit().transition().duration(200).attr("opacity", 0).remove();

  // --- Nodes ---
  const nodeData = root.descendants();
  const nodes = gNodes.selectAll("g.node").data(nodeData, d => d.data.id);

  // enter
  const enter = nodes.enter().append("g")
    .attr("class", d => "node node-" + d.data.state)
    .attr("transform", d => {
      const [x, y] = d.parent ? radialPoint(d.x, d.y) : [0, 0];
      return `translate(${x},${y})`;
    });

  enter.append("circle")
    .attr("r", d => nodeRadius(d))
    .attr("fill", d => STATE_COLORS[d.data.state] || "#64748b")
    .attr("stroke", "#1e293b")
    .attr("stroke-width", 2)
    .attr("opacity", 0.92);

  // name label
  enter.append("text")
    .attr("class", "label")
    .attr("text-anchor", "middle")
    .attr("dy", d => nodeRadius(d) + 14)
    .attr("fill", "#e2e8f0")
    .attr("font-size", d => d.parent ? "10px" : "12px")
    .attr("font-weight", d => d.parent ? "500" : "700")
    .text(d => {
      const n = d.data.name;
      return n.length > 16 ? n.slice(0, 14) + "…" : n;
    });

  // elapsed label (inside circle)
  enter.append("text")
    .attr("class", "elapsed")
    .attr("text-anchor", "middle")
    .attr("dy", "0.35em")
    .attr("fill", "#f8fafc")
    .attr("font-size", d => d.parent ? "9px" : "11px")
    .attr("font-weight", "600")
    .text(d => d.data.elapsed > 0 ? d.data.elapsed + "s" : "");

  // update
  const merged = enter.merge(nodes);
  merged
    .attr("class", d => "node node-" + d.data.state)
    .transition().duration(300)
    .attr("transform", d => {
      const [x, y] = d.parent ? radialPoint(d.x, d.y) : [0, 0];
      return `translate(${x},${y})`;
    });

  merged.select("circle")
    .transition().duration(300)
    .attr("r", d => nodeRadius(d))
    .attr("fill", d => STATE_COLORS[d.data.state] || "#64748b");

  merged.select("text.label")
    .attr("dy", d => nodeRadius(d) + 14);

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
  nodes.forEach(d => {
    const [px, py] = d.parent ? radialPoint(d.x, d.y) : [0, 0];
    const r = nodeRadius(d) + 20; // padding around node
    minX = Math.min(minX, px - r);
    maxX = Math.max(maxX, px + r);
    minY = Math.min(minY, py - r);
    maxY = Math.max(maxY, py + r);
  });
  const pad = 50;
  const w = maxX - minX + pad * 2;
  const h = maxY - minY + pad * 2;
  const svgEl = svg.node();
  const sw = svgEl.clientWidth;
  const sh = svgEl.clientHeight;
  const scale = Math.min(sw / w, sh / h, 1.8);
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const tx = sw / 2 - cx * scale;
  const ty = sh / 2 - cy * scale;
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


REPLAY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>docbot – Pipeline Replay</title>
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
  #header .title { font-weight: 600; color: #f59e0b; }
  #header .stats { color: #94a3b8; }
  #canvas { position: absolute; top: 40px; left: 0; right: 0; bottom: 80px; }
  svg { width: 100%; height: 100%; }

  /* Controls */
  #controls {
    position: fixed; bottom: 0; left: 0; right: 0;
    height: 80px;
    background: #1e293b;
    border-top: 1px solid #334155;
    display: flex;
    align-items: center;
    padding: 0 16px;
    gap: 12px;
    z-index: 10;
  }
  button {
    background: #3b82f6;
    border: none;
    color: white;
    padding: 8px 14px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
    transition: background 0.2s;
  }
  button:hover { background: #2563eb; }
  button:disabled { background: #475569; cursor: not-allowed; }
  select {
    background: #334155;
    color: white;
    border: 1px solid #475569;
    padding: 8px 10px;
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
  }
  #timeline {
    flex: 1;
    height: 40px;
    background: #334155;
    border-radius: 6px;
    position: relative;
    cursor: pointer;
  }
  #progress {
    height: 100%;
    background: linear-gradient(90deg, #3b82f6, #2563eb);
    border-radius: 6px;
    transition: width 0.05s linear;
    pointer-events: none;
  }
  #time-display {
    font-family: 'Courier New', monospace;
    font-size: 13px;
    min-width: 140px;
    text-align: center;
    color: #94a3b8;
  }

  /* Legend */
  #legend {
    position: fixed; bottom: 96px; right: 16px;
    background: #1e293bdd;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 12px;
    z-index: 10;
  }
  #legend .row { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
  #legend .swatch {
    width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0;
  }

  /* Pulse animation for running nodes */
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.55; }
  }
  .node-running circle { animation: pulse 1.4s ease-in-out infinite; }
</style>
</head>
<body>
<div id="header">
  <span class="title">🎬 docbot replay</span>
  <span class="stats" id="stats">loading…</span>
</div>
<div id="canvas"></div>
<div id="legend">
  <div class="row"><span class="swatch" style="background:#64748b"></span> Pending</div>
  <div class="row"><span class="swatch" style="background:#eab308"></span> Waiting</div>
  <div class="row"><span class="swatch" style="background:#3b82f6"></span> Running</div>
  <div class="row"><span class="swatch" style="background:#22c55e"></span> Done</div>
  <div class="row"><span class="swatch" style="background:#ef4444"></span> Error</div>
</div>
<div id="controls">
  <button id="play-pause">▶ Play</button>
  <button id="step-back">◀ Step</button>
  <button id="step-forward">Step ▶</button>
  <select id="speed">
    <option value="1">1x</option>
    <option value="2">2x</option>
    <option value="4">4x</option>
    <option value="8">8x</option>
  </select>
  <div id="timeline"><div id="progress"></div></div>
  <div id="time-display">0.0s / 0.0s</div>
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

const ROOT_R = 30;
const NODE_R = 20;
const LEAF_R = 15;

function nodeRadius(d) {
  if (!d.parent) return ROOT_R;
  return d.children && d.children.length ? NODE_R : LEAF_R;
}

function radialPoint(x, y) {
  return [y * Math.cos(x - Math.PI / 2), y * Math.sin(x - Math.PI / 2)];
}

// Replay state
let eventsData = null;
let currentTime = 0;
let isPlaying = false;
let playbackSpeed = 1;
let currentEventIndex = 0;
let animationFrame = null;
let lastFrameTime = 0;

// Virtual pipeline state
const nodes = new Map();
let rootId = null;

// D3 setup
const svg = d3.select("#canvas").append("svg");
const gRoot = svg.append("g");
const zoom = d3.zoom().scaleExtent([0.15, 4]).on("zoom", (e) => {
  gRoot.attr("transform", e.transform);
});
svg.call(zoom);
const gLinks = gRoot.append("g").attr("class", "links");
const gNodes = gRoot.append("g").attr("class", "nodes");

// Fetch events and initialize
fetch('/events')
  .then(r => r.json())
  .then(data => {
    eventsData = data;
    initReplay();
  })
  .catch(err => {
    document.getElementById('stats').textContent = 'Error loading events';
    console.error(err);
  });

function initReplay() {
  document.getElementById('time-display').textContent = 
    `0.0s / ${eventsData.total_duration.toFixed(1)}s`;
  document.getElementById('stats').textContent = 
    `Run: ${eventsData.run_id} | ${eventsData.events.length} events`;
  setupControls();
  renderTree();
}

function setupControls() {
  const playPauseBtn = document.getElementById('play-pause');
  const stepBackBtn = document.getElementById('step-back');
  const stepForwardBtn = document.getElementById('step-forward');
  const speedSelect = document.getElementById('speed');
  const timeline = document.getElementById('timeline');

  playPauseBtn.addEventListener('click', togglePlayPause);
  stepBackBtn.addEventListener('click', stepBackward);
  stepForwardBtn.addEventListener('click', stepForward);
  speedSelect.addEventListener('change', (e) => {
    playbackSpeed = parseFloat(e.target.value);
  });
  timeline.addEventListener('click', (e) => {
    const rect = timeline.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const percent = x / rect.width;
    seekTo(percent * eventsData.total_duration);
  });
}

function togglePlayPause() {
  isPlaying = !isPlaying;
  const btn = document.getElementById('play-pause');
  btn.textContent = isPlaying ? '⏸ Pause' : '▶ Play';
  if (isPlaying) {
    lastFrameTime = performance.now();
    playLoop();
  } else {
    if (animationFrame) cancelAnimationFrame(animationFrame);
  }
}

function playLoop() {
  if (!isPlaying) return;
  
  const now = performance.now();
  const delta = (now - lastFrameTime) / 1000 * playbackSpeed;
  lastFrameTime = now;
  
  currentTime += delta;
  if (currentTime >= eventsData.total_duration) {
    currentTime = eventsData.total_duration;
    isPlaying = false;
    document.getElementById('play-pause').textContent = '▶ Play';
  }
  
  applyEventsUpTo(currentTime);
  updateUI();
  
  if (isPlaying) {
    animationFrame = requestAnimationFrame(playLoop);
  }
}

function stepForward() {
  if (currentEventIndex < eventsData.events.length) {
    const event = eventsData.events[currentEventIndex];
    applyEvent(event);
    currentEventIndex++;
    currentTime = event.timestamp;
    updateUI();
  }
}

function stepBackward() {
  if (currentEventIndex > 0) {
    // Rebuild state from scratch up to previous event
    nodes.clear();
    rootId = null;
    currentEventIndex = Math.max(0, currentEventIndex - 1);
    for (let i = 0; i < currentEventIndex; i++) {
      applyEvent(eventsData.events[i]);
    }
    currentTime = currentEventIndex > 0 ? eventsData.events[currentEventIndex - 1].timestamp : 0;
    updateUI();
  }
}

function seekTo(time) {
  currentTime = Math.max(0, Math.min(time, eventsData.total_duration));
  applyEventsUpTo(currentTime);
  updateUI();
}

function applyEventsUpTo(time) {
  // Rebuild state from scratch
  nodes.clear();
  rootId = null;
  currentEventIndex = 0;
  
  for (const event of eventsData.events) {
    if (event.timestamp > time) break;
    applyEvent(event);
    currentEventIndex++;
  }
}

function applyEvent(event) {
  if (event.type === 'add') {
    nodes.set(event.node_id, {
      id: event.node_id,
      name: event.name,
      parent: event.parent_id,
      state: 'pending',
      detail: '',
      children: []
    });
    if (!event.parent_id) {
      rootId = event.node_id;
    } else if (nodes.has(event.parent_id)) {
      nodes.get(event.parent_id).children.push(event.node_id);
    }
  } else if (event.type === 'state') {
    const node = nodes.get(event.node_id);
    if (node) {
      node.state = event.state;
      node.detail = event.detail;
    }
  }
}

function updateUI() {
  const progress = (currentTime / eventsData.total_duration) * 100;
  document.getElementById('progress').style.width = progress + '%';
  document.getElementById('time-display').textContent = 
    `${currentTime.toFixed(1)}s / ${eventsData.total_duration.toFixed(1)}s`;
  renderTree();
}

function buildHierarchy(nodeId) {
  const node = nodes.get(nodeId);
  if (!node) return null;
  return {
    id: node.id,
    name: node.name,
    state: node.state,
    detail: node.detail,
    children: node.children.map(buildHierarchy).filter(Boolean)
  };
}

function renderTree() {
  if (!rootId || !nodes.has(rootId)) return;

  const rootData = buildHierarchy(rootId);
  if (!rootData) return;

  const root = d3.hierarchy(rootData);
  const nodeCount = root.descendants().length;

  const baseRadius = Math.max(140, nodeCount * 18);
  const treeLayout = d3.tree()
    .size([2 * Math.PI, baseRadius])
    .separation((a, b) => (a.parent === b.parent ? 1 : 2) / a.depth || 1);
  treeLayout(root);

  root.x = 0;
  root.y = 0;

  // --- Links ---
  const linkGen = d3.linkRadial().angle(d => d.x).radius(d => d.y);
  const links = gLinks.selectAll("path.link")
    .data(root.links(), d => d.source.data.id + "-" + d.target.data.id);

  links.enter()
    .append("path").attr("class", "link")
    .attr("fill", "none").attr("stroke", "#475569").attr("stroke-width", 1.5)
    .attr("d", linkGen)
    .attr("opacity", 0.7);

  links.attr("d", linkGen);
  links.exit().remove();

  // --- Nodes ---
  const nodeData = root.descendants();
  const nodesSelection = gNodes.selectAll("g.node").data(nodeData, d => d.data.id);

  const enter = nodesSelection.enter().append("g")
    .attr("class", d => "node node-" + d.data.state)
    .attr("transform", d => {
      const [x, y] = d.parent ? radialPoint(d.x, d.y) : [0, 0];
      return `translate(${x},${y})`;
    });

  enter.append("circle")
    .attr("r", d => nodeRadius(d))
    .attr("fill", d => STATE_COLORS[d.data.state] || "#64748b")
    .attr("stroke", "#1e293b")
    .attr("stroke-width", 2)
    .attr("opacity", 0.92);

  enter.append("text")
    .attr("class", "label")
    .attr("text-anchor", "middle")
    .attr("dy", d => nodeRadius(d) + 14)
    .attr("fill", "#e2e8f0")
    .attr("font-size", d => d.parent ? "10px" : "12px")
    .attr("font-weight", d => d.parent ? "500" : "700")
    .text(d => {
      const n = d.data.name;
      return n.length > 16 ? n.slice(0, 14) + "…" : n;
    });

  const merged = enter.merge(nodesSelection);
  merged
    .attr("class", d => "node node-" + d.data.state)
    .attr("transform", d => {
      const [x, y] = d.parent ? radialPoint(d.x, d.y) : [0, 0];
      return `translate(${x},${y})`;
    });

  merged.select("circle")
    .attr("r", d => nodeRadius(d))
    .attr("fill", d => STATE_COLORS[d.data.state] || "#64748b");

  merged.select("text.label")
    .attr("dy", d => nodeRadius(d) + 14);

  nodesSelection.exit().remove();
}
</script>
</body>
</html>
"""
