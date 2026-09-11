#!/usr/bin/env python3
"""Render a memory-layout artifact as a self-contained interactive 3D page.

This is a PREVIEW, not the product. The product is the shared pipeline:

    MesaOS -> memory-layout.json -> MLPL -> native3d -> viewer

and the renderer that matters lives in `../../sw-ml-study/demo-extensions`,
where it is deliberately system-agnostic so that SWTOS, MLOS and MesaOS all
render through the same code. Nothing here is meant to migrate there.

What this is for is the gap in between: the artifact is emitted now, and the
shared renderer gets to MesaOS when it gets to MesaOS. Until then this page
answers the only question that matters about a producer -- does the data
describe the system correctly? -- by putting it in front of a pair of eyes.
It reads the same JSON a consumer reads, through the same public columns, so
if the towers look wrong the artifact is wrong.

The output is one HTML file with the layout embedded and no external
requests: no CDN, no build step, no server. Open it from the filesystem.

The metaphor is the one in demo-extensions/docs/research.txt: adjacent towers
of classified blocks, one tower per address space, stacked in address order,
with the relationships drawn as lines between them.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


PAGE = r"""<!doctype html>
<meta charset="utf-8">
<title>MesaOS memory layout</title>
<style>
  :root {
    --bg: #10121a; --panel: #191d29; --line: #2b3145;
    --text: #e6e8f0; --muted: #8b93ad; --accent: #7aa2ff;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; overflow: hidden;
    background: var(--bg); color: var(--text);
    font: 13px/1.5 ui-sans-serif, -apple-system, "Segoe UI", sans-serif; }
  canvas { display: block; width: 100vw; height: 100vh; cursor: grab; }
  canvas.dragging { cursor: grabbing; }
  .panel { position: fixed; background: var(--panel);
    border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
  #controls { top: 14px; left: 14px; width: 226px; }
  #detail { top: 14px; right: 14px; width: 290px; display: none; }
  #legend { bottom: 14px; left: 14px; max-width: 260px;
    max-height: 44vh; overflow-y: auto; }
  h1 { font-size: 13px; margin: 0 0 2px; letter-spacing: .02em; }
  .sub { color: var(--muted); font-size: 11px; margin-bottom: 10px;
    word-break: break-all; }
  label { display: block; color: var(--muted); font-size: 11px;
    text-transform: uppercase; letter-spacing: .06em; margin: 10px 0 4px; }
  select, button { width: 100%; background: #222738; color: var(--text);
    border: 1px solid var(--line); border-radius: 6px; padding: 5px 7px;
    font: inherit; }
  button { cursor: pointer; margin-top: 8px; }
  button:hover { border-color: var(--accent); }
  .row { display: flex; justify-content: space-between; gap: 10px;
    padding: 3px 0; border-bottom: 1px solid var(--line); font-size: 12px; }
  .row:last-child { border-bottom: 0; }
  .row span:first-child { color: var(--muted); white-space: nowrap; }
  .row span:last-child { text-align: right; word-break: break-all;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .key { display: flex; align-items: center; gap: 7px; padding: 2px 0;
    font-size: 12px; cursor: pointer; }
  .key i { width: 11px; height: 11px; border-radius: 3px; flex: 0 0 auto; }
  .key.off { opacity: .35; }
  .hint { color: var(--muted); font-size: 11px; margin-top: 10px; }
</style>
<canvas id="gl"></canvas>

<div class="panel" id="controls">
  <h1>MesaOS memory layout</h1>
  <div class="sub" id="provenance"></div>
  <label for="mode">Colour by</label>
  <select id="mode"></select>
  <label for="scale">Block height</label>
  <select id="scale">
    <option value="log">Compressed (log) — small regions stay visible</option>
    <option value="linear">True scale — proportional to bytes</option>
    <option value="equal">Equal — one slab per region</option>
  </select>
  <button id="reset">Reset view</button>
  <div class="hint">Drag to orbit · right-drag or shift-drag to pan ·
    scroll to zoom · click a block to inspect it.</div>
</div>

<div class="panel" id="detail"></div>
<div class="panel" id="legend"></div>

<script id="layout" type="application/json">__LAYOUT__</script>
<script>
"use strict";
const LAYOUT = JSON.parse(document.getElementById("layout").textContent);

// ---------------------------------------------------------------------------
// The layout, read through the public columns only. Everything below treats
// the artifact as a consumer would: no MesaOS knowledge, just the contract.
// ---------------------------------------------------------------------------

const col = (name, fallback) => LAYOUT[name] || fallback;
const N = LAYOUT.region_id.length;
const SPACES = LAYOUT.spaces;

const MODES = [
  ["region_kind", "Purpose"], ["region_owner", "Owner"],
  ["region_location", "Location"], ["region_state", "State"],
  ["region_perm", "Permission"], ["region_space", "Address space"],
];
const modes = MODES.filter(([c]) => Array.isArray(LAYOUT[c]));

const regions = [];
for (let i = 0; i < N; i++) {
  regions.push({
    index: i,
    id: LAYOUT.region_id[i],
    space: LAYOUT.region_space[i],
    kind: LAYOUT.region_kind[i],
    name: LAYOUT.region_name[i],
    owner: col("region_owner", [])[i] || "",
    start: LAYOUT.region_start[i],
    length: LAYOUT.region_length[i],
    location: col("region_location", [])[i] || "",
    state: col("region_state", [])[i] || "",
    perm: col("region_perm", [])[i] || "",
  });
}

const edges = (LAYOUT.rel_kind || []).map((kind, i) => ({
  kind, from: LAYOUT.rel_from[i], to: LAYOUT.rel_to[i],
}));
const byId = new Map(regions.map((r) => [r.id, r]));

// ---------------------------------------------------------------------------
// Geometry: one tower per space, regions stacked in address order.
//
// Every tower is normalised to the same height so that spaces whose capacities
// differ by four orders of magnitude can sit side by side and still be read.
// Within a tower the proportions are whatever the scale mode says they are --
// which is why the mode is a control and not a constant: true scale is honest
// about how much of the kernel image is .rodata, and useless for finding the
// 16-byte .limine_requests_end next to it.
// ---------------------------------------------------------------------------

const TOWER_H = 34, TOWER_W = 9, TOWER_D = 9, GAP = 7;
let scaleMode = "log";

function weigh(region) {
  if (scaleMode === "equal") return 1;
  if (scaleMode === "linear") return region.length;
  return Math.log2(region.length + 1);
}

function build() {
  const towers = SPACES.map((id, i) => ({
    id, index: i,
    name: (LAYOUT.space_name || [])[i] || id,
    base: (LAYOUT.space_base_hex || [])[i] || "",
    capacity: (LAYOUT.space_capacity || [])[i] || 0,
    block: (LAYOUT.space_block || [])[i] || 1,
    rows: regions.filter((r) => r.space === id)
                 .sort((a, b) => a.start - b.start),
  }));
  const span = towers.length * TOWER_W + (towers.length - 1) * GAP;
  towers.forEach((tower, i) => {
    tower.x = -span / 2 + TOWER_W / 2 + i * (TOWER_W + GAP);
    const total = tower.rows.reduce((sum, r) => sum + weigh(r), 0) || 1;
    let y = 0;
    for (const region of tower.rows) {
      const h = Math.max((weigh(region) / total) * TOWER_H, 0.06);
      region.box = { x: tower.x, y: y + h / 2, z: 0,
                     w: TOWER_W, h, d: TOWER_D };
      region.tower = tower;
      y += h;
    }
    tower.height = y;
  });
  return towers;
}

// ---------------------------------------------------------------------------
// Colour. One meaning at a time, per the research note: the mode decides what
// colour means, and selection adds an outline rather than changing the colour.
// ---------------------------------------------------------------------------

const PALETTE = [
  [0.48, 0.64, 1.00], [0.98, 0.75, 0.36], [0.45, 0.83, 0.62],
  [0.93, 0.51, 0.56], [0.71, 0.58, 0.96], [0.40, 0.82, 0.87],
  [0.95, 0.64, 0.42], [0.62, 0.75, 0.42], [0.88, 0.55, 0.78],
  [0.55, 0.60, 0.78], [0.80, 0.80, 0.52], [0.50, 0.72, 0.94],
];
const NEUTRAL = [0.30, 0.33, 0.42];

let mode = modes[0][0];
let keys = [], colorOf = new Map(), hidden = new Set();

function classify() {
  const values = [...new Set(regions.map((r) => String(LAYOUT[mode][r.index] ?? "")))]
    .sort((a, b) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)));
  keys = values;
  colorOf = new Map(values.map((v, i) =>
    [v, v === "" ? NEUTRAL : PALETTE[i % PALETTE.length]]));
}

