import { S, notify } from "../store.js";
import { A } from "../actions.js";
import { startRun } from "../run.js";
import { fmt, mUSD, mt, esc, tr } from "../util.js";
import { pitByPit, pitLegend } from "../charts.js";
import { pageHead, empty } from "./common.js";

const cmp = (title, on, row) => `<div class="selcard ${on ? "on" : ""}"><h4>${title}</h4><div class="kv">
  <span>Rock</span><span>${mt(row.rock_t)} Mt</span><span>Umpan</span><span>${mt(row.ore_t)} Mt</span><span>SR</span><span>${fmt(row.sr, 2)} t/t</span>
  <span>Tak terdiskonto</span><span>${mUSD(row.value)} jt</span><span><b>NPV rata²</b></span><span><b>${mUSD(row.npv_avg)} jt</b></span></div></div>`;

export function render(view) {
  const r = S.results;
  if (!r) return empty("Pit by Pit");
  const rows = r.pit_by_pit, fp = r.final_pit;
  const pend = S.pendingFinal;
  const chosen = pend != null ? rows.find((x) => Math.abs(x.rf - pend) < 1e-9) : fp.row;
  const filled = rows.filter((x) => !x.empty).length;
  const explain = `<div class="grid g2" style="margin-bottom:16px">
    <div class="card row" style="align-items:flex-start;gap:12px"><span class="tagc info">RAF</span><div class="small"><b>Di layar ini pit dioptimasi ulang di tiap faktor harga.</b> Setiap batang adalah pit yang berbeda — bentuk, tonase, dan batasnya ikut berubah. Karena itu shell bersarang: shell kecil selalu ada di dalam shell besar.</div></div>
    <div class="card row" style="align-items:flex-start;gap:12px"><span class="tagc asumsi">SENSITIVITAS</span><div class="small"><b>Bukan yang dikerjakan di sini.</b> Di layar Sensitivitas, pit final <i>tetap</i> dan hanya dinilai ulang${r.kpis.breakeven ? ` — itulah yang menghasilkan break-even ${fmt(r.kpis.breakeven * 100, 1)}%` : ""}. Jangan bandingkan kedua angka secara langsung.</div></div></div>`;
  const chart = `<div class="card"><div class="cardhead"><h2>Grafik pit-by-pit</h2><span class="lbl">klik batang mana pun untuk memindahkan pit final</span><span class="grow"></span><span class="num xs muted">kiri: Mt · kanan: jt USD</span></div>
    <p class="howto">Nilai tak terdiskonto memuncak di RF ${fmt(fp.peak_undiscounted?.rf, 2)} — itu definisi, bukan rekomendasi. Pit final diambil dari NPV terdiskonto: shell terkecil yang masih dalam ${fmt(fp.tolerance * 100, 0)}% dari NPV rata-rata maksimum.</p>
    <div class="chart">${pitByPit(pend != null ? rows.map((x) => ({ ...x, final: Math.abs(x.rf - pend) < 1e-9 })) : rows, { w: 1140, h: 460 })}</div>${pitLegend()}</div>`;
  const pick = pend != null && Math.abs(pend - fp.rf) > 1e-9
    ? `<div class="card" style="border-color:var(--accent);background:var(--accent-soft)"><div class="row"><div class="grow small"><b>Pit final akan dipindah ke RF ${fmt(pend, 2)}.</b> Pushback, jadwal, sensitivitas, dan desain harus dihitung ulang untuk pit yang baru.</div><button class="btn" data-act="cancelPick">Batal</button><button class="btn primary" data-act="rerunFinal">Jalankan ulang dengan RF ${fmt(pend, 2)}</button></div></div>` : "";
  const cards = `<div class="card"><div class="grid" style="grid-template-columns:1.05fr 1fr 1fr 1fr;align-items:stretch">
    <div><div class="navh" style="padding:0 0 6px">PIT FINAL TERPILIH</div>
      <div><span class="num" style="font-size:32px;font-weight:600">RF ${fmt(chosen.rf, 2)}</span><span class="muted num" style="margin-left:10px">shell ${chosen.shell} dari ${rows.length}</span></div>
      <p class="small" style="line-height:1.5;margin:10px 0 14px">${pend != null && Math.abs(pend - fp.rf) > 1e-9 ? "Pilihan manual — belum dijalankan." : `Rekomendasi engine: ${esc(tr(fp.reason))}.`}</p>
      <button class="btn primary" data-go="pushback">Lanjut ke Pushback →</button></div>
    ${cmp(`Terpilih · RF ${fmt(chosen.rf, 2)}`, true, chosen)}
    ${fp.peak_avg ? cmp(`Puncak NPV rata² · RF ${fmt(fp.peak_avg.rf, 2)}`, false, fp.peak_avg) : "<div></div>"}
    ${fp.peak_undiscounted ? cmp(`Puncak tak terdiskonto · RF ${fmt(fp.peak_undiscounted.rf, 2)}`, false, fp.peak_undiscounted) : "<div></div>"}</div></div>`;
  const body = rows.map((x) => {
    const on = pend != null ? Math.abs(x.rf - pend) < 1e-9 : x.final;
    const dash = `<td class="faint">–</td>`;
    return x.empty
      ? `<tr class="dim"><td class="l"><b class="num">${fmt(x.rf, 2)}</b></td><td class="l num faint">${x.shell}</td>${dash.repeat(8)}<td class="l small faint" style="max-width:150px">${x.note}</td><td></td></tr>`
      : `<tr class="${on ? "sel" : ""}"><td class="l"><b class="num">${fmt(x.rf, 2)}</b></td><td class="l num faint">${x.shell}</td><td>${mt(x.rock_t)}</td><td>${mt(x.ore_t)}</td><td>${mt(x.waste_t)}</td><td>${fmt(x.sr, 2)}</td><td class="und">${mUSD(x.value)}</td><td class="best">${mUSD(x.npv_best)}</td><td class="worst">${mUSD(x.npv_worst)}</td><td><b>${mUSD(x.npv_avg)}</b></td><td class="l small muted" style="max-width:150px">${x.final ? "Rekomendasi engine" + (x.note ? " · " + x.note.toLowerCase() : "") : x.note}</td><td>${on ? `<span class="pill run">${pend != null ? "dipilih" : "terpilih"}</span>` : `<button class="btn sm" data-act="pickFinal" data-rf="${x.rf}">Pilih</button>`}</td></tr>`;
  }).join("");
  const table = `<div class="card flat" style="margin-top:16px"><div style="padding:14px 20px 10px"><h2 style="display:inline">Tabel pit-by-pit</h2> <span class="muted small">${rows.length} shell · nilai dalam jt USD kecuali disebut lain</span></div>
    <div style="overflow:auto"><table class="t"><thead><tr><th class="l">RF</th><th class="l">Shell</th><th>Rock Mt</th><th>Umpan Mt</th><th>Waste Mt</th><th>SR t/t</th><th>Tak terdiskonto</th><th style="color:var(--good)">NPV best</th><th style="color:var(--bad)">NPV worst</th><th>NPV rata²</th><th class="l">Catatan</th><th>Pit final</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
  const head = pageHead(view === "pit-final" ? "Pit Final" : "Pit by Pit", `${filled} dari ${rows.length} shell terisi · pit final dipilih dari NPV terdiskonto`);
  return `<div class="page">${head}${explain}${chart}${pick ? `<div style="margin-top:16px">${pick}</div>` : ""}<div style="margin-top:16px">${cards}</div>${table}</div>`;
}

export function mount(root) {
  root.addEventListener("click", (e) => {
    const hit = e.target.closest(".bar-hit");
    if (hit && !S.results.pit_by_pit.find((x) => x.shell === +hit.dataset.shell)?.empty) A.pickFinal({ dataset: { rf: hit.dataset.rf } });
  });
}

A.pickFinal = (el) => { S.pendingFinal = parseFloat(el.dataset.rf); notify(); };
A.cancelPick = () => { S.pendingFinal = null; notify(); };
A.rerunFinal = () => {
  const rf = S.pendingFinal;
  startRun({ "final_pit.revenue_factor": rf }, `${S.scenario}_rf${String(Math.round(rf * 100)).padStart(3, "0")}`);
};
