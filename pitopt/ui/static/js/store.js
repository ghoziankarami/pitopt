// Application state: the projects, the selected scenario, its results and
// the parameter edits not yet run. Views read S and call the actions.
import { api, qs, clone } from "./util.js";

export const S = {
  projects: [], project: null, scenario: null,
  results: null, raw: null, cfg: null, error: null, loading: false,
  view: "ringkasan", draft: {}, ve: +localStorage.getItem("pitopt-ve") || 5, theme: localStorage.getItem("pitopt-theme") || "light",
  job: null, compare: {}, pendingFinal: null,
};
const listeners = new Set();
export const subscribe = (fn) => listeners.add(fn);
export const notify = () => listeners.forEach((fn) => fn());

export async function loadProjects() {
  const [projects, meta] = await Promise.all([
    api("/api/projects"), api("/api/meta").catch(() => ({})),
  ]);
  S.projects = projects;
  if (!S.project && S.projects.length) {
    const saved = localStorage.getItem("pitopt-scenario-v2");
    const [p, s] = saved ? saved.split("/") : [];
    const preferred = meta.demo && S.projects.find((x) => x.id === meta.default_project && x.scenarios.some((sc) => sc.has_results));
    const proj = preferred || S.projects.find((x) => x.id === p) || S.projects.find((x) => x.scenarios.some((s2) => s2.has_results)) || S.projects[0];
    const sc = (!preferred && proj.scenarios.find((x) => x.id === s)) || proj.scenarios.find((x) => x.has_results) || proj.scenarios[0];
    await select(proj.id, sc.id);
  }
  notify();
}

export async function select(project, scenario) {
  S.project = project; S.scenario = scenario; S.loading = true; S.error = null; S.draft = {}; S.pendingFinal = null;
  localStorage.setItem("pitopt-scenario-v2", `${project}/${scenario}`);
  notify();
  try { S.cfg = await api(`/api/config?${qs({ project, scenario })}`); S.raw = S.cfg.raw; } catch (e) { S.cfg = null; S.raw = null; S.cfgError = e.message; }
  try { S.results = await api(`/api/results?${qs({ project, scenario })}`); }
  catch (e) { S.results = null; S.error = e.message; }
  S.loading = false;
  notify();
}

export async function refreshCurrent() { await loadProjects2(); await select(S.project, S.scenario); }
export async function loadProjects2() { S.projects = await api("/api/projects"); }

export async function loadCompare(ids) {
  for (const id of ids) {
    if (S.compare[id]) continue;
    const [p, s] = id.split("/");
    try { S.compare[id] = await api(`/api/results?${qs({ project: p, scenario: s })}`); } catch { S.compare[id] = null; }
  }
}
export function setTheme(t) {
  S.theme = t; document.documentElement.dataset.theme = t === "dark" ? "dark" : "";
  localStorage.setItem("pitopt-theme", t); notify();
}
export const scenarioMeta = () => {
  const p = S.projects.find((x) => x.id === S.project);
  return { project: p, scenario: p?.scenarios.find((x) => x.id === S.scenario) };
};
export const isChanged = () => Object.keys(S.draft).length > 0;
export function setDraft(path, value, original) {
  if (JSON.stringify(value) === JSON.stringify(original)) delete S.draft[path]; else S.draft[path] = value;
}
