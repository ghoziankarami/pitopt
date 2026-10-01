// SVG / canvas charts. Colours come from CSS variables so light and dark
// themes both work; nothing here knows about the DOM beyond returning strings.
import { fmt, niceMax, stageColor, esc, mUSD } from "./util.js";

const C = {
  ore: "var(--accent)", waste: "var(--grey)", avg: "var(--text)", best: "var(--good)", worst: "var(--bad)",
  und: "var(--pit)", grid: "var(--line2)", axis: "var(--faint)", text: "var(--muted)", panel: "var(--panel)",
};
const rf = (v) => fmt(v, 2);

function axisTicks(max, n = 4) { return Array.from({ length: n + 1 }, (_, i) => (max * i) / n); }

/* ───────────── pit by pit (Whittle-style) ───────────── */
export function pitByPit(rows, { w = 1100, h = 420, compact = false } = {}) {
  const m = { l: 52, r: 56, t: compact ? 20 : 34, b: compact ? 44 : 56 };
  const pw = w - m.l - m.r, ph = h - m.t - m.b, n = rows.length;
  if (!n) return "";
  const slot = pw / n, bw = slot * 0.44;
  const xc = (i) => m.l + slot * (i + 0.5);
  const rockMax = niceMax(Math.max(...rows.map((r) => (r.rock_t || 0) / 1e6), 0.1));
  const npvVals = rows.flatMap((r) => [r.value, r.npv_avg, r.npv_best, r.npv_worst]).filter((v) => v != null && v > 0).map((v) => v / 1e6);
  const npvMax = niceMax(Math.max(...npvVals, 1));
  const yl = (v) => m.t + ph - (v / rockMax) * ph;
  const yr = (v) => m.t + ph - (v / npvMax) * ph;
  const lead = (() => { let k = 0; while (k < n && rows[k].empty) k++; return k; })();
  const fin = rows.findIndex((r) => r.final);
  let s = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Grafik pit by pit">`;

  for (const t of axisTicks(rockMax)) {
    const y = yl(t);
    s += `<line x1="${m.l}" x2="${w - m.r}" y1="${y}" y2="${y}" style="stroke:${C.grid}"/>`;
    s += `<text x="${m.l - 8}" y="${y + 3.5}" text-anchor="end" font-size="10" style="fill:${C.text}">${fmt(t, rockMax < 4 ? 1 : 0)}</text>`;
  }
  for (const t of axisTicks(npvMax)) s += `<text x="${w - m.r + 8}" y="${yr(t) + 3.5}" font-size="10" style="fill:${C.text}">${fmt(t, npvMax < 4 ? 1 : 0)}</text>`;
  s += `<text x="${m.l - 8}" y="${m.t - 12}" text-anchor="end" font-size="10" style="fill:${C.text}">Mt rock</text>`;
  s += `<text x="${w - m.r + 8}" y="${m.t - 12}" font-size="10" style="fill:${C.text}">jt USD</text>`;

  if (lead > 0) {
    const x2 = m.l + slot * lead;
    s += `<rect x="${m.l}" y="${m.t}" width="${x2 - m.l}" height="${ph}" style="fill:var(--hover)"/>`;
    const cx = (m.l + x2) / 2, cy = m.t + ph * 0.45;
    if (x2 - m.l < 110) s += `<text transform="translate(${cx + 4},${cy}) rotate(-90)" text-anchor="middle" font-size="10.5" style="fill:${C.axis}">pit kosong — tidak ekonomis</text>`;
    else {
      s += `<text x="${cx}" y="${cy}" text-anchor="middle" font-size="11" style="fill:${C.axis}">pit kosong</text>`;
      if (!compact) s += `<text x="${cx}" y="${cy + 16}" text-anchor="middle" font-size="10" style="fill:${C.axis}">tidak ada blok yang ekonomis</text>`;
    }
  }
  if (fin >= 0) {
    s += `<rect x="${m.l + slot * fin}" y="${m.t}" width="${slot}" height="${ph}" style="fill:var(--accent-soft)"/>`;
    s += `<line x1="${xc(fin)}" x2="${xc(fin)}" y1="${m.t + 14}" y2="${m.t + ph}" stroke-dasharray="4 3" style="stroke:var(--accent);stroke-width:1.4"/>`;
    s += `<rect x="${xc(fin) - 32}" y="${m.t}" width="64" height="18" rx="3" style="fill:var(--accent)"/>`;
    s += `<text x="${xc(fin)}" y="${m.t + 12.5}" text-anchor="middle" font-size="9.5" font-weight="700" style="fill:#fff">PIT FINAL</text>`;
  }
  rows.forEach((r, i) => {
    if (r.empty) return;
    const ore = (r.ore_t || 0) / 1e6, waste = (r.waste_t || 0) / 1e6;
    s += `<rect x="${xc(i) - bw / 2}" y="${yl(ore)}" width="${bw}" height="${yl(0) - yl(ore)}" style="fill:${C.ore}"/>`;
    s += `<rect x="${xc(i) - bw / 2}" y="${yl(ore + waste)}" width="${bw}" height="${yl(ore) - yl(ore + waste)}" style="fill:${C.waste}"/>`;
  });
  const line = (key, color, dash, wdt) => {
    const pts = rows.map((r, i) => (r.empty || r[key] == null ? null : [xc(i), yr(r[key] / 1e6)]));
    let d = "", open = false;
    pts.forEach((p) => { if (!p) { open = false; return; } d += `${open ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`; open = true; });
    return `<path d="${d}" fill="none" stroke-width="${wdt}" ${dash ? `stroke-dasharray="${dash}"` : ""} style="stroke:${color}"/>`;
  };
  s += line("value", C.und, "5 3", 1.6) + line("npv_best", C.best, "", 1.8) + line("npv_worst", C.worst, "", 1.8) + line("npv_avg", C.avg, "", 2.6);
  rows.forEach((r, i) => { if (!r.empty && r.npv_avg != null) s += `<circle cx="${xc(i)}" cy="${yr(r.npv_avg / 1e6)}" r="${r.final ? 4.5 : 3}" style="fill:${C.avg}"/>`; });

  const peak = (key, label, dy) => {
    const cand = rows.filter((r) => !r.empty && r[key] != null);
    if (!cand.length) return;
    const top = cand.reduce((a, b) => (b[key] > a[key] ? b : a));
    const i = rows.indexOf(top), y = yr(top[key] / 1e6);
    s += `<circle cx="${xc(i)}" cy="${y}" r="7" fill="none" stroke-width="1.4" style="stroke:${key === "value" ? C.und : C.avg}"/>`;
    if (!compact) s += `<text x="${xc(i)}" y="${y + dy}" text-anchor="middle" font-size="10" style="fill:${key === "value" ? C.und : C.avg};paint-order:stroke;stroke:var(--panel);stroke-width:4px">${label}</text>`;
  };
  peak("value", "puncak tak terdiskonto", -14);
  peak("npv_avg", "puncak NPV rata²", 34);

  rows.forEach((r, i) => {
    s += `<text x="${xc(i)}" y="${h - m.b + 18}" text-anchor="middle" font-size="10.5" font-weight="${r.final ? 700 : 400}" style="fill:${r.final ? "var(--text)" : C.text}">${rf(r.rf)}</text>`;
    if (!compact) s += `<text x="${xc(i)}" y="${h - m.b + 32}" text-anchor="middle" font-size="9" style="fill:${C.axis}">shell ${r.shell}</text>`;
    s += `<rect class="bar-hit" data-shell="${r.shell}" data-rf="${r.rf}" x="${m.l + slot * i}" y="${m.t}" width="${slot}" height="${ph}" fill="transparent"><title>RF ${rf(r.rf)} · shell ${r.shell}${r.empty ? " · pit kosong" : ` · rock ${fmt(r.rock_t / 1e6)} Mt · NPV rata² ${mUSD(r.npv_avg)} jt`}</title></rect>`;
  });
  s += `<text x="${(m.l + w - m.r) / 2}" y="${h - 6}" text-anchor="middle" font-size="10" style="fill:${C.text}">Revenue Adjustment Factor (RAF) — pit dioptimasi ulang tiap faktor</text>`;
  return s + "</svg>";
}

