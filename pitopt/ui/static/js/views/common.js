import { S } from "../store.js";
import { esc, fmt } from "../util.js";

export const kpi = (label, value, unit, sub, cls = "", color = "") =>
  `<div class="kpi ${cls}"><div class="k">${esc(label)}</div><div class="v ${color}">${value}${unit ? `<span class="u">${unit}</span>` : ""}</div><div class="s">${sub || ""}</div></div>`;

export const pageHead = (title, sub, actions = "") =>
  `<div class="pagehead"><div class="grow"><h1>${title}</h1><div class="sub">${sub || ""}</div></div><div class="row">${actions}</div></div>`;

export function empty(title) {
  const sc = S.projects.find((p) => p.id === S.project)?.scenarios.find((s) => s.id === S.scenario);
  return `<div class="page">${pageHead(title, "")}<div class="card"><div class="empty" style="padding:48px">
    <div style="font-size:15px;font-weight:600;color:var(--text);margin-bottom:6px">Belum ada hasil untuk skenario “${esc(sc?.label || S.scenario)}”</div>
    <div style="margin-bottom:16px">${S.error ? esc(S.error) : "Jalankan optimasi untuk menghitung shell, pit final, pushback, dan jadwal."}</div>
    <button class="btn primary" data-act="runCurrent">Jalankan optimasi</button></div></div></div>`;
}

const LINKS = { plan: "pushback", "pit-by-pit": "pit-by-pit", sensitivitas: "sensitivitas", parameter: "parameter", pushback: "pushback" };
const LINK_TEXT = { plan: "Lihat di plan view →", "pit-by-pit": "Buka Pit by Pit →", sensitivitas: "Buka Sensitivitas →", parameter: "Buka Parameter →", pushback: "Buka Pushback →" };

export function banners(r) {
  const w = r.warnings;
  if (!w.length) return `<div class="banners" style="border-color:var(--good-line);background:var(--good-bg)"><div class="bh"><span class="tagc ok">OK</span><span>Tidak ada peringatan aktif pada hasil ini.</span></div></div>`;
  const hard = w.some((x) => x.level === "blokir");
  const n = w.length;
  const rows = w.map((x) => `<div class="brow"><span class="tagc ${x.level}">${esc(x.tag)}</span><span class="txt">${esc(x.text)}</span><a data-go="${LINKS[x.link] || "ringkasan"}">${LINK_TEXT[x.link] || "Buka →"}</a></div>`).join("");
  return `<div class="banners ${hard ? "bad" : ""}"><div class="bh"><span style="font-size:18px">⚠</span><b>${n} peringatan aktif pada hasil ini</b><span class="muted small">— tinjau sebelum angka dipakai di laporan</span><span class="grow"></span><span class="chip">ikut tercetak di laporan PDF</span></div>${rows}</div>`;
}

export const productsOf = (r) => Object.entries(r.kpis.products);
export const yearOf = (r) => (r.meta.run_at ? new Date(r.meta.run_at).getFullYear() + 1 : null);
