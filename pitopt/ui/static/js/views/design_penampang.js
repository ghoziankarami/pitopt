// 06 · Penampang — a section along a line drawn on the plan, at 1:1 and at an exaggerated scale side by side.
import { esc, fmt } from "../util.js";
import { D, ensure, loadSection } from "../design/core.js";
import { gate, legend, notice, page } from "../design/ui.js";
import { paintPlan } from "../design/planview.js";
import { drawSection } from "../design/section.js";
import { classColour } from "../design/plan.js";
import { A } from "../actions.js";

let view = null, drag = null;

export function render() {
  ensure();
  const g = gate("Penampang 1:1", { needResult: true });
  if (g) return g;
  const doc = D.result.document, sec = D.section;
  return page("Penampang 1:1", "Setiap tampilan 3D dan penampang menampilkan VE. Penampang default selalu tampil 1:1 berdampingan dengan versi eksagerasi.",
    `<button class="btn" data-act="dResetLine">Reset garis</button>`, `
  ${notice()}
  <div class="dd-sec">
    <div class="card"><div class="cardhead"><h2>Garis penampang</h2></div>
      <canvas id="dplan" class="plan" style="height:300px;cursor:crosshair"></canvas>
      <p class="xs muted" style="margin:8px 0 12px">Seret di plan view untuk menarik garis A–A′; penampang mengikuti. ${sec ? `Panjang <b class="num">${fmt(sec.length, 0)} m</b>.` : ""}</p>
      <div class="navh" style="padding:0 0 6px">LEGENDA</div>
      <div class="legend" style="flex-direction:column;gap:5px"><div class="li"><i class="ln" style="border-color:var(--pit)"></i>Desain praktis (bench + berm)</div><div class="li"><i class="ln" style="border-top-style:dashed;border-color:var(--text)"></i>Shell optimasi</div>
        <div class="li"><i class="ln" style="border-color:var(--accent)"></i>Ramp memotong wall</div><div class="li"><i class="ln" style="border-color:var(--topo)"></i>Topografi</div></div>
      <div class="navh" style="padding:14px 0 6px">BLOCK MODEL · ${esc(D.result.classes.grade_col || "")}</div>${legend(D.result.classes, D.color)}
      <div class="row small" style="gap:8px;padding:2px 0"><i class="swatch" style="opacity:.3;background:${classColour(2)}"></i>Blok sudah ditambang (pudar)</div>
      <p class="xs muted" style="margin:10px 0 0">Irisan blok tebal satu sel sepanjang A–A′.</p></div>
    <div>
      <div class="card"><div class="cardhead"><h2>Penampang 1:1</h2><span class="lbl">skala jujur — tinggi dan lebar sama</span></div><div id="sec1" style="overflow:auto"><canvas id="dsec1"></canvas></div></div>
      <div class="card"><div class="cardhead"><h2>Penampang yang sama, VE ${fmt(D.ve, 1)}×</h2><span class="lbl">dinding tampak lebih curam dari sebenarnya</span><span class="grow"></span>
        <span class="tabs">${[2, 3, 5].map((v) => `<button data-act="dVe" data-v="${v}" class="${D.ve === v ? "on" : ""}">${v}×</button>`).join("")}</span></div><div id="sec2"><canvas id="dsec2"></canvas></div>
        <p class="xs muted" style="margin:8px 0 0">Gunakan hanya untuk membaca berm dan ramp.</p></div>
    </div>
  </div>`);
}

A.dResetLine = () => { D.line = null; D.section = null; import("../store.js").then((m) => m.notify()); };
A.dVe = A.dVe || ((el) => { D.ve = +el.dataset.v; import("../store.js").then((m) => m.notify()); });

function defaultLine() {
  const [cx, cy] = D.result.centre;
  const r = Math.max(...D.result.benches[0].crest.flatMap((p) => p.o.map(([x]) => Math.abs(x - cx)))) * 1.08;
  return [[cx - r, cy], [cx + r, cy]];
}

export function mount() {
  const c = document.getElementById("dplan");
  if (!c || !D.plan || !D.result) return;
  const draw = () => {
    view = paintPlan(c, { plan: D.plan, result: D.result, layers: { ...D.layers, sector: false }, mode: D.color || "kadar", sectors: D.state.sectors, extra: (v) => {
      const ln = drag || (D.line && [D.line.p1, D.line.p2]);
      if (!ln) return;
      const ctx = v.ctx; ctx.strokeStyle = "#C0362C"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(v.X(ln[0][0]), v.Y(ln[0][1])); ctx.lineTo(v.X(ln[1][0]), v.Y(ln[1][1])); ctx.stroke();
      ctx.fillStyle = "#C0362C"; ctx.font = "600 12px 'IBM Plex Sans'"; ctx.fillText("A", v.X(ln[0][0]) + 4, v.Y(ln[0][1]) - 6); ctx.fillText("A′", v.X(ln[1][0]) + 4, v.Y(ln[1][1]) - 6);
    } });
  };
  draw();
  const at = (e) => { const r = c.getBoundingClientRect(); return view.world(e.clientX - r.left, e.clientY - r.top); };
  c.onmousedown = (e) => { drag = [at(e), at(e)]; };
  c.onmousemove = (e) => { if (drag) { drag[1] = at(e); draw(); } };
  c.onmouseup = () => { if (!drag) return; const [a, b] = drag; drag = null; if (Math.hypot(b[0] - a[0], b[1] - a[1]) > 20) loadSection(a, b); else draw(); };
  if (!D.line) { const [a, b] = defaultLine(); loadSection(a, b); return; }
  if (!D.section) return;
  const w1 = Math.max(400, document.getElementById("sec1").clientWidth - 2), w2 = Math.max(400, document.getElementById("sec2").clientWidth - 2);
  const opts = { mode: D.color || "kadar", sectors: D.state.sectors, centre: D.result.centre, p1: D.line.p1, p2: D.line.p2 };
  drawSection(document.getElementById("dsec1"), D.section, D.topo, { ...opts, ve: 1, width: w1 });
  drawSection(document.getElementById("dsec2"), D.section, D.topo, { ...opts, ve: D.ve, width: w2 });
}