export const pitLegend = () => `<div class="legend">
  <span class="li"><i class="box" style="background:${C.ore}"></i>Umpan (ore)</span>
  <span class="li"><i class="box" style="background:${C.waste}"></i>Waste</span>
  <span class="li"><i class="ln" style="border-color:var(--text);border-top-width:3px"></i>NPV rata-rata (dasar pemilihan)</span>
  <span class="li"><i class="ln" style="border-color:var(--good)"></i>NPV best case — shell demi shell</span>
  <span class="li"><i class="ln" style="border-color:var(--bad)"></i>NPV worst case — bench demi bench</span>
  <span class="li"><i class="ln" style="border-color:var(--pit);border-top-style:dashed"></i>Nilai tak terdiskonto</span></div>`;

/* ───────────── sensitivity ───────────── */
export function sensitivity(sens, { w = 520, h = 300, perProduct = false } = {}) {
  if (!sens || !sens.all.length) return "";
  const pts = sens.all.slice().sort((a, b) => a.price_factor - b.price_factor);
  const m = { l: 48, r: 18, t: 22, b: 44 };
  const pw = w - m.l - m.r, ph = h - m.t - m.b;
  const extra = perProduct ? Object.entries(sens.per_product) : [];
  const all = [...pts.map((p) => p.npv), ...extra.flatMap(([, rows]) => rows.map((p) => p.npv))].map((v) => v / 1e6);
  const lo = Math.min(...all, 0), hi = Math.max(...all, 1);
  const top = niceMax(hi), bottom = lo < 0 ? -niceMax(-lo) : 0;
  const x0 = pts[0].price_factor, x1 = pts[pts.length - 1].price_factor;
  const X = (f) => m.l + ((f - x0) / (x1 - x0)) * pw;
  const Y = (v) => m.t + ph - ((v - bottom) / (top - bottom)) * ph;
  let s = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Sensitivitas harga">`;
  const step = (top - bottom) / 4;
  for (let i = 0; i <= 4; i++) {
    const v = bottom + step * i;
    s += `<line x1="${m.l}" x2="${w - m.r}" y1="${Y(v)}" y2="${Y(v)}" style="stroke:${C.grid}"/><text x="${m.l - 6}" y="${Y(v) + 3.5}" text-anchor="end" font-size="9.5" style="fill:${C.text}">${fmt(v, Math.abs(step) < 4 ? 1 : 0)}</text>`;
  }
  s += `<text x="${m.l - 6}" y="${m.t - 9}" text-anchor="end" font-size="9.5" style="fill:${C.text}">NPV jt USD</text>`;
  const be = sens.breakeven;
  if (bottom < 0) {
    s += `<rect x="${m.l}" y="${Y(0)}" width="${pw}" height="${Y(bottom) - Y(0)}" style="fill:var(--bad-fill)" opacity=".7"/>`;
  }
  s += `<line x1="${m.l}" x2="${w - m.r}" y1="${Y(0)}" y2="${Y(0)}" style="stroke:var(--faint)"/>`;
  const path = (rows, color, dash, wd = 2) => `<path d="${rows.map((p, i) => `${i ? "L" : "M"}${X(p.price_factor).toFixed(1)},${Y(p.npv / 1e6).toFixed(1)}`).join("")}" fill="none" stroke-width="${wd}" ${dash ? `stroke-dasharray="${dash}"` : ""} style="stroke:${color}"/>`;
  const palette = ["var(--pit)", "var(--topo)", "var(--good)", "var(--bad)"];
  extra.forEach(([, rows], i) => { s += path(rows.slice().sort((a, b) => a.price_factor - b.price_factor), palette[i % palette.length], "4 3", 1.6); });
  s += path(pts, "var(--accent)", "", 2.4);
  const base = pts.find((p) => Math.abs(p.price_factor - 1) < 1e-9);
  if (base) {
    s += `<circle cx="${X(1)}" cy="${Y(base.npv / 1e6)}" r="4" style="fill:var(--accent)"/>`;
    s += `<text x="${X(1) + 8}" y="${Y(base.npv / 1e6) - 14}" font-size="9.5" font-weight="600" style="fill:var(--text)">harga rencana</text>`;
    s += `<text x="${X(1) + 8}" y="${Y(base.npv / 1e6) - 3}" font-size="9.5" style="fill:${C.text}">${mUSD(base.npv)} jt USD</text>`;
  }
  if (be != null && be >= x0 && be <= x1) {
    s += `<line x1="${X(be)}" x2="${X(be)}" y1="${m.t}" y2="${h - m.b}" stroke-dasharray="3 3" style="stroke:var(--bad);stroke-width:1.4"/>`;
    s += `<text x="${X(be) + 6}" y="${Y(0) + 26}" font-size="9.5" font-weight="700" style="fill:var(--bad)">break-even</text><text x="${X(be) + 6}" y="${Y(0) + 38}" font-size="9.5" style="fill:var(--bad)">${fmt(be * 100, 1)}% harga</text>`;
  }
  for (const p of pts) s += `<text x="${X(p.price_factor)}" y="${h - m.b + 15}" text-anchor="middle" font-size="9.5" font-weight="${Math.abs(p.price_factor - 1) < 1e-9 ? 700 : 400}" style="fill:${Math.abs(p.price_factor - 1) < 1e-9 ? "var(--text)" : C.text}">${fmt(p.price_factor, 2)}</text>`;
  s += `<text x="${(m.l + w - m.r) / 2}" y="${h - 6}" text-anchor="middle" font-size="9.5" style="fill:${C.text}">Faktor harga (${perProduct ? "semua produk bersama + per produk" : "semua produk bersama"})</text>`;
  return s + "</svg>";
}

