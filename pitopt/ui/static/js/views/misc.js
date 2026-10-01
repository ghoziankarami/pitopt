import { S, notify, loadCompare, scenarioMeta } from "../store.js";
import { A } from "../actions.js";
import { fmt, fmtInt, mUSD, mt, pcts, esc, tr, qs } from "../util.js";
import { sensitivity } from "../charts.js";
import { pageHead, empty, banners } from "./common.js";
import { startRun } from "../run.js";

const ui = { sensProduct: "all", pick: new Set(), files: new Set() };

export function render(view) {
  if (view === "jalankan") return jalankan();
  if (view === "bandingkan") return bandingkan();
  const r = S.results;
  if (!r) return empty({ sensitivitas: "Sensitivitas", data: "Data", qa: "QA Data", ekspor: "Ekspor" }[view]);
  return { sensitivitas, data, qa, ekspor }[view](r);
}

export function mount(root, view) {
  if (view === "jalankan") { const l = root.querySelector(".log"); if (l) l.scrollTop = l.scrollHeight; }
  if (view === "bandingkan") { const miss = [...ui.pick].filter((id) => !(id in S.compare)); if (miss.length) loadCompare(miss).then(notify); }
}

/* ── Sensitivitas ── */
function sensitivitas(r) {
  if (!r.sensitivity) return `<div class="page">${pageHead("Sensitivitas", "")}<div class="card"><div class="empty">Sensitivitas tidak dihitung di skenario ini. Aktifkan jadwal dan sensitivitas di Parameter.</div></div></div>`;
  const s = r.sensitivity, prods = Object.keys(s.per_product || {});
  const tabs = ["all", ...prods].map((p) => `<button data-act="sensProd" data-v="${esc(p)}" class="${ui.sensProduct === p ? "on" : ""}">${p === "all" ? "Semua harga" : esc(p)}</button>`).join("");
  const rows = (ui.sensProduct === "all" ? s.all : s.per_product[ui.sensProduct]);
  const be = s.breakeven;
  return `<div class="page">${pageHead("Sensitivitas", "NPV pit terhadap faktor harga, pit dioptimasi ulang di tiap titik", `<div class="tabs">${tabs}</div>`)}
  <div class="split"><div class="card"><div class="chart">${sensitivity(s, { w: 520, h: 300, perProduct: ui.sensProduct !== "all" ? ui.sensProduct : false })}</div>
    <p class="howto">${s.all.some((x) => x.npv < 0) ? `NPV negatif pada faktor harga ${s.all.filter((x) => x.npv < 0).map((x) => fmt(x.price_factor * 100, 0) + "%").join(", ")}. Pit final tetap; blok dinilai ulang pada harga itu.` : "NPV positif di seluruh rentang harga yang diuji."}</p></div>
  <div class="card flat"><div style="padding:14px 20px 4px"><h2>Tabel</h2></div><div style="overflow:auto"><table class="t"><thead><tr><th class="l">Faktor harga</th><th>Value jt</th><th>NPV jt</th>${ui.sensProduct === "all" ? "<th>Umpan Mt</th><th>Periode</th>" : ""}</tr></thead>
    <tbody>${rows.map((x) => `<tr class="${x.price_factor === 1 ? "final" : ""}"><td class="l">${fmt(x.price_factor * 100, 0)}%</td><td>${mUSD(x.value)}</td><td class="${x.npv < 0 ? "bad" : ""}">${mUSD(x.npv)}</td>${ui.sensProduct === "all" ? `<td>${mt(x.ore_tonnes)}</td><td>${x.periods}</td>` : ""}</tr>`).join("")}</tbody></table></div>
    <p class="xs muted" style="padding:10px 20px 14px;margin:0">Titik impas: <b>${be != null ? pcts(be, 1) : "tidak ditemukan"}</b> dari harga rencana. ${r.kpis.leverage ? `Leverage ${fmt(r.kpis.leverage, 1)}× — 1% harga menggeser NPV ~${fmt(r.kpis.leverage, 1)}%.` : ""}</p></div></div></div>`;
}
A.sensProd = (el) => { ui.sensProduct = el.dataset.v; notify(); };

