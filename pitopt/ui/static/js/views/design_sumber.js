// 06 · Sumber shell — where the design starts from: the PitOpt run, its shell, the starting parameters and the
// block model, with a plan of the shell over the blocks.
import { D, ensure } from "../design/core.js";
import { legend, notice, page, gate, planControls } from "../design/ui.js";
import { paintPlan } from "../design/planview.js";
import { classColour } from "../design/plan.js";
import { esc, fmt, fmtInt } from "../util.js";

const src = (k) => D.state.provenance?.[k]?.source || "default";
const badge = (k) => `<span class="badge ${src(k)}">${{ dokumen: "DOKUMEN", asumsi: "ASUMSI", default: "DEFAULT" }[src(k)]}</span>`;
const kb = (n) => (n >= 1e6 ? `${fmt(n / 1e6, 1)} MB` : `${fmt(n / 1e3, 0)} KB`);

export function render() {
  ensure();
  const g = gate("Sumber shell");
  if (g) return g;
  const s = D.state, m = s.meta, v = s.verification, fp = s.final_pit, b = D.block;
  const clean = v.walls === 0 && v.cone === 0 && v.schedule === 0;
  const when = new Date(m.run_at).toLocaleString("id-ID", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  const file = (suffix) => s.files.find((f) => f.name.endsWith(suffix));
  const shellDxf = file("_pit_shell.dxf"), faceDxf = file("_pit_face_position.dxf");
  const row = (checked, disabled, name, sub, fname, size, tag) => `<tr class="${disabled ? "dim" : ""}"><td class="l"><input type="radio" name="perm" ${checked ? "checked" : ""} disabled> <b>${name}</b><div class="xs muted">${sub}</div></td>
    <td class="l num small">${fname}</td><td class="num">${size}</td><td class="l">${tag}</td></tr>`;
  const sector = s.sectors?.[0];
  const asum = s.assumptions.length;
  return page("Sumber shell", "Ambil hasil optimasi PitOpt sebagai titik awal desain detail (bench, sektor, ramp) — shell dibaca read-only.", "", `
  ${notice()}
  <div class="banners" style="border-color:var(--good-line);background:var(--good-bg);margin-bottom:16px"><div class="bh"><span class="tagc ok">RUN TERBACA</span>
    <span>Run PitOpt <b class="num">${esc(when)}</b> · engine ${esc(m.engine_version)} · verifikasi <span class="num">${v.walls} / ${v.cone} / ${v.schedule}</span> pelanggaran · skenario ${esc(m.scenario)}.</span>
    <span class="grow"></span><a data-act="showLog">Lihat log run →</a></div></div>
  <div class="dd-cols">
    <div>
      <div class="card"><div class="cardhead"><h2>Permukaan yang ditemukan</h2><span class="lbl">dibaca dari folder hasil run PitOpt</span></div>
        <table class="t"><thead><tr><th class="l" style="width:38%">Surfaces</th><th class="l">File</th><th>Size</th><th class="l">Status</th></tr></thead><tbody>
          ${row(true, false, `Pit final RF ${fmt(fp.rf, 2)}`, "mangkuk desain · sumber geometri", "tabel blok · in_pit", `${fmtInt(D.block?.blocks || 0)} blok`, `<span class="tagc ok">OK · dipilih</span>`)}
          ${row(false, !faceDxf, `Face position RF ${fmt(fp.rf, 2)}`, "shell dipotong topografi · overlay referensi", faceDxf?.name || "—", faceDxf ? kb(faceDxf.bytes) : "—", faceDxf ? `<span class="tagc ok">OK · overlay</span>` : `<span class="tagc info">tidak ada</span>`)}
          ${row(false, !shellDxf, "Pit shell (mangkuk)", "surface DXF dari desain bench seragam", shellDxf?.name || "—", shellDxf ? kb(shellDxf.bytes) : "—", shellDxf ? `<span class="tagc ok">OK · referensi</span>` : `<span class="tagc info">tidak ada</span>`)}
          ${row(false, true, "Akhir pushback", "satu shell per sesi · pilihan pushback", "pushback_*.dxf", "—", `<span class="tagc info">Fase 3 · staged</span>`)}
        </tbody></table>
        <p class="howto" style="margin:10px 0 0">Modul ini memakai <b>satu shell</b> sebagai panduan crest dan batas luar. Desain pushback bertahap (staged) menyusul setelah alur satu shell stabil. Impor DXF/surface manual belum tersedia.</p></div>
      <div class="card"><div class="cardhead"><h2>Parameter awal dari PitOpt</h2><span class="lbl">dipakai sebagai nilai global — bisa ditimpa per sektor</span></div>
        ${[["Slope overall optimasi", fmt(s.slope_deg, 1), "°", "slope.overall_angle_deg", "slope.overall_angle_deg"],
           ["Tinggi bench", fmt(s.params.bench_height, 1), "m", "design.bench_height", "design.bench_height"],
           ["Sudut muka bench", fmt(s.params.bench_face_angle_deg, 1), "°", "design.bench_face_angle_deg", "design.bench_face_angle_deg"],
           ["Lebar berm (dihitung)", sector ? fmt(sector.berm_width, 2) : "–", "m", "", "design.detail.berm.method"]]
          .map(([l, val, u, key, prov]) => `<div class="row" style="padding:8px 0;border-top:1px solid var(--line2);gap:14px"><span class="grow">${l}</span><span class="num" style="min-width:90px;text-align:right"><b>${val}</b> <span class="muted">${u}</span></span>${badge(prov)}<span class="num xs muted" style="width:210px">${key}</span></div>`).join("")}
        <p class="howto" style="margin:10px 0 0">Berm tidak diketik bebas: ia dihitung dari tinggi bench dan sudut muka lewat kriteria Ritchie, Ryan, sudut slope optimasi, atau manual — pilihannya ada di langkah Crest &amp; Sektor.</p></div>
      <div class="card"><div class="cardhead"><h2>Block model</h2><span class="lbl">dibaca dari folder hasil run PitOpt</span><span class="grow"></span><span class="tagc ok">OK · dipakai</span></div>
        ${b ? `<div class="kv"><span class="muted">File</span><span>${esc(b.file)}</span><span class="muted">Ukuran blok</span><span>${fmt(b.dx, 0)} × ${fmt(b.dy, 0)} × ${fmt(b.dz, 0)} m</span>
          <span class="muted">Jumlah blok</span><span>${fmtInt(b.blocks)}</span><span class="muted">Extent X · Y · Z</span><span>${["x", "y", "z"].map((k) => `${fmt(b.extent[k][0], 0)}…${fmt(b.extent[k][1], 0)}`).join(" · ")}</span>
          <span class="muted">Variabel</span><span>${b.attrs.filter((a) => a.type === "numeric").map((a) => esc(a.key)).join(", ")}</span></div>` : `<div class="empty">Memuat model blok…</div>`}
        <p class="howto" style="margin:10px 0 0">Block model hanya dipakai untuk visual dan rekonsiliasi; ia tidak memengaruhi geometri bench dan ramp.</p></div>
    </div>
    <div>
      <div class="card"><div class="cardhead"><h2>Pratinjau plan view</h2><span class="lbl">shell RF ${fmt(fp.rf, 2)} · garis putus = shell</span></div>
        <div class="xs" style="margin-bottom:8px">${planControls({ modes: true })}</div>
        <canvas id="dplan" class="plan" style="height:380px"></canvas>
        <div class="row xs muted" style="margin-top:8px"><span class="num">${D.plan ? `crest +${fmt(D.plan.shell_levels.at(-1) + D.plan.dz / 2, 0)} · lantai +${fmt(D.plan.shell_levels[0] - D.plan.dz / 2, 0)}` : ""}</span><span class="grow"></span><span class="num">${b ? `${fmt(b.dx, 0)} × ${fmt(b.dy, 0)} × ${fmt(b.dz, 0)} m/blok` : ""}</span></div>
        <div style="margin-top:10px">${D.plan ? legend(D.plan.classes, D.color) : ""}</div></div>
      <div class="card"><div class="cardhead"><h2>Pemeriksaan cepat</h2></div>
        ${s.qa.slice(0, 5).map((c) => `<div class="row small" style="padding:7px 0;border-top:1px solid var(--line2);gap:10px"><span class="tagc ${c.status === "ok" ? "ok" : c.status === "blokir" ? "blokir" : c.status === "info" ? "info" : "peringatan"}">${c.status === "ok" ? "OK" : c.status.toUpperCase()}</span><span>${esc(c.name)}. <span class="muted">${esc(c.detail)}</span></span></div>`).join("")}
        ${asum ? `<div class="row small" style="padding:7px 0;border-top:1px solid var(--line2);gap:10px"><span class="tagc asumsi">ASUMSI</span><span>${asum} parameter PitOpt belum berdokumen.</span><span class="grow"></span><a data-go="parameter">Buka Parameter →</a></div>` : ""}
      </div>
    </div>
  </div>`);
}

export function mount() {
  const c = document.getElementById("dplan");
  if (c && D.plan) paintPlan(c, { plan: D.plan, layers: D.layers, mode: D.color || "kadar", showDesign: false });
  document.querySelectorAll(".swatch[data-cls]").forEach((el) => { el.style.background = classColour(+el.dataset.cls); });
}
