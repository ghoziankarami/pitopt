import { S, notify } from "../store.js";
import { A } from "../actions.js";
import { fmt, fmtInt, mUSD, mt, signed, esc, tr, stageColor } from "../util.js";
import { drawPlan, gantt, production, legendSwatches, benchWall } from "../charts.js";
import { pageHead, empty, yearOf } from "./common.js";

const state = { mode: "pushback", variant: "plan" };

function pushbackTable(r) {
  const rows = r.pushbacks.rows, prods = r.schedule.products;
  const n = rows.length;
  const body = rows.map((p) => `<tr><td class="l"><span class="swatch" style="background:${stageColor(p.pushback, n)}"></span><b>${p.pushback}</b></td>
    <td class="l num small">${p.strips ? `${p.strips[0]}–${p.strips[1]}` : esc(tr(p.definition))}</td>    <td>${mt(p.ore_tonnes)}</td><td>${mt(p.waste_tonnes)}</td><td>${fmt(p.strip_ratio, 2)}</td><td class="und">${mUSD(p.value)}</td><td>${fmt(p.value_per_tonne_mined, 2)}</td>
    <td>${p.periods ? (p.periods[0] === p.periods[1] ? p.periods[0] : `${p.periods[0]}–${p.periods[1]}`) : "–"}</td></tr>`).join("");
  const tot = rows.reduce((a, p) => ({ ore: a.ore + p.ore_tonnes, waste: a.waste + p.waste_tonnes, value: a.value + p.value, blocks: a.blocks + p.blocks, strips: a.strips + (p.strips ? p.strips[1] - p.strips[0] + 1 : 0) }), { ore: 0, waste: 0, value: 0, blocks: 0, strips: 0 });
  const rockTotal = tot.ore + tot.waste;
  return `<div class="card flat"><div style="padding:14px 20px 8px"><h2 style="display:inline">Tabel pushback</h2> <span class="muted small">inkremental · tonase seimbang</span></div>
    <div style="overflow:auto"><table class="t"><thead><tr><th class="l">PB</th><th class="l">${rows[0]?.strips ? "Strip" : "Batas"}</th><th>Umpan Mt</th><th>Waste Mt</th><th>SR</th><th>Nilai jt</th><th>USD/t</th><th>Periode</th></tr></thead>
    <tbody>${body}<tr class="total"><td class="l">Total</td><td class="l num small">${rows[0]?.strips ? `1–${rows[rows.length - 1].strips[1]}` : ""}</td><td>${mt(tot.ore)}</td><td>${mt(tot.waste)}</td><td>${fmt(tot.waste / tot.ore, 2)}</td><td>${mUSD(tot.value)}</td><td>${fmt(tot.value / rockTotal, 2)}</td><td>1–${r.schedule.plan.length}</td></tr></tbody></table></div>
    <p class="xs muted" style="padding:10px 20px 14px;margin:0">Nilai/t = nilai pushback ÷ rock tergali di pushback itu, pada harga rencana.</p></div>`;
}

function scheduleTable(r, variant) {
  const rows = r.schedule[variant];
  const prods = r.schedule.products;
  const year = yearOf(r);
  const body = rows.map((p) => `<tr><td class="l">${p.period}${year ? ` · ${year + p.period - 1}` : ""}</td>
    <td class="l">${(p.pushbacks || "").split(",").filter(Boolean).map((t) => `<span class="swatch" style="background:${stageColor(parseInt(t.replace(/\D/g, "")), r.pushbacks.rows.length)}"></span>${esc(t.trim())}`).join(" ")}</td>
    <td>${mt(p.ore_tonnes)}</td><td>${mt(p.waste_tonnes)}</td>${prods.map((n) => `<td>${fmtInt(p[`${n}_tonnes`])}</td>`).join("")}<td>${mUSD(p.cash_flow)}</td><td><b>${mUSD(p.npv)}</b></td></tr>`).join("");
  const sum = (k) => rows.reduce((a, p) => a + (p[k] || 0), 0);
  return `<table class="t"><thead><tr><th class="l">Periode</th><th class="l">Pushback aktif</th><th>Umpan Mt</th><th>Waste Mt</th>${prods.map((n) => `<th>${esc(n)} t</th>`).join("")}<th>Cash flow jt</th><th>NPV kum. jt</th></tr></thead>
    <tbody>${body}<tr class="total"><td class="l">Total</td><td class="l muted">${rows.length} periode</td><td>${mt(sum("ore_tonnes"))}</td><td>${mt(sum("waste_tonnes"))}</td>${prods.map((n) => `<td>${fmtInt(sum(`${n}_tonnes`))}</td>`).join("")}<td>${mUSD(sum("cash_flow"))}</td><td>${mUSD(rows[rows.length - 1]?.npv)}</td></tr></tbody></table>`;
}