/* ── Data ── */
function data(r) {
  const inp = r.inputs, pm = r.params.block_model || {}, prov = r.provenance || {};
  const rows = inp.map((x) => `<tr><td class="l">${esc(x.item)}</td><td class="l num">${esc(x.value)}</td><td class="l muted">${esc(x.unit)}</td></tr>`).join("");
  const src = [["Block model", S.raw?.block_model?.path], ["Topografi", S.raw?.surface?.path || S.raw?.surface?.topography]].filter((x) => x[1]);
  return `<div class="page">${pageHead("Data", "ringkasan input yang dibaca engine")}
  <div class="split"><div class="card flat"><div style="padding:14px 20px 4px"><h2>Model blok</h2></div><table class="t"><tbody>${rows}</tbody></table></div>
  <div class="card"><h2>Berkas sumber</h2>${src.map(([k, v]) => `<div class="row small" style="padding:6px 0"><span class="muted" style="width:110px">${k}</span><span class="num">${esc(v)}</span></div>`).join("") || `<div class="muted small">–</div>`}
    <p class="xs muted">Path relatif terhadap folder proyek. Data mentah tidak diunggah; server hanya membaca dalam folder proyek.</p></div></div></div>`;
}

/* ── QA ── */
function qa(r) {
  const q = r.qa;
  const pill = (s) => `<span class="pill ${s === "ok" ? "ok" : s === "peringatan" ? "warn" : "bad"}">${esc(s)}</span>`;
  const prods = Object.keys(q.domain_class[0] || {}).filter((k) => !["domain", "resource_class", "blocks", "volume", "ore_domain"].includes(k));
  return `<div class="page">${pageHead("QA Data", "pemeriksaan sebelum optimasi")}
  <div class="card" style="margin-bottom:16px">${q.checks.map((c) => `<div class="checkrow"><div style="width:96px">${pill(c.status)}</div><div class="grow"><b>${esc(c.name)}</b><div class="xs muted">${esc(tr(c.detail))}</div></div></div>`).join("")}</div>
  <div class="card flat"><div style="padding:14px 20px 4px"><h2>Domain × kelas sumberdaya</h2><span class="muted small">rata-rata grade, pembobotan volume</span></div><div style="overflow:auto"><table class="t"><thead><tr><th class="l">Domain</th><th class="l">Kelas</th><th>Blok</th><th>Volume m³</th>${prods.map((p) => `<th>${esc(p)}</th>`).join("")}<th class="l">Bijih</th></tr></thead>
  <tbody>${q.domain_class.map((d) => `<tr><td class="l">${esc(d.domain)}</td><td class="l">${esc(d.resource_class)}</td><td>${fmtInt(d.blocks)}</td><td>${fmtInt(d.volume)}</td>${prods.map((p) => `<td>${fmt(d[p], 2)}</td>`).join("")}<td class="l">${d.ore_domain ? "ya" : "–"}</td></tr>`).join("")}</tbody></table></div></div></div>`;
}

/* ── Jalankan ── */
function jalankan() {
  const j = S.job, { scenario } = scenarioMeta();
  const logBtn = `<button class="btn" data-act="showLog" ${S.results ? "" : "disabled"}>Log run</button>`;
  const runBtn = logBtn + `<button class="btn primary" data-act="runCurrent" ${j?.status === "running" ? "disabled" : ""}>Jalankan ${esc(scenario?.name || "")}</button>`;
  if (!j) return `<div class="page">${pageHead("Jalankan", "optimasi, penjadwalan, dan verifikasi", runBtn)}<div class="card"><div class="empty">Belum ada run di sesi ini. ${S.results ? `Hasil terakhir: ${esc(S.results.meta.run_at || "")}, ${fmt(S.results.meta.elapsed_s, 0)} s.` : ""}<br><a data-act="showLog">Lihat log run terakhir</a></div></div></div>`;
  const st = j.stages || [];
  const stepper = st.map((n, i) => `<div class="step ${i < j.stage || j.status === "done" ? "done" : i === j.stage ? (j.status === "error" ? "err" : "cur") : ""}"><i>${i < j.stage || j.status === "done" ? "✓" : i + 1}</i><span>${esc(tr(n))}</span></div>`).join("");
  const cls = j.status === "error" ? "bad" : j.status === "done" ? "good" : "";
  return `<div class="page">${pageHead("Jalankan", `skenario ${esc(j.scenario || "")}`, runBtn)}
  <div class="card"><div class="row"><b class="${cls}">${{ running: "Berjalan…", done: "Selesai", error: "Gagal" }[j.status] || j.status}</b><span class="num muted small">${fmt(j.elapsed, 0)} s</span><span class="grow"></span><span class="num small">${fmt(j.fraction * 100, 0)}%</span></div>
    <div class="bar"><div style="width:${fmt(j.fraction * 100, 0)}%"></div></div><div class="stepper">${stepper}</div>
    ${j.error ? `<div class="banner bad small" style="margin-top:12px">${esc(j.error)}</div>` : ""}
    <pre class="log" style="margin-top:14px;max-height:420px;overflow:auto">${esc((j.log || []).join("\n"))}</pre>
    ${j.status === "done" ? `<div style="margin-top:12px"><a data-go="ringkasan">Lihat ringkasan →</a></div>` : ""}</div></div>`;
}

