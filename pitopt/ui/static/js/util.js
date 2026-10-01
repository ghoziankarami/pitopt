// Formatting, colours and tiny helpers shared by every screen.
import { locale, lang, t as tt } from "./i18n.js";
const nf = (d) => new Intl.NumberFormat(locale(), { minimumFractionDigits: d, maximumFractionDigits: d });
const cache = {};
export function fmt(v, d = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return (cache[locale() + d] ||= nf(d)).format(v);
}
export const fmtInt = (v) => fmt(v, 0);
export const mUSD = (v, d = 2) => (v === null || v === undefined ? "–" : fmt(v / 1e6, d));
export const mt = (v, d = 2) => (v === null || v === undefined ? "–" : fmt(v / 1e6, d));
export const pct = (v, d = 1) => (v === null || v === undefined ? "–" : fmt(v * 100, d));
export const pcts = (v, d = 1) => (v === null || v === undefined ? "–" : fmt(v * 100, d) + "%");
export const signed = (v, d = 1) => (v === null || v === undefined ? "–" : (v > 0 ? "+" : v < 0 ? "−" : "") + fmt(Math.abs(v), d));
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { "X-PitOpt": "1", ...(opts.headers || {}) } });
  const type = res.headers.get("Content-Type") || "";
  const body = type.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error(tt((body && body.error) || res.statusText));
  return body;
}
export const qs = (o) => new URLSearchParams(o).toString();

// viridis, sampled — the sequential palette for pushbacks and periods
const V = ["#440154", "#482878", "#3E4A89", "#31688E", "#26828E", "#1F9E89", "#35B779", "#6DCD59", "#B4DE2C", "#FDE725"];
export function viridis(t) {
  const x = Math.min(1, Math.max(0, t)) * (V.length - 1);
  const i = Math.floor(x), f = x - i;
  if (i >= V.length - 1) return V[V.length - 1];
  const a = hex(V[i]), b = hex(V[i + 1]);
  return `rgb(${[0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * f)).join(",")})`;
}
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
export const stageColor = (n, total) => viridis(total <= 1 ? 0.5 : (n - 1) / (total - 1));

export function niceMax(v) {
  if (v <= 0) return 1;
  const e = Math.pow(10, Math.floor(Math.log10(v)));
  const m = v / e;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * e;
}
export function toast(msg, ms = 3500) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = tt(msg);
  document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}
export const clone = (o) => JSON.parse(JSON.stringify(o));
export function getPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : Array.isArray(o) ? o.find((p) => p.name === k) : o[k]), obj);
}

// Engine strings are English; the UI is Indonesian. Only the few phrases the
// engine emits into the results are translated here.
export function tr(t) {
  if (lang === "en") return String(t ?? "");          // the engine already speaks English
  return String(t ?? "")
    .replace(/auto: target ([\d.]+) y, lengthened to ([\d.]+) y so a (\d+) m pit sinks at <= (\d+) m\/y/, (m, a, b, c, d) => `otomatis: target ${a.replace(".", ",")} th, diperpanjang ke ${b.replace(".", ",")} th agar pit ${c} m turun ≤ ${d} m/th`)
    .replace(/auto: target ([\d.]+) y/, (m, a) => `otomatis: target ${a.replace(".", ",")} th`)
    .replace(/manual duration ([\d.]+) y/, (m, a) => `durasi manual ${a.replace(".", ",")} th`)
    .replace(/mine life (\d+) y/, "umur tambang $1 th")
    .replace(/set manually/, "diatur manual")
    .replace("smallest shell within", "shell terkecil dalam")
    .replace(/of the maximum (\w+)-case NPV/, (m, k) => `dari NPV ${{ average: "rata-rata", best: "best case", worst: "worst case" }[k] || k} maksimum`)
    .replace(/\(peak at RF ([\d.]+)\)/, (m, x) => `(puncak di RF ${x.replace(".", ",")})`)
    .replace(/maximum (\w+)-case NPV/, (m, k) => `NPV ${{ average: "rata-rata", best: "best case", worst: "worst case" }[k] || k} maksimum`)
    .replace(/^(\d+) pushbacks of (\d+) strips x ([\d.]+) m, advancing (.+)$/, (m, n, k, w, d) => `${n} pushback dari ${k} strip × ${w.replace(".0", "")} m, maju ${{ "south to north": "selatan → utara", "north to south": "utara → selatan", "west to east": "barat → timur", "east to west": "timur → barat" }[d] || d}`)
    .replace(/^(\d+) pushbacks, specified case with (\d+) bench lag$/, "$1 pushback, specified case, lag $2 bench");
}