const valueOf = (region) => String(LAYOUT[mode][region.index] ?? "");

// ---------------------------------------------------------------------------
// WebGL. Two passes over the same boxes: one shaded, one flat-coloured by a
// per-region id so a click can be resolved by reading back a single pixel.
// ---------------------------------------------------------------------------

const canvas = document.getElementById("gl");
const gl = canvas.getContext("webgl", { antialias: true, preserveDrawingBuffer: true });
if (!gl) document.body.innerHTML =
  "<p style='padding:2rem'>This page needs WebGL.</p>";

function shader(type, source) {
  const s = gl.createShader(type);
  gl.shaderSource(s, source); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
    throw new Error(gl.getShaderInfoLog(s));
  return s;
}
function program(vs, fs) {
  const p = gl.createProgram();
  gl.attachShader(p, shader(gl.VERTEX_SHADER, vs));
  gl.attachShader(p, shader(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS))
    throw new Error(gl.getProgramInfoLog(p));
  return p;
}

const solid = program(`
  attribute vec3 position, normal, colour;
  uniform mat4 mvp; varying vec3 vC; varying vec3 vN;
  void main() { vC = colour; vN = normal; gl_Position = mvp * vec4(position, 1.0); }`, `
  precision mediump float; varying vec3 vC; varying vec3 vN;
  void main() {
    float light = 0.55 + 0.45 * max(dot(normalize(vN),
      normalize(vec3(0.45, 0.82, 0.36))), 0.0);
    gl_FragColor = vec4(vC * light, 1.0);
  }`);

