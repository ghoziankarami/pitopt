import { S, notify, isChanged, setDraft, scenarioMeta } from "../store.js";
import { A } from "../actions.js";
import { fmt, esc, api, toast, getPath, clone } from "../util.js";
import { pageHead } from "./common.js";
import { startRun } from "../run.js";
import { modal, closeModal } from "../modal.js";

const ui = { derived: null, deriveFor: "" };
const arr = (s) => String(s).split(/[,\s;]+/).filter(Boolean).map(Number);
const isNum = (t) => t === "num" || t === "list";

// [path, label, unit, type, hint, options]
const SECTIONS = [
  ["Produk & harga", null], // rendered by productsTable()
  ["Biaya & perolehan", [
    ["economics.mining_recovery", "Mining recovery", "0–1", "num", "Fraksi bijih yang benar-benar tergali."],
    ["economics.dilution", "Dilusi", "0–1", "num", "Waste yang ikut tergali bersama bijih."],
    ["economics.royalty_rate", "Royalti", "0–1", "num", "Terhadap pendapatan."],
    ["economics.mining_cost_per_tonne", "Biaya tambang", "USD/t", "num", ""],
    ["economics.mining_cost_per_volume", "Biaya tambang", "USD/m³", "num", "Dipakai bila biaya per volume."],
    ["economics.mining_cost_increment_per_m", "Kenaikan biaya per kedalaman", "USD/t/m", "num", "0 = biaya datar."],
    ["economics.rehabilitation_cost_per_volume", "Rehabilitasi", "USD/m³", "num", ""],
    ["economics.rehabilitation_cost_per_tonne", "Rehabilitasi", "USD/t", "num", ""],
    ["economics.processing_cost_per_tonne", "Biaya proses (umum)", "USD/t", "num", "Biaya proses per produk ada di tabel produk."],
    ["economics.processing_cost_per_volume", "Biaya proses (umum)", "USD/m³", "num", ""],
  ]],
  ["Sumberdaya & domain", [
    ["block_model.density", "Densitas bawaan", "t/m³", "num", ""],
    ["block_model.include_classes", "Kelas sumberdaya dipakai", "", "text", "Pisah dengan koma.", "csv"],
    ["block_model.ore_domains", "Domain bijih", "", "text", "Kosong = semua domain dapat jadi umpan.", "csv"],
    ["economics.grade_basis", "Basis kadar", "", "sel", "", ["mass_percent", "volume_percent", "ppm", "g_per_t", "fraction"]],
  ]],
  ["Geoteknik & bench", [
    ["slope.overall_angle_deg", "Sudut lereng overall", "°", "num", "Dipakai solver untuk template precedence."],
    ["design.enabled", "Bangun desain bench", "", "bool", ""],
    ["design.bench_height", "Tinggi bench", "m", "num", ""],
    ["design.bench_face_angle_deg", "Sudut muka bench", "°", "num", "Harus lebih curam dari sudut overall."],
    ["design.berm_width", "Lebar berm", "m", "num", "Kosong = dihitung otomatis dari sudut overall.", "optnum"],
  ]],
  ["RF & pit final", [
    ["shells.revenue_factors", "Revenue factor (RAF)", "", "list", "Pisah dengan koma; makin rapat makin halus."],
    ["final_pit.criterion", "Kriteria pit final", "", "sel", "", ["average", "best", "worst"]],
    ["final_pit.tolerance", "Toleransi NPV", "0–1", "num", "Shell terkecil dalam toleransi terhadap NPV maksimum."],
    ["final_pit.revenue_factor", "Kunci RF pit final", "", "optnum", "Kosong = otomatis.", "optnum"],
  ]],
  ["Pushback & jadwal", [
    ["pushbacks.method", "Metode pushback", "", "sel", "", ["strips", "shells"]],
    ["pushbacks.count", "Jumlah pushback", "", "optnum", "Kosong = otomatis dari durasi target.", "optnum"],
    ["pushbacks.target_duration_years", "Durasi target per pushback", "tahun", "num", "Dipakai bila jumlah otomatis."],
    ["pushbacks.max_pushbacks", "Maks pushback", "", "num", ""],
    ["pushbacks.strip_width", "Lebar strip", "m", "num", ""],
    ["pushbacks.min_width", "Lebar kerja minimum", "m", "num", ""],
    ["schedule.ore_capacity", "Kapasitas umpan", "t/periode", "num", "Isi ini atau umur tambang."],
    ["schedule.periods", "Umur tambang", "periode", "optnum", "Kapasitas mengikuti umur ini bila diisi.", "optnum"],
    ["schedule.period_years", "Panjang periode", "tahun", "num", ""],
    ["schedule.discount_rate", "Diskonto", "0–1", "num", ""],
  ]],
  ["Sensitivitas", [
    ["sensitivity.enabled", "Jalankan sensitivitas", "", "bool", ""],
    ["sensitivity.price_factors", "Faktor harga", "", "list", "Pisah dengan koma."],
  ]],
];

