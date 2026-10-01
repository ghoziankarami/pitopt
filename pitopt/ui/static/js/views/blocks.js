// Block model viewer: plan slices per bench and E-W / N-S sections, coloured by any attribute.
import { S, notify } from "../store.js";
import { A } from "../actions.js";
import { fmt, fmtInt, esc, api, qs, viridis, toast } from "../util.js";
import { t } from "../i18n.js";
import { pageHead, empty } from "./common.js";

const st = { meta: null, key: "", attr: null, axis: "z", index: 0, slice: null, busy: false, playing: null, err: null };
const PALETTE = ["#2B4C8C", "#B36B00", "#1E6B48", "#8A3B6B", "#4A8FA8", "#A89B3B", "#7A4A00", "#6B7A3A", "#B3261E", "#56606C"];

async function ensureMeta() {
  const key = `${S.project}/${S.scenario}`;
  if (st.key === key && st.meta) return;
  st.key = key; st.meta = null; st.slice = null; st.err = null;
  try {
    st.meta = await api(`/api/blockmeta?${qs({ project: S.project, scenario: S.scenario })}`);
    const pref = st.meta.attrs.find((a) => a.type === "numeric") || st.meta.attrs[0];
    st.attr = pref.key; st.axis = "z"; st.index = Math.floor(st.meta.nz / 2);
  } catch (e) { st.err = e.message; }
  notify();
}
const size = () => (st.axis === "z" ? st.meta.nz : st.axis === "y" ? st.meta.ny : st.meta.nx);
async function loadSlice() {
  if (!st.meta) return;
  try { st.slice = await api(`/api/blockslice?${qs({ project: S.project, scenario: S.scenario, axis: st.axis, index: st.index, attr: st.attr })}`); st.err = null; }
  catch (e) { st.err = e.message; }
  drawSlice();
}
const attrMeta = () => st.meta.attrs.find((a) => a.key === st.attr);

export function render() {
  if (!S.results) return empty("Model Blok");
  if (st.err && !st.meta) return `<div class="page">${pageHead("Model Blok", "")}<div class="card"><div class="empty">${esc(st.err)}</div></div></div>`;
  if (!st.meta) { ensureMeta(); return `<div class="page">${pageHead("Model Blok", "memuat model blok…")}</div>`; }
  const m = st.meta, a = attrMeta(), n = size();
  const axisTabs = [["z", "Plan per bench"], ["y", "Penampang E–W"], ["x", "Penampang N–S"]].map(([k, l]) => `<button data-act="bAxis" data-v="${k}" class="${st.axis === k ? "on" : ""}">${l}</button>`).join("");
  const attrOpts = m.attrs.map((x) => `<option value="${x.key}" ${x.key === st.attr ? "selected" : ""}>${esc(x.label)}</option>`).join("");
  const where = st.slice && st.slice.coord != null
    ? (st.axis === "z" ? `RL ${fmt(st.slice.coord, 1)} m` : st.axis === "y" ? `Northing ${fmt(st.slice.coord, 0)}` : `Easting ${fmt(st.slice.coord, 0)}`) : "";
  return `<div class="page">${pageHead("Model Blok", `${fmtInt(m.blocks)} blok · ${m.nx}×${m.ny}×${m.nz} · ${fmt(m.dx, 0)}×${fmt(m.dy, 0)}×${fmt(m.dz, 0)} m — data hasil run, bukan model mentah`, `<div class="tabs">${axisTabs}</div>`)}
  <div class="card"><div class="row" style="flex-wrap:wrap;gap:16px">
    <div class="field"><label>Warnai dengan</label><select data-on="bAttr">${attrOpts}</select></div>
    <div class="row grow" style="gap:10px;min-width:260px"><button class="btn" data-act="bStep" data-d="-1">◀</button><input type="range" min="0" max="${n - 1}" value="${st.index}" data-input="bIndex" style="flex:1"><button class="btn" data-act="bStep" data-d="1">▶</button>
      <b class="num" id="bwhere" style="min-width:150px">${st.axis === "z" ? "Bench" : "Irisan"} ${st.index + 1}/${n} ${where ? "· " + where : ""}</b><button class="btn" data-act="bPlay">${st.playing ? "Berhenti" : "Putar"}</button></div></div>
    ${st.axis !== "z" ? `<div class="row small muted" style="margin-top:8px;gap:6px">Skala vertikal: ${[1, 2, 3, 5].map((v) => `<button class="btn ${S.ve === v ? "primary" : ""}" data-act="ve" data-v="${v}">${v}×</button>`).join("")}</div>` : ""}</div>
  <div class="card" style="margin-top:16px"><div class="row" style="align-items:flex-start;gap:20px;flex-wrap:wrap">
    <div style="flex:1;min-width:0;overflow:auto"><canvas id="bcanvas" class="plan" style="cursor:crosshair"></canvas><div id="bhover" class="num small muted" style="height:20px;margin-top:6px"></div></div>
    <div style="width:220px">${legend(a)}<p class="xs muted" style="margin-top:14px">Skala warna memakai rentang seluruh model, bukan hanya irisan ini, sehingga warna sebanding antar irisan.</p>
      ${st.slice ? `<p class="xs muted">${fmtInt(st.slice.count)} blok di irisan ini.</p>` : ""}${st.err ? `<p class="small bad">${esc(st.err)}</p>` : ""}</div></div></div></div>`;
}