function overlapNote(rows) {
  const ranges = rows.filter((p) => p.periods);
  const pairs = ranges.slice(1).filter((p, i) => p.periods[0] <= ranges[i].periods[1]);
  if (!ranges.length) return "";
  return pairs.length
    ? `Pushback berurutan saling tumpang tindih di ${pairs.length} dari ${ranges.length - 1} pasangan (mis. PB${pairs[0].pushback} mulai di periode ${pairs[0].periods[0]} saat PB${pairs[0].pushback - 1} masih berjalan sampai periode ${ranges[pairs[0].pushback - 2].periods[1]}).`
    : "Pushback berjalan berurutan tanpa tumpang tindih periode.";
}
function productionNote(r) {
  const plan = r.schedule.plan, cap = r.kpis.capacity, last = plan[plan.length - 1];
  const parts = [];
  if (cap) parts.push(`Kapasitas umpan ${fmt(cap / 1e6, 2)} Mt/periode; umur tambang ${plan.length} periode.`);
  if (cap && last && last.ore_tonnes < 0.5 * cap) parts.push(`Periode ${last.period} hanya ${fmt(last.ore_tonnes / 1e6, 2)} Mt (${fmt((last.ore_tonnes / cap) * 100, 0)}% kapasitas), sisa cadangan.`);
  return parts.join(" ");
}
function designNote(rc) {
  const rock = rc.rock_tonnes_change * 100, ore = rc.ore_tonnes_change * 100, val = rc.value_change * 100;
  const dir = (x) => (x > 0 ? "lebih banyak" : "lebih sedikit");
  return `Dibanding shell optimasi, desain bench menggali ${fmt(Math.abs(rock), 1)}% ${dir(rock)} batuan dan ${fmt(Math.abs(ore), 1)}% ${dir(ore)} bijih, dengan nilai ${signed(val, 1)}%. ${Math.abs(val) > 5 ? "Selisih di atas 5% menandakan geometri bench dan ukuran blok kurang selaras — periksa tinggi bench dan sudut muka." : "Selisih kecil seperti ini wajar karena dinding menerus menggantikan tangga blok."}`;
}
function reconNote(r) {
  const t = r.schedule.tag_reconciliation;
  if (!t || t.max_relative_difference < 0.02) return "";
  return `<div class="banner warn small" style="margin:8px 20px"><b>Cash flow per periode ≠ jumlah nilai blok berlabel periode</b> (selisih maks ${fmt(t.max_relative_difference * 100, 1)}% dari cash flow terbesar; total sama, selisih ${mUSD(t.total_difference)} jt). Penjadwal membagi tiap bench-run antar periode secara proporsional tonase agar hasil tidak bergantung urutan baris; kolom <span class="num">period</span> di CSV adalah penetapan blok utuh. Angka di tabel ini yang dipakai laporan.</div>`;
}

export function render(view) {
  const r = S.results;
  if (!r) return empty(view === "desain" ? "Desain" : "Pushback & Rencana Periode");
  return view === "desain" ? designPage(r) : planPage(r);
}

