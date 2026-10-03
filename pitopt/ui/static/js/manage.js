// Project management: rename project / scenario, delete scenario / project (with a look at what goes first).
import { S, notify, loadProjects2, select, scenarioMeta } from "./store.js";
import { A } from "./actions.js";
import { modal, closeModal } from "./modal.js";
import { fmt, esc, api, qs, toast } from "./util.js";
import { t } from "./i18n.js";

const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const mb = (b) => (b >= 1e9 ? `${fmt(b / 1e9, 2)} GB` : b >= 1e6 ? `${fmt(b / 1e6, 1)} MB` : `${fmt(b / 1e3, 0)} kB`);

A.manage = () => {
  if (S.demoMode) { location.hash = "#/unggah"; return; }      // the public demo cannot create, rename or delete
  const { project, scenario } = scenarioMeta();
  if (!project) return A.newProject();
  modal("Kelola proyek", `
    <button class="btn primary" data-act="newProject" style="width:100%;margin-bottom:16px">+ Proyek baru dari data Anda</button>
    <div class="fld"><label>Nama proyek</label><div class="row" style="gap:8px"><input type="text" id="mg-title" style="flex:1" value="${esc(project.title)}"><button class="btn" data-act="mgRename" data-kind="project">Simpan</button></div>
      <div class="hint">Folder <span class="num">projects/${esc(project.id)}</span> tidak berubah; hanya nama tampilan.</div></div>
    <div class="fld" style="margin-top:14px"><label>Nama skenario ini</label><div class="row" style="gap:8px"><input type="text" id="mg-scen" style="flex:1" value="${esc(scenario?.label || "")}"><button class="btn" data-act="mgRename" data-kind="scenario">Simpan</button></div></div>
    <div class="card" style="margin-top:20px;border-color:var(--bad);background:var(--bad-bg)"><b class="bad">Hapus</b>
      <p class="small muted" style="margin:6px 0 10px">Penghapusan permanen dan tidak bisa dibatalkan. Anda akan melihat daftar berkas sebelum mengonfirmasi.</p>
      <div class="row" style="gap:8px"><button class="btn" data-act="mgDelete" data-kind="scenario" ${project.scenarios.length < 2 ? "disabled title='Satu-satunya skenario; hapus proyeknya'" : ""}>Hapus skenario ini…</button><button class="btn" data-act="mgDelete" data-kind="project">Hapus proyek…</button></div></div>`, "");
};

A.mgRename = async (el) => {
  const kind = el.dataset.kind, name = document.getElementById(kind === "project" ? "mg-title" : "mg-scen").value.trim();
  try {
    await post("/api/rename", { project: S.project, scenario: kind === "scenario" ? S.scenario : null, name });
    await loadProjects2(); closeModal(); notify(); toast("Nama disimpan.");
  } catch (e) { toast(e.message); }
};

A.mgDelete = async (el) => {
  const kind = el.dataset.kind, { project, scenario } = scenarioMeta();
  const target = kind === "scenario" ? S.scenario : S.project;
  let pre;
  try { pre = await api(`/api/delete-preview?${qs({ project: S.project, scenario: kind === "scenario" ? S.scenario : "" })}`); } catch (e) { return toast(e.message); }
  modal(kind === "scenario" ? `Hapus skenario "${scenario?.label}"` : `Hapus proyek "${project.title}"`, `
    <p class="small" style="margin:0 0 10px">Yang akan dihapus dari disk (${mb(pre.bytes)}):</p>
    <div class="card" style="padding:8px 12px">${pre.items.map((i) => `<div class="row small"><span class="num grow">${esc(i.path)}</span><span class="num muted">${mb(i.bytes)}</span></div>`).join("")}</div>
    ${pre.has_raw_data ? `<div class="banner bad small" style="margin-top:10px"><b>Termasuk folder <span class="num">raw/</span> (data mentah).</b> Pastikan Anda punya salinan aslinya.</div>` : ""}
    <div class="fld" style="margin-top:14px"><label>Ketik <span class="num">${esc(target)}</span> untuk mengonfirmasi</label><input type="text" id="mg-confirm" data-input="mgConfirm" data-want="${esc(target)}" style="width:100%" autocomplete="off"></div>`,
    `<button class="btn" data-act="closeModal">Batal</button><button class="btn danger" id="mg-go" data-act="mgDoDelete" data-kind="${kind}" disabled>Hapus permanen</button>`);
};
A.mgConfirm = (el) => { const b = document.getElementById("mg-go"); if (b) b.disabled = el.value !== el.dataset.want; };
document.addEventListener("input", (e) => { if (e.target.dataset?.input === "mgConfirm") A.mgConfirm(e.target); });

A.mgDoDelete = async (el) => {
  const kind = el.dataset.kind, confirm = document.getElementById("mg-confirm").value;
  try {
    await post("/api/delete", { project: S.project, scenario: kind === "scenario" ? S.scenario : null, confirm });
    await loadProjects2();
    closeModal();
    let p = S.projects.find((x) => x.id === S.project);
    if (kind === "project" || !p) p = S.projects.find((x) => x.scenarios.some((s) => s.has_results)) || S.projects[0];
    if (p) { const sc = p.scenarios.find((s) => s.has_results) || p.scenarios[0]; await select(p.id, sc.id); } else { S.project = null; S.results = null; S.cfg = null; notify(); }
    toast("Terhapus.");
  } catch (e) { toast(e.message); }
};
