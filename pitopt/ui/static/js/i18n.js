// Interface language. The screens are written in Indonesian; English is a dictionary
// applied to the HTML (and short strings) just before it reaches the DOM, so every
// screen, chart label, dialog and toast switches together and numbers, dates and
// decimal marks follow the language too.
//
// Keys are Indonesian text with every number replaced by {#}; the English value
// carries the same {#} in the same order. Text with no entry stays as written and is
// listed in `missing` (see window.__pitopt.i18n) so gaps are found, not guessed.
export let lang = localStorage.getItem("pitopt-lang") === "en" ? "en" : "id";
export const locale = () => (lang === "en" ? "en-US" : "id-ID");
export const seen = new Set();
export const missing = new Set();
let dict = {};

export async function loadDictionary() {
  try { dict = await (await fetch("/static/i18n/en.json", { cache: "no-cache" })).json(); } catch { dict = {}; }
}
export function setLang(l) {
  lang = l === "en" ? "en" : "id";
  localStorage.setItem("pitopt-lang", lang);
  document.documentElement.lang = lang;
  document.title = "PitOpt";
}

const NUM = /\d+(?:[.,]\d+)*/g;
const LETTERS = /[A-Za-zÀ-ÿ]{2}/;

function translateCore(core, report) {
  const key = core.replace(/\s+/g, " ").replace(NUM, "{#}");
  if (report) seen.add(key);
  if (lang !== "en") return core;
  const nums = core.match(NUM) || [];
  let hit = dict[key];
  if (hit === undefined && / ·$|^· /.test(key)) {                        // dangling separator before/after an inline tag
    const inner = key.replace(/ ·$/, "").replace(/^· /, "");
    const en = dict[inner];
    if (en !== undefined) {
      let i = 0;
      const body = en.replace(/\{#\}/g, () => nums[i++] ?? "");
      return /^· /.test(key) ? `· ${body}` : `${body} ·`;
    }
  }
  if (hit === undefined && key.includes(" · ")) {                      // "label · status" fragments
    const parts = key.split(" · ");
    const done = parts.map((p) => dict[p]);
    if (done.some((d) => d !== undefined)) {
      let n = 0;
      return parts.map((p, i) => {
        const cnt = (p.match(/\{#\}/g) || []).length;
        const mine = nums.slice(n, n + cnt); n += cnt;
        const v = done[i] ?? p;
        let k = 0;
        return v.replace(/\{#\}/g, () => mine[k++]);
      }).join(" · ");
    }
  }
  if (hit === undefined) {
    for (const [re, out] of patterns) { const m = core.match(re); if (m) return out(...m.slice(1)); }
    if (report && /\s/.test(core)) missing.add(key);          // single tokens are names, units or identifiers
    return core;
  }
  let i = 0;
  return hit.replace(/\{#\}/g, () => nums[i++] ?? "");
}

// messages whose dynamic part is a name or a column, not a number
const patterns = [
  [/^ukuran blok target \(dx, dy, dz\) harus (?:>|&gt;) 0$/, () => "target block size (dx, dy, dz) must be > 0"],
  [/^isi ukuran parent block \(dx, dy, dz\) atau pilih kolom ukuran blok$/, () => "fill in the parent block size (dx, dy, dz) or choose the block size columns"],
  [/^kolom (\w+) wajib dipilih$/, (n) => `column ${n} is required`],
  [/^kolom tidak ada di berkas: (.+)$/, (n) => `column not in the file: ${n}`],
  [/^reblock hanya untuk model blok CSV$/, () => "reblock only works on a CSV block model"],
  [/^Mengunggah (.+) — (\d+)%$/, (n, p) => `Uploading ${n} — ${p}%`],
  [/^folder: (.+)$/, (n) => `folder: ${n}`],
  [/^Rekomendasi engine: (.+)$/, (n) => `Engine recommendation: ${n}`],
  // text the engine already wrote in English (results.json), possibly with a dangling separator
  [/^((?:smallest shell within .+|maximum (?:average|best|worst)-case NPV|\d+ \(auto: .+\)|\d+ pushbacks.+|no results.+|slope\.overall_angle_deg.+))$/, (n) => n],
  [/^Margin (.+)$/, (n) => `Margin ${n}`],
  [/^(\w{3} \d{1,2}, \d{4}, \d{1,2}:\d{2}(?::\d{2})?\s?(?:AM|PM)?)$/, (n) => n],       // run date in the header: a value, not text
  [/^Jalankan (.+)$/, (n) => `Run ${n}`],
  [/^Hapus skenario (?:&quot;|")(.+)(?:&quot;|")$/, (n) => `Delete scenario "${n}"`],
  [/^Hapus proyek (?:&quot;|")(.+)(?:&quot;|")$/, (n) => `Delete project "${n}"`],
  [/^Kadar (.+)$/, (n) => `Grade ${n}`],
  [/^Belum ada hasil untuk skenario “(.+)”$/, (n) => `No results yet for scenario “${n}”`],
  [/^tidak ditemukan: (.+)$/, (n) => `not found: ${n}`],
  [/^permintaan tidak valid: (.+)$/, (n) => `invalid request: ${n}`],
  [/^kesalahan server: (.+)$/, (n) => `server error: ${n}`],
  [/^ketik '(.+)' untuk mengonfirmasi$/, (n) => `type '${n}' to confirm`],
  [/^menolak menghapus (.+)$/, (n) => `refusing to delete ${n}`],
  [/^atribut tidak ada: (.+)$/, (n) => `attribute does not exist: ${n}`],
  [/^(.+) belum diunggah: (.+)$/, (a, b) => `${a} has not been uploaded: ${b}`],
  [/^path di luar folder proyek: (.+)$/, (n) => `path outside the project folder: ${n}`],
  [/^tidak ada produk bernama (.+) di (.+)$/, (a, b) => `no product named ${a} in ${b}`],
  [/^tidak bisa mengatur (.+)$/, (n) => `cannot set ${n}`],
  [/^jenis berkas tidak diterima \(pakai (.+)\): (.+)$/, (a, b) => `file type not accepted (use ${a}): ${b}`],
  [/^ukuran berkas harus 1 B – (\d+) GB$/, (n) => `file size must be 1 B – ${n} GB`],
  [/^Proyek '(.+)' sudah ada — pakai nama lain\.$/, (n) => `Project '${n}' already exists — use another name.`],
  [/^Ukuran blok (\w+) wajib diisi \(tidak ada kolom (\w+)\)$/, (a) => `Block size ${a} is required (there is no ${a} column)`],
  [/^block_model\.(\w+) wajib diisi$/, (a) => `block_model.${a} is required`],
  [/^Topografi: (Easting|Northing) \((.+)\) tidak beririsan dengan model blok \((.+)\)\. Sistem koordinat berbeda\?$/, (a, b, c) => `Topography: ${a} (${b}) does not overlap the block model (${c}). Different coordinate system?`],
  [/^(\d+) parameter belum dikonfirmasi pemilik studi — (.+)\.$/, (n, list) => `${n} parameters not yet confirmed by the study owner — ${list.split(", ").map((x) => dict[x] ?? x).join(", ")}.`],
];
export const addPattern = (re, out) => patterns.push([re, out]);

function text(s, report = true) {
  const m = s.match(/^(\s*)([\s\S]*?)(\s*)$/);
  if (!m[2] || !LETTERS.test(m[2])) return s;
  return m[1] + translateCore(m[2], report) + m[3];
}

const SPLIT = /(<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>|<pre[\s\S]*?<\/pre>|<[^>]+>)/;   // <pre> holds the engine log: already English
const ATTR = /(\s(?:title|placeholder|aria-label|alt)=")([^"]*)(")/g;
export function tx(html) {
  return String(html).split(SPLIT).map((p, i) => (i % 2 ? (/^<pre/.test(p) ? p : p.replace(ATTR, (_m, a, v, c) => a + text(v) + c)) : text(p))).join("");
}
export const t = (s) => text(String(s ?? ""));