/* ── Bandingkan ── */
function bandingkan() {
  const all = S.projects.flatMap((p) => p.scenarios.filter((s) => s.has_results).map((s) => ({ id: `${p.id}/${s.id}`, p, s })));
  if (!ui.pick.size && all.length) for (const a of all.slice(0, 4)) ui.pick.add(a.id);
  const chosen = [...ui.pick].filter((id) => S.compare[id]);
  const picks = all.map((a) => `<label class="chk"><input type="checkbox" data-act="cmpPick" data-id="${esc(a.id)}" ${ui.pick.has(a.id) ? "checked" : ""}> ${esc(a.p.title || a.p.id)} · ${esc(a.s.name)}</label>`).join("");
  const line = (label, f) => `<tr><td class="l">${label}</td>${chosen.map((id) => `<td>${f(S.compare[id])}</td>`).join("")}</tr>`;
  const table = chosen.length ? `<div class="card flat" style="margin-top:16px;overflow:auto"><table class="t"><thead><tr><th class="l"></th>${chosen.map((id) => `<th>${esc(S.compare[id].meta.scenario || id.split("/")[1])}</th>`).join("")}</tr></thead><tbody>
    ${line("RF pit final", (r) => fmt(r.kpis.final_rf, 2))}${line("Rock Mt", (r) => mt(r.kpis.rock_t))}${line("Umpan Mt", (r) => mt(r.kpis.ore_t))}${line("SR", (r) => fmt(r.kpis.strip_ratio, 2))}
    ${line("Value jt", (r) => mUSD(r.kpis.value_undiscounted))}${line("NPV rencana jt", (r) => `<b>${mUSD(r.kpis.npv_plan)}</b>`)}${line("NPV best/worst jt", (r) => `${mUSD(r.kpis.npv_best)} / ${mUSD(r.kpis.npv_worst)}`)}
    ${line("Pushback", (r) => r.kpis.pushbacks)}${line("Periode", (r) => r.kpis.periods)}${line("Impas harga", (r) => (r.kpis.breakeven != null ? pcts(r.kpis.breakeven, 0) : "–"))}</tbody></table></div>` : `<div class="card" style="margin-top:16px"><div class="empty">Pilih minimal satu skenario dengan hasil.</div></div>`;
  return `<div class="page">${pageHead("Bandingkan", "skenario berdampingan; hanya yang sudah dijalankan")}<div class="card"><div class="row" style="flex-wrap:wrap;gap:14px">${picks || "Belum ada skenario dengan hasil."}</div></div>${table}</div>`;
}
A.cmpPick = (el) => { el.checked ? ui.pick.add(el.dataset.id) : ui.pick.delete(el.dataset.id); loadCompare([...ui.pick]).then(notify); };

/* ── Ekspor ── */
function ekspor(r) {
  const files = r.outputs;
  const size = (b) => (b > 1e6 ? fmt(b / 1e6, 1) + " MB" : fmt(b / 1e3, 0) + " kB");
  const rows = files.map((f) => `<tr><td class="l"><input type="checkbox" data-act="filePick" data-f="${esc(f.name)}" ${ui.files.has(f.name) ? "checked" : ""}></td><td class="l num">${esc(f.name)}</td><td class="l">${esc(f.kind)}</td><td>${size(f.bytes)}</td><td><a data-act="download" data-file="${esc(f.name)}">Unduh</a></td></tr>`).join("");
  return `<div class="page">${pageHead("Ekspor", "berkas hasil run", `<button class="btn" data-act="packageSel" ${ui.files.size ? "" : "disabled"}>Paket terpilih (${ui.files.size})</button><button class="btn primary" data-act="package">Paket lengkap (zip)</button>`)}
  <div class="card flat"><table class="t"><thead><tr><th></th><th class="l">Berkas</th><th class="l">Jenis</th><th>Ukuran</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
  <p class="xs muted">DXF: pit shell &amp; face position per pushback/periode · CSV: blok + shell + pushback + periode · Excel/PDF: laporan · HTML: viewer 3D mandiri.</p></div>`;
}
A.filePick = (el) => { el.checked ? ui.files.add(el.dataset.f) : ui.files.delete(el.dataset.f); notify(); };
A.packageSel = () => { location.href = `/api/package?${qs({ project: S.project, scenario: S.scenario, files: [...ui.files].join(",") })}`; };
