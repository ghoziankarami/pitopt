import { S, notify } from "../store.js";
import { A } from "../actions.js";
import { fmt, esc, api, qs, toast } from "../util.js";
import { drawPlan, section } from "../charts.js";
import { pageHead, empty } from "./common.js";

const ui = { layers: new Set(["topo", "face"]), pb: 0, period: 1, playing: null, line: null, sec: null, secBusy: false, plotly: null };

function loadPlotly() {
  if (window.Plotly) return Promise.resolve(window.Plotly);
  return (ui.plotly ||= new Promise((ok, no) => {
    const s = document.createElement("script"); s.src = "/static/vendor/plotly.min.js";
    s.onload = () => ok(window.Plotly); s.onerror = () => no(new Error("Plotly gagal dimuat")); document.head.appendChild(s);
  }));
}

export function render() {
  const r = S.results;
  if (!r) return empty("3D & Penampang");
  const nPb = r.pushbacks.rows.length, nPer = r.schedule.plan.length;
  const chk = (k, label) => `<label class="chk"><input type="checkbox" data-act="l3" data-k="${k}" ${ui.layers.has(k) ? "checked" : ""}> ${label}</label>`;
  const ves = [1, 2, 3, 5, 10].map((v) => `<button data-act="ve" data-v="${v}" class="${S.ve === v ? "on" : ""}">${v}×</button>`).join("");
  return `<div class="page">${pageHead("3D & Penampang", "surface pit, face position, pushback, dan posisi akhir periode", `<div class="tabs">${ves}</div>`)}
  <div class="card"><div class="row" style="flex-wrap:wrap;gap:16px">${chk("topo", "Topografi")}${chk("bowl", "Pit shell (mangkok)")}${chk("face", "Face position")}${chk("pb", "Pushback")}${chk("period", "Akhir periode")}
    ${ui.layers.has("pb") ? `<select data-on="pbSel"><option value="0">semua pushback</option>${Array.from({ length: nPb }, (_, i) => `<option value="${i + 1}" ${ui.pb === i + 1 ? "selected" : ""}>PB${i + 1}</option>`).join("")}</select>` : ""}
    ${ui.layers.has("period") ? `<span class="row" style="gap:8px"><button class="btn" data-act="play">${ui.playing ? "Berhenti" : "Putar"}</button><input type="range" min="1" max="${nPer}" value="${ui.period}" data-input="perSel"><b class="num">P${ui.period}</b></span>` : ""}
    <span class="grow"></span><span class="ve">VE ${S.ve}×</span></div></div>
  <div class="card" style="margin-top:16px;padding:0"><div id="plot3d" style="height:560px"></div></div>
  <div class="split" style="margin-top:16px"><div class="card"><div class="cardhead"><h2>Garis penampang</h2></div><p class="howto">Klik dua titik pada plan view untuk menarik garis penampang.</p><canvas id="secplan" class="plan" style="cursor:crosshair"></canvas></div>
   <div style="display:flex;flex-direction:column;gap:16px"><div class="card"><div class="cardhead"><h2>Penampang 1:1</h2></div><div id="sec1">${ui.sec ? section(ui.sec, { ve: 1, layers: secLayers(), title: "Penampang 1:1" }) : `<div class="empty">Belum ada garis.</div>`}</div></div>
   <div class="card"><div class="cardhead"><h2>Penampang VE ${S.ve}×</h2></div><div id="secv">${ui.sec ? section(ui.sec, { ve: S.ve, layers: secLayers(), title: "Penampang VE" }) : `<div class="empty">Belum ada garis.</div>`}</div></div></div></div></div>`;
}
const secLayers = () => ["face", ...(ui.layers.has("bowl") ? ["bowl"] : [])];

