// 06 · Ramp — the haul road: pattern, width from the truck, grade, and what it does to the overall slope angle.
import { A } from "../actions.js";
import { esc, fmt } from "../util.js";
import { D, ensure, pill, changed } from "../design/core.js";
import { field, gate, noDesign, notice, page, planControls, saveButton } from "../design/ui.js";
import { paintPlan } from "../design/planview.js";
import { css } from "../design/plan.js";

const norm = (a) => ((a % 360) + 360) % 360;

export function render() {
  ensure();
  const g = gate("Ramp");
  if (g) return g;
  const st = D.state, ramp = st.ramp, doc = D.result?.document, r = doc?.ramp;
  const pattern = st.params.detail.ramp.pattern;
  const p = st.params.detail.ramp;
  const toggle = (k, label) => `<button class="btn ${p.pattern === k ? "on" : ""}" data-act="dPattern" data-k="${k}" style="flex:1;height:44px">${label}</button>`;
  return page("Ramp", "Langkah 3 dari 5 · satu ramp per pit (spiral atau switchback), lebar dari spesifikasi alat, grade tetap.",
    `${changed() ? `<button class="btn" data-act="dResetDraft">Batalkan perubahan</button>${saveButton()}` : ""}<button class="btn primary" data-act="dGenerate">${D.result ? "Terapkan & regenerasi" : "Generate desain"}</button>`, `
  ${notice()}
  <div class="dd-cols3">
    <div class="card"><div class="cardhead"><h2>Alignment ramp</h2></div>
      <div class="row" style="gap:8px;margin-bottom:12px">${toggle("spiral", "◎ Spiral")}${toggle("switchback", "⇄ Switchback")}</div>
      <div class="navh" style="padding:0 0 8px">LEBAR RAMP — DARI ALAT ANGKUT</div>
      <div class="dd-two">${field({ label: "Lebar truk terbesar", path: "ramp.truck_width_m", unit: "m" })}${field({ label: "Jumlah jalur", path: "ramp.lanes", unit: "jalur", kind: "int", step: 1, min: 1 })}
        ${field({ label: "Berm keselamatan", path: "ramp.safety_berm_m", unit: "m" })}${field({ label: "Drainase", path: "ramp.drain_m", unit: "m" })}</div>
      <div class="note" style="margin:12px 0"><div class="row"><span class="grow">Lebar ramp (hasil)</span><b class="num" style="font-size:22px">${ramp ? fmt(ramp.width_m, 1) : "—"}</b><span class="muted">m</span></div>
        ${ramp?.required_width_m != null && ramp.source === "manual" && !ramp.width_ok ? `<div class="xs" style="color:var(--bad);margin-top:6px">Lebar manual ${fmt(ramp.width_m, 1)} m lebih sempit dari kebutuhan armada ${fmt(ramp.required_width_m, 1)} m.</div>` : ""}
        ${ramp ? "" : `<div class="xs" style="color:var(--bad);margin-top:6px">Isi lebar truk (atau lebar ramp manual) agar ramp bisa dihitung. Tidak ada default armada.</div>`}</div>
      ${field({ label: "Lebar ramp manual (opsional)", path: "ramp.width_m", unit: "m", hint: "Kosong = dari lebar truk. Diisi = dipakai apa adanya dan dicek terhadap kebutuhan armada." })}
      <div class="navh" style="padding:14px 0 8px">KEMIRINGAN &amp; TITIK</div>
      <div class="dd-two">${field({ label: "Grade", path: "ramp.grade_pct", unit: "%" })}${field({ label: "Arah putar", path: "ramp.direction", kind: "select", options: [["clockwise", "searah jam"], ["anticlockwise", "berlawanan jam"]] })}
        ${field({ label: "Azimut masuk", path: "ramp.entry_azimuth_deg", unit: "°", hint: `Kosong = di azimut tempat dinding terlebar${r?.entry_defaulted ? `: ${fmt(r.entry_azimuth_deg, 0)}°` : ""}.` })}
        ${p.pattern === "switchback" ? `${field({ label: "Jumlah balik arah", path: "ramp.switchbacks", kind: "int", step: 1, min: 1 })}${field({ label: "Radius hairpin", path: "ramp.hairpin_radius_m", unit: "m", hint: "Dari lingkaran putar truk; tanpa default." })}` : ""}</div>
      <p class="xs muted" style="margin:10px 0 0">Grade dalam batas ${fmt(p.grade_min_pct, 0)}–${fmt(p.grade_max_pct, 0)} %; batas traksi 12 %.${D.result && r ? ` Panjang centerline <b class="num">${fmt(r.horizontal_length_m, 0)} m</b> untuk naik ${fmt(D.result.document.crest_rl - D.result.document.floor_rl, 0)} m.` : ""}</p></div>
    <div>
      <div class="card"><div class="cardhead"><h2>Alignment di plan view</h2><span class="lbl">lingkaran kosong = masuk di dasar · pita = lebar ramp</span></div>
        ${D.result ? `<div style="margin-bottom:8px">${planControls({ modes: false })}</div><canvas id="dplan" class="plan" style="height:440px"></canvas>` : noDesign()}</div>
      <div class="card"><div class="cardhead"><h2>Profil memanjang</h2><span class="lbl">elevasi terhadap jarak · sektor yang dilewati di bawah sumbu</span></div>
        ${D.result?.ramp ? `<canvas id="dprofile" class="plan" style="height:220px"></canvas>` : `<div class="empty">Belum ada ramp untuk ditampilkan.</div>`}</div>
    </div>
    <div>${side(doc, r)}</div>
  </div>`);
}