const flat = program(`
  attribute vec3 position, colour;
  uniform mat4 mvp; varying vec3 vC;
  void main() { vC = colour; gl_Position = mvp * vec4(position, 1.0); }`, `
  precision mediump float; varying vec3 vC;
  void main() { gl_FragColor = vec4(vC, 1.0); }`);

const CUBE = [
  // face vertices (x, y, z as +/- half extents) and the face normal
  [[-1,-1, 1], [ 1,-1, 1], [ 1, 1, 1], [-1, 1, 1], [ 0, 0, 1]],
  [[ 1,-1,-1], [-1,-1,-1], [-1, 1,-1], [ 1, 1,-1], [ 0, 0,-1]],
  [[-1, 1, 1], [ 1, 1, 1], [ 1, 1,-1], [-1, 1,-1], [ 0, 1, 0]],
  [[-1,-1,-1], [ 1,-1,-1], [ 1,-1, 1], [-1,-1, 1], [ 0,-1, 0]],
  [[ 1,-1, 1], [ 1,-1,-1], [ 1, 1,-1], [ 1, 1, 1], [ 1, 0, 0]],
  [[-1,-1,-1], [-1,-1, 1], [-1, 1, 1], [-1, 1,-1], [-1, 0, 0]],
];

const buffers = {
  position: gl.createBuffer(), normal: gl.createBuffer(),
  colour: gl.createBuffer(), pick: gl.createBuffer(),
  edgeLine: gl.createBuffer(), edgeColour: gl.createBuffer(),
  outline: gl.createBuffer(),
};
let vertexCount = 0, edgeCount = 0, outlineCount = 0;
let towers = [], selected = null;

const idColour = (i) => [((i + 1) & 255) / 255,
                         (((i + 1) >> 8) & 255) / 255,
                         (((i + 1) >> 16) & 255) / 255];

function upload() {
  const position = [], normal = [], colour = [], pick = [];
  vertexCount = 0;
  regions.forEach((region) => {
    if (hidden.has(valueOf(region))) return;
    const { x, y, z, w, h, d } = region.box;
    const c = colorOf.get(valueOf(region)) || NEUTRAL;
    const p = idColour(region.index);
    for (const face of CUBE) {
      const [a, b, cc, dd, n] = face;
      for (const v of [a, b, cc, a, cc, dd]) {
        position.push(x + v[0] * w / 2, y + v[1] * h / 2, z + v[2] * d / 2);
        normal.push(n[0], n[1], n[2]);
        colour.push(c[0], c[1], c[2]);
        pick.push(p[0], p[1], p[2]);
        vertexCount++;
      }
    }
  });
  const put = (buffer, data) => {
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW);
  };
  put(buffers.position, position); put(buffers.normal, normal);
  put(buffers.colour, colour); put(buffers.pick, pick);
  uploadEdges(); uploadOutline();
}