function legend(a) {
  if (a.type === "numeric") return `<div class="navh" style="padding:0 0 6px">${esc(a.label)}</div><div style="height:12px;border-radius:3px;background:linear-gradient(90deg,${[0, .25, .5, .75, 1].map((t) => viridis(t)).join(",")})"></div><div class="row num xs"><span>${fmt(a.min, 2)}</span><span class="grow"></span><span>${fmt(a.max, 2)}</span></div>`;
  const items = a.type === "category" ? a.values.map((v, i) => [v, PALETTE[i % PALETTE.length]]) : [["Tidak ada (0)", "#C9CED4"], ...Array.from({ length: a.max }, (_, i) => [`${a.label} ${i + 1}`, viridis(a.max <= 1 ? 0.5 : i / (a.max - 1))])];
  return `<div class="navh" style="padding:0 0 6px">${esc(a.label)}</div>${items.slice(0, 40).map(([l, c]) => `<div class="row small" style="gap:8px;padding:2px 0"><i style="display:inline-block;width:12px;height:12px;border-radius:2px;background:${c}"></i>${esc(l)}</div>`).join("")}`;
}

function colour(a, v) {
  if (v == null) return null;
  if (a.type === "numeric") return viridis(a.max > a.min ? (v - a.min) / (a.max - a.min) : 0.5);
  if (a.type === "category") return PALETTE[v % PALETTE.length];
  return v === 0 ? "#C9CED4" : viridis(a.max <= 1 ? 0.5 : (v - 1) / (a.max - 1));
}
const label = (a, v) => (v == null ? "tidak ada blok" : a.type === "numeric" ? fmt(v, 3) : a.type === "category" ? a.values[v] : v === 0 ? "tidak ada" : `${a.label} ${v}`);

function drawSlice() {
  const canvas = document.getElementById("bcanvas");
  if (!canvas || !st.slice) return;
  const s = st.slice, a = attrMeta(), m = st.meta;
  const sx = { z: m.dx, y: m.dx, x: m.dy }[st.axis], sy = st.axis === "z" ? m.dy : m.dz * S.ve;
  const box = canvas.parentElement.clientWidth || 700;
  const cw = Math.max(2, Math.min(14, Math.floor(box / s.w))), ch = Math.max(1, Math.round((cw * sy) / sx));
  canvas.width = s.w * cw; canvas.height = s.h * ch;
  const g = canvas.getContext("2d");
  g.fillStyle = document.documentElement.dataset.theme === "dark" ? "#12171C" : "#F7F8FA"; g.fillRect(0, 0, canvas.width, canvas.height);
  for (let r = 0; r < s.h; r++) for (let c = 0; c < s.w; c++) {
    const col = colour(a, s.cells[r * s.w + c]);
    if (col) { g.fillStyle = col; g.fillRect(c * cw, r * ch, cw, ch); }
  }
  canvas.onmousemove = (e) => {
    const b = canvas.getBoundingClientRect(), c = Math.floor(((e.clientX - b.left) / b.width) * s.w), r = Math.floor(((e.clientY - b.top) / b.height) * s.h);
    const v = s.cells[r * s.w + c], el = document.getElementById("bhover");
    if (!el || c < 0 || r < 0 || c >= s.w || r >= s.h) return;
    const pos = st.axis === "z" ? `E ${fmt(m.x0 + c * m.dx, 0)} · N ${fmt(m.y0 + (s.h - 1 - r) * m.dy, 0)}` : st.axis === "y" ? `E ${fmt(m.x0 + c * m.dx, 0)} · RL ${fmt(m.ztop - r * m.dz, 1)}` : `N ${fmt(m.y0 + c * m.dy, 0)} · RL ${fmt(m.ztop - r * m.dz, 1)}`;
    el.textContent = `${pos} — ${t(a.label)}: ${t(label(a, v))}`;
  };
  const where = document.getElementById("bwhere");
  if (where) where.textContent = `${t(st.axis === "z" ? "Bench" : "Irisan")} ${st.index + 1}/${size()} ${s.coord != null ? "· " + (st.axis === "z" ? `RL ${fmt(s.coord, 1)} m` : st.axis === "y" ? `Northing ${fmt(s.coord, 0)}` : `Easting ${fmt(s.coord, 0)}`) : ""}`;
}

export function mount() { if (st.meta) loadSlice(); else ensureMeta(); }
export function unmount() { clearInterval(st.playing); st.playing = null; }

let pending;
const reload = () => { clearTimeout(pending); pending = setTimeout(loadSlice, 60); };
A.bAxis = (el) => { st.axis = el.dataset.v; st.index = Math.min(st.index, size() - 1); st.index = Math.floor(size() / 2); notify(); };
A.bAttr = (el) => { st.attr = el.value; notify(); };
A.bIndex = (el) => { st.index = +el.value; reload(); };
A.bStep = (el) => { st.index = Math.max(0, Math.min(size() - 1, st.index + +el.dataset.d)); const r = document.querySelector('input[data-input="bIndex"]'); if (r) r.value = st.index; reload(); };
A.bPlay = () => {
  if (st.playing) { clearInterval(st.playing); st.playing = null; return notify(); }
  st.playing = setInterval(() => { st.index = (st.index + 1) % size(); const r = document.querySelector('input[data-input="bIndex"]'); if (r) r.value = st.index; loadSlice(); }, 500);
  notify();
};
