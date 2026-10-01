// 06 · Generate & Tinjau — compute the design, watch it arrive bench by bench in 3D, cancel it, read the result.
import { A } from "../actions.js";
import { esc, fmt } from "../util.js";
import { D, ensure, pill, running } from "../design/core.js";
import { findingsBanner, gate, noDesign, notice, page, say } from "../design/ui.js";
import { paintPlan } from "../design/planview.js";
import { draw } from "../design/three.js";

export function render() {
  ensure();
  const g = gate("Generate & Tinjau");
  if (g) return g;
  const st = D.state, doc = D.result?.document, job = D.job;
  const busy = running(), sectors = st.sectors || [], sel = Math.min(D.sel, sectors.length - 1), s = sectors[sel];
  const pct = job ? Math.round(job.fraction * 100) : 0;
  const nProblems = doc ? doc.findings.filter((f) => f.status !== "OK").length : 0;
  const stale = st.session && !st.session.current;
  const layer = (k, label) => `<label class="chk" style="display:flex;padding:3px 0"><input type="checkbox" data-act="dLayer" data-k="${k}" ${D.layers[k] ? "checked" : ""}> ${label}</label>`;
  const osa = doc?.sectors.find((x) => x.name === s?.name);
  return page("Generate & Tinjau", "Langkah 4 dari 5 · hitung bench dan ramp dari parameter, tinjau hasil per sektor.",
    `${busy ? `<button class="btn danger" data-act="dCancel">Batalkan generate</button>` : `<button class="btn primary" data-act="dGenerate">${D.result ? "Generate ulang" : "Generate desain"}</button>`}`, `
  ${notice()}
  ${busy ? `<div class="banners" style="border-color:var(--accent-line);background:var(--accent-soft);margin-bottom:16px"><div class="bh" style="gap:14px"><span class="tagc info">SEDANG BERJALAN</span>
      <div class="pbar" style="width:220px"><i style="width:${pct}%"></i></div><span class="num">bench ${job.done || 0} / ${job.total ?? "…"} · ${pct} % · ${fmt(job.elapsed, 1)} s</span><span class="muted small">Bench yang selesai langsung tampil di viewer.</span></div></div>`
    : stale ? `<div class="banners" style="margin-bottom:16px"><div class="bh"><span class="tagc asumsi">BASI</span><span>Parameter berubah sejak desain ini dibuat. Generate ulang agar angka dan gambar sesuai.</span></div></div>`
    : doc ? findingsBanner(doc, { limit: 3 }) : ""}
  ${!D.result && !busy ? noDesign() : `
  <div class="dd-gen">
    <div class="card"><div class="navh" style="padding:0 0 8px">SEKTOR GEOTEKNIK</div>
      <div class="chips">${sectors.map((x, i) => `<button class="btn sm ${i === sel ? "on" : ""}" data-act="dSel" data-i="${i}">${esc(x.name)}</button>`).join("")}</div>
      ${s ? `<div class="note num small" style="margin:10px 0">H ${fmt(s.bench_height, 0)} m · β ${fmt(s.face_angle_deg, 0)}° · berm ${fmt(s.berm_width, 1)} m · IRA ${fmt(s.ira_deg, 1)}°</div>` : ""}
      <div class="navh" style="padding:8px 0 6px">LAYER</div>${layer("shell", "Shell PitOpt")}${layer("bench", "Bench (crest + toe)")}${layer("ramp", "Ramp centerline")}${layer("sector", "Sektor")}${layer("blocks", "Block model (slice)")}
      <p class="xs muted" style="margin:10px 0 0">Skala vertikal selalu ditampilkan; penampang 1:1 tersedia di layar Penampang.</p></div>
    <div class="card" style="padding:0"><div class="row" style="padding:12px 16px;border-bottom:1px solid var(--line);gap:12px"><h2>Viewer 3D</h2><span class="muted small">desain praktis</span><span class="grow"></span>
        <span class="xs muted">VERTICAL EXAGGERATION</span><span class="tabs">${[1, 2, 5].map((v) => `<button data-act="dVe" data-v="${v}" class="${D.ve === v ? "on" : ""}">${v}×</button>`).join("")}</span><span class="ve ${D.ve === 1 ? "one" : ""}">VE ${fmt(D.ve, 1)}×</span></div>
      <div style="position:relative"><div id="d3d" style="height:600px"></div>
        ${D.layers.blocks && D.plan ? `<div class="inset"><div class="xs" style="padding:6px 8px 0"><b>Block model</b> · slice RL <span class="num">${fmt(D.plan.rl, 1)}</span></div><canvas id="dplan" style="width:220px;height:170px;display:block"></canvas></div>` : ""}
        ${busy ? `<div class="chip" style="position:absolute;left:50%;bottom:14px;transform:translateX(-50%);background:var(--panel)">Bench ${job.done || 0}${job.total ? ` dari ${job.total}` : ""} sudah tampil</div>` : ""}</div></div>
    <div class="card" style="padding:0"><div class="tabs" style="border:0;border-bottom:1px solid var(--line);border-radius:0;display:flex"><button class="${D.tab === "param" ? "on" : ""}" data-act="dTab" data-k="param" style="flex:1">Parameter</button><button class="${D.tab === "val" ? "on" : ""}" data-act="dTab" data-k="val" style="flex:1">Validasi ${nProblems ? `<span class="pill warn">${nProblems}</span>` : ""}</button></div>
      <div style="padding:14px 16px">${D.tab === "val" ? valTab(doc) : paramTab(s, osa, doc)}</div></div>
  </div>`}`);
}

