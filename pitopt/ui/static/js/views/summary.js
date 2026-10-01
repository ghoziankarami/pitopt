import { S } from "../store.js";
import { A } from "../actions.js";
import { fmt, fmtInt, mUSD, mt, pct, pcts, signed, esc, tr } from "../util.js";
import { pitByPit, pitLegend, sensitivity } from "../charts.js";
import { kpi, pageHead, empty, banners, productsOf } from "./common.js";

export function render() {
  const r = S.results;
  if (!r) return empty("Ringkasan hasil");
  const k = r.kpis, p = r.params;
  const prods = productsOf(r);
  const cls = p.block_model.include_classes?.length ? p.block_model.include_classes.join(" + ") : "semua kelas";
  const dom = p.block_model.ore_domains?.length ? `domain ${p.block_model.ore_domains.join(", ")}` : "semua domain";
  const be = k.breakeven, lev = k.leverage, dc = k.design_change;
  const rb = r.qa.reblock;
  const cards = [
    kpi("Nilai tak terdiskonto", mUSD(k.value_undiscounted), "jt USD", `RF ${fmt(k.final_rf, 2)} · ${fmtInt(k.value_undiscounted)} USD`),
    kpi("NPV rencana", mUSD(k.npv_plan), "jt USD", `${esc(k.plan_label.includes("strip") ? "strip" : "specified case")} · diskonto ${pcts(k.discount_rate, 0)}/tahun · ${k.periods ?? "–"} periode`, "", "accent"),
    kpi("NPV best case", mUSD(k.npv_best), "jt USD", "shell demi shell · batas atas", "", "good"),
    kpi("NPV worst case", mUSD(k.npv_worst), "jt USD", "bench demi bench · batas bawah", "", "bad"),
    kpi("Rock", mt(k.rock_t), "Mt", "total material tergali"),
    kpi("Umpan (ore)", mt(k.ore_t), "Mt", `${esc(dom)} · ${esc(cls)}`),
    kpi("Waste", mt(k.waste_t), "Mt", `strip ratio ${fmt(k.strip_ratio, 2)} t/t`),
    kpi("Kedalaman maks", fmt(k.max_depth_m, 0), "m", `crest RL ${fmt(k.crest_rl, 1)} · toe RL ${fmt(k.toe_rl, 1)}`),
    ...prods.slice(0, 2).map(([name, pr]) => kpi(name, fmtInt(pr.tonnes), "t", `${fmtInt(pr.price)} USD/${pr.price_unit} · recovery ${pcts(pr.recovery, 2)}`)),
    kpi("Umur tambang", k.periods ?? "–", "tahun", k.capacity ? `±${fmt(k.capacity / 1e6, 1)} Mt umpan/periode` : ""),
    kpi("Pushback", k.pushbacks ?? "–", "tahapan", esc(tr(k.pushback_reason))),
    kpi("Break-even harga", be != null ? fmt(be * 100, 1) : "–", "% harga rencana", "pit final tetap, dinilai ulang", be != null && be > 0.85 ? "risk" : "", "bad"),
    kpi("Leverage harga", lev != null ? fmt(lev, 1) : "–", "× %NPV / %harga", "semua produk bersama"),
    kpi("Desain vs shell", dc ? signed(dc.value_change * 100, 1) : "–", "% value", dc ? `rock ${signed(dc.rock_tonnes_change * 100, 1)}% · ore ${signed(dc.ore_tonnes_change * 100, 1)}% · bench ${fmt(r.design.bench_height, 0)} m` : "desain bench tidak aktif"),
    rb ? kpi("Rekonsiliasi reblock", fmt(rb.output_volume - rb.source_volume, 3), "m³ selisih", `${fmtInt(rb.blocks)} blok ${rb.target.map((v) => fmt(v, 0)).join("×")} m`, "", "good")
       : kpi("Blok dipakai", fmtInt(r.meta.blocks), "blok", `${fmt(p.block_model.dx, 0)}×${fmt(p.block_model.dy, 0)}×${fmt(p.block_model.dz, 0)} m`),
  ];
  return `<div class="page">
  ${pageHead("Ringkasan hasil", `Pit final RF <span class="num">${fmt(k.final_rf, 2)}</span> · ${esc(k.plan_label.includes("strip") ? "rencana strip" : "rencana specified case")} · diskonto <span class="num">${pcts(k.discount_rate, 0)}</span>/tahun${k.capacity ? ` · kapasitas <span class="num">${fmt(k.capacity / 1e6, 1)}</span> Mt/tahun` : ""} · mata uang ${esc(r.meta.currency)}`,
    ["Excel", "DXF", "PDF", "HTML 3D"].map((x) => `<button class="btn" data-act="exportKind" data-kind="${x}">${x}</button>`).join(""))}
  ${banners(r)}
  <div class="grid g4">${cards.join("")}</div>
  <div class="grid g2" style="margin-top:16px;grid-template-columns:1.55fr 1fr">
    <div class="card"><div class="cardhead"><h2>Pit by pit</h2><span class="lbl">nilai &amp; NPV tiap shell RAF</span><a class="to" data-go="pit-by-pit">Buka layar penuh →</a></div>
      <p class="howto"><b>Cara baca:</b> batang = tonase shell, garis = NPV setelah tiap shell dijadwalkan dan didiskonto. Pit final dipilih dari NPV terdiskonto, ${r.final_pit.peak_undiscounted ? `bukan dari puncak nilai tak terdiskonto (RF ${fmt(r.final_pit.peak_undiscounted.rf, 2)}).` : "bukan dari nilai tak terdiskonto."}</p>
      <div class="chart">${pitByPit(r.pit_by_pit, { w: 760, h: 340, compact: true })}</div>${pitLegend()}</div>
    <div class="card"><div class="cardhead"><h2>Sensitivitas harga</h2><a class="to" data-go="sensitivitas">Buka →</a></div>
      <p class="howto"><b>Cara baca:</b> pit final <b>tetap</b>, hanya dinilai ulang pada harga lain — berbeda dari RAF, yang mengoptimasi ulang pit di tiap harga.</p>
      <div class="chart">${r.sensitivity ? sensitivity(r.sensitivity, { w: 460, h: 320 }) : `<div class="empty">Sensitivitas tidak dihitung di skenario ini.</div>`}</div>
      <div class="legend"><span class="li"><i class="ln" style="border-color:var(--accent)"></i>NPV rencana</span><span class="li"><i class="box" style="background:var(--bad-fill)"></i>Zona NPV negatif</span></div></div>
  </div></div>`;
}

A.exportKind = (el) => {
  const ext = { Excel: ".xlsx", PDF: ".pdf", DXF: "_pit_face_position.dxf", "HTML 3D": "_3d_viewer.html" }[el.dataset.kind];
  const f = S.results.outputs.find((o) => o.name.endsWith(ext));
  if (!f) return import("../util.js").then((u) => u.toast(`Berkas ${el.dataset.kind} tidak ditemukan untuk skenario ini`));
  A.download({ dataset: { file: f.name } });
};