function uploadEdges() {
  // Relationships are drawn only for the selected region: all 30-odd at once
  // is a ball of wool, and the point of the edge table is to answer "what
  // explains this one thing?".
  const line = [], colour = [];
  if (selected) {
    for (const edge of edges) {
      if (edge.from !== selected.id && edge.to !== selected.id) continue;
      const a = byId.get(edge.from), b = byId.get(edge.to);
      if (!a || !b || !a.box || !b.box) continue;
      if (hidden.has(valueOf(a)) || hidden.has(valueOf(b))) continue;
      line.push(a.box.x, a.box.y, a.box.z, b.box.x, b.box.y, b.box.z);
      const c = edge.kind === "loads-to" ? [1.0, 0.82, 0.35]
              : edge.kind === "embeds" ? [0.55, 0.92, 0.75]
              : [0.62, 0.72, 1.0];
      colour.push(...c, ...c);
    }
  }
  edgeCount = line.length / 3;
  gl.bindBuffer(gl.ARRAY_BUFFER, buffers.edgeLine);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(line), gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER, buffers.edgeColour);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(colour), gl.STATIC_DRAW);
}

function uploadOutline() {
  const line = [];
  if (selected && selected.box) {
    const { x, y, z, w, h, d } = selected.box;
    const X = w / 2 + 0.05, Y = h / 2 + 0.02, Z = d / 2 + 0.05;
    const corner = (i, j, k) => [x + i * X, y + j * Y, z + k * Z];
    const E = [[-1,-1,-1],[1,-1,-1],[1,-1,1],[-1,-1,1],
               [-1,1,-1],[1,1,-1],[1,1,1],[-1,1,1]];
    const pairs = [[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],
                   [0,4],[1,5],[2,6],[3,7]];
    for (const [a, b] of pairs)
      line.push(...corner(...E[a]), ...corner(...E[b]));
  }
  outlineCount = line.length / 3;
  gl.bindBuffer(gl.ARRAY_BUFFER, buffers.outline);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(line), gl.STATIC_DRAW);
}

// --- camera -----------------------------------------------------------------

const HOME = { yaw: -0.6, pitch: 0.45, distance: 78, target: [0, TOWER_H / 2, 0] };
let cam = { ...HOME, target: [...HOME.target] };

function matrix() {
  const { yaw, pitch, distance, target } = cam;
  const eye = [
    target[0] + distance * Math.cos(pitch) * Math.sin(yaw),
    target[1] + distance * Math.sin(pitch),
    target[2] + distance * Math.cos(pitch) * Math.cos(yaw),
  ];
  const f = norm(sub(target, eye));
  const s = norm(cross(f, [0, 1, 0]));
  const u = cross(s, f);
  const view = [
    s[0], u[0], -f[0], 0, s[1], u[1], -f[1], 0, s[2], u[2], -f[2], 0,
    -dot(s, eye), -dot(u, eye), dot(f, eye), 1,
  ];
  const aspect = canvas.width / canvas.height;
  const t = 1 / Math.tan(0.55 / 2), near = 0.5, far = 800;
  const proj = [t / aspect, 0, 0, 0, 0, t, 0, 0, 0, 0,
                (far + near) / (near - far), -1, 0, 0,
                2 * far * near / (near - far), 0];
  return multiply(proj, view);
}
const sub = (a, b) => [a[0]-b[0], a[1]-b[1], a[2]-b[2]];
const dot = (a, b) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2],
                         a[0]*b[1]-a[1]*b[0]];
const norm = (a) => { const l = Math.hypot(...a) || 1;
  return [a[0]/l, a[1]/l, a[2]/l]; };
function multiply(a, b) {
  const out = new Float32Array(16);
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
    let sum = 0;
    for (let k = 0; k < 4; k++) sum += a[k * 4 + j] * b[i * 4 + k];
    out[i * 4 + j] = sum;
  }
  return out;
}

// --- drawing ----------------------------------------------------------------

function bind(prog, name, buffer, size) {
  const loc = gl.getAttribLocation(prog, name);
  if (loc < 0) return;
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
}

