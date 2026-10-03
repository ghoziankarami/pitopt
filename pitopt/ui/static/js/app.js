import { S, subscribe, loadProjects, select, notify, setTheme, scenarioMeta } from "./store.js";
import { esc, fmt, fmtInt, api, qs, toast, tr, $ } from "./util.js";
import { A } from "./actions.js";
import { lang, setLang, loadDictionary, tx, t, locale, seen, missing } from "./i18n.js";
import "./manage.js";
import { modal, closeModal } from "./modal.js";
import * as summary from "./views/summary.js";
import * as pitbypit from "./views/pitbypit.js";
import * as plan from "./views/plan.js";
import * as view3d from "./views/view3d.js";
import * as params from "./views/params.js";
import { pollJob } from "./run.js";
import * as upload from "./views/upload.js";
import * as blocks from "./views/blocks.js";
import * as misc from "./views/misc.js";
import * as dSumber from "./views/design_sumber.js";
import * as dSektor from "./views/design_sektor.js";
import * as dRamp from "./views/design_ramp.js";
import * as dGenerate from "./views/design_generate.js";
import * as dValidasi from "./views/design_validasi.js";
import * as dPenampang from "./views/design_penampang.js";
import * as dEkspor from "./views/design_ekspor.js";
import { D } from "./design/core.js";

const VIEWS = {
  ringkasan: summary, "pit-by-pit": pitbypit, "pit-final": pitbypit, pushback: plan, rencana: plan, desain: plan,
  "d-sumber": dSumber, "d-sektor": dSektor, "d-ramp": dRamp, "d-generate": dGenerate, "d-validasi": dValidasi,
  "d-penampang": dPenampang, "d-ekspor": dEkspor,
  unggah: upload, blok: blocks, sensitivitas: misc, "3d": view3d, parameter: params, data: misc, qa: misc, jalankan: misc, bandingkan: misc, ekspor: misc,
};
const $app = document.getElementById("app");
let mounted = null;

A.closeModal = closeModal;
A.go = (el) => { location.hash = `#/${el.dataset.go}`; };
function renderDemoBanner() {
  const banner = $("#demo-banner");
  if (!banner || !document.body.classList.contains("demo")) return;
  banner.innerHTML = `<span>${t("Demo sintetis · prototipe riset, bukan desain siap tambang. NPV memakai shell dan asumsi model.")}</span><a href="#/unggah">${t("Jalankan dengan data Anda →")}</a><a href="${esc(S.demoRepoUrl)}" target="_blank" rel="noopener noreferrer">★ ${t("Star di GitHub")}</a>`;
}
A.lang = (el) => { setLang(el.dataset.v); renderDemoBanner(); closeModal(); notify(); };
A.theme = () => setTheme(S.theme === "dark" ? "light" : "dark");
A.showLog = async () => {
  const { log } = await api(`/api/runlog?${qs({ project: S.project, scenario: S.scenario })}`);
  modal("Log run", `<pre class="log">${esc(log.join("\n") || t("Belum ada log untuk skenario ini."))}</pre>`);
};
A.package = () => { location.href = `/api/package?${qs({ project: S.project, scenario: S.scenario })}`; };
A.download = (el) => { location.href = `/api/download?${qs({ project: S.project, scenario: S.scenario, file: el.dataset.file })}`; };