/* ───────────── pushback gantt ───────────── */
export function gantt(rows, periods, { w = 620 } = {}) {
  if (!rows.length) return "";
  const rowH = 24, m = { l: 44, r: 14, t: 26, b: 8 }, h = m.t + rows.length * rowH + m.b;
  const pw = w - m.l - m.r, cw = pw / periods;
  let s = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Pushback per periode">`;
  for (let p = 1; p <= periods; p++) {
    s += `<text x="${m.l + cw * (p - 0.5)}" y="${m.t - 10}" text-anchor="middle" font-size="10" style="fill:${C.text}">${p}</text>`;
    s += `<line x1="${m.l + cw * p}" x2="${m.l + cw * p}" y1="${m.t - 4}" y2="${h - m.b}" style="stroke:${C.grid}"/>`;
  }
  s += `<text x="${w - m.r}" y="${m.t - 10}" text-anchor="end" font-size="9" style="fill:${C.axis}">periode</text>`;
  rows.forEach((r, i) => {
    const y = m.t + i * rowH;
    s += `<text x="${m.l - 8}" y="${y + 16}" text-anchor="end" font-size="11" font-weight="700" style="fill:var(--text)">PB${r.pushback}</text>`;
    if (r.periods) {
      const [a, b] = r.periods;
      s += `<rect x="${m.l + cw * (a - 1) + 1}" y="${y + 3}" width="${cw * (b - a + 1) - 2}" height="${rowH - 8}" rx="2" style="fill:${stageColor(r.pushback, rows.length)}"><title>PB${r.pushback}: periode ${a}–${b}</title></rect>`;
    }
  });
  return s + "</svg>";
}