function draw(picking) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = canvas.clientWidth * dpr;
  canvas.height = canvas.clientHeight * dpr;
  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.enable(gl.DEPTH_TEST);
  gl.clearColor(...(picking ? [0, 0, 0, 1] : [0.063, 0.071, 0.102, 1]));
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

  const mvp = matrix();
  const prog = picking ? flat : solid;
  gl.useProgram(prog);
  gl.uniformMatrix4fv(gl.getUniformLocation(prog, "mvp"), false, mvp);
  bind(prog, "position", buffers.position, 3);
  bind(prog, "colour", picking ? buffers.pick : buffers.colour, 3);
  if (!picking) bind(prog, "normal", buffers.normal, 3);
  gl.drawArrays(gl.TRIANGLES, 0, vertexCount);

  if (picking) return;
  gl.useProgram(flat);
  gl.uniformMatrix4fv(gl.getUniformLocation(flat, "mvp"), false, mvp);
  if (outlineCount) {
    bind(flat, "position", buffers.outline, 3);
    gl.disableVertexAttribArray(gl.getAttribLocation(flat, "colour"));
    gl.vertexAttrib3f(gl.getAttribLocation(flat, "colour"), 1, 1, 1);
    gl.drawArrays(gl.LINES, 0, outlineCount);
  }
  if (edgeCount) {
    bind(flat, "position", buffers.edgeLine, 3);
    bind(flat, "colour", buffers.edgeColour, 3);
    gl.drawArrays(gl.LINES, 0, edgeCount);
  }
}

function pick(x, y) {
  draw(true);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const px = new Uint8Array(4);
  gl.readPixels(Math.round(x * dpr), Math.round((canvas.clientHeight - y) * dpr),
                1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
  const index = px[0] + (px[1] << 8) + (px[2] << 16) - 1;
  draw(false);
  return index >= 0 && index < regions.length ? regions[index] : null;
}

// --- interaction ------------------------------------------------------------

let drag = null;
canvas.addEventListener("pointerdown", (e) => {
  drag = { x: e.clientX, y: e.clientY, moved: 0,
           pan: e.button === 2 || e.shiftKey };
  canvas.setPointerCapture(e.pointerId);
  canvas.classList.add("dragging");
});
canvas.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  drag.x = e.clientX; drag.y = e.clientY;
  drag.moved += Math.abs(dx) + Math.abs(dy);
  if (drag.pan) {
    const k = cam.distance * 0.0016;
    cam.target[0] -= (dx * Math.cos(cam.yaw)) * k;
    cam.target[2] += (dx * Math.sin(cam.yaw)) * k;
    cam.target[1] += dy * k;
  } else {
    cam.yaw -= dx * 0.006;
    cam.pitch = Math.max(-1.45, Math.min(1.45, cam.pitch + dy * 0.006));
  }
  draw(false);
});
canvas.addEventListener("pointerup", (e) => {
  const wasClick = drag && drag.moved < 5;
  drag = null;
  canvas.classList.remove("dragging");
  if (!wasClick) return;
  const rect = canvas.getBoundingClientRect();
  select(pick(e.clientX - rect.left, e.clientY - rect.top));
});
canvas.addEventListener("contextmenu", (e) => e.preventDefault());
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  cam.distance = Math.max(8, Math.min(400,
    cam.distance * (1 + Math.sign(e.deltaY) * 0.09)));
  draw(false);
}, { passive: false });

// --- panels -----------------------------------------------------------------

const bytes = (n) => n >= 1 << 20 ? (n / (1 << 20)).toFixed(2) + " MiB"
                   : n >= 1024 ? (n / 1024).toFixed(2) + " KiB"
                   : n + " B";
