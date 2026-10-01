// Pieces every design screen uses: the page frame, the states that come before there is anything to show
// (loading, no run yet, an error), parameter fields with their provenance, and the validation banner.
import { notify as _n } from "../store.js";
import { A } from "../actions.js";
import { esc, fmt } from "../util.js";
import { pageHead } from "../views/common.js";
import { S } from "../store.js";
import { api } from "../util.js";
import { modal, closeModal } from "../modal.js";
import { D, badge, loadPlan, pill, setParam, value, worst } from "./core.js";

export const page = (title, sub, actions, body) => `<div class="page dd">${pageHead(title, sub, actions)}${body}</div>`;

/** The state a screen shows when it cannot show its content yet, or null when it can. */
export function gate(title, { needResult = false } = {}) {
  const wrap = (msg) => `<div class="page dd">${pageHead(title, "")}${msg}</div>`;
  if (D.loading) return wrap(`<div class="card"><div class="empty" style="padding:48px">Memuat parameter dan hasil PitOpt…</div></div>`);
  if (D.err) return wrap(`<div class="banners bad"><div class="bh"><span class="tagc blokir">GAGAL</span><span>${esc(D.err)}</span><span class="grow"></span><button class="btn sm" data-act="dReload">Coba lagi</button></div></div>`);
  const s = D.state;
  if (!s?.has_results) {
    return wrap(`<div class="card"><div class="empty" style="padding:48px"><div style="font-size:15px;font-weight:600;color:var(--text);margin-bottom:6px">Belum ada hasil PitOpt untuk skenario ini</div>
      <div style="margin-bottom:16px">Desain Detail memakai shell dari hasil optimasi. Jalankan optimasi dulu; setelah selesai, kembali ke sini.</div>
      <button class="btn primary" data-act="runCurrent">Jalankan optimasi</button></div></div>`);
  }
  if (!s.blocks_ready) {
    return wrap(`<div class="banners bad"><div class="bh"><span class="tagc blokir">BLOKIR</span><span>Hasil run tidak memuat tabel blok (<span class="num">_blocks.csv</span>), jadi shell tidak bisa dibaca. Jalankan ulang optimasi.</span><span class="grow"></span><button class="btn sm" data-act="runCurrent">Jalankan optimasi</button></div></div>`);
  }
  if (s.params_error) {
    return wrap(`<div class="banners bad"><div class="bh"><span class="tagc blokir">PARAMETER</span><span>${esc(s.params_error)}</span><span class="grow"></span>${Object.keys(D.draft).length ? `<button class="btn sm" data-act="dResetDraft">Batalkan perubahan</button>` : ""}</div></div>`);
  }
  if (needResult && !D.result) return wrap(noDesign());
  return null;
}

export const noDesign = () => `<div class="card"><div class="empty" style="padding:40px"><div style="font-size:15px;font-weight:600;color:var(--text);margin-bottom:6px">Desain belum di-generate</div>
  <div style="margin-bottom:16px">Bench, ramp, validasi, dan rekonsiliasi dihitung dari parameter di layar Crest &amp; Sektor dan Ramp. Butuh beberapa detik.</div>
  <button class="btn primary" data-act="dGenerate">Generate desain</button></div></div>`;

export const notice = () => (D.notice ? `<div class="banners bad" style="margin-bottom:16px"><div class="bh"><span class="tagc blokir">GAGAL</span><span>${esc(D.notice)}</span></div></div>` : "");

