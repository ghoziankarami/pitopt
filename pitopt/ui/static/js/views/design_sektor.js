// 06 · Crest & Sektor — the wall geometry per azimuth sector: bench face angle, berm criterion, the limits the
// design is checked against. The crest itself follows the PitOpt shell (read-only); what is edited is the wall.
import { A } from "../actions.js";
import { esc, fmt } from "../util.js";
import { D, changed, ensure, setParam, value } from "../design/core.js";
import { gate, legend, notice, page, planControls, saveButton } from "../design/ui.js";
import { paintPlan } from "../design/planview.js";
import { classColour } from "../design/plan.js";

let view = null;

const cfgSectors = () => structuredClone(value("sectors") || []);
const edit = (i, key, v) => { const list = cfgSectors(); list[i][key] = v; setParam("sectors", list); };
const norm = (a) => ((a % 360) + 360) % 360;

function dial(s) {
  const from = norm(s.azimuth_from), span = ((s.azimuth_to - s.azimuth_from) % 360 + 360) % 360 || 360;
  const pt = (a) => { const r = ((a - 90) * Math.PI) / 180; return [22 + 16 * Math.cos(r), 22 + 16 * Math.sin(r)]; };
  const [x0, y0] = pt(from), [x1, y1] = pt(from + span);
  return `<svg width="44" height="44" viewBox="0 0 44 44"><circle cx="22" cy="22" r="16" fill="none" stroke="var(--line)" stroke-width="6"/>
    ${span >= 359.9 ? `<circle cx="22" cy="22" r="16" fill="none" stroke="var(--accent)" stroke-width="6"/>` : `<path d="M${x0} ${y0} A16 16 0 ${span > 180 ? 1 : 0} 1 ${x1} ${y1}" fill="none" stroke="var(--accent)" stroke-width="6"/>`}</svg>`;
}

export function render() {
  ensure();
  const g = gate("Crest & Sektor");
  if (g) return g;
  const st = D.state, sectors = st.sectors || [], sel = Math.min(D.sel, sectors.length - 1), s = sectors[sel];
  const configured = (value("sectors") || []).length > 0;
  const cards = sectors.map((x, i) => `<div class="selcard ${i === sel ? "on" : ""}" data-act="dSel" data-i="${i}" style="cursor:pointer;margin-bottom:8px"><div class="row" style="gap:10px">${dial(x)}
      <div class="grow"><div class="row"><b>${esc(x.name)}</b><span class="grow"></span><span class="num xs muted">${fmt(norm(x.azimuth_from), 0)}°–${fmt(norm(x.azimuth_to), 0)}°</span></div>
      <div class="num xs muted">H ${fmt(x.bench_height, 0)} m · β ${fmt(x.face_angle_deg, 0)}° · berm ${fmt(x.berm_width, 1)} m</div>
      <div class="num xs muted">N=${x.berm_every_n} · IRA ${x.ira_max_deg == null ? "—" : `≤ ${fmt(x.ira_max_deg, 1)}°`}</div></div></div></div>`).join("");
  const asum = (st.assumptions || []).length;
  return page("Crest & Sektor", "Langkah 2 dari 5 · crest mengikuti shell PitOpt; bagi dinding menurut azimut dan isi parameter geoteknik tiap sektor.",
    `${changed() ? `<button class="btn" data-act="dResetDraft">Batalkan perubahan</button>${saveButton()}` : ""}<button class="btn primary" data-act="dGenerate">${D.result ? "Terapkan & regenerasi" : "Generate desain"}</button>`, `
  ${notice()}
  ${changed() ? `<div class="banners" style="margin-bottom:16px"><div class="bh"><span class="tagc asumsi">DIUBAH</span><span>${Object.keys(D.draft).length} parameter diubah dan belum digenerate. Nilai ini ditandai <b>ASUMSI</b> sampai Anda mendokumentasikannya, dan tidak menimpa file skenario.</span></div></div>` : ""}
  ${asum ? `<div class="banners" style="border-color:var(--warn-line);background:var(--warn-panel);margin-bottom:16px"><div class="bh"><span class="tagc asumsi">ASUMSI</span><span><b>${asum} parameter</b> belum berdokumen; ikut tercatat di laporan dan blok provenance.</span></div></div>` : ""}
  <div class="dd-cols3">
    <div class="card"><div class="cardhead"><h2>Sektor geoteknik</h2><span class="grow"></span><button class="btn sm" data-act="dAddSector">+ Sektor</button></div>
      ${cards}
      ${configured ? "" : `<div class="note" style="margin-top:8px">Belum ada sektor: seluruh dinding memakai satu geometri. <a data-act="dSplit4">Bagi menjadi 4 sektor (U/T/S/B)</a> untuk memberi parameter berbeda per arah.</div>`}
      <p class="xs muted" style="margin:10px 0 0">Sektor tanpa parameter eksplisit memakai nilai global PitOpt. Transisi ±${fmt(value("blend_deg") ?? 12, 0)}° di batas azimut.</p></div>
    <div class="card"><div class="cardhead"><h2>Plan view — crest &amp; sektor</h2><span class="lbl">garis putus = shell · biru = desain pada slice ini</span></div>
      <div style="margin-bottom:8px">${planControls()}</div>
      <canvas id="dplan" class="plan" style="height:520px;cursor:pointer"></canvas>
      <div class="row xs muted" style="margin-top:8px;gap:18px"><span>Klik busur untuk memilih sektor</span><span class="grow"></span></div>
      <div style="margin-top:8px">${D.plan ? legend(D.plan.classes, D.color) : ""}</div></div>
    ${s ? panel(s, sel, configured) : `<div class="card"><div class="empty">Tidak ada sektor.</div></div>`}
  </div>`);
}