function planPage(r) {
  const pb = r.pushbacks, plan = r.schedule.plan, k = r.kpis;
  const npv = (v) => r.schedule[v].length ? r.schedule[v][r.schedule[v].length - 1].npv : null;
  const cont = r.schedule.contiguity;
  const sc = S.projects.find((p) => p.id === S.project)?.scenarios.filter((x) => x.has_results && x.id !== S.scenario) || [];
  const shellsNote = pb.candidates_total > 0
    ? `<div class="card" style="border-color:var(--warn-line);background:var(--warn-panel);margin-top:16px"><div class="row"><span class="tagc asumsi">METODE SHELLS</span><b>${pb.candidates_total} kandidat diuji · ${pb.candidates_practical} praktis</b></div>
        <p class="small" style="margin:8px 0 0;line-height:1.5">${pb.candidates_practical === 0 ? `Pembagian berbasis shell menghasilkan tahapan yang lebih sempit dari lebar kerja minimum ${fmt(pb.min_width, 0)} m; pembagian yang paling tidak sempit dipakai.` : `Pembagian dengan NPV specified terbaik di antara yang memenuhi lebar kerja dan tonase minimum dipilih.`}</p></div>`
    : sc.length ? `<div class="card" style="border-color:var(--warn-line);background:var(--warn-panel);margin-top:16px"><div class="small"><span class="tagc info">METODE</span> &nbsp; Skenario lain di proyek ini punya hasil — bandingkan metode pushback yang berbeda di layar Bandingkan. <a data-go="bandingkan">Bandingkan skenario →</a></div></div>` : "";
  const variantTabs = `<div class="tabs" role="tablist">${[["plan", "Rencana"], ["best", "Best case"], ["worst", "Worst case"]].map(([v, l]) => `<button data-act="planVariant" data-v="${v}" class="${state.variant === v ? "on" : ""}">${l}</button>`).join("")}</div>`;
  const modeTabs = `<div class="tabs">${[["pushback", "Per pushback"], ["period", "Per periode"], ["depth", "Kedalaman"]].map(([v, l]) => `<button data-act="planMode" data-v="${v}" class="${state.mode === v ? "on" : ""}">${l}</button>`).join("")}</div>`;
  const total = state.mode === "period" ? plan.length : pb.rows.length;
  const labels = state.mode === "period" ? plan.map((p) => `P${p.period}`) : pb.rows.map((p) => `PB${p.pushback}${p.strips ? ` · ${p.strips[0]}–${p.strips[1]}` : ""}`);
  return `<div class="page">
  ${pageHead("Pushback &amp; Rencana Periode", `${esc(tr(pb.plan_label))} · <span class="muted">${pb.method === "strips" ? "strip" : "shells"}</span>`, variantTabs)}
  <div class="card" style="margin-bottom:16px"><div class="row"><span class="tagc info">JUMLAH PUSHBACK</span><b>${pb.rows.length}</b><span class="muted small">${esc(tr(pb.count_reason))}</span><span class="grow"></span><a data-go="parameter" class="small">Ubah di Parameter →</a></div>
    <p class="howto" style="margin:8px 0 0"><b>Pushback</b> adalah tahapan <i>ruang</i> di dalam pit final; <b>periode</b> adalah <i>waktu</i>. Satu pushback biasanya berjalan lebih dari satu periode dan pushback berurutan saling tumpang tindih. Satu pushback per periode hanyalah kasus khusus, bukan aturan.</p></div>
  <div class="split">
    <div class="card"><div class="cardhead"><h2>Plan view pit final</h2><span class="lbl">RF ${fmt(r.final_pit.rf, 2)} · utara ke atas</span><span class="grow"></span>${modeTabs}</div>
      <canvas class="plan" id="planview"></canvas>${state.mode === "depth" ? `<div class="xs muted" style="margin-top:8px">Warna lebih gelap = lebih dalam (maks ${fmt(k.max_depth_m, 0)} m).</div>` : legendSwatches(total, labels)}</div>
    <div style="display:flex;flex-direction:column;gap:16px">
      <div class="card"><div class="cardhead"><h2>Pushback per periode</h2></div><p class="howto">${overlapNote(pb.rows)}</p><div class="chart">${gantt(pb.rows, plan.length)}</div></div>
      ${pushbackTable(r)}</div></div>
  ${shellsNote}
  <div class="card" style="margin-top:16px"><div class="cardhead"><h2>Produksi per periode &amp; NPV kumulatif</h2><span class="grow"></span><span class="num xs muted">kiri: Mt · kanan: jt USD</span></div>
    <p class="howto">${productionNote(r)}</p>
    <div class="chart">${production(plan, pb.rows.length, { startYear: yearOf(r) })}</div>
    <div class="legend"><span class="li"><i class="box" style="background:var(--accent)"></i>Umpan (ore)</span><span class="li"><i class="box" style="background:var(--grey)"></i>Waste</span><span class="li"><i class="ln" style="border-color:var(--text);border-top-width:3px"></i>NPV kumulatif terdiskonto</span><span class="li muted">Pita bawah: pushback yang aktif di tiap periode</span></div></div>
  <div class="card flat" style="margin-top:16px" id="rencana"><div style="padding:14px 20px 4px;display:flex;align-items:baseline;gap:10px"><h2>Rencana tambang per periode</h2><span class="muted small">${state.variant === "plan" ? esc(tr(pb.plan_label)) : state.variant === "best" ? "best case · shell demi shell" : "worst case · bench demi bench"} · diskonto ${fmt(k.discount_rate * 100, 0)}%/tahun · NPV ${mUSD(npv(state.variant))} jt USD</span><span class="grow"></span><a class="small" style="font-weight:600" data-act="planVariant" data-v="${state.variant === "plan" ? "best" : "plan"}">${state.variant === "plan" ? `Bandingkan dengan best ${mUSD(npv("best"))} / worst ${mUSD(npv("worst"))} →` : "Kembali ke rencana →"}</a></div>
    ${reconNote(r)}<p class="howto" style="padding:0 20px">Tiap periode menghasilkan satu surface akhir (DXF face position). Verifikasi keterhubungan area: <b class="${cont.contiguous === cont.periods ? "good" : "bad"}">${cont.contiguous} dari ${cont.periods} periode</b> satu area tambang menyambung.</p>
    <div style="overflow:auto">${scheduleTable(r, state.variant)}</div></div></div>`;
}