const cur = (path) => (path in S.draft ? S.draft[path] : getResolved(path));
const orig = (path) => getResolved(path);
function getResolved(path) { return getPath(S.cfg?.resolved, path); }
function prodVal(name, key) {
  const p = (S.cfg?.resolved?.economics?.products || []).find((x) => x.name === name);
  const path = `economics.products.${name}.${key}`;
  return { path, value: path in S.draft ? S.draft[path] : p?.[key], original: p?.[key] };
}
const provOf = (path) => S.cfg?.provenance?.[path];

function checks() {
  const bad = [];
  const g = (p) => Number(cur(p));
  if (g("slope.overall_angle_deg") <= 0 || g("slope.overall_angle_deg") >= 90) bad.push(["slope.overall_angle_deg", "Sudut lereng harus 0–90°."]);
  if (cur("design.enabled") && g("design.bench_face_angle_deg") <= g("slope.overall_angle_deg")) bad.push(["design.bench_face_angle_deg", "Sudut muka bench harus lebih curam dari sudut overall."]);
  for (const p of ["economics.mining_recovery", "economics.dilution", "schedule.discount_rate", "final_pit.tolerance"]) if (g(p) < 0 || g(p) > 1) bad.push([p, "Nilai harus 0–1."]);
  if (cur("schedule.ore_capacity") != null && g("schedule.ore_capacity") <= 0 && !cur("schedule.periods")) bad.push(["schedule.ore_capacity", "Kapasitas harus > 0."]);
  const rf = cur("shells.revenue_factors") || []; if (rf.some((x) => !(x > 0))) bad.push(["shells.revenue_factors", "RF harus > 0."]);
  return bad;
}