function side(doc, r) {
  if (!doc || !r) return `<div class="card"><div class="empty">Hasil ramp muncul setelah desain di-generate.</div></div>`;
  const n = doc.benches.length, present = new Set(D.result.ramp.bench);
  const cells = Array.from({ length: n }, (_, i) => {
    const bench = i + 1, ok = present.has(bench);
    return `<span class="num" style="display:inline-flex;width:22px;height:22px;align-items:center;justify-content:center;border-radius:3px;font-size:10px;border:1px solid ${ok ? "var(--good-line)" : "var(--bad-line)"};background:${ok ? "var(--good-bg)" : "var(--bad-fill)"};color:${ok ? "var(--good)" : "var(--bad-d)"}">${bench}</span>`;
  }).join("");
  const rows = doc.sectors.filter((s) => s.osa_deg != null).map((s) => {
    const d = s.osa_deg - s.osa_no_ramp_deg;
    return `<tr><td class="l">${esc(s.name)}</td><td>${fmt(s.osa_no_ramp_deg, 1)}</td><td class="${s.osa_status === "BLOKIR" ? "worst" : ""}">${fmt(s.osa_deg, 1)}</td><td class="muted">${fmt(d, 1)}</td></tr>`;
  }).join("");
  const width = doc.floor_width_m, min = doc.provenance.parameters.find((p) => p.id === "limits.min_mining_width_m")?.value ?? 30;
  return `<div class="card"><div class="cardhead"><h2>Efek ramp pada OSA</h2></div>
      <table class="t"><thead><tr><th class="l">Sektor</th><th>OSA tanpa</th><th>OSA + ramp</th><th>Δ</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="xs muted" style="margin:8px 0 0">Ramp memakan ruang berm: tiap perpotongan menambah lebar ramp dikurangi berm ke lebar dinding. Sektor yang dilewati ramp ${fmt(Math.max(...doc.sectors.map((s) => s.ramp_crossings_max || 0)), 0)}× di garis kritis turun paling jauh.</p></div>
    <div class="card"><div class="cardhead"><h2>Continuity check</h2><span class="lbl">titik potong ramp di tiap bench</span></div>
      <div class="row" style="flex-wrap:wrap;gap:4px">${cells}</div>
      <div class="row" style="margin-top:10px;gap:10px">${pill(r.complete ? "OK" : "BLOKIR")}<span class="small">${r.complete ? `Satu jalur menerus dari dasar sampai puncak — ${n} / ${n} bench terpotong.` : `Ramp putus di bench ${r.broken.bench}: ${esc(r.broken.reason)}`}</span></div>
      ${r.pattern === "switchback" ? `<p class="xs muted" style="margin:8px 0 0">Platform hairpin diasumsikan muat; geometrinya tidak digambar atau dicek.</p>` : ""}</div>
    <div class="card"><div class="cardhead"><h2>Lebar dasar pit</h2></div>
      <div class="row" style="gap:10px;align-items:baseline"><b class="num" style="font-size:26px">${fmt(width, 0)}</b><span class="muted">m</span><span class="grow"></span><span class="small muted">min. mining width <b class="num">${fmt(min, 0)} m</b></span></div>
      <div class="row" style="margin-top:8px;gap:10px">${pill(doc.findings.find((f) => f.check === "min_width")?.status || "OK")}<span class="small">Dasar pit selebar lingkaran terbesar yang muat — yang dibutuhkan alat untuk berputar.${doc.floor_widened ? " Dasar dilebarkan sampai lebar minimum." : ""}</span></div></div>`;
}