const T = (m) => m[0].map((_, j) => m.map((row) => row[j]));
async function plot(root) {
  const el = root.querySelector("#plot3d"); const g = S.results.grids3d; if (!el || !g) return;
  const P = await loadPlotly();
  const surf = (z, color, name, opacity = 1) => ({ type: "surface", x: g.x, y: g.y, z: T(z), name, showscale: false, opacity, colorscale: [[0, color], [1, color]], hoverinfo: "name+z", lighting: { ambient: 0.65, diffuse: 0.6 } });
  const data = [];
  if (ui.layers.has("topo")) data.push(surf(g.topo, "#6B7A3A", "Topografi", 0.9));
  if (ui.layers.has("bowl")) data.push(surf(g.layers.bowl, "#B8A37A", "Pit shell"));
  if (ui.layers.has("face")) data.push(surf(g.layers.face, "#8A6A3B", "Face position"));
  if (ui.layers.has("pb")) { const n = S.results.pushbacks.rows.length; for (let i = 1; i <= n; i++) if (!ui.pb || ui.pb === i) { const t = n <= 1 ? 0.5 : (i - 1) / (n - 1); data.push(surf(g.layers[`pushback_${i}`], vir(t), `PB${i}`)); } }
  if (ui.layers.has("period")) data.push(surf(g.layers[`period_${ui.period}`], vir((ui.period - 1) / Math.max(1, S.results.schedule.plan.length - 1)), `Akhir P${ui.period}`));
  const dark = document.documentElement.dataset.theme === "dark";
  const xr = g.x[g.x.length - 1] - g.x[0], yr = g.y[g.y.length - 1] - g.y[0], zs = g.topo.flat().filter((v) => v != null);
  const zr = Math.max(...zs) - Math.min(...zs) || 1;
  const layout = { margin: { l: 0, r: 0, t: 0, b: 0 }, paper_bgcolor: "rgba(0,0,0,0)", font: { color: dark ? "#ddd" : "#14181D" },
    scene: { aspectmode: "manual", aspectratio: { x: 1, y: yr / xr, z: (zr / xr) * S.ve }, xaxis: { title: "E" }, yaxis: { title: "N" }, zaxis: { title: "RL" }, camera: ui.cam || undefined }, showlegend: false };
  await P.react(el, data, layout, { responsive: true, displaylogo: false });
  el.on?.("plotly_relayout", (e) => { if (e["scene.camera"]) ui.cam = e["scene.camera"]; });
}
const vir = (t) => { const c = ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"], x = t * (c.length - 1), i = Math.min(c.length - 2, Math.floor(x)); return t <= 0 ? c[0] : t >= 1 ? c[4] : c[i]; };

export function mount(root) {
  const r = S.results; if (!r) return;
  plot(root).catch((e) => toast(e.message));
  const canvas = root.querySelector("#secplan"); if (!canvas) return;
  const pv = r.plan_view, sc = drawPlan(canvas, pv, "depth", 1, { maxWidth: 560 });
  if (ui.line) { const g = canvas.getContext("2d"); g.strokeStyle = "#B3261E"; g.lineWidth = 2; g.beginPath(); g.moveTo(...ui.line[0]); if (ui.line[1]) g.lineTo(...ui.line[1]); g.stroke(); }
  canvas.onclick = async (e) => {
    const b = canvas.getBoundingClientRect(), px = ((e.clientX - b.left) / b.width) * canvas.width, py = ((e.clientY - b.top) / b.height) * canvas.height;
    if (!ui.line || ui.line.length === 2) ui.line = [[px, py]]; else ui.line.push([px, py]);
    if (ui.line.length < 2) return notify();
    const xy = ui.line.map(([x, y]) => [pv.x0 + (x / sc) * pv.dx, pv.y0 + (pv.ny - y / sc) * pv.dy]);
    try { ui.sec = await api(`/api/section?${qs({ project: S.project, scenario: S.scenario, x1: xy[0][0], y1: xy[0][1], x2: xy[1][0], y2: xy[1][1], layers: secLayers().join(",") })}`); } catch (err) { toast(err.message); }
    notify();
  };
}
export function unmount() { clearInterval(ui.playing); ui.playing = null; }

A.l3 = (el) => { el.checked ? ui.layers.add(el.dataset.k) : ui.layers.delete(el.dataset.k); notify(); };
A.ve = (el) => { S.ve = +el.dataset.v; localStorage.setItem("pitopt-ve", S.ve); notify(); };
A.pbSel = (el) => { ui.pb = +el.value; notify(); };
A.perSel = (el) => { ui.period = +el.value; document.querySelector(".page b.num").textContent = `P${ui.period}`; plot(document.getElementById("app")); };
A.play = () => {
  if (ui.playing) { clearInterval(ui.playing); ui.playing = null; return notify(); }
  const n = S.results.schedule.plan.length;
  ui.playing = setInterval(() => { ui.period = ui.period % n + 1; const root = document.getElementById("app"); root.querySelector("input[type=range]").value = ui.period; root.querySelector(".page b.num").textContent = `P${ui.period}`; plot(root); }, 900);
  notify();
};
