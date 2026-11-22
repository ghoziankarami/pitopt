// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (c) 2026 Orebit (Ghozian Islam Karami)
// New project & 1-screen Quick Pit Estimation: sample/CSV → instant pre-validation & RAM → run → KPI & 3D.
import { S, notify, loadProjects2, select, ensureGrids3d } from "../store.js";
import { A } from "../actions.js";
import { fmt, fmtInt, mUSD, mt, pcts, esc, api, qs, toast, tr } from "../util.js";
import { pageHead, kpi } from "./common.js";
import { pollJob } from "../run.js";
import { t } from "../i18n.js";

const fresh = () => ({
  mode: "quick",
  title: "", slug: "", sampleSource: "", block: null, surface: null, progress: null, busy: false, error: null, warnings: [],
  map: {}, size: {}, density: "", uniques: {}, include_classes: [], ore_domains: [],
  eco: { grade_basis: "mass_percent", mining_recovery: 1, dilution: 0, royalty_rate: 0, mining_cost_per_tonne: "", processing_cost_per_tonne: 0 },
  products: [{ name: "", grade_col: "", price: "", price_unit: "t", plant_recovery: 1, processing_cost_per_tonne: 0, selling_cost_per_tonne: 0, density: "" }],
  rb: { target: { dx: "", dy: "", dz: "" }, parent: { dx: "", dy: "", dz: "" }, grades: [], strip: false, busy: false, err: null, result: null },
  crs: "", vertical_datum: "", volume_col: "", slope_angle: 45, capacity: "", periods: "", discount_rate: 0.1, bench_height: "", bench_face_angle: 65, touched: new Set(),
  ram: null, ramBusy: false, quickProject: null,
});
let w = fresh();
let plotlyLoader = null;
const slug = () => (w.slug || w.title).trim().toLowerCase().replace(/[^0-9a-z_-]+/g, "_").replace(/^_+|_+$/g, "");

function ensureQuickTitle(prefix = "Quick Pit") {
  if (!slug()) {
    const tag = Date.now().toString(36).slice(-4);
    w.title = `${prefix} ${tag}`;
    w.slug = slug();
  }
}

function loadPlotly() {
  if (window.Plotly) return Promise.resolve(window.Plotly);
  return (plotlyLoader ||= new Promise((ok, no) => {
    const s = document.createElement("script"); s.src = "/static/vendor/plotly.min.js";
    s.onload = () => ok(window.Plotly); s.onerror = () => no(new Error(t("Plotly gagal dimuat"))); document.head.appendChild(s);
  }));
}

function upload(file, kind) {
  if (w.mode === "quick") ensureQuickTitle("Quick Pit");
  const project = slug();
  if (!project) return toast("Isi nama proyek dulu.");
  w.error = null; w.progress = { kind, name: file.name, pct: 0 }; notify();
  const xhr = new XMLHttpRequest();
  xhr.open("POST", `/api/upload?${qs({ project, name: file.name })}`);
  xhr.setRequestHeader("X-PitOpt", "1");
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) { w.progress.pct = e.loaded / e.total; notify(); } };
  xhr.onload = async () => {
    w.progress = null;
    let res; try { res = JSON.parse(xhr.responseText); } catch { res = { error: "respon tidak valid" }; }
    if (xhr.status !== 200) { w.error = res.error || "Unggah gagal"; return notify(); }
    if (kind === "block") await acceptBlock(res); else acceptSurface(res);
    notify();
  };
  xhr.onerror = () => { w.progress = null; w.error = "Unggah gagal (koneksi)."; notify(); };
  xhr.send(file);
}

async function acceptBlock(res) {
  const info = res.inspect;
  if (info.kind === "surface" || info.kind === "surface_csv") { w.error = "Berkas ini terlihat seperti topografi, bukan model blok. Unggah di kotak Topografi."; return; }
  w.block = { file: res.file, info };
  w.crs = ""; w.vertical_datum = "";
  w.map = { x_col: info.guess?.x || "", y_col: info.guess?.y || "", z_col: info.guess?.z || "", density_col: info.guess?.density || "", domain_col: info.guess?.domain || "", class_col: info.guess?.class || "", dx_col: info.guess?.dx || "", dy_col: info.guess?.dy || "", dz_col: info.guess?.dz || "" };
  w.size = { dx: info.spacing?.x || "", dy: info.spacing?.y || "", dz: info.spacing?.z || "" };
  w.bench_height = info.spacing?.z || "";
  w.volume_col = "";
  const skip = new Set([w.map.x_col, w.map.y_col, w.map.z_col, w.map.density_col, w.map.dx_col, w.map.dy_col, w.map.dz_col]);
  w.rb = { ...fresh().rb, grades: (info.numeric || []).filter((c) => !skip.has(c)) };
  const grades = Object.keys(info.stats || {}).filter((c) => c !== w.map.density_col);
  if (grades.length === 1 && !w.products[0].grade_col) { w.products[0].grade_col = grades[0]; w.products[0].name ||= grades[0].replace(/_?(PCT|PPM|GPT)$/i, ""); }
  w.warnings = [...(info.warnings || [])];
  w.ram = info.ram_default || null;
  await loadUniques("domain_col"); await loadUniques("class_col");
  checkExtents();
  if (w.mode === "quick" && !w.ram) await refreshRam();
}

function acceptSurface(res) {
  const i = res.inspect;
  w.surface = { file: res.file, info: i, format: i.format };
  if (i.format === "csv") w.surface.map = { x_col: i.guess.x || "", y_col: i.guess.y || "", z_col: i.guess.z || "" };
  checkExtents();
}

function checkExtents() {
  w.warnings = w.warnings.filter((x) => !x.startsWith("Topografi"));
  const e = w.block?.info.extent, s = w.surface?.info.extent;
  if (!e || !s) return;
  for (const [k, label] of [["x", "Easting"], ["y", "Northing"]]) if (s[k][1] < e[k][0] || s[k][0] > e[k][1]) w.warnings.push(`Topografi: ${label} (${fmt(s[k][0], 0)}–${fmt(s[k][1], 0)}) tidak beririsan dengan model blok (${fmt(e[k][0], 0)}–${fmt(e[k][1], 0)}). Sistem koordinat berbeda?`);
}

