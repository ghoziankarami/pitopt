// New project from the user's own files: upload → map columns → economics → create.
import { S, notify, loadProjects2, select } from "../store.js";
import { A } from "../actions.js";
import { fmt, fmtInt, esc, api, qs, toast } from "../util.js";
import { pageHead } from "./common.js";
import { t } from "../i18n.js";

const fresh = () => ({
  title: "", slug: "", block: null, surface: null, progress: null, busy: false, error: null, warnings: [],
  map: {}, size: {}, density: "", uniques: {}, include_classes: [], ore_domains: [],
  eco: { grade_basis: "mass_percent", mining_recovery: 1, dilution: 0, royalty_rate: 0, mining_cost_per_tonne: "", processing_cost_per_tonne: 0 },
  products: [{ name: "", grade_col: "", price: "", price_unit: "t", plant_recovery: 1, processing_cost_per_tonne: 0, selling_cost_per_tonne: 0, density: "" }],
  rb: { target: { dx: "", dy: "", dz: "" }, parent: { dx: "", dy: "", dz: "" }, grades: [], strip: false, busy: false, err: null, result: null },
  volume_col: "", slope_angle: 45, capacity: "", periods: "", discount_rate: 0.1, bench_height: "", bench_face_angle: 65, touched: new Set(),
});
let w = fresh();
const slug = () => (w.slug || w.title).trim().toLowerCase().replace(/[^0-9a-z_-]+/g, "_").replace(/^_+|_+$/g, "");

