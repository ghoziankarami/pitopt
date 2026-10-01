// 06 · Validasi & Rekonsiliasi — every criterion recomputed from the generated geometry, the design against the
// shell in three tiers, dilution traced to its cause, and the block-by-block map of one bench.
import { esc, fmt, fmtInt, signed } from "../util.js";
import { D, ensure, pill } from "../design/core.js";
import { findingsBanner, gate, notice, page } from "../design/ui.js";
import { View, boundsOf, css, drawBlocks, stroke } from "../design/plan.js";

const CAT = { both: ["Di dalam shell dan desain", "#8FA8C8"], design_only: ["Hanya di desain · dilusi masuk", "#E39A3B"], shell_only: ["Hanya di shell · tertinggal", "#C6483D"] };
const CAUSE = { batter: "Sudut lereng aktual (batter)", min_width: "Lebar kerja minimum", ramp: "Ramp (OSA lebih landai)" };
const CAUSE_COLOUR = { batter: "#8FA8C8", min_width: "#C3CCE0", ramp: "#2B4C8C" };
const mt = (v) => fmt(v / 1e6, 2), jt = (v) => fmt(v / 1e6, 1);

export function render() {
  ensure();
  const g = gate("Validasi & Rekonsiliasi", { needResult: true });
  if (g) return g;
  const doc = D.result.document, r = doc.reconciliation, sh = r.shell, pr = r.practical_design, ra = r.raster_design;
  const waste = (t) => t.rock_tonnes - t.ore_tonnes, sr = (t) => (t.ore_tonnes ? waste(t) / t.ore_tonnes : NaN);
  const chg = (a, b) => (a ? (100 * (b - a)) / a : NaN);
  const kpi = (label, val, unit, sub, cls = "") => `<div class="kpi"><div class="k">${label}</div><div class="v ${cls}">${val}<span class="u">${unit}</span></div><div class="s">${sub}</div></div>`;
  const sectors = doc.sectors;
  const gauge = (v, lim, lo, hi, status) => {
    const pos = (x) => `${Math.min(100, Math.max(0, ((x - lo) / (hi - lo)) * 100))}%`;
    return `<div style="position:relative;height:14px;min-width:170px;background:linear-gradient(90deg,var(--good-bg) ${lim == null ? 100 : pos(lim)},var(--bad-fill) 0);border-radius:3px"><i style="position:absolute;left:${lim == null ? 0 : pos(lim)};top:-2px;width:2px;height:18px;background:var(--text)"></i><i style="position:absolute;left:${pos(v)};top:2px;width:10px;height:10px;margin-left:-5px;border-radius:50%;background:${status === "BLOKIR" ? "var(--bad)" : status === "PERINGATAN" ? "#B36B00" : "var(--good)"}"></i></div>`;
  };
  const gains = Object.entries(r.gained), lost = r.left_behind;
  const totalAbs = gains.reduce((a, [, t]) => a + Math.abs(t.value), 0) || 1;
  return page("Validasi & Rekonsiliasi", "Setiap kriteria dihitung dari geometri hasil generate, bukan dari parameter input, dan dihitung ulang tiap perubahan.",
    `<a class="btn" data-go="d-generate" style="text-decoration:none;line-height:34px">Kembali ke Generate</a><button class="btn primary" data-go="d-ekspor">Lanjut: Ekspor →</button>`, `
  ${notice()}
  ${findingsBanner(doc, { limit: 8 })}
  <div class="dd-two" style="margin-bottom:16px">
    <div class="card"><div class="row" style="gap:12px;align-items:flex-start"><span class="tagc info">SHELL</span><span class="small"><b>Shell adalah bentuk teoretis optimasi</b>; desain praktis menambah berm, ramp, dan lebar kerja. Selisih keduanya normal — yang dinilai adalah <b>besar dan penyebabnya</b>.</span></div></div>
    <div class="card"><div class="row" style="gap:12px;align-items:flex-start"><span class="tagc asumsi">IRA ≠ OSA</span><span class="small">IRA menghitung bench + berm <b>tanpa ramp</b>; OSA melewati ramp, jadi selalu lebih landai dari IRA — makin sering ramp memotong sektor, makin besar bedanya.</span></div></div></div>
  <div class="grid g4" style="margin-bottom:16px">
    ${kpi("NILAI DESAIN", jt(pr.value), "jt USD", `shell ${jt(sh.value)} · ${signed(chg(sh.value, pr.value), 1)} %`, doc.reconciliation.status.value !== "OK" ? "bad" : "")}
    ${kpi("ROCK DESAIN", mt(pr.rock_tonnes), "Mt", `shell ${mt(sh.rock_tonnes)} · ${signed(chg(sh.rock_tonnes, pr.rock_tonnes), 1)} %`)}
    ${kpi("UMPAN DESAIN", mt(pr.ore_tonnes), "Mt", `shell ${mt(sh.ore_tonnes)} · ${signed(chg(sh.ore_tonnes, pr.ore_tonnes), 1)} %`)}
    ${kpi("STRIP RATIO", fmt(sr(pr), 2), "", `shell ${fmt(sr(sh), 2)}`)}</div>
  <div class="card"><div class="cardhead"><h2>Rekonsiliasi terhadap shell PitOpt</h2><span class="lbl">tiga tingkat: shell → desain bench seragam → desain praktis</span></div>
    <table class="t"><thead><tr><th class="l">Metrik</th><th>Shell optimasi</th><th>Desain PitOpt</th><th>Desain praktis</th><th>Δ vs shell</th></tr></thead><tbody>
      <tr><td class="l">Rock <span class="muted xs">Mt</span></td><td>${mt(sh.rock_tonnes)}</td><td>${ra ? mt(ra.rock_tonnes) : "–"}</td><td><b>${mt(pr.rock_tonnes)}</b></td><td class="${r.status.rock_tonnes !== "OK" ? "worst" : ""}">${signed((pr.rock_tonnes - sh.rock_tonnes) / 1e6, 2)} (${signed(r.change_pct.rock_tonnes, 1)} %)</td></tr>
      <tr><td class="l">Umpan <span class="muted xs">Mt</span></td><td>${mt(sh.ore_tonnes)}</td><td>${ra ? mt(ra.ore_tonnes) : "–"}</td><td><b>${mt(pr.ore_tonnes)}</b></td><td class="${r.status.ore_tonnes !== "OK" ? "worst" : ""}">${signed((pr.ore_tonnes - sh.ore_tonnes) / 1e6, 2)} (${signed(r.change_pct.ore_tonnes, 1)} %)</td></tr>
      <tr><td class="l">Waste <span class="muted xs">Mt</span></td><td>${mt(waste(sh))}</td><td>${ra ? mt(waste(ra)) : "–"}</td><td><b>${mt(waste(pr))}</b></td><td>${signed((waste(pr) - waste(sh)) / 1e6, 2)} (${signed(chg(waste(sh), waste(pr)), 1)} %)</td></tr>
      <tr><td class="l">Strip ratio</td><td>${fmt(sr(sh), 2)}</td><td>${ra ? fmt(sr(ra), 2) : "–"}</td><td><b>${fmt(sr(pr), 2)}</b></td><td>${signed(sr(pr) - sr(sh), 2)}</td></tr>
      <tr><td class="l">Nilai <span class="muted xs">jt USD</span></td><td>${jt(sh.value)}</td><td>${ra ? jt(ra.value) : "–"}</td><td><b>${jt(pr.value)}</b></td><td class="${r.status.value !== "OK" ? "worst" : ""}">${signed((pr.value - sh.value) / 1e6, 1)} (${signed(r.change_pct.value, 1)} %)</td></tr>
      <tr><td class="l">Blok</td><td>${fmtInt(sh.blocks)}</td><td>${ra ? fmtInt(ra.blocks) : "–"}</td><td><b>${fmtInt(pr.blocks)}</b></td><td>${signed(pr.blocks - sh.blocks, 0)}</td></tr></tbody></table>
    <p class="xs muted" style="margin:10px 0 0">Kolom "Desain PitOpt" = hasil layar Hasil › Desain (bench seragam, tanpa ramp dan tanpa sektor). Selisih kolom kanan terhadap kolom itu adalah dampak ramp dan sektor. Ambang: peringatan &gt; ${fmt(r.thresholds_pct.warn, 0)} %, blokir &gt; ${fmt(r.thresholds_pct.block, 0)} %; tabel ini ditulis dari penjumlahan blok, sisa hitung ${fmt(Math.max(...Object.values(r.residual).map(Math.abs)), 1)}.</p></div>
  <div class="card"><div class="cardhead"><h2>Dilusi dapat ditelusuri</h2><span class="lbl">nilai blok yang masuk desain tetapi tidak di shell, menurut penyebab</span></div>
    <div class="row" style="height:34px;border-radius:4px;overflow:hidden">${gains.map(([k, t]) => `<div title="${CAUSE[k]}" style="width:${(100 * Math.abs(t.value)) / totalAbs}%;background:${CAUSE_COLOUR[k]};color:${k === "ramp" ? "#fff" : "#14181D"};display:flex;align-items:center;justify-content:center;font-family:'IBM Plex Mono',monospace;font-size:12px;min-width:${t.blocks ? 34 : 0}px">${t.blocks ? jt(t.value) : ""}</div>`).join("")}</div>
    <div class="legend" style="margin-top:10px">${gains.map(([k, t]) => `<div class="li"><i class="box" style="background:${CAUSE_COLOUR[k]}"></i>${CAUSE[k]} <span class="num muted">${fmtInt(t.blocks)} blok · ${fmtInt(t.ore_blocks)} bijih</span></div>`).join("")}</div>
    <div class="row small" style="margin-top:10px;gap:10px"><span class="tagc peringatan">TERTINGGAL</span><span>${fmtInt(lost.blocks)} blok shell tidak masuk desain (${fmtInt(lost.ore_blocks)} bijih, ${jt(lost.value)} jt USD).</span></div></div>
  <div class="dd-two">
    <div class="card"><div class="cardhead">${pill(worstOf(sectors.map((s) => s.ira_status)))}<h2>IRA per sektor</h2></div>
      <table class="t"><thead><tr><th class="l">Sektor</th><th>Aktual °</th><th>Batas °</th><th>Margin</th><th class="l"></th></tr></thead><tbody>${sectors.map((s) => { const lim = s.ira_max_deg; return `<tr><td class="l">${esc(s.name)}</td><td>${fmt(s.ira_deg, 1)}</td><td>${lim == null ? "—" : fmt(lim, 1)}</td><td class="${s.ira_status === "BLOKIR" ? "worst" : ""}">${lim == null ? "—" : signed(lim - s.ira_deg, 1)}</td><td class="l">${gauge(s.ira_deg, lim, 30, 60, s.ira_status)}</td></tr>`; }).join("")}</tbody></table>
      <p class="xs muted" style="margin:8px 0 0">Garis hitam = batas geoteknik; titik = nilai dari geometri aktual.</p></div>
    <div class="card"><div class="cardhead">${pill(worstOf(sectors.map((s) => s.osa_status)))}<h2>OSA per sektor</h2></div>
      <table class="t"><thead><tr><th class="l">Sektor</th><th>Tanpa ramp °</th><th>Dengan ramp °</th><th>Batas °</th><th>Margin</th></tr></thead><tbody>${sectors.map((s) => `<tr><td class="l">${esc(s.name)}</td><td>${fmt(s.osa_no_ramp_deg, 1)}</td><td>${fmt(s.osa_deg, 1)}</td><td>${s.osa_max_deg == null ? "—" : fmt(s.osa_max_deg, 1)}</td><td class="${s.osa_status === "BLOKIR" ? "worst" : ""}">${s.osa_max_deg == null ? "—" : signed(s.osa_max_deg - s.osa_deg, 1)}</td></tr>`).join("")}</tbody></table>
      <p class="xs muted" style="margin:8px 0 0">OSA terukur dari geometri, dibanding rumus analitik: selisih tanpa ramp ${fmt(Math.max(...sectors.map((s) => Math.abs(s.osa_no_ramp_deg - s.osa_analytic_no_ramp_deg))), 2)}°.</p></div></div>
  ${map()}`);
}
const worstOf = (l) => (l.includes("BLOKIR") ? "BLOKIR" : l.includes("PERINGATAN") ? "PERINGATAN" : "OK");

function map() {
  const p = D.plan;
  if (!p) return "";
  const count = (cat) => { let ore = 0, waste = 0; p.x.forEach((_, i) => { const c = p.in_shell[i] && p.in_design[i] ? "both" : p.in_design[i] ? "design_only" : p.in_shell[i] ? "shell_only" : ""; if (c === cat) (p.ore[i] ? ore++ : waste++); }); return [ore, waste]; };
  return `<div class="card"><div class="cardhead"><h2>Peta rekonsiliasi per blok</h2><span class="lbl">satu bench: tiap blok diklasifikasi menurut pusatnya</span><span class="grow"></span>
      <button class="btn sm" data-act="dSlice" data-d="1">▼</button><b class="num" style="margin:0 10px">RL ${fmt(p.rl, 1)}</b><button class="btn sm" data-act="dSlice" data-d="-1">▲</button></div>
    <div class="dd-map"><canvas id="dmap" class="plan" style="height:420px"></canvas>
    <div>${Object.entries(CAT).map(([k, [label, colour]]) => { const [o, w] = count(k); return `<div class="row" style="gap:10px;padding:8px 0;border-top:1px solid var(--line2)"><i class="swatch" style="background:${colour};width:14px;height:14px"></i><div class="grow"><b class="small">${label}</b><div class="num xs muted">${fmtInt(o)} bijih · ${fmtInt(w)} waste</div></div></div>`; }).join("")}
      <p class="xs muted" style="margin:10px 0 0">Hitungan blok pada bench ini; jumlah seluruh bench membentuk tabel rekonsiliasi di atas (dites otomatis).</p></div></div></div>`;
}

export function mount() {
  const c = document.getElementById("dmap");
  if (!c || !D.plan) return;
  const p = D.plan, v = new View(c, boundsOf([...p.shell, ...p.design, ...D.result.benches[0].crest]));
  v.clear(css("--panel2"));
  const cat = (i) => (p.in_shell[i] && p.in_design[i] ? "both" : p.in_design[i] ? "design_only" : p.in_shell[i] ? "shell_only" : "");
  const idx = p.x.map((_, i) => i).filter((i) => cat(i));
  const sub = { ...p, x: idx.map((i) => p.x[i]), y: idx.map((i) => p.y[i]) };
  drawBlocks(v, sub, idx.map((i) => CAT[cat(i)][1]), idx.map(() => false));
  stroke(v, p.shell, { color: css("--text"), width: 1.3, dash: [6, 4] });
  stroke(v, p.design, { color: css("--accent"), width: 2 });
}