export function mount(root, view) {
  if (view === "desain") return;
  const r = S.results;
  const canvas = root.querySelector("#planview");
  if (!canvas || !r) return;
  const total = state.mode === "period" ? r.schedule.plan.length : r.pushbacks.rows.length;
  drawPlan(canvas, r.plan_view, state.mode, total, { maxWidth: 700 });
  if (location.hash.includes("rencana")) root.querySelector("#rencana")?.scrollIntoView();
}

A.planMode = (el) => { state.mode = el.dataset.v; notify(); };
A.planVariant = (el) => { state.variant = el.dataset.v; notify(); };

/* ───────────── Desain ───────────── */
function designPage(r) {
  const d = r.design, v = r.verification.detail, dd = v.design;
  if (!d) return `<div class="page">${pageHead("Desain", "")}<div class="card"><div class="empty">Desain bench tidak aktif di skenario ini. Aktifkan bagian <span class="num">design:</span> di parameter.</div></div></div>`;
  const rc = d.reconciliation;
  const row = (a, b, cls = "") => `<span>${a}</span><span class="${cls}">${b}</span>`;
  const ok = (n) => (n === 0 ? `<span class="pill ok">0 pelanggaran</span>` : `<span class="pill bad">${fmtInt(n)} pelanggaran</span>`);
  const checks = [
    ["Dinding pada surface pit vs sudut desain", v.walls?.violations, `${fmtInt(v.walls?.pairs_checked)} pasangan kolom diperiksa · dinding tercuram ${fmt(v.walls?.steepest_wall_deg_over_30m, 1)}°`],
    ["Kerucut lereng sebenarnya tiap blok pit", v.cone?.in_pit_blocks_with_unmined_block_inside_cone, `sudut desain ${fmt(r.params.slope.overall_angle_deg, 1)}° · toleransi 1 blok`],
    ["Urutan jadwal vs kerucut lereng", v.schedule?.blocks_mined_before_a_block_in_their_cone, `${v.schedule?.periods ?? "–"} periode · tidak ada blok ditambang sebelum blok di atasnya`],
  ];
  return `<div class="page">${pageHead("Desain", "geometri bench yang dibangun ulang dari lantai hasil optimasi")}
  <div class="split">
    <div class="card"><div class="cardhead"><h2>Parameter desain</h2><span class="lbl">bench ${fmt(d.bench_height, 0)} m</span></div>
      <div class="kv" style="margin-bottom:16px">${row("Tinggi bench", `${fmt(d.bench_height, 2)} m`)}${row("Sudut muka bench", `${fmt(d.face_angle_deg, 2)}°`)}${row("Lebar berm", `${fmt(d.berm_width, 2)} m`)}${row("Sudut overall hasil", `<b>${fmt(d.overall_angle_deg, 2)}°</b>`)}${row("Muka tercuram terukur", `${dd ? fmt(dd.steepest_local_face_deg, 2) : "–"}°`)}${row("Dinding 3 bench terukur", `${dd ? fmt(dd.steepest_over_3_benches_deg, 1) : "–"}° <span class="faint">(${dd ? fmt(dd.three_bench_span_m, 0) : "–"} m)</span>`)}</div>
      <div class="chart" style="max-width:340px;margin:0 auto">${benchWall(d)}</div>
      <p class="xs muted" style="margin:10px 0 0">Berm dihitung otomatis agar sudut overall sama dengan sudut yang dipakai optimasi. Lebar berm bisa dikunci manual di layar Parameter.</p></div>
    <div class="card"><div class="cardhead"><h2>Rekonsiliasi desain vs shell optimasi</h2></div>
      <div class="kv" style="margin-bottom:12px">${row("Rock", `<span class="${rc.rock_tonnes_change > 0 ? "" : ""}">${signed(rc.rock_tonnes_change * 100, 1)}%</span>`)}${row("Ore", `${signed(rc.ore_tonnes_change * 100, 1)}%`)}${row("Value", `<b class="${rc.value_change < 0 ? "bad" : "good"}">${signed(rc.value_change * 100, 1)}%</b>`)}
        ${row("Value desain", `${mUSD(rc.design.value)} jt`)}${row("Value shell", `${mUSD(rc.shell.value)} jt`)}</div>
      <p class="small muted" style="line-height:1.55;margin:0">${designNote(rc)}</p>
      <div style="margin-top:14px"><a data-go="3d">Lihat penampang dan viewer 3D →</a></div></div></div>
  <div class="card" style="margin-top:16px"><div class="cardhead"><h2>Verifikasi independen</h2><span class="lbl">tidak memakai template precedence solver</span></div>
    ${checks.map(([n, c, det]) => `<div class="checkrow"><div style="width:118px">${ok(c ?? 0)}</div><div class="grow"><b>${n}</b><div class="xs muted">${det}</div></div></div>`).join("")}</div></div>`;
}