function route() {
  const name = (location.hash.replace(/^#\/?/, "") || "ringkasan").split("?")[0];
  S.view = VIEWS[name] ? name : "ringkasan";
  render();
}

const NAV = [
  ["data", "01", "Data"], ["qa", "02", "QA Data"], ["parameter", "03", "Parameter"], ["jalankan", "04", "Jalankan"],
];

function pillFor(id, r) {
  if (!r) return `<span class="pill mute">belum</span>`;
  if (id === "data") return `<span class="pill ok">OK</span>`;
  if (id === "qa") {
    const n = r.qa.checks.filter((c) => c.status === "peringatan" || c.status === "blokir").length;
    return n ? `<span class="pill warn">${n} ⚠</span>` : `<span class="pill ok">OK</span>`;
  }
  if (id === "parameter") return r.assumptions.length ? `<span class="pill warn">${r.assumptions.length} asumsi</span>` : "";
  if (id === "jalankan") return S.job && S.job.status === "running" ? `<span class="pill run">berjalan</span>` : `<span class="num xs muted">${r.meta.duration_s ? fmt(r.meta.duration_s, 0) + " s" : ""}</span>`;
  return "";
}

// Detailed design (06): the steps, in order, with what each shows in the sidebar.
const DESIGN = [["d-sumber", "Sumber shell"], ["d-sektor", "Crest & Sektor"], ["d-ramp", "Ramp"], ["d-generate", "Generate & Tinjau"], ["d-validasi", "Validasi"], ["d-penampang", "Penampang 1:1"], ["d-ekspor", "Ekspor"]];
const RAIL = new Set(["d-sektor", "d-ramp", "d-generate"]);        // the working screens give their room to the drawing
function designPill(id) {
  const st = D.state;
  if (!st?.has_results) return "";
  const checks = D.result?.document?.provenance?.validation || st.session?.status || {};
  const n = D.result ? D.result.document.findings.filter((f) => f.status !== "OK").length : 0;
  if (id === "d-sumber") return `<span class="pill ok">OK</span>`;
  if (id === "d-sektor") return `<span class="pill mute">${(st.sectors || []).length} sektor</span>`;
  if (id === "d-ramp") return st.ramp ? `<span class="pill mute">${esc(st.params.detail.ramp.pattern === "spiral" ? "spiral" : "switchback")}</span>` : `<span class="pill warn">isi</span>`;
  if (id === "d-generate") return D.job?.status === "running" ? `<span class="pill run">berjalan</span>` : D.result ? `<span class="num xs muted">${D.result.benches.length} bench</span>` : `<span class="pill mute">belum</span>`;
  if (id === "d-validasi") return D.result ? (n ? `<span class="pill warn">${n} ⚠</span>` : `<span class="pill ok">OK</span>`) : "";
  void checks;
  return "";
}

function shell() {
  const { project } = scenarioMeta();
  const r = S.results, meta = r?.meta;
  const v = r?.verification;
  const clean = v && v.walls === 0 && v.cone === 0 && v.schedule === 0;
  const when = meta?.run_at ? new Date(meta.run_at).toLocaleString(locale(), { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
  const sub = (id, label) => `<a data-go="${id}" class="${S.view === id ? "active" : ""}">${label}</a>`;
  const nav = (id, no, label, extra = "") => `<a class="nav ${S.view === id ? "active" : ""}" data-go="${id}"><span class="no num">${no}</span><span class="grow">${label}</span>${extra}</a>`;
  const inDesign = S.view.startsWith("d-");
  const inResult = ["ringkasan", "pit-by-pit", "pit-final", "pushback", "rencana", "desain", "blok", "sensitivitas"].includes(S.view);
  const compareCount = project ? project.scenarios.filter((s) => s.has_results).length : 0;
  return `
<header class="top">
  <div class="brand"><svg width="22" height="22" viewBox="0 0 22 22"><path d="M2 5H20L16.5 10H13L10.5 15H7L5.5 19H2Z" fill="#C9A97A" stroke="#8A6A3B" stroke-width="1.2" stroke-linejoin="round"/></svg>PitOpt<span class="tag num">engine ${esc(meta?.engine_version || "0.4")}</span></div>
  <div class="vsep"></div>
  <div class="field"><label for="proyek">Proyek</label><select id="proyek" data-on="project">${S.projects.map((p) => `<option value="${esc(p.id)}" ${p.id === S.project ? "selected" : ""}>${esc(p.title)}</option>`).join("")}</select></div>
  <div class="field"><label for="skenario">Skenario</label><select id="skenario" data-on="scenario">${(project?.scenarios || []).map((s) => `<option value="${esc(s.id)}" ${s.id === S.scenario ? "selected" : ""}>${esc(s.label)}${s.has_results ? "" : " · belum dijalankan"}</option>`).join("")}</select></div>
  <div class="grow"></div>
  ${meta ? `<div class="runinfo num">Run <span>${esc(when)}</span> · ${meta.shells} shell · ${fmt(meta.duration_s, 0)} s<br><span class="${clean ? "good" : "bad"}">verifikasi ${v.walls}/${v.cone}/${v.schedule} pelanggaran</span></div>` : ""}
  <button class="btn" data-act="manage" title="Proyek baru, ganti nama, hapus">Kelola</button>
  <div class="tabs lang" role="group" aria-label="Language"><button data-act="lang" data-v="id" class="${lang === "id" ? "on" : ""}" title="Bahasa Indonesia">ID</button><button data-act="lang" data-v="en" class="${lang === "en" ? "on" : ""}" title="English">EN</button></div>
  <button class="btn" data-act="theme" title="Mode gelap / terang">${S.theme === "dark" ? "☀" : "☾"}</button>
  ${S.demoMode ? `<button class="btn primary" data-go="unggah">Pakai data Anda →</button>` : `<button class="btn primary" data-act="package" ${r ? "" : "disabled"}>Ekspor .zip</button>`}
</header>
<div class="shell">
  <nav class="side ${RAIL.has(S.view) ? "rail" : ""}" aria-label="Alur kerja">
    <div class="navh">ALUR KERJA</div>
    ${NAV.map(([id, no, label]) => nav(id, no, label, pillFor(id, r))).join("")}
    <a class="nav parent ${inResult ? "active" : ""}" data-go="ringkasan"><span class="no num">05</span><span class="grow">Hasil</span></a>
    <div class="subnav">
      ${sub("ringkasan", "Ringkasan")}${sub("pit-by-pit", "Pit by Pit")}${sub("pit-final", "Pit Final")}${sub("pushback", "Pushback")}${sub("rencana", "Rencana Periode")}${sub("desain", "Desain")}${sub("blok", "Model Blok")}${sub("sensitivitas", "Sensitivitas")}
    </div>
    <a class="nav parent ${inDesign ? "active" : ""}" data-go="d-sumber"><span class="no num">06</span><span class="grow">Desain Detail</span></a>
    <div class="subnav">${DESIGN.map(([id, label]) => `<a data-go="${id}" class="${S.view === id ? "active" : ""}"><span>${label}</span>${designPill(id)}</a>`).join("")}</div>
    ${nav("3d", "07", "3D &amp; Penampang", `<span class="num xs muted">VE ${fmt(S.ve, 0)}×</span>`)}
    ${nav("bandingkan", "08", "Bandingkan", `<span class="num xs muted">${compareCount}</span>`)}
    ${nav("ekspor", "09", "Ekspor")}
    ${r ? `<div class="side-foot"><div class="navh" style="padding:0">PIT FINAL AKTIF</div><div class="num" style="font-size:13px;font-weight:600">RF ${fmt(r.final_pit.rf, 2)} · shell ${r.final_pit.shell}</div><div class="xs muted" style="line-height:1.45">${esc(tr(r.final_pit.reason).replace(/ \(puncak.*$/, ""))}</div></div>` : ""}
  </nav>
  <main id="main"></main>
</div>`;
}

function render() {
  const main = $("#main");
  const scroll = main ? main.scrollTop : 0;
  const same = mounted === S.view;
  if (mounted && VIEWS[mounted]?.unmount) VIEWS[mounted].unmount(S.view);
  $app.innerHTML = tx(shell());
  const mainEl = $("#main");
  const view = VIEWS[S.view];
  if (S.loading) mainEl.innerHTML = tx(`<div class="loading">Memuat…</div>`);
  else mainEl.innerHTML = tx(view.render(S.view));
  mounted = S.view;
  if (view.mount && !S.loading) view.mount(mainEl, S.view);
  if (same) mainEl.scrollTop = scroll;
}

$app.addEventListener("click", (e) => {
  const go = e.target.closest("[data-go]");
  if (go && !e.target.closest("[data-act]")) { e.preventDefault(); location.hash = `#/${go.dataset.go}`; return; }
  const el = e.target.closest("[data-act]");
  if (el && A[el.dataset.act]) A[el.dataset.act](el, e);
});
document.addEventListener("click", (e) => {
  const el = e.target.closest("#modal [data-act]");
  if (el && A[el.dataset.act]) A[el.dataset.act](el, e);
});
$app.addEventListener("change", async (e) => {
  const on = e.target.dataset.on;
  if (on === "project") {
    const p = S.projects.find((x) => x.id === e.target.value);
    const sc = p.scenarios.find((x) => x.has_results) || p.scenarios[0];
    await select(p.id, sc.id);
  } else if (on === "scenario") await select(S.project, e.target.value);
  else if (on && A[on]) A[on](e.target, e);
});
$app.addEventListener("input", (e) => { const on = e.target.dataset.input; if (on && A[on]) A[on](e.target, e); });

subscribe(render);
window.addEventListener("hashchange", route);
document.documentElement.dataset.theme = S.theme === "dark" ? "dark" : "";
window.__pitopt = { S, A, i18n: { seen, missing } };
// Load demo mode before the first render so a new hosted-demo visitor sees English immediately.
loadDictionary().then(async () => {
  const meta = await api("/api/meta").catch(() => ({}));
  if (meta.demo) {
    document.body.classList.add("demo");
    if (!localStorage.getItem("pitopt-lang")) setLang("en");
  }
  setLang(lang);
  renderDemoBanner();
  await loadProjects();
  const job = await api("/api/current-job").catch(() => null);
  if (job?.status === "running") { S.job = { ...job, scenario: S.scenario }; pollJob(); }
  route();
}).catch((e) => { $app.innerHTML = `<div class="loading">Gagal memuat proyek: ${esc(e.message)}</div>`; });
