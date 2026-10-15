// Detailed design (Desain Detail): the state every one of its screens shares, and the calls that fill it.
//
// One design is held per scenario. Parameter edits are a draft sent with each Generate; they never touch the
// scenario's file, and "Simpan sebagai skenario" writes them to a new one like any other PitOpt parameter change.
import { S, notify } from "../store.js";
import { api, toast } from "../util.js";

const fresh = () => ({
  state: null, block: null, topo: null, err: null, loading: true, draft: {}, job: null, live: [], result: null, notice: null,
  rl: null, plan: null, planBusy: false, section: null, line: null, layers: { shell: true, bench: true, ramp: true, sector: true, blocks: true },
  color: null, ve: 2, sel: 0, tab: "param", exported: null, supportPrompt: false, baseline: null,
});
export const D = { key: "", selectionVersion: -1, ...fresh() };
let generation = 0;
const tickets = {};
const context = (kind) => ({kind, generation, selection: S.selectionVersion, key: D.key, ticket: tickets[kind] = (tickets[kind] || 0) + 1});
const current = (owner) => owner.generation === generation && owner.selection === S.selectionVersion
  && owner.key === D.key && owner.ticket === tickets[owner.kind];

const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: S.project, scenario: S.scenario, ...body }) });
const get = (path, q = {}) => api(`${path}?${new URLSearchParams({ project: S.project, scenario: S.scenario, ...q })}`);

/** Called by every design screen's render: reset and load when the scenario changed. */
export function ensure() {
  const key = `${S.project}/${S.scenario}`;
  if (D.key === key && D.selectionVersion === S.selectionVersion) return;
  generation++; D.selectionVersion = S.selectionVersion;
  D.key = key;
  Object.assign(D, fresh());
  const owner = context("ensure");
  loadState().then(async () => {
    if (!current(owner)) return;
    if (!D.state?.has_results || !D.state.blocks_ready) return;
    await Promise.all([loadBlock(), loadPlan(null)]);
    if (current(owner) && D.state?.session) await loadResult();
  });
}

async function loadBlock() {
  const owner = context("block");
  try { const block = await get("/api/design/blocks"); if (!current(owner)) return; D.block = block; } catch (e) { if (!current(owner)) return; D.block = null; D.notice = e.message; }
  notify();
}

export async function loadState() {
  const owner = context("state");
  try { const state = await post("/api/design/state", { params: D.draft }); if (!current(owner)) return; D.state = state; D.err = null; }
  catch (e) { if (!current(owner)) return; D.state = null; D.err = e.message; }
  D.loading = false;
  if (D.state?.params && !changed()) D.baseline = structuredClone(D.state.params.detail);   // the scenario as its file has it
  notify();
}

export async function loadResult() {
  const owner = context("result");
  try {
    const result = await get("/api/design/result");
    if (!current(owner)) return;
    D.result = result;
    D.color = D.result.classes.configured ? (D.color || "kelas") : "kadar";
    await loadPlan();
  } catch (e) { if (!current(owner)) return; D.result = null; D.notice = e.message; }
  notify();
}

function maybePromptForSupport() {
  try {
    if (localStorage.getItem("pitopt-support-prompted")) return;
    D.supportPrompt = true;
    localStorage.setItem("pitopt-support-prompted", "1");
  } catch { /* storage may be disabled; show it for this session */
    D.supportPrompt = true;
  }
}

export async function loadPlan(rl = D.rl) {
  const owner = context("plan");
  D.planBusy = true;
  try {
    const plan = await get("/api/design/plan", rl === null ? {} : { rl });
    if (!current(owner)) return;
    D.plan = plan;
    D.rl = D.plan.rl;
    D.color ||= D.plan.classes.configured ? "kelas" : "kadar";     // classes come from the project's own configuration
  } catch (e) { if (!current(owner)) return; D.plan = null; D.notice = e.message; }
  D.planBusy = false;
  notify();
}