A.dPattern = (el) => import("../design/core.js").then((m) => m.setParam("ramp.pattern", el.dataset.k));

export function mount() {
  const c = document.getElementById("dplan");
  if (c && D.plan && D.result) paintPlan(c, { plan: D.plan, result: D.result, layers: { ...D.layers, blocks: D.layers.blocks }, mode: D.color || "kadar", sectors: D.state.sectors });
  const pc = document.getElementById("dprofile");
  if (pc && D.result?.ramp) profile(pc);
}

function profile(canvas) {
  const R = D.result.ramp, dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const c = canvas.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0);
  const s = [0]; for (let i = 1; i < R.x.length; i++) s.push(s[i - 1] + Math.hypot(R.x[i] - R.x[i - 1], R.y[i] - R.y[i - 1]));
  const L = s.at(-1), z0 = R.z[0], z1 = R.z.at(-1), padL = 52, padR = 14, padT = 12, padB = 42;
  const X = (d) => padL + ((w - padL - padR) * d) / L, Y = (z) => padT + (h - padT - padB) * (1 - (z - z0) / (z1 - z0));
  const ink = css("--text"), muted = css("--muted"), accent = css("--accent");
  c.fillStyle = css("--panel2"); c.fillRect(0, 0, w, h);
  c.font = "10px 'IBM Plex Mono', monospace"; c.fillStyle = muted; c.strokeStyle = css("--line2");
  for (let i = 0; i <= 4; i++) { const z = z0 + ((z1 - z0) * i) / 4, y = Y(z); c.beginPath(); c.moveTo(padL, y); c.lineTo(w - padR, y); c.stroke(); c.fillText(`+${fmt(z, 0)}`, 4, y + 3); }
  for (let i = 0; i <= 4; i++) c.fillText(fmt((L * i) / 4, 0), X((L * i) / 4) - 8, h - padB + 14);
  c.fillText("jarak sepanjang centerline (m)", padL, h - padB + 28);
  c.beginPath(); R.z.forEach((z, i) => (i ? c.lineTo(X(s[i]), Y(z)) : c.moveTo(X(s[i]), Y(z)))); c.strokeStyle = accent; c.lineWidth = 2.4; c.stroke();
  c.fillStyle = ink; c.font = "11px 'IBM Plex Sans', sans-serif";
  c.fillText(`grade ${fmt(D.result.document.ramp.grade_pct, 1)} % konstan`, X(L * 0.35), Y(z0 + (z1 - z0) * 0.55) - 8);
  // the sector under the road, along the bottom
  const sectors = D.state.sectors || [];
  const name = (az) => sectors.find((sec) => ((norm(az) - sec.azimuth_from + 360) % 360) < (((sec.azimuth_to - sec.azimuth_from) % 360 + 360) % 360 || 360))?.name || "";
  let start = 0; c.font = "10px 'IBM Plex Sans', sans-serif";
  for (let i = 1; i <= R.x.length; i++) {
    if (i === R.x.length || name(R.azimuth[i]) !== name(R.azimuth[start])) {
      c.fillStyle = css("--accent-bg"); c.fillRect(X(s[start]), h - 16, X(s[i - 1]) - X(s[start]), 14);
      c.fillStyle = css("--accent-d"); c.fillText(name(R.azimuth[start]), X(s[start]) + 3, h - 6); start = i;
    }
  }
}