function panel(s, i, configured) {
  const list = value("sectors") || [];
  const cfg = list[i] || {};
  const method = (cfg.berm && cfg.berm.method) || value("berm.method") || "ritchie";
  const opt = (k, label, formula) => {
    const o = s.berm_options?.[k];
    return `<label class="selcard ${method === k ? "on" : ""}" style="display:block;margin-bottom:8px;cursor:pointer"><div class="row" style="gap:8px"><input type="radio" name="berm" ${method === k ? "checked" : ""} data-act="dBerm" data-k="${k}" ${configured ? "" : "disabled"}>
      <b>${label}</b><span class="grow"></span>${o ? `<span class="num small">${fmt(o.berm_width, 1)} m</span><span class="num small muted">${fmt(o.ira_deg, 1)}°</span>` : `<span class="num small muted">[ANGKA]</span>`}</div>
      <div class="xs muted" style="margin:4px 0 0 24px">${formula}</div></label>`;
  };
  const over = s.ira_max_deg != null && s.ira_deg > s.ira_max_deg;
  const dis = !configured;
  // data-on (not data-act): this is a typed field, fired by the app shell's "change" listener on blur/Tab/Enter,
  // not by the click listener that data-act hooks into — a plain click would leave whatever was typed unsaved.
  const num = (label, key, unit, v, extra = "") => `<div class="fld"><label>${label}</label><div class="inp"><input type="number" step="any" value="${v ?? ""}" data-on="dSecField" data-i="${i}" data-key="${key}" ${dis ? "readonly" : ""} ${extra}><span class="unit">${unit}</span></div></div>`;
  return `<div class="card"><div class="cardhead"><div><div class="navh" style="padding:0">SEKTOR TERPILIH</div><h2 style="font-size:18px">${esc(s.name)}</h2></div><span class="grow"></span>${(D.state.provenance?.[`design.detail.sectors.${s.name}.ira_max_deg`]?.source === "asumsi") ? `<span class="tagc asumsi">BATAS ASUMSI</span>` : ""}</div>
    <div class="dd-two">${num("Azimut mulai", "azimuth_from", "°", cfg.azimuth_from)}${num("Azimut akhir", "azimuth_to", "°", cfg.azimuth_to)}</div>
    <div class="dd-two">
      <div class="fld"><label>Tinggi bench <span class="badge default">GLOBAL</span></label><div class="inp"><input type="number" value="${s.bench_height}" readonly><span class="unit">m</span></div><div class="hint">Bench berbagi elevasi di seluruh pit.</div></div>
      ${num(`Sudut muka β`, "face_angle_deg", "°", cfg.face_angle_deg ?? "", `placeholder="${s.face_angle_deg}"`)}
      ${num("Berm tiap N", "berm_every_n_benches", "bench", cfg.berm_every_n_benches ?? "", `placeholder="${s.berm_every_n}" step="1"`)}<span></span>
      ${num("IRA maks", "ira_max_deg", "°", cfg.ira_max_deg ?? "")}${num("OSA maks", "osa_max_deg", "°", cfg.osa_max_deg ?? "")}
    </div>
    <div class="navh" style="padding:14px 0 6px">BERM — KRITERIA</div>
    ${opt("ritchie", "Ritchie", "W = 0,2·H + 4,5 m (Ritchie termodifikasi)")}
    ${opt("ryan", "Ryan", s.berm_options?.ryan ? "koefisien dari laporan geoteknik" : "koefisien wajib dari geoteknik — tanpa default")}
    ${opt("slope", `Dari slope optimasi ${fmt(D.state.slope_deg, 0)}°`, "berm yang membuat IRA = slope optimasi")}
    <div class="navh" style="padding:14px 0 6px">TURUNAN LANGSUNG</div>
    <div class="kv"><span class="muted">Offset horizontal H/tan β</span><span>${fmt(s.run_m, 2)} m</span><span class="muted">Lebar berm</span><span>${fmt(s.berm_width, 2)} m</span>
      <span class="muted">IRA hasil (bench + berm)</span><span class="${over ? "bad" : ""}">${fmt(s.ira_deg, 1)}°${s.ira_max_deg != null ? ` ${over ? ">" : "≤"} ${fmt(s.ira_max_deg, 1)}°` : ""}</span></div>
    ${over ? `<p class="xs" style="color:var(--bad);margin:8px 0 0">IRA hasil melampaui batas: perkecil sudut muka, turunkan tinggi bench, atau perlebar berm sebelum generate.</p>` : ""}
    ${D.state.notes?.length ? `<p class="xs muted">${D.state.notes.map(esc).join("; ")}</p>` : ""}
    <div class="row" style="margin-top:12px;gap:8px"><button class="btn primary grow" data-act="dGenerate">Terapkan sektor</button>${configured ? `<button class="btn danger" data-act="dDelSector" data-i="${i}">Hapus</button>` : ""}</div></div>`;
}