function field(path, label, unit, type, hint, opt, errs) {
  const v = cur(path);
  if (v === undefined && !(path in (S.cfg?.resolved ? flat(S.cfg.resolved) : {})) && !path.startsWith("final_pit") && !path.startsWith("design.berm")) return "";
  const changed = path in S.draft;
  const pv = provOf(path);
  const err = errs.find((e) => e[0] === path);
  const tag = pv ? `<span class="tagc ${pv.source === "asumsi" ? "asumsi" : pv.source === "dokumen" ? "ok" : "info"}" title="${esc(pv.note || "")}${pv.ref ? " · " + esc(pv.ref) : ""}">${{ dokumen: "DOKUMEN", asumsi: "ASUMSI", input: "INPUT" }[pv.source] || "DEFAULT"}</span>` : "";
  let input;
  if (type === "bool") input = `<input type="checkbox" data-on="pset" data-path="${path}" data-t="bool" ${v ? "checked" : ""}>`;
  else if (type === "sel") input = `<select data-on="pset" data-path="${path}" data-t="sel">${opt.map((o) => `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select>`;
  else {
    const shown = v === null || v === undefined ? "" : Array.isArray(v) ? v.join(", ") : v;
    input = `<input type="text" data-on="pset" data-path="${path}" data-t="${type === "list" ? "list" : opt === "csv" ? "csv" : type === "optnum" || opt === "optnum" ? "optnum" : "num"}" value="${esc(shown)}" ${type === "num" || type === "optnum" ? 'inputmode="decimal"' : ""}>`;
  }
  return `<div class="fld ${pv?.source === "asumsi" ? "assume" : ""} ${changed ? "changed" : ""} ${err ? "err" : ""}"><label>${esc(label)} ${unit ? `<span class="muted xs">${esc(unit)}</span>` : ""} <span class="grow"></span>${tag}</label>${input}${err ? `<div class="hint bad">${esc(err[1])}</div>` : hint ? `<div class="hint">${esc(hint)}</div>` : ""}${pv?.note && !err ? `<div class="hint">${esc(pv.note)}${pv.ref ? ` · <span class="num">${esc(pv.ref)}</span>` : ""}</div>` : ""}</div>`;
}
function flat(o, pre = "", out = {}) { for (const [k, v] of Object.entries(o || {})) { if (v && typeof v === "object" && !Array.isArray(v)) flat(v, pre + k + ".", out); else out[pre + k] = v; } return out; }

function productsTable(errs) {
  const prods = S.cfg.resolved.economics.products || [];
  const der = ui.derived || S.cfg.derived || {};
  const cell = (name, key, w = 84) => { const { path, value } = prodVal(name, key); return `<td><input type="text" style="width:${w}px;text-align:right" class="${path in S.draft ? "chg" : ""}" data-on="pset" data-path="${path}" data-t="num" value="${esc(value ?? "")}"></td>`; };
  return `<div style="overflow:auto"><table class="t"><thead><tr><th class="l">Produk</th><th>Harga</th><th class="l">Satuan</th><th>Recovery pabrik</th><th>Biaya proses USD/t</th><th>Biaya jual USD/m³</th><th>Margin/ t umpan</th></tr></thead><tbody>
    ${prods.map((p) => `<tr><td class="l"><b>${esc(p.name)}</b></td>${cell(p.name, "price")}<td class="l muted">USD/${esc(p.price_unit)}</td>${cell(p.name, "plant_recovery", 70)}${cell(p.name, "processing_cost_per_tonne")}${cell(p.name, "selling_cost_per_volume")}<td class="num ${(der.margins?.[p.name] ?? 0) < 0 ? "bad" : ""}">${der.margins?.[p.name] != null ? fmt(der.margins[p.name], 2) : "–"}</td></tr>`).join("")}</tbody></table></div>`;
}

export function render() {
  if (!S.cfg) return `<div class="page">${pageHead("Parameter", "")}<div class="card"><div class="empty">${esc(S.cfgError || "Memuat konfigurasi…")}</div></div></div>`;
  const errs = checks();
  const { scenario } = scenarioMeta();
  const n = Object.keys(S.draft).length;
  const asumsi = Object.values(S.cfg.provenance || {}).filter((p) => p.source === "asumsi").length;
  const body = SECTIONS.map(([title, fields], i) => `<div class="card" id="sec${i}" style="margin-bottom:16px"><div class="cardhead"><h2>${title}</h2></div>
    ${fields ? `<div class="pgrid">${fields.map((f) => field(...f.slice(0, 4), f[4], f[5], errs)).join("")}</div>` : productsTable(errs)}</div>`).join("");
  const d = ui.derived || S.cfg.derived || {};
  const actions = `<button class="btn" data-act="pReset" ${n ? "" : "disabled"}>Kembalikan perubahan</button><button class="btn" data-act="pDup">Duplikat sebagai skenario baru</button><button class="btn" data-act="pSave" ${n && !errs.length ? "" : "disabled"}>Simpan skenario</button><button class="btn primary" data-act="pRun" ${errs.length ? "disabled" : ""}>Jalankan optimasi${n ? ` (${n} perubahan)` : ""}</button>`;
  return `<div class="page">${pageHead("Parameter", `${esc(scenario?.label || S.scenario)} · <span class="muted">${asumsi} asumsi belum dikonfirmasi</span>`, actions)}
  ${errs.length ? `<div class="banner bad" style="margin-bottom:16px"><b>${errs.length} masalah sebelum run:</b> ${errs.map((e) => esc(e[1])).join(" ")}</div>` : ""}
  <div class="split psplit"><div>${body}</div>
   <aside class="card" style="position:sticky;top:16px;align-self:start"><div class="cardhead"><h2>Turunan langsung</h2></div>
    <div class="kv">${Object.entries(d.margins || {}).map(([k, v]) => `<span>Margin ${esc(k)}</span><span class="${v < 0 ? "bad" : ""}">${fmt(v, 2)} USD/t</span>`).join("")}
     <span>Level template</span><span>${d.template_levels ?? "–"}</span><span>Sudut efektif sumbu</span><span>${fmt(d.effective_axis_deg, 1)}°</span><span>Sudut efektif diagonal</span><span>${fmt(d.effective_diagonal_deg, 1)}°</span></div>
    <p class="xs muted" style="margin:12px 0 0">Angka ini dihitung ulang server dari parameter yang sedang diedit, tanpa menjalankan optimasi.</p></aside></div></div>`;
}

let timer;
async function derive() {
  if (!isChanged()) { ui.derived = null; return notify(); }
  clearTimeout(timer);
  timer = setTimeout(async () => {
    try { const r = await api("/api/derive", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: S.project, scenario: S.scenario, overrides: S.draft }) }); ui.derived = r.derived; }
    catch (e) { ui.derived = null; toast(e.message); }
    notify();
  }, 250);
}

A.pset = (el) => {
  const path = el.dataset.path, t = el.dataset.t;
  let v;
  if (t === "bool") v = el.checked;
  else if (t === "sel") v = el.value;
  else if (t === "list") v = arr(el.value);
  else if (t === "csv") v = el.value.split(",").map((x) => x.trim()).filter(Boolean);
  else if (t === "optnum") v = el.value.trim() === "" ? null : Number(el.value.replace(",", "."));
  else v = Number(el.value.replace(",", "."));
  if ((t === "num" || t === "optnum") && v !== null && Number.isNaN(v)) { toast("Angka tidak valid."); return notify(); }
  const original = path.startsWith("economics.products.") ? (() => { const [, , name, key] = path.split("."); return prodVal(name, key).original; })() : orig(path);
  setDraft(path, v, original);
  notify(); derive();
};
A.pReset = () => { S.draft = {}; ui.derived = null; notify(); };
A.pRun = () => startRun(clone(S.draft), `${S.scenario} (ubahan)`);
A.pSave = () => askSave(false);
A.pDup = () => askSave(true);
function askSave(dup) {
  modal("Simpan skenario", `<div class="fld"><label>Nama skenario baru</label><input type="text" id="sname" style="width:100%" value="${esc(S.scenario)} (baru)"></div><div id="serr" class="small bad"></div>`, `<button class="btn primary" data-act="doSave" data-dup="${dup ? 1 : ""}">Simpan</button>`);
}
A.doSave = async (el) => {
  const name = document.getElementById("sname").value.trim();
  if (!name) return (document.getElementById("serr").textContent = "Nama wajib diisi.");
  try {
    const r = await api("/api/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: S.project, scenario: S.scenario, overrides: el.dataset.dup ? {} : S.draft, save_as: name }) });
    closeModal();
    const { loadProjects2, select } = await import("../store.js");
    await loadProjects2(); await select(S.project, r.scenario);
    toast(`Skenario "${name}" disimpan.`);
  } catch (e) { document.getElementById("serr").textContent = e.message; }
};