async function loadUniques(key) {
  const col = w.map[key];
  if (!col) { delete w.uniques[key]; return; }
  try { w.uniques[key] = await api(`/api/uniques?${qs({ project: slug(), file: w.block.file, col })}`); } catch { delete w.uniques[key]; }
}

async function refreshRam() {
  const rows = w.block?.info?.rows, dx = Number(w.size.dx), dy = Number(w.size.dy), dz = Number(w.size.dz), angle = Number(w.slope_angle);
  if (!(rows > 0 && dx > 0 && dy > 0 && dz > 0 && angle > 0 && angle < 90)) { w.ram = null; return; }
  w.ramBusy = true;
  try {
    w.ram = await api("/api/quick/ram", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows, dx, dy, dz, slope_angle: angle }) });
  } catch { /* keep previous or null */ }
  w.ramBusy = false;
}

const sel = (path, options, value, blank = "— tidak ada —") => `<select data-on="wset" data-path="${path}">${blank === null ? "" : `<option value="">${blank}</option>`}${options.map((o) => `<option ${o === value ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
const num = (path, value, ph = "") => `<input type="text" inputmode="decimal" data-on="wset" data-path="${path}" data-num="1" value="${esc(value ?? "")}" placeholder="${esc(ph)}">`;
const fld = (label, input, hint = "") => `<div class="fld"><label>${label}</label>${input}${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
const drop = (kind, title, hint, done) => `<label class="drop ${done ? "done" : ""}"><input type="file" hidden data-on="wfile" data-kind="${kind}" accept="${kind === "block" ? ".csv" : ".dxf,.csv"}">
  <b>${title}</b><span class="muted small">${done ? `<span class="good">✓</span> ${esc(done)}` : hint}</span></label>`;

function renderQuick() {
  const b = w.block, i = b?.info, cols = i?.columns || [], numeric = i?.numeric || [];
  const sampleOpts = S.projects.map((p) => `<option value="${esc(p.id)}" ${(w.sampleSource || S.projects[0]?.id) === p.id ? "selected" : ""}>${esc(p.title || p.id)}</option>`).join("");
  const uploading = w.progress ? `<div class="banner small" style="margin-top:12px">Mengunggah ${esc(w.progress.name)} — ${fmt(w.progress.pct * 100, 0)}%<div class="bar"><div style="width:${w.progress.pct * 100}%"></div></div></div>` : "";

  const ram = w.ram;
  const ramPill = !ram ? "" : ram.status === "ok"
    ? `<span class="pill ok">RAM cukup</span>`
    : ram.status === "warn"
      ? `<span class="pill warn">Mendekati batas RAM</span>`
      : `<span class="pill bad">Melebihi RAM</span>`;
  const precheck = !b
    ? `<div class="empty" style="padding:28px">Pilih dataset contoh atau unggah CSV untuk melihat pra-validasi dan estimasi memori instan.</div>`
    : `<div class="kv">
        <span>Jumlah blok</span><span>${fmtInt(i.rows)}</span>
        <span>Ukuran blok</span><span>${w.size.dx ? `${fmt(w.size.dx, 1)} × ${fmt(w.size.dy, 1)} × ${fmt(w.size.dz, 1)} m` : "–"}</span>
        <span>Kisi reguler</span><span><span class="pill ${i.regular === false ? "warn" : "ok"}">${i.regular === false ? "Tidak reguler" : "OK"}</span></span>
        <span>Kolom X / Y / Z</span><span>${esc(w.map.x_col || "–")} / ${esc(w.map.y_col || "–")} / ${esc(w.map.z_col || "–")}</span>
        ${ram ? `<span>Estimasi RAM solver</span><span>${fmt(ram.need_gb, 2)} GB ${ramPill}</span>` : ""}
        ${ram?.available_gb != null ? `<span>RAM tersedia</span><span>${fmt(ram.available_gb, 1)} GB</span>` : ""}
      </div>
      ${ram && !ram.fits ? `<div class="banner bad small" style="margin-top:10px">Model melebihi kapasitas RAM tersedia. Gunakan reblock di Pengaturan Lengkap atau kecilkan area model.</div>` : ""}
      ${i.regular === false ? `<div class="banner warn small" style="margin-top:10px">Model tidak reguler — gunakan Pengaturan Lengkap untuk reblock sebelum optimasi.</div>` : ""}
      ${(w.warnings || []).map((x) => `<div class="banner warn small" style="margin-top:8px">${esc(x)}</div>`).join("")}`;

  const p0 = w.products[0];
  const needsDensity = b && !w.map.density_col;
  const quickReady = b && (i.regular !== false) && w.map.x_col && w.map.y_col && w.map.z_col && slug()
    && (w.capacity || w.periods) && w.eco.mining_cost_per_tonne !== ""
    && (!needsDensity || Number(w.density) > 0)
    && p0.name && p0.grade_col && Number(p0.price) > 0
    && Number(w.slope_angle) > 0 && Number(w.slope_angle) < 90
    && (!ram || ram.fits);
  const jobRunning = S.job && S.job.project === w.quickProject && S.job.status === "running";
  const jobError = S.job && S.job.project === w.quickProject && S.job.status === "error";
  const hasQuickResults = w.quickProject && S.project === w.quickProject && S.results && !jobRunning;

  const paramsCard = b ? `<div class="card" style="margin-top:16px">
    <div class="cardhead"><h2>2 · Parameter kunci</h2><span class="lbl">cukup untuk estimasi cepat; detail lain dicatat sebagai ASUMSI</span></div>
    <div class="pgrid">
      ${fld("Nama produk", `<input type="text" data-on="wset" data-path="products.0.name" value="${esc(p0.name)}" placeholder="mis. SN">`)}
      ${fld("Kolom kadar", sel("products.0.grade_col", numeric, p0.grade_col, "pilih…"))}
      ${fld("Basis kadar", sel("eco.grade_basis", ["mass_percent", "volume_percent", "ppm", "gpt", "kgm3", "gm3"], w.eco.grade_basis, null))}
      ${fld("Harga produk", num("products.0.price", p0.price, "mis. 30000"))}
      ${fld("Satuan harga", sel("products.0.price_unit", ["t", "kg", "g", "oz", "lb"], p0.price_unit, null))}
      ${fld("Biaya tambang <span class='muted xs'>USD/t</span>", num("eco.mining_cost_per_tonne", w.eco.mining_cost_per_tonne, "mis. 2.5"))}
      ${fld("Biaya proses <span class='muted xs'>USD/t</span>", num("eco.processing_cost_per_tonne", w.eco.processing_cost_per_tonne, "0"))}
      ${fld("Sudut lereng overall <span class='muted xs'>°</span>", num("slope_angle", w.slope_angle, "45"))}
      ${fld("Kapasitas umpan <span class='muted xs'>t/periode</span>", num("capacity", w.capacity, "mis. 250000"))}
      ${needsDensity ? fld("Densitas seragam <span class='muted xs'>t/m³</span>", num("density", w.density, "mis. 1.8")) : ""}
    </div>
    <div class="row" style="margin-top:16px;gap:10px">
      <span class="grow small muted">Parameter lain memakai nilai bawaan dan ditandai sebagai ASUMSI di Parameter.</span>
      <button class="btn primary" data-act="qRun" ${quickReady && !w.busy && !jobRunning ? "" : "disabled"}>${w.busy || jobRunning ? "Optimasi berjalan…" : "Jalankan Optimasi Cepat"}</button>
    </div>
  </div>` : "";

  let resultCard = "";
  if (jobRunning) {
    const j = S.job;
    const st = j.stages?.[j.stage] ? tr(j.stages[j.stage]) : "Memproses…";
    resultCard = `<div class="card" style="margin-top:16px">
      <div class="cardhead"><h2>3 · Progres optimasi</h2><span class="num small muted">${fmt(j.elapsed, 0)} s · ${fmt(j.fraction * 100, 0)}%</span></div>
      <div class="small muted" style="margin-bottom:8px">${esc(st)}</div>
      <div class="bar"><div style="width:${fmt(j.fraction * 100, 0)}%"></div></div>
    </div>`;
  } else if (jobError) {
    resultCard = `<div class="card" style="margin-top:16px"><div class="banner bad small">${esc(S.job.error)}</div></div>`;
  } else if (hasQuickResults) {
    const r = S.results, k = r.kpis;
    resultCard = `<div class="card" style="margin-top:16px">
      <div class="cardhead"><h2>3 · Ringkasan KPI &amp; Pratinjau 3D</h2><span class="lbl">RF ${fmt(k.final_rf, 2)} · ${k.periods ?? "–"} periode</span></div>
      <div class="grid g3">
        ${kpi("NPV rencana", mUSD(k.npv_plan), "jt USD", `diskonto ${pcts(k.discount_rate, 0)}/tahun`, "", "accent")}
        ${kpi("Nilai tak terdiskonto", mUSD(k.value_undiscounted), "jt USD", `RF ${fmt(k.final_rf, 2)}`)}
        ${kpi("Rock", mt(k.rock_t), "Mt", "total material tergali")}
        ${kpi("Umpan (ore)", mt(k.ore_t), "Mt", `strip ratio ${fmt(k.strip_ratio, 2)} t/t`)}
        ${kpi("Waste", mt(k.waste_t), "Mt", "")}
        ${kpi("Kedalaman maks", fmt(k.max_depth_m, 0), "m", `crest RL ${fmt(k.crest_rl, 1)} · toe RL ${fmt(k.toe_rl, 1)}`)}
      </div>
      <div id="quick-plot3d" style="height:400px;margin-top:16px;border:1px solid var(--line);border-radius:6px"></div>
      <div class="row" style="margin-top:14px;gap:10px;flex-wrap:wrap">
        <a class="btn primary" data-go="ringkasan">Buka Ringkasan Lengkap →</a>
        <a class="btn" data-go="3d">Buka 3D &amp; Penampang →</a>
        <a class="btn" data-go="parameter">Ubah Parameter Lengkap →</a>
      </div>
    </div>`;
  }

  return `<div class="grid g2">
    <div class="card">
      <div class="cardhead"><h2>1 · Sumber data</h2><span class="lbl">sampel atau CSV lokal</span></div>
      ${fld("Nama proyek", `<input type="text" data-on="wset" data-path="title" value="${esc(w.title)}" placeholder="mis. Quick Pit Blok A">`, slug() ? `folder: projects/${esc(slug())}` : "")}
      <div class="fld" style="margin-top:12px">
        <label for="q-sample">Dataset contoh</label>
        <div class="row" style="gap:8px;flex-wrap:wrap">
          <select id="q-sample" data-on="qSamplePick" style="flex:1;min-width:0">${sampleOpts || `<option value="">— tidak ada sampel —</option>`}</select>
          <button class="btn" data-act="qUseSample" ${S.projects.length ? "" : "disabled"}>Muat sampel</button>
        </div>
      </div>
      <div class="drops" style="margin-top:12px">
        ${drop("block", "Unggah model blok CSV", "CSV (pusat blok, satu baris per blok)", b && `${b.file} · ${fmtInt(i.rows)} blok`)}
        ${drop("surface", "Topografi (opsional)", "DXF atau CSV XYZ", w.surface && `${w.surface.file}`)}
      </div>
      ${uploading}
    </div>
    <div class="card">
      <div class="cardhead"><h2>Pra-validasi &amp; Estimasi RAM</h2><span class="lbl">instan sebelum run</span></div>
      ${precheck}
    </div>
  </div>${paramsCard}${resultCard}`;
}

export function render() {
  if (S.demoMode) return `<div class="page">${pageHead(t("Gunakan data Anda sendiri"), t("Jalankan PitOpt secara lokal untuk mengolah model blok Anda."), "")}
    <div class="card demo-own-data"><span class="tagc info">${t("WEB WORKSPACE")}</span><h2>${t("Gunakan model blok Anda sendiri")}</h2>
      <p>${t("Workspace web ini memakai dataset studi kasus yang sudah dihitung. Unggah data dan optimasi pit baru dijalankan di aplikasi desktop lokal, sehingga block model dan DXF Anda tetap di komputer Anda. Hasil desain wajib ditinjau Competent Person sesuai standar industri.")}</p>
      <ul class="demo-gets"><li>${t("Unggah model blok CSV dan topografi DXF Anda sendiri")}</li><li>${t("Jalankan optimasi pit penuh: shell RAF, pit by pit, pushback, jadwal, sensitivitas")}</li><li>${t("Ekspor Excel, PDF, DXF dan viewer 3D")}</li><li>${t("Gratis dan open source (AGPL) — data tidak pernah meninggalkan komputer Anda")}</li></ul>
      <div class="demo-actions"><a class="btn primary" href="${esc(S.demoRepoUrl)}/blob/main/docs/INSTALLATION.md" target="_blank" rel="noopener noreferrer">${t("Panduan instalasi lokal →")}</a><a class="btn" href="${esc(S.demoRepoUrl)}" target="_blank" rel="noopener noreferrer">★ ${t("Star di GitHub")}</a></div>
      <div class="note demo-install"><b>${t("Mulai cepat · Windows, macOS, Linux (Python 3.10+)")}</b><pre class="demo-install-code">git clone ${esc(S.demoRepoUrl)}.git\ncd pitopt\nPitOpt.bat            # Windows\nbash PitOpt.command   # macOS\nbash scripts/start_ui.sh  # Linux</pre><span class="small">${t("Instalasi pertama beberapa menit; dataset studi kasus sudah dijalankan saat aplikasi terbuka. Panduan lengkap ada di panduan instalasi lokal.")}</span></div>
    </div>
    <div class="card demo-own-data"><h2>${t("Coba workflow data sampel di sini")}</h2><p>${t("Pilih salah satu project sintetis dari menu project. Di Desain Detail, Anda bisa mengubah parameter bench, sektor, dan ramp, lalu generate ulang desain. Perubahan hanya disimpan sementara di memori demo ini; upload data dan optimasi pit strategis baru perlu dijalankan secara lokal.")}</p><a class="btn" href="#/d-generate">${t("Buka Desain Detail →")}</a></div>
  </div>`;

  const modeTabs = `<div class="tabs" role="tablist"><button role="tab" aria-selected="${w.mode === "quick"}" data-act="wMode" data-v="quick" class="${w.mode === "quick" ? "on" : ""}">Estimasi Cepat (1 layar)</button><button role="tab" aria-selected="${w.mode === "full"}" data-act="wMode" data-v="full" class="${w.mode === "full" ? "on" : ""}">Pengaturan Lengkap</button></div>`;
  if (w.mode === "quick") {
    return `<div class="page">${pageHead("Estimasi Pit Cepat", "pilih sampel atau unggah CSV, validasi RAM instan, jalankan, dan lihat KPI serta 3D", modeTabs)}
    ${w.error ? `<div class="banner bad small" style="margin-bottom:12px">${esc(w.error)}</div>` : ""}
    ${renderQuick()}</div>`;
  }

  const b = w.block, i = b?.info, cols = i?.columns || [], numeric = i?.numeric || [];
  const uploading = w.progress ? `<div class="banner small" style="margin-top:12px">Mengunggah ${esc(w.progress.name)} — ${fmt(w.progress.pct * 100, 0)}%<div class="bar"><div style="width:${w.progress.pct * 100}%"></div></div></div>` : "";
  const step2 = b ? `<div class="card" style="margin-top:16px"><div class="cardhead"><h2>2 · Kolom &amp; ukuran blok</h2><span class="lbl">${fmtInt(i.rows)} blok · ${cols.length} kolom</span></div>
    ${(w.warnings || []).map((x) => `<div class="banner warn small" style="margin-bottom:10px">${esc(x)}</div>`).join("")}
    <div class="pgrid">
      ${fld("CRS (opsional)", `<input type="text" data-on="wset" data-path="crs" value="${esc(w.crs)}" placeholder="EPSG:32748">`)}${fld("Datum vertikal (opsional)", `<input type="text" data-on="wset" data-path="vertical_datum" value="${esc(w.vertical_datum)}">`)}
      ${fld("Easting (X)", sel("map.x_col", cols, w.map.x_col, "pilih…"))}${fld("Northing (Y)", sel("map.y_col", cols, w.map.y_col, "pilih…"))}${fld("Elevasi (Z)", sel("map.z_col", cols, w.map.z_col, "pilih…"), "Koordinat harus pusat blok.")}
      ${fld("Densitas", sel("map.density_col", numeric, w.map.density_col, "seragam (isi angka)"))}
      ${w.map.density_col ? "" : fld("Densitas seragam <span class='muted xs'>t/m³</span>", num("density", w.density))}
      ${fld("Domain / litologi", sel("map.domain_col", cols, w.map.domain_col))}${fld("Kelas sumberdaya", sel("map.class_col", cols, w.map.class_col))}
      ${["dx", "dy", "dz"].map((k) => w.map[`${k}_col`] ? fld(`Ukuran ${k}`, sel(`map.${k}_col`, numeric, w.map[`${k}_col`], "seragam")) : fld(`Ukuran ${k} <span class='muted xs'>m</span>`, `${num(`size.${k}`, w.size[k])}`, i.spacing?.[k[1]] ? `Terdeteksi dari jarak antar-pusat: ${fmt(i.spacing[k[1]], 2)} m` : "")).join("")}
    </div>
    ${w.uniques.class_col ? `<div class="fld" style="margin-top:14px"><label>Kelas yang boleh diproses (bijih)</label><div class="row" style="flex-wrap:wrap;gap:12px">${w.uniques.class_col.values.map((u) => `<label class="chk"><input type="checkbox" data-on="wlist" data-list="include_classes" data-v="${esc(u.value)}" ${w.include_classes.includes(u.value) ? "checked" : ""}> ${esc(u.value)} <span class="muted xs">${fmtInt(u.count)}</span></label>`).join("")}</div><div class="hint">Kelas lain tetap digali bila di dalam pit, tanpa pendapatan. Kosong = semua kelas.</div></div>` : ""}
    ${w.uniques.domain_col ? `<div class="fld" style="margin-top:14px"><label>Domain yang boleh jadi umpan</label><div class="row" style="flex-wrap:wrap;gap:12px">${w.uniques.domain_col.values.map((u) => `<label class="chk"><input type="checkbox" data-on="wlist" data-list="ore_domains" data-v="${esc(u.value)}" ${w.ore_domains.includes(u.value) ? "checked" : ""}> ${esc(u.value)} <span class="muted xs">${fmtInt(u.count)}</span></label>`).join("")}</div><div class="hint">Overburden dan batuan dasar bukan umpan berapa pun kadarnya. Kosong = semua domain.</div></div>` : ""}
    <div style="overflow:auto;margin-top:14px"><table class="t"><thead><tr>${cols.map((c) => `<th class="l">${esc(c)}</th>`).join("")}</tr></thead><tbody>${i.preview.map((r) => `<tr>${r.map((v) => `<td class="l num">${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>` : "";

  const rb = w.rb, needs = b && (i.regular === false);
  const sizeCols = w.map.dx_col && w.map.dy_col && w.map.dz_col;
  const rbNum = (path, v) => num(path, v);
  const step2b = b && (needs || rb.result) ? `<div class="card" style="margin-top:16px;border-color:${rb.result ? "var(--good)" : "var(--warn-line)"}"><div class="cardhead"><h2>${rb.result ? "Hasil reblock" : "Reblock — model tidak reguler"}</h2><span class="lbl">${rb.result ? "model blok diganti dengan hasil reblock" : "wajib sebelum optimasi"}</span></div>
    ${rb.result ? reblockResult(rb.result) : `<p class="small muted" style="margin:0 0 12px">Optimasi butuh satu grid reguler. Reblock menggabungkan sub-cell ke blok penambangan: grade dirata-ratakan menurut massa (atau volume bila tanpa densitas), domain/kelas diambil yang volumenya terbesar, dan volume dijaga persis.</p>
    ${rb.err ? `<div class="banner bad small" style="margin-bottom:10px">${esc(rb.err)}</div>` : ""}
    <div class="pgrid">
      ${sizeCols ? fld("Ukuran parent", `<div class="small muted" style="padding:8px 0">dari kolom ${esc(w.map.dx_col)}, ${esc(w.map.dy_col)}, ${esc(w.map.dz_col)}</div>`) : ["dx", "dy", "dz"].map((k) => fld(`Parent block ${k} <span class='muted xs'>m</span>`, rbNum(`rb.parent.${k}`, rb.parent[k]), k === "dx" ? "Ukuran blok induk sebelum dipecah." : "")).join("")}
      ${["dx", "dy", "dz"].map((k) => fld(`Blok penambangan ${k} <span class='muted xs'>m</span>`, rbNum(`rb.target.${k}`, rb.target[k]), k === "dx" ? "Kelipatan ukuran parent agar grid sejajar." : "")).join("")}
    </div>
    <div class="fld" style="margin-top:14px"><label>Kolom grade yang dirata-ratakan</label><div class="row" style="flex-wrap:wrap;gap:12px">${(i.numeric || []).filter((c) => ![w.map.x_col, w.map.y_col, w.map.z_col, w.map.density_col, w.map.dx_col, w.map.dy_col, w.map.dz_col].includes(c)).map((c) => `<label class="chk"><input type="checkbox" data-on="rbGrade" data-v="${esc(c)}" ${rb.grades.includes(c) ? "checked" : ""}> ${esc(c)}</label>`).join("")}</div></div>
    ${w.map.class_col ? `<label class="chk" style="margin-top:12px"><input type="checkbox" data-on="wset" data-path="rb.strip" data-bool="1" ${rb.strip ? "checked" : ""}> Gabungkan kelas berakhiran angka (mis. TERTUNJUK1 dan TERTUNJUK2)</label>` : ""}
    <div class="row" style="margin-top:14px"><span class="grow small muted">Domain dan kelas mengikuti pemetaan di atas.</span><button class="btn primary" data-act="rbRun" ${rb.busy ? "disabled" : ""}>${rb.busy ? "Reblock berjalan…" : "Jalankan reblock"}</button></div>`}</div>` : "";

  const step3 = b ? `<div class="card" style="margin-top:16px"><div class="cardhead"><h2>3 · Ekonomi</h2><span class="lbl">semua angka Anda; yang tidak diubah ditandai asumsi</span></div>
    <div class="pgrid">
      ${fld("Basis kadar", sel("eco.grade_basis", ["mass_percent", "volume_percent", "ppm", "gpt", "kgm3", "gm3"], w.eco.grade_basis, null))}
      ${fld("Mining recovery <span class='muted xs'>0–1</span>", num("eco.mining_recovery", w.eco.mining_recovery))}${fld("Dilusi <span class='muted xs'>0–1</span>", num("eco.dilution", w.eco.dilution))}${fld("Royalti <span class='muted xs'>0–1</span>", num("eco.royalty_rate", w.eco.royalty_rate))}
      ${fld("Biaya tambang <span class='muted xs'>USD/t</span>", num("eco.mining_cost_per_tonne", w.eco.mining_cost_per_tonne), "Wajib diisi.")}${fld("Biaya proses (umpan) <span class='muted xs'>USD/t</span>", num("eco.processing_cost_per_tonne", w.eco.processing_cost_per_tonne))}
    </div>
    <h3 style="margin:18px 0 8px;font-size:13px">Produk</h3>
    <div style="overflow:auto"><table class="t"><thead><tr><th class="l">Nama</th><th class="l">Kolom kadar</th><th>Harga</th><th class="l">Satuan</th><th>Recovery pabrik</th><th>Biaya proses USD/t</th><th>Biaya jual USD/t</th>${w.eco.grade_basis === "volume_percent" ? "<th>Densitas produk</th>" : ""}<th></th></tr></thead><tbody>
    ${w.products.map((p, n) => `<tr><td class="l"><input type="text" style="width:96px" data-on="wset" data-path="products.${n}.name" value="${esc(p.name)}"></td><td class="l">${sel(`products.${n}.grade_col`, numeric, p.grade_col, "pilih…")}</td>
      <td>${num(`products.${n}.price`, p.price)}</td><td class="l">${sel(`products.${n}.price_unit`, ["t", "kg", "g", "oz", "lb"], p.price_unit, null)}</td>
      <td>${num(`products.${n}.plant_recovery`, p.plant_recovery)}</td><td>${num(`products.${n}.processing_cost_per_tonne`, p.processing_cost_per_tonne)}</td><td>${num(`products.${n}.selling_cost_per_tonne`, p.selling_cost_per_tonne)}</td>
      ${w.eco.grade_basis === "volume_percent" ? `<td>${num(`products.${n}.density`, p.density)}</td>` : ""}<td>${w.products.length > 1 ? `<a data-act="wDelProduct" data-n="${n}">hapus</a>` : ""}</td></tr>`).join("")}</tbody></table></div>
    <button class="btn" style="margin-top:8px" data-act="wAddProduct">+ Produk</button>
    <h3 style="margin:18px 0 8px;font-size:13px">Geoteknik, jadwal</h3>
    <div class="pgrid">${fld("Sudut lereng overall <span class='muted xs'>°</span>", num("slope_angle", w.slope_angle), "Ganti dengan angka studi geoteknik.")}
      ${fld("Tinggi bench <span class='muted xs'>m</span>", num("bench_height", w.bench_height))}${fld("Sudut muka bench <span class='muted xs'>°</span>", num("bench_face_angle", w.bench_face_angle))}
      ${fld("Kapasitas umpan <span class='muted xs'>t/periode</span>", num("capacity", w.capacity), "Isi ini <b>atau</b> umur tambang; salah satu wajib untuk jadwal.")}${fld("Umur tambang <span class='muted xs'>periode</span>", num("periods", w.periods), "Kapasitas mengikuti umur yang Anda tetapkan.")}${fld("Diskonto <span class='muted xs'>0–1</span>", num("discount_rate", w.discount_rate))}</div></div>` : "";

  const ready = b && (w.block.info.regular !== false || w.rb.result) && w.map.x_col && w.map.y_col && w.map.z_col && slug() && (w.capacity || w.periods) && w.eco.mining_cost_per_tonne !== "" && w.products.every((p) => p.name && p.grade_col && p.price);
  return `<div class="page">${pageHead("Proyek baru dari data Anda", "unggah model blok (dan topografi), petakan kolom, isi ekonomi", modeTabs)}
  ${w.error ? `<div class="banner bad small" style="margin-bottom:12px">${esc(w.error)}</div>` : ""}
  <div class="card"><div class="cardhead"><h2>1 · Berkas</h2><span class="lbl">berkas tetap di komputer ini (server lokal)</span></div>
    <div class="pgrid" style="margin-bottom:14px">${fld("Nama proyek", `<input type="text" data-on="wset" data-path="title" value="${esc(w.title)}" placeholder="mis. Tambang Nikel Blok A">`, slug() ? `folder: projects/${esc(slug())}` : "")}</div>
    <div class="drops">${drop("block", "Model blok", "CSV (pusat blok, satu baris per blok)", b && `${b.file} · ${fmtInt(i.rows)} blok`)}${drop("surface", "Topografi (opsional)", "DXF (3DFACE/MESH/POLYLINE/POINT) atau CSV XYZ", w.surface && `${w.surface.file}${w.surface.info.points ? ` · ${fmtInt(w.surface.info.points)} titik` : ""}`)}</div>${uploading}
    <p class="xs muted" style="margin:10px 0 0">Tanpa topografi, seluruh model diperlakukan sebagai batuan dan pit dipotong pada puncak model. Data mentah tidak meninggalkan mesin ini.</p></div>
  ${step2}${step2b}${step3}
  ${b ? `<div class="row" style="margin-top:16px;gap:10px"><span class="grow small muted">Tidak ada nilai yang diisi otomatis tanpa tanda: yang tidak Anda ubah muncul sebagai ASUMSI di layar Parameter.</span><button class="btn primary" data-act="wCreate" ${ready && !w.busy ? "" : "disabled"}>${w.busy ? "Membuat…" : "Buat proyek"}</button></div>` : ""}</div>`;
}

const T = (m) => m[0].map((_, j) => m.map((row) => row[j]));
async function plotQuick3D(root) {
  const el = root.querySelector("#quick-plot3d");
  if (!el) return;
  try {
    const g = await ensureGrids3d();
    if (!g) return;
    const P = await loadPlotly();
    const surf = (z, color, name, opacity = 1) => ({ type: "surface", x: g.x, y: g.y, z: T(z), name, showscale: false, opacity, colorscale: [[0, color], [1, color]], hoverinfo: "name+z", lighting: { ambient: 0.65, diffuse: 0.6 } });
    const data = [surf(g.topo, "#6B7A3A", t("Topografi"), 0.85), surf(g.layers.face, "#8A6A3B", t("Face position"), 1)];
    const dark = document.documentElement.dataset.theme === "dark";
    const xr = g.x[g.x.length - 1] - g.x[0], yr = g.y[g.y.length - 1] - g.y[0], zs = g.topo.flat().filter((v) => v != null);
    const zr = Math.max(...zs) - Math.min(...zs) || 1;
    await P.react(el, data, {
      margin: { l: 0, r: 0, t: 0, b: 0 }, paper_bgcolor: "rgba(0,0,0,0)", font: { color: dark ? "#ddd" : "#14181D" },
      scene: { aspectmode: "manual", aspectratio: { x: 1, y: yr / xr, z: (zr / xr) * S.ve }, xaxis: { title: "E" }, yaxis: { title: "N" }, zaxis: { title: "RL" } },
      showlegend: false,
    }, { responsive: true, displaylogo: false });
  } catch (e) { toast(e.message); }
}

export function mount(root) {
  if (w.error) root.querySelector(".page")?.scrollIntoView();
  if (w.mode === "quick" && w.quickProject && S.project === w.quickProject && S.results) plotQuick3D(root);
}

function setPath(path, value) {
  const parts = path.split(".");
  let node = w;
  for (const k of parts.slice(0, -1)) node = node[k];
  node[parts[parts.length - 1]] = value;
}

function buildSpec() {
  const m = w.map, size = w.size;
  const block_model = { crs: w.crs || null, vertical_datum: w.vertical_datum || null, volume_col: w.volume_col || null, file: w.block.file, x_col: m.x_col, y_col: m.y_col, z_col: m.z_col, domain_col: m.domain_col || null, class_col: m.class_col || null, density_col: m.density_col || null, density: w.density, include_classes: w.include_classes, ore_domains: w.ore_domains };
  for (const k of ["dx", "dy", "dz"]) { if (m[`${k}_col`]) block_model[`${k}_col`] = m[`${k}_col`]; else block_model[k] = size[k]; }
  return {
    title: w.title, slug: slug(), block_model,
    economics: { ...w.eco, products: w.products.map((p) => ({ ...p, density: p.density || undefined })) },
    surface: w.surface ? { file: w.surface.file, format: w.surface.format, ...(w.surface.map || {}) } : null,
    slope_angle: w.slope_angle, capacity: w.capacity || null, periods: w.periods || null,
    discount_rate: w.discount_rate, bench_height: w.bench_height, bench_face_angle: w.bench_face_angle, touched: [...w.touched],
  };
}

A.wMode = (el) => { w.mode = el.dataset.v; notify(); };
A.qSamplePick = (el) => { w.sampleSource = el.value; };
A.qUseSample = async () => {
  const src = w.sampleSource || document.getElementById("q-sample")?.value || S.projects[0]?.id;
  if (!src) return toast("Pilih dataset contoh dulu.");
  w.sampleSource = src;
  const target = `quick_${src}_${Date.now().toString(36).slice(-4)}`;
  w.title = `Quick ${src}`;
  w.slug = target;
  w.error = null; w.quickProject = null;
  try {
    const res = await api("/api/quick/sample", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_project: src, target_project: target }) });
    const d = res.defaults || {}, bm = d.block_model || {}, eco = d.economics || {};
    w.block = { file: res.file, info: res.inspect };
    w.surface = res.surface || null;
    w.map = {
      x_col: bm.x_col || res.inspect.guess?.x || "", y_col: bm.y_col || res.inspect.guess?.y || "", z_col: bm.z_col || res.inspect.guess?.z || "",
      density_col: bm.density_col || res.inspect.guess?.density || "", domain_col: bm.domain_col || res.inspect.guess?.domain || "",
      class_col: bm.class_col || res.inspect.guess?.class || "", dx_col: "", dy_col: "", dz_col: "",
    };
    w.size = { dx: bm.dx || res.inspect.spacing?.x || "", dy: bm.dy || res.inspect.spacing?.y || "", dz: bm.dz || res.inspect.spacing?.z || "" };
    w.density = bm.density ?? "";
    w.include_classes = bm.include_classes || [];
    w.ore_domains = bm.ore_domains || [];
    w.eco = {
      grade_basis: eco.grade_basis || "mass_percent",
      mining_recovery: eco.mining_recovery ?? 1, dilution: eco.dilution ?? 0, royalty_rate: eco.royalty_rate ?? 0,
      mining_cost_per_tonne: eco.mining_cost_per_tonne ?? "", processing_cost_per_tonne: eco.processing_cost_per_tonne ?? 0,
    };
    w.products = (eco.products?.length ? eco.products : fresh().products).map((p) => ({
      name: p.name || "", grade_col: p.grade_col || "", price: p.price ?? "", price_unit: p.price_unit || "t",
      plant_recovery: p.plant_recovery ?? 1, processing_cost_per_tonne: p.processing_cost_per_tonne ?? 0,
      selling_cost_per_tonne: p.selling_cost_per_tonne ?? 0, density: p.density ?? "",
    }));
    w.slope_angle = d.slope_angle ?? 45;
    w.capacity = d.capacity ?? "";
    w.periods = d.periods ?? "";
    w.discount_rate = d.discount_rate ?? 0.1;
    w.bench_height = d.bench_height || w.size.dz || "";
    w.bench_face_angle = d.bench_face_angle ?? 65;
    w.warnings = [...(res.inspect.warnings || [])];
    w.touched = new Set(["slope_angle", "mining_cost_per_tonne", "processing_cost_per_tonne"]);
    if (w.capacity) w.touched.add("capacity");
    if (w.periods) w.touched.add("periods");
    if (w.density) w.touched.add("density");
    checkExtents();
    await refreshRam();
    notify();
  } catch (e) { w.error = e.message; notify(); }
};

A.qRun = async () => {
  w.busy = true; w.error = null; notify();
  try {
    const r = await api("/api/create-project", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildSpec()) });
    await loadProjects2();
    await select(r.project, r.scenario);
    w.quickProject = r.project;
    const job = await api("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: r.project, scenario: r.scenario, overrides: {}, save_as: null }) });
    S.job = { id: job.job, project: r.project, sourceScenario: r.scenario, selectionVersion: S.selectionVersion, status: "running", scenario: job.scenario, log: [], stage: 0, stages: [], fraction: 0, next: 0, elapsed: 0 };
    w.busy = false;
    notify();
    pollJob();
  } catch (e) { w.busy = false; w.error = e.message; notify(); }
};

A.wfile = (el) => { const f = el.files[0]; if (f) upload(f, el.dataset.kind); };
A.wset = async (el) => {
  const path = el.dataset.path;
  let v = el.type === "checkbox" ? el.checked : el.dataset.num ? (el.value.trim() === "" ? "" : Number(el.value.replace(",", "."))) : el.value;
  if (el.dataset.num && v !== "" && Number.isNaN(v)) { toast("Angka tidak valid."); return notify(); }
  setPath(path, v);
  if (path === "title" && !w.slug) w.slug = "";
  const touch = { slope_angle: "slope_angle", capacity: "capacity", periods: "periods", discount_rate: "discount_rate", bench_height: "bench_height", bench_face_angle: "bench_face_angle", "eco.mining_recovery": "mining_recovery", "eco.dilution": "dilution", density: "density", "eco.mining_cost_per_tonne": "mining_cost_per_tonne", "eco.processing_cost_per_tonne": "processing_cost_per_tonne" }[path];
  if (touch) w.touched.add(touch);
  if (path === "map.domain_col") { w.ore_domains = []; await loadUniques("domain_col"); }
  if (path === "map.class_col") { w.include_classes = []; await loadUniques("class_col"); }
  if (w.mode === "quick" && (path === "slope_angle" || path.startsWith("size."))) await refreshRam();
  notify();
};
A.wlist = (el) => { const l = w[el.dataset.list], v = el.dataset.v; el.checked ? l.push(v) : l.splice(l.indexOf(v), 1); notify(); };
A.wAddProduct = () => { w.products.push({ name: "", grade_col: "", price: "", price_unit: "t", plant_recovery: 1, processing_cost_per_tonne: 0, selling_cost_per_tonne: 0, density: "" }); notify(); };
A.wDelProduct = (el) => { w.products.splice(+el.dataset.n, 1); notify(); };
A.wCreate = async () => {
  w.busy = true; w.error = null; notify();
  try {
    const r = await api("/api/create-project", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildSpec()) });
    await loadProjects2(); await select(r.project, r.scenario);
    w = fresh(); toast("Proyek dibuat. Periksa parameter lalu jalankan optimasi."); location.hash = "#/parameter";
  } catch (e) { w.busy = false; w.error = e.message; notify(); }
};
A.newProject = () => { document.getElementById("modal")?.remove(); w = fresh(); location.hash = "#/unggah"; notify(); };

function reblockResult(r) {
  const diff = r.volume_difference;
  const p = r.parent_size;
  return `<div class="kv" style="margin-bottom:12px"><span>Blok hasil</span><span>${fmtInt(r.blocks)}</span><span>Parent terdeteksi</span><span>${fmt(p.x, 1)} × ${fmt(p.y, 1)} × ${fmt(p.z, 1)} m</span>
    <span>Volume sumber</span><span>${fmtInt(r.source_volume)} m³</span><span>Volume hasil</span><span>${fmtInt(r.output_volume)} m³</span>
    <span>Selisih volume</span><span class="${Math.abs(diff) < 1e-3 ? "good" : "bad"}">${fmt(diff, 3)} m³</span><span>Bobot grade</span><span>${r.grade_weighting === "mass" ? "massa" : "volume"}</span>
    <span>Blok terisi &lt; 50% (tepi)</span><span>${fmt(r.partial_fill_below_half * 100, 1)}%</span></div>
    ${r.by_category.length ? `<div style="overflow:auto;max-height:180px"><table class="t"><thead><tr>${Object.keys(r.by_category[0]).map((c) => `<th class="l">${esc(c)}</th>`).join("")}</tr></thead><tbody>${r.by_category.map((row) => `<tr>${Object.values(row).map((v, n) => `<td class="${n < Object.keys(row).length - 1 ? "l" : ""}">${typeof v === "number" ? fmtInt(v) : esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div><p class="xs muted">Bandingkan volume per kategori dengan tabel sumberdaya resmi sebelum melanjutkan.</p>` : ""}`;
}
A.rbGrade = (el) => { const l = w.rb.grades, v = el.dataset.v; el.checked ? l.includes(v) || l.push(v) : l.splice(l.indexOf(v), 1); notify(); };
A.rbRun = async () => {
  const rb = w.rb, m = w.map, sizeCols = m.dx_col && m.dy_col && m.dz_col;
  rb.busy = true; rb.err = null; notify();
  const body = { project: slug(), file: w.block.file, x: m.x_col, y: m.y_col, z: m.z_col, density: m.density_col || null,
    grades: rb.grades, categories: [m.domain_col, m.class_col].filter(Boolean), strip_digits: rb.strip && m.class_col ? [m.class_col] : [],
    target: [rb.target.dx, rb.target.dy, rb.target.dz].map(Number) };
  if (sizeCols) Object.assign(body, { size_x: m.dx_col, size_y: m.dy_col, size_z: m.dz_col });
  else body.parent = [rb.parent.dx, rb.parent.dy, rb.parent.dz].map(Number);
  try {
    const r = await api("/api/reblock", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const c = r.columns;
    w.block = { file: r.file, info: r.inspect, reblocked: true };
    w.map = { x_col: c.x, y_col: c.y, z_col: c.z, density_col: c.density || "", domain_col: m.domain_col || "", class_col: m.class_col || "", dx_col: "", dy_col: "", dz_col: "" };
    w.size = { dx: rb.target.dx, dy: rb.target.dy, dz: rb.target.dz };
    w.bench_height = rb.target.dz; w.volume_col = "volume"; w.include_classes = []; w.ore_domains = [];
    w.warnings = (r.inspect.warnings || []).slice(); rb.result = r; rb.busy = false;
    await loadUniques("domain_col"); await loadUniques("class_col"); checkExtents();
  } catch (e) { rb.busy = false; rb.err = e.message; }
  notify();
};
