// Starting a run: name the scenario when parameters changed, POST it, and
// hand over to the Jalankan screen which streams the log.
import { S, notify } from "./store.js";
import { api, esc, toast } from "./util.js";
import { t } from "./i18n.js";
import { A } from "./actions.js";
import { modal, closeModal } from "./modal.js";

export function startRun(overrides = {}, suggestion = "") {
  const changed = Object.keys(overrides).length > 0;
  if (!changed) {
    return modal("Jalankan optimasi", `<p class="small muted" style="margin:0">Skenario ini akan dijalankan ulang dengan parameter tersimpan. Hasil sebelumnya ditimpa. Bisa memakan beberapa menit untuk model besar.</p>`,
      `<button class="btn primary" data-act="confirmRun">Jalankan</button>`);
  }
  const list = Object.entries(overrides).map(([k, v]) => `<div class="row small"><span class="num grow">${esc(k)}</span><span class="num">${esc(JSON.stringify(v))}</span></div>`).join("");
  modal("Simpan sebagai skenario baru",
    `<p class="small muted" style="margin:0">Parameter yang diubah tidak menimpa skenario asli. Beri nama skenario baru; hasil lama tetap ada untuk dibandingkan.</p>
     <div class="card" style="padding:10px 14px">${list}</div>
     <div class="fld"><label>Nama skenario</label><input type="text" id="saveas" style="width:100%" value="${esc(suggestion)}"></div><div id="runerr" class="small bad"></div>`,
    `<button class="btn primary" data-act="confirmRun" data-changed="1">Simpan &amp; jalankan</button>`);
  S.pendingOverrides = overrides;
}

A.confirmRun = async (el) => {
  const overrides = el.dataset.changed ? S.pendingOverrides : {};
  const save_as = el.dataset.changed ? document.getElementById("saveas").value.trim() : null;
  if (el.dataset.changed && !save_as) { document.getElementById("runerr").textContent = t("Nama skenario wajib diisi."); return; }
  try {
    const res = await api("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: S.project, scenario: S.scenario, overrides, save_as }) });
    closeModal();
    S.job = { id: res.job, status: "running", scenario: res.scenario, log: [], stage: 0, stages: [], fraction: 0, next: 0, elapsed: 0 };
    S.runTarget = res.scenario;
    location.hash = "#/jalankan";
    notify();
    pollJob();
  } catch (e) {
    const box = document.getElementById("runerr");
    if (box) box.textContent = e.message; else toast(e.message);
  }
};
A.runCurrent = () => startRun({});

// Global poller: while a job is active, stream its log into S.job.
let polling = false;
export async function pollJob() {
  if (polling) return;
  polling = true;
  try {
    while (S.job && S.job.status === "running") {
      const snap = await api(`/api/job?id=${S.job.id}&since=${S.job.next || 0}`);
      const log = (S.job.log || []).concat(snap.log);
      S.job = { ...S.job, ...snap, log, scenario: S.job.scenario };
      notify();
      if (snap.status !== "running") break;
      await new Promise((r) => setTimeout(r, 700));
    }
    if (S.job && S.job.status === "done") {
      const { loadProjects2, select } = await import("./store.js");
      await loadProjects2();
      await select(S.project, S.runTarget || S.scenario);
      toast("Run selesai — hasil dimuat.");
    }
  } catch (e) { toast(e.message); }
  polling = false;
}