// ── parameters ──
export const base = () => D.state?.params?.detail;
export function value(path) {
  if (path in D.draft) return D.draft[path];
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), base());
}
export function setParam(path, val) {
  const original = path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), D.baseline);
  if (JSON.stringify(val) === JSON.stringify(original)) delete D.draft[path]; else D.draft[path] = val;
  loadState();
}
export function resetDraft() { D.draft = {}; return loadState(); }
export const changed = () => Object.keys(D.draft).length > 0;
/** Where a parameter came from: the project's own record, or "changed here" for an edit not yet saved. */
export function provenance(path) {
  if (path in D.draft) return { source: "asumsi", note: "diubah di layar ini, belum disimpan" };
  const p = D.state?.provenance || {};
  return p[`design.detail.${path}`] || p[`design.${path}`] || { source: "default" };
}
export const badge = (path) => {
  const { source, note, ref } = provenance(path);
  const known = ["dokumen", "asumsi", "default"].includes(source) ? source : "default";
  const label = { dokumen: "DOKUMEN", asumsi: "ASUMSI", default: "DEFAULT" }[known];
  const title = String(ref || note || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[c]);
  return `<span class="badge ${known}" title="${title}">${label}</span>`;
};

// ── generate / cancel ──
let polling = false;
export async function generate() {
  if (D.job?.status === "running") return;
  const owner = context("generate");
  D.live = []; D.notice = null;
  try {
    const { job } = await post("/api/design/run", { params: D.draft });
    if (!current(owner)) return;
    D.job = { id: job, status: "running", fraction: 0, next: 0, elapsed: 0, total: null, done: 0 };
    D.tab = "param";
    notify();
    poll();
  } catch (e) { if (!current(owner)) return; D.notice = e.message; D.job = null; notify(); }
}
export async function cancelGenerate() {
  if (D.job?.status !== "running") return;
  try { await post("/api/design/cancel", { id: D.job.id }); } catch (e) { toast(e.message); }
}
async function poll() {
  if (polling) return;
  polling = true;
  const owner = context("poll");
  try {
    while (D.job && D.job.status === "running") {
      const id = D.job.id;
      const snap = await get("/api/design/job", { id, since: D.job.next });
      if (!current(owner) || !D.job || D.job.id !== id) return;
      for (const e of snap.events) if (e.type === "bench_done") { D.live.push(e); D.job.total = e.total; D.job.done = e.done; }
      D.job = { ...D.job, status: snap.status, fraction: snap.fraction, next: snap.next, elapsed: snap.elapsed, error: snap.error };
      notify();
      if (snap.status !== "running") break;
      await new Promise((r) => setTimeout(r, 200));
    }
    if (!current(owner)) return;
    const status = D.job?.status;
    if (status === "done") { maybePromptForSupport(); await loadResult(); await loadState(); toast("Desain selesai."); }
    else if (status === "cancelled") toast("Generate dibatalkan — desain sebelumnya tetap ditampilkan.");
    else if (status === "error") D.notice = D.job.error;
    D.live = [];
  } catch (e) { if (current(owner)) D.notice = e.message; }
  finally { polling = false; if (!current(owner) && D.job?.status === "running") poll(); }
  if (current(owner)) notify();
}
export const running = () => D.job?.status === "running";
/** The benches to draw: the ones streamed in while computing, else the finished design. */
export const benches = () => (running() ? D.live : D.result?.benches || []);

export async function exportFiles(kinds) {
  const owner = context("export");
  try {
    const response = await post("/api/design/export", { kinds });
    if (!current(owner)) return;
    D.exported = response.files;
    toast(`${D.exported.length} file ditulis ke folder hasil.`);
  }
  catch (e) { if (!current(owner)) return; D.notice = e.message; }
  notify();
}
export async function loadSection(p1, p2) {
  const owner = context("section");
  D.line = { p1, p2 };
  try {
    const q = { x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1] };
    const [section, topo] = await Promise.all([get("/api/design/section", q), get("/api/section", { ...q, layers: "" }).catch(() => null)]);
    if (!current(owner)) return;
    D.section = section; D.topo = topo; D.notice = null;
  }
  catch (e) { if (!current(owner)) return; D.section = null; D.notice = e.message; }
  notify();
}

// ── shared bits ──
export const STATUS = { OK: ["ok", "OK"], PERINGATAN: ["peringatan", "PERINGATAN"], BLOKIR: ["blokir", "BLOKIR"] };
export const pill = (status) => `<span class="tagc ${(STATUS[status] || STATUS.OK)[0]}">${(STATUS[status] || STATUS.OK)[1]}</span>`;
export const worst = (list) => list.reduce((w, s) => (["OK", "PERINGATAN", "BLOKIR"].indexOf(s) > ["OK", "PERINGATAN", "BLOKIR"].indexOf(w) ? s : w), "OK");