function upload(file, kind) {
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
  w.map = { x_col: info.guess?.x || "", y_col: info.guess?.y || "", z_col: info.guess?.z || "", density_col: info.guess?.density || "", domain_col: info.guess?.domain || "", class_col: info.guess?.class || "", dx_col: info.guess?.dx || "", dy_col: info.guess?.dy || "", dz_col: info.guess?.dz || "" };
  w.size = { dx: info.spacing?.x || "", dy: info.spacing?.y || "", dz: info.spacing?.z || "" };
  w.bench_height = info.spacing?.z || "";
  w.volume_col = "";
  const skip = new Set([w.map.x_col, w.map.y_col, w.map.z_col, w.map.density_col, w.map.dx_col, w.map.dy_col, w.map.dz_col]);
  w.rb = { ...fresh().rb, grades: (info.numeric || []).filter((c) => !skip.has(c)) };
  const grades = Object.keys(info.stats || {}).filter((c) => c !== w.map.density_col);
  if (grades.length === 1 && !w.products[0].grade_col) { w.products[0].grade_col = grades[0]; w.products[0].name ||= grades[0].replace(/_?(PCT|PPM|GPT)$/i, ""); }
  w.warnings = [...(info.warnings || [])];
  await loadUniques("domain_col"); await loadUniques("class_col");
  checkExtents();
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

const sel = (path, options, value, blank = "— tidak ada —") => `<select data-on="wset" data-path="${path}">${blank === null ? "" : `<option value="">${blank}</option>`}${options.map((o) => `<option ${o === value ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
const num = (path, value, ph = "") => `<input type="text" inputmode="decimal" data-on="wset" data-path="${path}" data-num="1" value="${esc(value ?? "")}" placeholder="${esc(ph)}">`;
const fld = (label, input, hint = "") => `<div class="fld"><label>${label}</label>${input}${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
const drop = (kind, title, hint, done) => `<label class="drop ${done ? "done" : ""}"><input type="file" hidden data-on="wfile" data-kind="${kind}" accept="${kind === "block" ? ".csv" : ".dxf,.csv"}">
  <b>${title}</b><span class="muted small">${done ? `<span class="good">✓</span> ${esc(done)}` : hint}</span></label>`;

export function render() {
  if (S.demoMode) return `<div class="page">${pageHead(t("Gunakan data Anda sendiri"), t("Jalankan PitOpt secara lokal untuk mengolah model blok Anda."), "")}
    <div class="card demo-own-data"><span class="tagc info">${t("DEMO PUBLIK")}</span><h2>${t("Gunakan model blok Anda sendiri")}</h2>
      <p>${t("Demo ini memakai data sampel sintetis yang sudah tersedia. Demo publik tidak menerima unggahan atau menjalankan optimasi pit strategis baru. Untuk menjaga model privat dan menjalankan optimasi penuh, instal PitOpt di komputer Anda.")}</p>
      <div class="demo-actions"><a class="btn primary" href="${esc(S.demoRepoUrl)}#web-ui" target="_blank" rel="noopener noreferrer">${t("Panduan instalasi lokal →")}</a><a class="btn" href="${esc(S.demoRepoUrl)}" target="_blank" rel="noopener noreferrer">${t("Lihat source code GitHub")}</a></div>
      <div class="note demo-install"><b>${t("Mulai cepat · macOS / Linux")}</b><pre class="demo-install-code">git clone https://github.com/ghoziankarami/pitopt.git\ncd pitopt\nmake setup &amp;&amp; make ui</pre><span class="small">${t("Petunjuk untuk Windows tersedia di panduan instalasi.")}</span></div>
    </div>
    <div class="card demo-own-data"><h2>${t("Coba workflow data sampel di sini")}</h2><p>${t("Pilih salah satu project sintetis dari menu project. Di Desain Detail, Anda bisa mengubah parameter bench, sektor, dan ramp, lalu generate ulang desain. Perubahan hanya disimpan sementara di memori demo ini; upload data dan optimasi pit strategis baru perlu dijalankan secara lokal.")}</p><a class="btn" href="#/d-generate">${t("Buka Desain Detail →")}</a></div>
  </div>`;
  const b = w.block, i = b?.info, cols = i?.columns || [], numeric = i?.numeric || [];
  const uploading = w.progress ? `<div class="banner small" style="margin-top:12px">Mengunggah ${esc(w.progress.name)} — ${fmt(w.progress.pct * 100, 0)}%<div class="bar"><div style="width:${w.progress.pct * 100}%"></div></div></div>` : "";
  const step2 = b ? `<div class="card" style="margin-top:16px"><div class="cardhead"><h2>2 · Kolom &amp; ukuran blok</h2><span class="lbl">${fmtInt(i.rows)} blok · ${cols.length} kolom</span></div>
    ${(w.warnings || []).map((x) => `<div class="banner warn small" style="margin-bottom:10px">${esc(x)}</div>`).join("")}
    <div class="pgrid">
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
      ${fld("Basis kadar", sel("eco.grade_basis", ["mass_percent", "volume_percent", "ppm", "g_per_t", "fraction"], w.eco.grade_basis, null))}
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
  return `<div class="page">${pageHead("Proyek baru dari data Anda", "unggah model blok (dan topografi), petakan kolom, isi ekonomi", "")}
  ${w.error ? `<div class="banner bad small" style="margin-bottom:12px">${esc(w.error)}</div>` : ""}
  <div class="card"><div class="cardhead"><h2>1 · Berkas</h2><span class="lbl">berkas tetap di komputer ini (server lokal)</span></div>
    <div class="pgrid" style="margin-bottom:14px">${fld("Nama proyek", `<input type="text" data-on="wset" data-path="title" value="${esc(w.title)}" placeholder="mis. Tambang Nikel Blok A">`, slug() ? `folder: projects/${esc(slug())}` : "")}</div>
    <div class="drops">${drop("block", "Model blok", "CSV (pusat blok, satu baris per blok)", b && `${b.file} · ${fmtInt(i.rows)} blok`)}${drop("surface", "Topografi (opsional)", "DXF (3DFACE/MESH/POLYLINE/POINT) atau CSV XYZ", w.surface && `${w.surface.file}${w.surface.info.points ? ` · ${fmtInt(w.surface.info.points)} titik` : ""}`)}</div>${uploading}
    <p class="xs muted" style="margin:10px 0 0">Tanpa topografi, seluruh model diperlakukan sebagai batuan dan pit dipotong pada puncak model. Data mentah tidak meninggalkan mesin ini.</p></div>
  ${step2}${step2b}${step3}
  ${b ? `<div class="row" style="margin-top:16px;gap:10px"><span class="grow small muted">Tidak ada nilai yang diisi otomatis tanpa tanda: yang tidak Anda ubah muncul sebagai ASUMSI di layar Parameter.</span><button class="btn primary" data-act="wCreate" ${ready && !w.busy ? "" : "disabled"}>${w.busy ? "Membuat…" : "Buat proyek"}</button></div>` : ""}</div>`;
}

export function mount(root) { if (w.error) root.querySelector(".page")?.scrollIntoView(); }

function setPath(path, value) {
  const parts = path.split(".");
  let node = w;
  for (const k of parts.slice(0, -1)) node = node[k];
  node[parts[parts.length - 1]] = value;
}
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
  notify();
};
A.wlist = (el) => { const l = w[el.dataset.list], v = el.dataset.v; el.checked ? l.push(v) : l.splice(l.indexOf(v), 1); notify(); };
A.wAddProduct = () => { w.products.push({ name: "", grade_col: "", price: "", price_unit: "t", plant_recovery: 1, processing_cost_per_tonne: 0, selling_cost_per_tonne: 0, density: "" }); notify(); };
A.wDelProduct = (el) => { w.products.splice(+el.dataset.n, 1); notify(); };
A.wCreate = async () => {
  w.busy = true; w.error = null; notify();
  const m = w.map, size = w.size;
  const block_model = { volume_col: w.volume_col || null, file: w.block.file, x_col: m.x_col, y_col: m.y_col, z_col: m.z_col, domain_col: m.domain_col || null, class_col: m.class_col || null, density_col: m.density_col || null, density: w.density, include_classes: w.include_classes, ore_domains: w.ore_domains };
  for (const k of ["dx", "dy", "dz"]) { if (m[`${k}_col`]) block_model[`${k}_col`] = m[`${k}_col`]; else block_model[k] = size[k]; }
  const spec = { title: w.title, slug: slug(), block_model, economics: { ...w.eco, products: w.products.map((p) => ({ ...p, density: p.density || undefined })) },
    surface: w.surface ? { file: w.surface.file, format: w.surface.format, ...(w.surface.map || {}) } : null,
    slope_angle: w.slope_angle, capacity: w.capacity || null, periods: w.periods || null, discount_rate: w.discount_rate, bench_height: w.bench_height, bench_face_angle: w.bench_face_angle, touched: [...w.touched] };
  try {
    const r = await api("/api/create-project", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(spec) });
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
