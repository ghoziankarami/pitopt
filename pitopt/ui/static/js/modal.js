import { esc } from "./util.js";
import { tx } from "./i18n.js";
export function modal(title, bodyHtml, buttons = "") {
  closeModal();
  const el = document.createElement("div");
  el.className = "modal"; el.id = "modal";
  el.innerHTML = tx(`<div class="box"><div class="row"><h2 style="font-size:16px">${esc(title)}</h2><span class="grow"></span><button class="btn sm" data-act="closeModal">Tutup</button></div>${bodyHtml}<div class="row" style="justify-content:flex-end">${buttons}</div></div>`);
  el.addEventListener("click", (e) => { if (e.target === el) closeModal(); });
  document.body.appendChild(el);
  return el;
}
export const closeModal = () => document.getElementById("modal")?.remove();