/** A parameter field. kind: num | int | text | select; path is relative to design.detail. */
export function field({ label, path, unit = "", kind = "num", hint = "", options = [], min, max, step = "any", fallback, readonly = false, compact = false }) {
  const v = value(path) ?? fallback ?? "";
  const changed = path in D.draft ? " changed" : "";
  const src = D.state ? badge(path) : "";
  const assume = /asumsi/i.test(src) && !changed ? " assume" : "";
  const ctl = kind === "select"
    ? `<select data-on="dParam" data-path="${path}" data-kind="text" ${readonly ? "disabled" : ""}>${options.map(([k, l]) => `<option value="${k}" ${String(v) === String(k) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`
    : `<div class="inp"><input type="${kind === "text" ? "text" : "number"}" ${kind === "text" ? "" : `step="${step}"`} ${min !== undefined ? `min="${min}"` : ""} ${max !== undefined ? `max="${max}"` : ""} value="${esc(v)}" data-on="dParam" data-path="${path}" data-kind="${kind}" ${readonly ? "readonly" : ""}>${unit ? `<span class="unit">${unit}</span>` : ""}</div>`;
  return `<div class="fld${changed}${assume}"><label>${label} ${compact ? "" : src}</label>${ctl}${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
}

A.dParam = (el) => {
  const raw = el.value.trim();
  const kind = el.dataset.kind;
  const v = kind === "text" ? raw : raw === "" ? null : kind === "int" ? Math.round(+raw) : +raw;
  if (kind !== "text" && v !== null && Number.isNaN(v)) return;
  setParam(el.dataset.path, v);
};
A.dReload = () => { D.key = ""; location.reload(); };
A.dResetDraft = async () => { const { resetDraft } = await import("./core.js"); resetDraft(); };
A.dGenerate = async () => { const { generate } = await import("./core.js"); generate(); };
A.dCancel = async () => { const { cancelGenerate } = await import("./core.js"); cancelGenerate(); };

/** One line per problem, worst first, each linking to where it is fixed. */
const LINK = { shape_fit: ["d-sumber", "Lihat sumber shell →"], ira: ["d-sektor", "Buka Crest & Sektor →"], osa: ["d-ramp", "Buka Ramp →"],
  reconciliation: ["d-validasi", "Lihat rekonsiliasi →"], ramp: ["d-ramp", "Buka Ramp →"],
  self_intersection: ["d-generate", "Lihat di viewport →"], min_width: ["d-validasi", "Lihat rekonsiliasi →"] };
const NAME = { shape_fit: "BENTUK SHELL", ira: "IRA", osa: "OSA", reconciliation: "DILUSI", ramp: "RAMP",
  self_intersection: "GEOMETRI", min_width: "LEBAR DASAR" };

/** A finding in the UI's language, built from what it measured (value and limit) rather than from the engine's English. */
export function say(f) {
  const v = f.value, l = f.limit;
  if (f.check === "shape_fit") {
    if (f.status === "OK") return `Desain mengikuti shell hingga ${fmt(v * 100, 0)} % di seluruh tumpukan (titik terlemah ${f.scope}).`;
    const verb = f.status === "BLOKIR" ? "tidak cocok dengan" : "mungkin kurang dari";
    return `Pada ${f.scope}, luas desain hanya ${fmt(v * 100, 0)} % dari luas shell asli di elevasi itu — offset dari satu titik acuan ${verb} lebar sebenarnya shell di sana.`
      + (f.status === "BLOKIR" ? " Bentuk shell ini tidak menyempit ke satu kerucut; rekonsiliasi di bawah tidak bisa dipercaya begitu saja." : "");
  }
  if (f.check === "ira" || f.check === "osa") {
    const what = f.check === "ira" ? "Sudut inter-ramp" : "Sudut overall (dengan ramp)";
    if (l == null) return `${what} ${fmt(v, 1)}°; belum ada batas.`;
    return f.status === "BLOKIR" ? `${what} ${fmt(v, 1)}° melampaui batas ${fmt(l, 1)}° (margin ${fmt(l - v, 1)}°).`
      : f.status === "PERINGATAN" ? `${what} ${fmt(v, 1)}° hampir di batas ${fmt(l, 1)}° (margin ${fmt(l - v, 1)}°).` : `${what} ${fmt(v, 1)}° di dalam batas ${fmt(l, 1)}°.`;
  }
  if (f.check === "reconciliation") {
    const name = { rock: "Rock", ore: "Umpan", value: "Nilai" }[f.scope] || f.scope;
    return `${name} desain ${v > 0 ? "+" : ""}${fmt(v, 1)} % terhadap shell (peringatan > ${fmt(f.status === "BLOKIR" ? 5 : l, 0)} %, blokir > ${fmt(f.status === "BLOKIR" ? l : 10, 0)} %).`;
  }
  if (f.check === "min_width") return `Dasar pit selebar ${fmt(v, 0)} m; lebar kerja minimum ${fmt(l, 0)} m.`;
  return f.message;
}

export function findingsBanner(doc, { limit = 6, links = true } = {}) {
  const problems = (doc?.findings || []).filter((f) => f.status !== "OK").sort((a, b) => (a.status === b.status ? 0 : a.status === "BLOKIR" ? -1 : 1));
  if (!doc) return "";
  if (!problems.length) return `<div class="banners" style="border-color:var(--good-line);background:var(--good-bg)"><div class="bh"><span class="tagc ok">OK</span><span>Semua validasi lolos: bentuk shell, sudut, rekonsiliasi, ramp, dan geometri.</span></div></div>`;
  const hard = problems.some((f) => f.status === "BLOKIR");
  const rows = problems.slice(0, limit).map((f) => {
    const [to, text] = LINK[f.check] || ["d-validasi", "Buka Validasi →"];
    return `<div class="brow">${pill(f.status)}<span class="tagc info">${NAME[f.check] || f.check}</span><span class="txt">${f.scope ? `<b>${esc(f.scope)}</b> — ` : ""}${esc(say(f))}</span>${links ? `<a data-go="${to}">${text}</a>` : ""}</div>`;
  }).join("");
  return `<div class="banners ${hard ? "bad" : ""}"><div class="bh"><span style="font-size:18px">⚠</span><b>${problems.length} hal perlu perhatian</b><span class="muted small">— bukan error yang memblokir; ubah parameter lalu regenerasi</span></div>${rows}${problems.length > limit ? `<div class="brow muted small">+ ${problems.length - limit} lagi di layar Validasi.</div>` : ""}</div>`;
}
export const statusOf = (doc) => (doc ? worst(doc.findings.map((f) => f.status)) : "OK");

export const legend = (classes, mode) => {
  if (mode !== "kelas" || !classes.configured) return `<div class="xs muted">Warna: ${mode === "nilai" ? "nilai blok (USD)" : `kadar ${esc(classes.grade_col || "")}`}, skala kontinu.${!classes.configured ? " Ambang kelas belum diatur di <span class=\"num\">design.detail.grade_classes</span>." : ""}</div>`;
  const b = classes.breaks;
  return classes.names.map((n, i) => {
    const rng = i === 0 ? `< ${fmt(b[0], 2)}` : i === b.length ? `≥ ${fmt(b[i - 1], 2)}` : `${fmt(b[i - 1], 2)}–${fmt(b[i], 2)}`;
    return `<div class="row small" style="gap:8px;padding:2px 0"><i class="swatch" data-cls="${i}"></i><span class="grow">${esc(n)}</span><span class="num muted">${rng} ${esc(classes.unit || "")}</span></div>`;
  }).join("");
};

// ── plan controls shared by the screens that show the block slice ──
export function planControls({ modes = true } = {}) {
  const p = D.plan;
  if (!p) return "";
  const levels = p.levels, idx = Math.max(0, levels.indexOf(p.rl));
  const layer = (k, l) => `<label class="chk"><input type="checkbox" data-act="dLayer" data-k="${k}" ${D.layers[k] ? "checked" : ""}> ${l}</label>`;
  return `<div class="ctl">${layer("blocks", "Block model")}${layer("shell", "Shell")}${layer("ramp", "Ramp")}${layer("sector", "Sektor")}
    ${modes ? `<span class="row" style="gap:6px"><span class="xs muted">Warna menurut</span><span class="tabs">${[["kelas", "Kelas"], ["kadar", "Kadar"], ["nilai", "Nilai"]].map(([k, l]) => `<button data-act="dColor" data-k="${k}" class="${D.color === k ? "on" : ""}">${l}</button>`).join("")}</span></span>` : ""}
    <span class="slice"><span class="xs muted">Slice</span><button class="btn sm" data-act="dSlice" data-d="1">▼</button>
      <input type="range" min="0" max="${levels.length - 1}" value="${levels.length - 1 - idx}" data-input="dSliceRange" style="flex:1"><button class="btn sm" data-act="dSlice" data-d="-1">▲</button>
      <b class="num" style="min-width:76px;white-space:nowrap">RL ${fmt(p.rl, 1)}</b></span></div>`;
}
A.dLayer = (el) => { D.layers[el.dataset.k] = el.checked; _n(); };
A.dColor = (el) => { D.color = el.dataset.k; _n(); };
A.dSlice = (el) => { const l = D.plan.levels, i = l.indexOf(D.plan.rl) + (+el.dataset.d); if (i >= 0 && i < l.length) loadPlan(l[i]); };
A.dSliceRange = (el) => { const l = D.plan.levels; loadPlan(l[l.length - 1 - +el.value]); };

// ── keeping edits: a changed parameter is saved as a new scenario, like every other PitOpt parameter change ──
export const saveButton = () => `<button class="btn" data-act="dSaveAs">Simpan sebagai skenario…</button>`;
A.dSaveAs = () => {
  const list = Object.entries(D.draft).map(([k, v]) => `<div class="row small"><span class="num grow">design.detail.${esc(k)}</span><span class="num">${esc(JSON.stringify(v))}</span></div>`).join("");
  modal("Simpan sebagai skenario baru", `<p class="small muted" style="margin:0">Parameter desain yang diubah tidak menimpa skenario asli. Beri nama skenario baru; skenario baru perlu dijalankan sekali (optimasi) sebelum desainnya bisa dibuat.</p>
    <div class="card" style="padding:10px 14px">${list}</div><div class="fld"><label>Nama skenario</label><input type="text" id="dsaveas" style="width:100%" placeholder="mis. Desain v2"></div><div id="dsaveerr" class="small bad"></div>`,
    `<button class="btn primary" data-act="dSaveConfirm">Simpan</button>`);
};
A.dSaveConfirm = async () => {
  const name = document.getElementById("dsaveas").value.trim();
  if (!name) { document.getElementById("dsaveerr").textContent = "Nama skenario wajib diisi."; return; }
  const overrides = Object.fromEntries(Object.entries(D.draft).map(([k, v]) => [`design.detail.${k}`, v]));
  try {
    const { scenario } = await api("/api/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: S.project, scenario: S.scenario, overrides, save_as: name }) });
    closeModal();
    const { loadProjects2, select } = await import("../store.js");
    await loadProjects2();
    D.draft = {};
    await select(S.project, scenario);
  } catch (e) { document.getElementById("dsaveerr").textContent = e.message; }
};