const hex = (n) => "0x" + n.toString(16).padStart(8, "0");
const escape = (s) => String(s).replace(/[&<>]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

function select(region) {
  selected = region;
  uploadEdges(); uploadOutline();
  const panel = document.getElementById("detail");
  if (!region) { panel.style.display = "none"; draw(false); return; }

  const tower = region.tower;
  const absolute = tower.base
    ? "0x" + (BigInt(tower.base) + BigInt(region.start)).toString(16)
    : hex(region.start);
  const rows = [
    ["space", tower.name], ["purpose", region.kind],
    ["owner", region.owner || "--"], ["state", region.state || "--"],
    ["location", region.location || "--"], ["mapped", region.perm || "not mapped"],
    ["address", absolute],
    ["offset", hex(region.start) + " .. " + hex(region.start + region.length)],
    ["size", bytes(region.length) + " (" + region.length + ")"],
    ["blocks", Math.ceil(region.length / tower.block) + " x " + bytes(tower.block)],
    ["region id", region.id],
  ];
  const related = edges
    .filter((e) => e.from === region.id || e.to === region.id)
    .map((e) => {
      const other = byId.get(e.from === region.id ? e.to : e.from);
      const arrow = e.from === region.id ? "→" : "←";
      return `<div class="row"><span>${escape(e.kind)}</span>` +
             `<span>${arrow} ${escape(other ? other.name : "?")}</span></div>`;
    }).join("");

  panel.innerHTML =
    `<h1>${escape(region.name)}</h1><div class="sub">${escape(tower.id)}</div>` +
    rows.map(([k, v]) =>
      `<div class="row"><span>${k}</span><span>${escape(v)}</span></div>`).join("") +
    (related ? `<label>Relationships</label>${related}` : "");
  panel.style.display = "block";
  draw(false);
}

function renderLegend() {
  const label = modes.find(([c]) => c === mode)[1];
  const counts = new Map();
  for (const region of regions) {
    const v = valueOf(region);
    counts.set(v, (counts.get(v) || 0) + 1);
  }
  document.getElementById("legend").innerHTML =
    `<h1>${label}</h1><div class="sub">click a key to hide it</div>` +
    keys.map((k) => {
      const c = colorOf.get(k).map((v) => Math.round(v * 255)).join(",");
      return `<div class="key ${hidden.has(k) ? "off" : ""}" data-key="${escape(k)}">` +
             `<i style="background:rgb(${c})"></i>` +
             `<span>${escape(k || "(none)")}</span>` +
             `<span style="margin-left:auto;color:var(--muted)">${counts.get(k)}</span></div>`;
    }).join("");
  document.querySelectorAll("#legend .key").forEach((el) => {
    el.onclick = () => {
      const k = el.dataset.key;
      hidden.has(k) ? hidden.delete(k) : hidden.add(k);
      if (selected && hidden.has(valueOf(selected))) select(null);
      upload(); renderLegend(); draw(false);
    };
  });
}

function refresh() {
  towers = build();
  classify();
  hidden = new Set([...hidden].filter((k) => keys.includes(k)));
  upload(); renderLegend(); draw(false);
}

const modeSelect = document.getElementById("mode");
modeSelect.innerHTML = modes.map(([c, label]) =>
  `<option value="${c}">${label}</option>`).join("");
modeSelect.onchange = () => { mode = modeSelect.value; hidden.clear(); refresh(); };
document.getElementById("scale").onchange = (e) => {
  scaleMode = e.target.value;
  towers = build();
  if (selected) select(selected);
  upload(); draw(false);
};
document.getElementById("reset").onclick = () => {
  cam = { ...HOME, target: [...HOME.target] };
  select(null);
};
const p = LAYOUT.provenance || {};
document.getElementById("provenance").textContent =
  `${p.producer || "?"} @ ${p.revision || "?"} · ${N} regions · ` +
  `${SPACES.length} spaces`;

window.addEventListener("resize", () => draw(false));
refresh();
</script>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("artifact", type=Path, nargs="?",
                        default=ROOT / "build" / "memory-layout.json")
    parser.add_argument("-o", "--output", type=Path,
                        default=ROOT / "build" / "memory-layout.html")
    parser.add_argument("--open", action="store_true",
                        help="open the page in the default browser")
    args = parser.parse_args()

    if not args.artifact.exists():
        print(f"memory-layout-preview: no artifact at {args.artifact}; "
              f"run scripts/memory-layout.py first", file=sys.stderr)
        return 1

    document = json.loads(args.artifact.read_text())
    # The artifact is embedded in a <script type="application/json"> block, so
    # the only sequence that could end it early is a literal "</script>".
    payload = json.dumps(document).replace("</", "<\\/")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(PAGE.replace("__LAYOUT__", payload))

    print(f"memory-layout-preview: {args.output}")
    print(f"  {len(document['region_id'])} regions, "
          f"{len(document['spaces'])} spaces, "
          f"{len(document.get('rel_kind', []))} edges")
    if args.open:
        import webbrowser
        webbrowser.open(args.output.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