/* ───────────── production + cumulative NPV ───────────── */
export function production(plan, pushbackCount, { w = 1000, h = 300, startYear = null } = {}) {
  if (!plan.length) return "";
  const m = { l: 50, r: 56, t: 22, b: 62 };
  const pw = w - m.l - m.r, ph = h - m.t - m.b, n = plan.length, slot = pw / n, bw = slot * 0.5;
  const tonnesMax = niceMax(Math.max(...plan.map((p) => (p.ore_tonnes + p.waste_tonnes) / 1e6), 0.1) * 1.05);
  const npvMax = niceMax(Math.max(...plan.map((p) => p.npv / 1e6), 1));
  const yl = (v) => m.t + ph - (v / tonnesMax) * ph, yr = (v) => m.t + ph - (v / npvMax) * ph, xc = (i) => m.l + slot * (i + 0.5);
  let s = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Produksi per periode">`;
  for (const t of axisTicks(tonnesMax)) s += `<line x1="${m.l}" x2="${w - m.r}" y1="${yl(t)}" y2="${yl(t)}" style="stroke:${C.grid}"/><text x="${m.l - 8}" y="${yl(t) + 3.5}" text-anchor="end" font-size="10" style="fill:${C.text}">${fmt(t, 1)}</text>`;
  for (const t of axisTicks(npvMax)) s += `<text x="${w - m.r + 8}" y="${yr(t) + 3.5}" font-size="10" style="fill:${C.text}">${fmt(t, npvMax < 4 ? 1 : 0)}</text>`;
  s += `<text x="${m.l - 8}" y="${m.t - 9}" text-anchor="end" font-size="10" style="fill:${C.text}">Mt</text><text x="${w - m.r + 8}" y="${m.t - 9}" font-size="10" style="fill:${C.text}">jt USD</text>`;
  plan.forEach((p, i) => {
    const ore = p.ore_tonnes / 1e6, waste = p.waste_tonnes / 1e6;
    s += `<rect x="${xc(i) - bw / 2}" y="${yl(ore)}" width="${bw}" height="${yl(0) - yl(ore)}" style="fill:${C.ore}"/>`;
    s += `<rect x="${xc(i) - bw / 2}" y="${yl(ore + waste)}" width="${bw}" height="${yl(ore) - yl(ore + waste)}" style="fill:${C.waste}"/>`;
    s += `<text x="${xc(i)}" y="${h - m.b + 16}" text-anchor="middle" font-size="10.5" style="fill:${C.text}">${p.period}</text>`;
    if (startYear) s += `<text x="${xc(i)}" y="${h - m.b + 29}" text-anchor="middle" font-size="9" style="fill:${C.axis}">${startYear + p.period - 1}</text>`;
    // pushback ribbon
    const active = String(p.pushbacks || "").replace(/\s/g, "").split(",").filter(Boolean).map((t) => parseInt(t.slice(2)));
    active.forEach((a, k) => {
      const seg = slot / active.length;
      s += `<rect x="${m.l + slot * i + seg * k}" y="${h - 20}" width="${seg}" height="9" style="fill:${stageColor(a, pushbackCount)}"><title>PB${a}</title></rect>`;
    });
  });
  s += `<path d="${plan.map((p, i) => `${i ? "L" : "M"}${xc(i).toFixed(1)},${yr(p.npv / 1e6).toFixed(1)}`).join("")}" fill="none" stroke-width="2.2" style="stroke:var(--text)"/>`;
  plan.forEach((p, i) => { s += `<circle cx="${xc(i)}" cy="${yr(p.npv / 1e6)}" r="3" style="fill:var(--text)"/>`; });
  const last = plan[plan.length - 1];
  s += `<text x="${xc(n - 1)}" y="${yr(last.npv / 1e6) - 10}" text-anchor="middle" font-size="11" font-weight="700" style="fill:var(--text)">${mUSD(last.npv)}</text>`;
  s += `<text x="${m.l - 8}" y="${h - 11}" text-anchor="end" font-size="8.5" style="fill:${C.axis}">pushback aktif</text>`;
  return s + "</svg>";
}