A.dSel = (el) => { D.sel = +el.dataset.i; import("../store.js").then((m) => m.notify()); };
A.dAddSector = () => {
  const list = cfgSectors();
  const last = list.at(-1);
  const from = last ? norm(last.azimuth_to) : 0;
  list.push({ name: `Sektor ${list.length + 1}`, azimuth_from: from, azimuth_to: norm(from + 30) });
  setParam("sectors", list);
};
A.dSplit4 = () => setParam("sectors", [["Utara", 315, 45], ["Timur", 45, 135], ["Selatan", 135, 225], ["Barat", 225, 315]].map(([name, a, b]) => ({ name, azimuth_from: a, azimuth_to: b })));
A.dDelSector = (el) => { const list = cfgSectors(); list.splice(+el.dataset.i, 1); D.sel = 0; setParam("sectors", list); };
A.dSecField = (el) => { const v = el.value.trim() === "" ? null : +el.value; if (v === null || !Number.isNaN(v)) edit(+el.dataset.i, el.dataset.key, el.dataset.key === "berm_every_n_benches" && v !== null ? Math.round(v) : v); };
A.dBerm = (el) => { const list = cfgSectors(), i = D.sel; list[i].berm = { method: el.dataset.k }; setParam("sectors", list); };

export function mount() {
  const c = document.getElementById("dplan");
  if (!c || !D.plan) return;
  const st = D.state, sectors = st.sectors || [];
  view = paintPlan(c, { plan: D.plan, result: D.result, layers: D.layers, mode: D.color || "kadar", sel: sectors.length > 1 ? D.sel : null, sectors });
  document.querySelectorAll(".swatch[data-cls]").forEach((el) => { el.style.background = classColour(+el.dataset.cls); });
  c.onclick = (e) => {
    if (!D.result || sectors.length < 2) return;
    const r = c.getBoundingClientRect(), [wx, wy] = view.world(e.clientX - r.left, e.clientY - r.top);
    const az = norm((Math.atan2(wx - D.result.centre[0], wy - D.result.centre[1]) * 180) / Math.PI);
    const hit = sectors.findIndex((s) => ((az - s.azimuth_from + 360) % 360) < (((s.azimuth_to - s.azimuth_from) % 360 + 360) % 360 || 360));
    if (hit >= 0) A.dSel({ dataset: { i: hit } });
  };
}
