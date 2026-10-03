// 06 · Ekspor — what gets written, the DXF layer structure, and the provenance every file carries.
import { A } from "../actions.js";
import { esc, fmt } from "../util.js";
import { D, ensure, exportFiles } from "../design/core.js";
import { gate, notice, page } from "../design/ui.js";

const OUTPUTS = [
  ["benches", "Bench — crest dan toe", "polyline 3D tertutup · dipisah per elevasi", "DXF · AC1024"],
  ["ramp", "Ramp — centerline dan tepi", "satu jalur dasar → puncak", "DXF · AC1024"],
  ["json", "Sesi desain + provenance", "parameter per sektor, hasil validasi, hash shell sumber", "JSON"],
  ["sectors", "Garis batas sektor", "garis azimut di elevasi crest", "DXF · AC1024"],
  ["tables", "Tabel rekonsiliasi dan validasi", "shell → desain PitOpt → desain praktis · per bench", "CSV · XLSX"],
];
let picked = new Set(OUTPUTS.map((o) => o[0]));

export function render() {
  ensure();
  const g = gate("Ekspor desain", { needResult: true });
  if (g) return g;
  const doc = D.result.document, prov = doc.provenance, n = doc.benches.length;
  const first = doc.benches[0], last = doc.benches.at(-1), rl = (v) => String(Math.round(v)).replace(".", "_");
  const asum = prov.parameters.filter((p) => p.source === "ASUMSI").length;
  const problems = doc.findings.filter((f) => f.status !== "OK").length;
  const shown = { ...prov, parameters: prov.parameters.filter((p) => p.source !== "DEFAULT").slice(0, 5) };
  return page("Ekspor desain", "Langkah 5 dari 5 · bench dan ramp sebagai DXF, sesi sebagai JSON dengan provenance. Setiap output membawa parameter, asumsi, versi engine, dan tanggal.", "", `
  ${notice()}
  <div class="banners" style="margin-bottom:16px"><div class="bh"><span style="font-size:18px">⚠</span><b>Yang perlu diketahui sebelum file dipakai di CAD atau dikirim ke CP</b></div>
    <div class="brow"><span class="tagc peringatan">VALIDASI</span><span class="txt">${problems ? `Desain ini punya <b class="num">${problems}</b> hal yang perlu perhatian. Ekspor tetap boleh; status ini otomatis tertulis di blok provenance dan tidak bisa dihapus dari file.` : "Semua validasi lolos. Statusnya tetap tertulis di blok provenance."}</span><a data-go="d-validasi">Buka Validasi →</a></div>
    ${asum ? `<div class="brow"><span class="tagc asumsi">ASUMSI</span><span class="txt"><b class="num">${asum}</b> parameter belum berdokumen — ikut tercatat sebagai asumsi.</span><a data-go="d-sektor">Buka Crest &amp; Sektor →</a></div>` : ""}</div>
  <div class="dd-cols2">
    <div>
      <div class="card"><div class="cardhead"><h2>Output</h2><span class="lbl">centang yang akan ditulis ke folder hasil skenario</span></div>
        <table class="t"><thead><tr><th class="l"></th><th class="l">Output</th><th class="l">Format</th></tr></thead><tbody>${OUTPUTS.map(([k, name, sub, fmtName]) => `<tr><td class="l"><input type="checkbox" data-act="dPick" data-k="${k}" ${picked.has(k) ? "checked" : ""} ${k === "json" ? "disabled" : ""}></td><td class="l"><b>${name}</b><div class="xs muted">${sub}</div></td><td class="l num small">${fmtName}</td></tr>`).join("")}</tbody></table>
        <p class="xs muted" style="margin:8px 0">JSON selalu ditulis: ia membawa provenance dan status validasi.</p>
        <div class="row" style="gap:10px;margin-top:6px"><span class="num small muted grow">folder hasil skenario ${esc(D.state.meta.scenario)}</span><button class="btn primary" data-act="dExport">Ekspor terpilih (${picked.size} jenis)</button></div>
        ${D.exported ? `<div style="margin-top:14px"><div class="navh" style="padding:0 0 6px">FILE DITULIS</div>${D.exported.map((f) => `<div class="row small" style="padding:5px 0;border-top:1px solid var(--line2)"><span class="tagc ok">OK</span><span class="num grow">${esc(f.name)}</span><span class="num muted">${fmt(f.bytes / 1024, 0)} KB</span><a data-act="dDownload" data-file="${esc(f.name)}">Unduh</a></div>`).join("")}</div>` : ""}
        </div>
      <div class="card"><div class="cardhead"><h2>Struktur layer DXF</h2><span class="lbl">terbuka terpisah di AutoCAD dan Surpac</span></div>
        <table class="t"><tbody>
          <tr><td class="l num">PD_CREST_${rl(first.crest_rl)} … PD_CREST_${rl(last.crest_rl)}</td><td class="l muted">${n} layer · polyline 3D</td></tr>
          <tr><td class="l num">PD_TOE_${rl(first.toe_rl)} … PD_TOE_${rl(last.toe_rl)}</td><td class="l muted">${n} layer · polyline 3D</td></tr>
          <tr><td class="l num">PD_RAMP_CL</td><td class="l muted">centerline · elevasi z = jalur nyata</td></tr>
          <tr><td class="l num">PD_RAMP_EDGE</td><td class="l muted">tepi kiri dan kanan</td></tr>
          <tr><td class="l num">PD_SECTOR</td><td class="l muted">${doc.sectors.length} garis batas · nama sektor</td></tr>
          <tr><td class="l num">PD_SHELL_REF</td><td class="l muted">opsional · crest shell RF ${fmt(prov.sourceShell.final_rf, 2)}</td></tr></tbody></table>
        <p class="xs muted" style="margin:8px 0 0">Satuan meter, sistem koordinat sama dengan shell PitOpt (tanpa transformasi). Format AC1024. Nama layer memakai RL ganjil dengan garis bawah karena titik tidak boleh ada di nama layer.</p></div>
    </div>
    <div><div class="card"><div class="cardhead"><h2>Blok provenance</h2><span class="lbl">ikut di JSON sesi dan header DXF</span></div>
      <pre class="log prov">${esc(JSON.stringify({ provenance: shown }, null, 1))}</pre>
      <p class="xs muted" style="margin:8px 0 0">Status validasi dan asumsi wajib ikut selama ada masalah. Ditandai <span class="num">signedByCP: false</span> sampai ditandatangani orang yang berwenang.</p></div></div>
  </div>`);
}

A.dPick = (el) => { if (el.checked) picked.add(el.dataset.k); else picked.delete(el.dataset.k); import("../store.js").then((m) => m.notify()); };
A.dExport = () => exportFiles([...picked]);
A.dDownload = (el) => { location.href = `/api/download?project=${encodeURIComponent(D.key.split("/")[0])}&scenario=${encodeURIComponent(D.key.split("/")[1])}&file=${encodeURIComponent(el.dataset.file)}`; };
export function mount() {}