/* ───────────── plan view (canvas) ───────────── */
export function drawPlan(canvas, pv, mode, total, opts = {}) {
  const values = pv[mode];
  const { nx, ny } = pv;
  const sc = Math.max(2, Math.floor((opts.maxWidth || 640) / nx));
  canvas.width = nx * sc; canvas.height = ny * sc;
  const g = canvas.getContext("2d");
  g.clearRect(0, 0, canvas.width, canvas.height);
  const depthMax = mode === "depth" ? Math.max(...values, 1) : 1;
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const v = values[j * nx + i];
      if (!v) continue;
      g.fillStyle = mode === "depth" ? `rgb(${Math.round(232 - 110 * (v / depthMax))},${Math.round(207 - 100 * (v / depthMax))},${Math.round(163 - 90 * (v / depthMax))})` : stageColor(v, total);
      g.fillRect(i * sc, (ny - 1 - j) * sc, sc, sc);
    }
  }
  return sc;
}
export const legendSwatches = (n, labels = []) =>
  `<div class="legend">${Array.from({ length: n }, (_, i) => `<span class="li"><i class="box" style="background:${stageColor(i + 1, n)}"></i>${esc(labels[i] ?? `PB${i + 1}`)}</span>`).join("")}</div>`;

/* ───────────── bench wall profile ───────────── */
export function benchWall(d, { w = 320, h = 210 } = {}) {
  const H = d.bench_height, face = d.face_angle_deg, berm = d.berm_width, tf = Math.tan((face * Math.PI) / 180);
  const run = H / tf + berm, n = 3;
  const totalW = run * n + 4, totalH = H * n + 2;
  const sc = Math.min((w - 70) / totalW, (h - 50) / totalH);
  const ox = 26, oy = h - 26;
  const P = (x, z) => `${(ox + x * sc).toFixed(1)},${(oy - z * sc).toFixed(1)}`;
  let poly = `${P(0, 0)}`, x = 0, z = 0;
  for (let i = 0; i < n; i++) { x += H / tf; z += H; poly += ` ${P(x, z)}`; x += berm; poly += ` ${P(x, z)}`; }
  poly += ` ${P(x + 3, z)} ${P(x + 3, 0)}`;
  let s = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Detail dinding bench">`;
  s += `<polygon points="${poly}" style="fill:var(--accent-bg);stroke:var(--pit);stroke-width:1.6"/>`;
  s += `<line x1="${ox + 0}" y1="${oy}" x2="${ox + run * n * sc}" y2="${oy - H * n * sc}" stroke-dasharray="5 3" style="stroke:var(--text);stroke-width:1"/>`;
  s += `<line x1="${ox - 8}" y1="${oy}" x2="${ox - 8}" y2="${oy - H * sc}" style="stroke:var(--muted)"/><text x="${ox - 12}" y="${oy - H * sc / 2 + 3}" text-anchor="end" font-size="9" style="fill:var(--muted)">${fmt(H, 0)} m</text>`;
  s += `<text x="${ox + (H / tf) * sc * 0.4}" y="${oy - H * sc * 0.28}" font-size="9" style="fill:var(--muted)">${fmt(face, 0)}°</text>`;
  s += `<text x="${ox + (H / tf + berm / 2) * sc}" y="${oy - H * sc - 5}" text-anchor="middle" font-size="9" style="fill:var(--muted)">${fmt(berm, 2)} m</text>`;
  s += `<text x="${ox + run * 2.1 * sc}" y="${oy - H * 1.2 * sc}" font-size="10" font-weight="700" style="fill:var(--text)">overall ${fmt(d.overall_angle_deg, 1)}°</text>`;
  return s + "</svg>";
}