function paramTab(s, osa, doc) {
  if (!s) return `<div class="empty">Tidak ada sektor.</div>`;
  return `<div class="navh" style="padding:0">SEKTOR TERPILIH</div><h2 style="font-size:17px;margin:2px 0 10px">${esc(s.name)}</h2>
    <div class="kv"><span class="muted">Tinggi bench</span><span>${fmt(s.bench_height, 0)} m</span><span class="muted">Sudut muka β</span><span>${fmt(s.face_angle_deg, 0)}°</span><span class="muted">Berm tiap N=${s.berm_every_n}</span><span>${fmt(s.berm_width, 2)} m</span></div>
    <div class="note" style="margin-top:12px"><div class="navh" style="padding:0 0 6px">HASIL GEOMETRI AKTUAL</div>
      <div class="kv"><span class="muted">Offset H/tan β</span><span>${fmt(s.run_m, 2)} m</span>
      <span class="muted">IRA</span><span>${osa ? `${fmt(doc.sectors.find((x) => x.name === s.name).ira_deg, 1)}° / ${s.ira_max_deg == null ? "—" : fmt(s.ira_max_deg, 1) + "°"}` : "–"}</span>
      <span class="muted">OSA (dengan ramp)</span><span>${osa ? `${fmt(osa.osa_deg, 1)}° / ${s.osa_max_deg == null ? "—" : fmt(s.osa_max_deg, 1) + "°"}` : "–"}</span></div></div>
    <button class="btn primary" style="width:100%;margin-top:12px" data-act="dGenerate">Terapkan &amp; regenerasi</button>
    <p class="xs muted" style="margin:8px 0 0">Seluruh tumpukan dibangun ulang (sekitar ${D.result ? fmt(D.result.elapsed, 1) : "beberapa"} detik): dinding satu sektor menyatu dengan tetangganya lewat blend di batas azimut, sehingga sektor lain tidak bisa dipakai ulang begitu saja. Parameter yang tidak berubah dipakai dari hasil sebelumnya.</p>
    <a data-go="d-sektor" class="small">Ubah parameter di Crest &amp; Sektor →</a>`;
}
function valTab(doc) {
  if (!doc) return `<div class="empty">Belum ada hasil.</div>`;
  return `${doc.findings.map((f) => `<div class="row small" style="gap:8px;padding:7px 0;border-top:1px solid var(--line2);align-items:flex-start">${pill(f.status)}<span>${f.scope ? `<b>${esc(f.scope)}</b> — ` : ""}${esc(say(f))}</span></div>`).join("")}
    <a data-go="d-validasi" class="btn" style="display:block;text-align:center;margin-top:12px;text-decoration:none">Buka Validasi lengkap →</a>`;
}

A.dTab = (el) => { D.tab = el.dataset.k; import("../store.js").then((m) => m.notify()); };
A.dVe = (el) => { D.ve = +el.dataset.v; import("../store.js").then((m) => m.notify()); };

export function mount() {
  const el = document.getElementById("d3d");
  if (el) draw(el).catch((e) => { el.innerHTML = `<div class="empty" style="margin:40px">${esc(e.message)}</div>`; });
  const c = document.getElementById("dplan");
  if (c && D.plan) paintPlan(c, { plan: D.plan, result: D.result, layers: { blocks: true, shell: true }, mode: D.color || "kadar", showRamp: false });
}