/* ───────────── section ───────────── */
export function section(data, { ve = 1, layers = ["face"], w = 760, title = "" } = {}) {
  const dist = data.distance, series = data.series;
  const vals = ["topo", "optimiser", ...layers].flatMap((k) => series[k] || []).filter((v) => v != null);
  if (!vals.length) return `<div class="empty">Tidak ada data pada garis penampang ini.</div>`;
  const zmin = Math.min(...vals) - 1, zmax = Math.max(...vals) + 1, len = dist[dist.length - 1] || 1;
  const m = { l: 44, r: 12, t: 14, b: 26 };
  const sx = (w - m.l - m.r) / len;
  const ph = Math.max(40, (zmax - zmin) * sx * ve);
  const h = ph + m.t + m.b;
  const X = (d) => m.l + d * sx, Y = (z) => m.t + ph - (z - zmin) * sx * ve;
  const path = (arr, step) => {
    let d = "", open = false, prev = null;
    arr.forEach((v, i) => {
      if (v == null) { open = false; return; }
      if (step && open && prev != null) d += `L${X(dist[i]).toFixed(1)},${Y(prev).toFixed(1)}`;
      d += `${open ? "L" : "M"}${X(dist[i]).toFixed(1)},${Y(v).toFixed(1)}`; open = true; prev = v;
    });
    return d;
  };
  let s = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(title)}">`;
  const ticks = 4;
  for (let i = 0; i <= ticks; i++) {
    const z = zmin + ((zmax - zmin) * i) / ticks;
    s += `<line x1="${m.l}" x2="${w - m.r}" y1="${Y(z)}" y2="${Y(z)}" style="stroke:${C.grid}"/><text x="${m.l - 6}" y="${Y(z) + 3}" text-anchor="end" font-size="9" style="fill:${C.text}">${fmt(z, 0)}</text>`;
  }
  for (let d = 0; d <= len; d += niceMax(len / 6) / 1) { if (d > len) break; s += `<text x="${X(d)}" y="${h - 8}" text-anchor="middle" font-size="9" style="fill:${C.text}">${fmt(d, 0)}</text>`; }
  const face = series[layers[0]] || series.topo, topo = series.topo;
  // mined material between topography and face
  let poly = "", started = false;
  for (let i = 0; i < dist.length; i++) if (topo[i] != null && face[i] != null && face[i] < topo[i] - 0.05) { poly += `${started ? "L" : "M"}${X(dist[i]).toFixed(1)},${Y(topo[i]).toFixed(1)}`; started = true; }
  for (let i = dist.length - 1; i >= 0; i--) if (topo[i] != null && face[i] != null && face[i] < topo[i] - 0.05) poly += `L${X(dist[i]).toFixed(1)},${Y(face[i]).toFixed(1)}`;
  if (poly) s += `<path d="${poly}Z" style="fill:var(--pit-l);opacity:.45"/>`;
  s += `<path d="${path(series.optimiser, true)}" fill="none" stroke-width="1" style="stroke:var(--grey)"/>`;
  s += `<path d="${path(topo)}" fill="none" stroke-width="1.6" style="stroke:var(--topo)"/>`;
  if (series.bowl && layers.includes("bowl")) s += `<path d="${path(series.bowl)}" fill="none" stroke-width="1.3" stroke-dasharray="5 3" style="stroke:var(--pit)"/>`;
  if (face) s += `<path d="${path(face)}" fill="none" stroke-width="2" style="stroke:var(--pit)"/>`;
  return s + "</svg>";
}
