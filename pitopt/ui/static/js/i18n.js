// Interface language defaults to English. The screens are written in Indonesian;
// English is a dictionary applied to the HTML (and short strings) just before it reaches the DOM, so every
// screen, chart label, dialog and toast switches together and numbers, dates and
// decimal marks follow the language too.
//
// Keys are Indonesian text with every number replaced by {#}; the English value
// carries the same {#} in the same order. Text with no entry stays as written and is
// listed in `missing` (see window.__pitopt.i18n) so gaps are found, not guessed.
export let lang = localStorage.getItem("pitopt-lang") || "en";
if (lang !== "en" && lang !== "id") lang = "en";
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
const decodeEnt = (s) => s.replace(/&amp;/g, "&").replace(/&gt;/g, ">").replace(/&lt;/g, "<").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
const encodeEnt = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function applyDict(hit, nums) {
  let i = 0;
  return hit.replace(/\{#\}/g, () => nums[i++] ?? "");
}

function translateCore(core, report, isHtml = false) {
  const key = core.replace(/\s+/g, " ").replace(NUM, "{#}");
  if (report) seen.add(key);
  if (lang !== "en") return core;
  const nums = core.match(NUM) || [];
  let hit = dict[key];
  if (hit !== undefined) return applyDict(hit, nums);

  // Try matching entity-decoded text (e.g. "&amp;" -> "&", "&gt;" -> ">") when inside HTML
  const decoded = isHtml && /&(?:amp|gt|lt|quot|#39);/.test(core) ? decodeEnt(core) : core;
  const dKey = decoded.replace(/\s+/g, " ").replace(NUM, "{#}");
  const dNums = decoded.match(NUM) || [];
  if (decoded !== core) {
    hit = dict[dKey];
    if (hit !== undefined) return encodeEnt(applyDict(hit, dNums));
  }

  if (/ ·$|^· /.test(dKey)) {                        // dangling separator before/after an inline tag
    const inner = dKey.replace(/ ·$/, "").replace(/^· /, "");
    const en = dict[inner];
    if (en !== undefined) {
      const body = applyDict(en, dNums);
      const out = /^· /.test(dKey) ? `· ${body}` : `${body} ·`;
      return isHtml ? encodeEnt(out) : out;
    }
  }
  if (dKey.includes(" · ")) {                      // "label · status" fragments
    const parts = dKey.split(" · ");
    const done = parts.map((p) => dict[p]);
    if (done.some((d) => d !== undefined)) {
      let n = 0;
      const out = parts.map((p, i) => {
        const cnt = (p.match(/\{#\}/g) || []).length;
        const mine = dNums.slice(n, n + cnt); n += cnt;
        const v = done[i] ?? p;
        let k = 0;
        return v.replace(/\{#\}/g, () => mine[k++]);
      }).join(" · ");
      return isHtml ? encodeEnt(out) : out;
    }
  }
  for (const [re, out] of patterns) {
    const m = decoded.match(re);
    if (m) {
      const res = out(...m.slice(1));
      return isHtml ? encodeEnt(res) : res;
    }
  }
  if (report && /\s/.test(core)) missing.add(key);          // single tokens are names, units or identifiers
  return core;
}

// messages whose dynamic part is a name or a column, not a number
const patterns = [
  [/^ukuran blok target \(dx, dy, dz\) harus > 0$/, () => "target block size (dx, dy, dz) must be > 0"],
  [/^isi ukuran parent block \(dx, dy, dz\) atau pilih kolom ukuran blok$/, () => "fill in the parent block size (dx, dy, dz) or choose the block size columns"],
  [/^kolom (\w+) wajib dipilih$/, (n) => `column ${n} is required`],
  [/^kolom tidak ada di berkas: (.+)$/, (n) => `column not in the file: ${n}`],
  [/^reblock hanya untuk model blok CSV$/, () => "reblock only works on a CSV block model"],
  [/^Mengunggah (.+) — (\d+)%$/, (n, p) => `Uploading ${n} — ${p}%`],
  [/^folder: (.+)$/, (n) => `folder: ${n}`],
  [/^Rekomendasi engine: (.+)$/, (n) => `Engine recommendation: ${n}`],
  [/^Rekomendasi engine · (.+)$/, (n) => `Engine recommendation · ${dict[n] ?? translateCore(n, false)}`],
  // text the engine already wrote in English (results.json), possibly with a dangling separator
  [/^((?:smallest shell within .+|maximum (?:average|best|worst)-case NPV|\d+ \(auto: .+\)|\d+ \(set manually\)|\d+ pushbacks.+|no results.+|slope\.overall_angle_deg.+))$/, (n) => n],
  [/^Margin (.+)$/, (n) => `Margin ${n}`],
  [/^(\w{3} \d{1,2}, \d{4}, \d{1,2}:\d{2}(?::\d{2})?\s?(?:AM|PM)?)$/, (n) => n],       // run date in the header: a value, not text
  [/^(\d{1,2}) (Jan|Feb|Mar|Apr|Mei|May|Jun|Jul|Agu|Aug|Sep|Okt|Oct|Nov|Des|Dec) (\d{4})$/, (d, m, y) => `${d} ${{ Mei: "May", Agu: "Aug", Okt: "Oct", Des: "Dec" }[m] || m} ${y}`],
  [/^Jalankan (.+)$/, (n) => `Run ${n}`],
  [/^Hapus skenario "(.+)"$/, (n) => `Delete scenario "${n}"`],
  [/^Hapus proyek "(.+)"$/, (n) => `Delete project "${n}"`],
  [/^Skenario "(.+)" disimpan\.$/, (n) => `Scenario "${n}" saved.`],
  [/^Kadar (.+)$/, (n) => `Grade ${n}`],
  [/^Belum ada hasil untuk skenario “(.+)”$/, (n) => `No results yet for scenario “${translateCore(n, false)}”`],
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
  [/^mis\. (.+)$/, (n) => `e.g. ${n}`],
  [/^Berkas (.+) tidak ditemukan untuk skenario ini$/, (k) => `${k} file not found for this scenario`],
  [/^Terdeteksi nilai sentinel -999 \(blok belum terestimasi\) pada kolom (.+) — saring baris unestimated atau jalankan reblock sebelum optimasi\.$/, (cols) => `Sentinel value -999 (unestimated blocks) detected in column(s) ${cols} — filter unestimated rows or run reblock before optimising.`],
  [/^Hasil\/input tidak dapat diverifikasi: (.+)$/, (e) => `Results/inputs could not be verified: ${e}`],
  [/^proyek sumber tidak memiliki skenario: (.+)$/, (p) => `source project has no scenarios: ${p}`],
  [/^rute desain tidak dikenal: (.+)$/, (r) => `unknown design route: ${r}`],
  [/^(.+) USD\/(\w+) · recovery (.+)%$/, (p, u, r) => `${p} USD/${u} · recovery ${r}%`],
  [/^domain (.+)$/, (d) => `domain ${d}`],
  [/^rock ([+−-]?[\d.,]+)% · ore ([+−-]?[\d.,]+)% · bench ([\d.,]+) m$/, (r, o, b) => `rock ${r}% · ore ${o}% · bench ${b} m`],
  [/^Dibanding shell optimasi, desain bench menggali ([\d.,]+)% (lebih banyak|lebih sedikit) batuan dan ([\d.,]+)% (lebih banyak|lebih sedikit) bijih, dengan nilai ([+−-]?[\d.,]+)%\. (.+)$/, (r, rd, o, od, v, tail) => `Compared with the optimiser shell, the bench design mines ${r}% ${rd === "lebih banyak" ? "more" : "less"} rock and ${o}% ${od === "lebih banyak" ? "more" : "less"} ore, with value ${v}%. ${translateCore(tail, false)}`],
  [/^Pembagian berbasis shell menghasilkan tahapan yang lebih sempit dari lebar kerja minimum ([\d.,]+) m; pembagian yang paling tidak sempit dipakai\.$/, (w) => `Shell-based division produced stages narrower than the ${w} m minimum working width; the least-narrow division is used.`],
  [/^NPV negatif pada faktor harga (.+)\. Pit final tetap; blok dinilai ulang pada harga itu\.$/, (list) => `Negative NPV at price factors ${list}. The final pit stays fixed; blocks are revalued at that price.`],
  [/^dari harga rencana\. Leverage ([\d.,]+)× — ([\d.,]+)% harga menggeser NPV ~([\d.,]+)%\.$/, (l1, p, l2) => `of plan price. Leverage ${l1}× — a ${p}% price change shifts NPV ~${l2}%.`],
  [/^(\d+) blok keluar dari shell yang lebih besar — periksa numerik\.$/, (n) => `${n} blocks exited the larger shell — check numerics.`],
  [/^Tidak ada pembagian shell yang memenuhi lebar kerja dan tonase minimum \((\d+) kandidat diuji\)\.$/, (n) => `No shell division satisfies minimum working width and tonnage (${n} candidates tested).`],
  [/^([\d.,]+) m³ \(([\d.,]+)% volume galian desain\) berada di antara topografi dan puncak model tanpa blok — tidak dihitung biaya maupun tonasenya\.$/, (v, p) => `${v} m³ (${p}% of design excavation volume) lies between topography and top of model with no blocks — neither costed nor counted in tonnage.`],
  [/^Parent ([\d.,]+)×([\d.,]+)×([\d.,]+) m → ([\d.,]+) blok (.+) m\. Selisih volume ([+−-]?[\d.,]+) m³\.$/, (px, py, pz, nb, tgt, diff) => `Parent ${px}×${py}×${pz} m → ${nb} blocks ${tgt} m. Volume difference ${diff} m³.`],
  [/^([\d.,]+)% blok terisi < 50% — volume sebenarnya dipakai, bukan ukuran nominal\.$/, (p) => `${p}% of blocks filled < 50% — actual volume is used, not nominal size.`],
  [/^(\d+) pushback dari (\d+) strip × ([\d.,]+) m, maju (.+)$/, (n, k, w, d) => `${n} pushbacks of ${k} strips × ${w} m, advancing ${{ "selatan → utara": "south → north", "utara → selatan": "north → south", "barat → timur": "west → east", "timur → barat": "east → west" }[d] || d}`],
  [/^RL ([−-]?[\d.,]+)$/, (v) => `RL ${v}`],
  [/^RL ([−-]?[\d.,]+) m$/, (v) => `RL ${v} m`],
  [/^crest ([+−-]?[\d.,]+) · lantai ([+−-]?[\d.,]+)$/, (a, b) => `crest ${a} · floor ${b}`],
  [/^Warna: kadar (.+), skala kontinu\.$/, (g) => `Colour: grade ${g}, continuous scale.`],
  [/^BLOCK MODEL · (.+)$/, (g) => `BLOCK MODEL · ${g}`],
  [/^PD_CREST_(.+) … PD_CREST_(.+)$/, (a, b) => `PD_CREST_${a} … PD_CREST_${b}`],
  [/^PD_TOE_(.+) … PD_TOE_(.+)$/, (a, b) => `PD_TOE_${a} … PD_TOE_${b}`],
  [/^folder hasil skenario (.+)$/, (s) => `scenario output folder ${s}`],
  [/^pelanggaran · skenario (.+)\.$/, (s) => `violations · scenario ${s}.`],
  [/^N=(\d+) · IRA (.+)$/, (n, ira) => `N=${n} · IRA ${ira}`],
  [/^Kosong = di azimut tempat dinding terlebar: ([−-]?[\d.,]+)°\.$/, (a) => `Blank = use the azimuth with the widest wall: ${a}°.`],
  [/^Bench (\d+) sudah tampil$/, (b) => `Bench ${b} shown`],
  [/^Bench (\d+) dari (\d+) sudah tampil$/, (b, tot) => `${b} of ${tot} benches shown`],
  [/^skenario (.+)$/, (s) => `scenario ${translateCore(s, false)}`],
  [/^Ramp putus di bench (\d+): (.+)$/, (b, r) => `Ramp broken at bench ${b}: ${r}`],
  [/^(Rock|Umpan|Nilai) desain ([+−-]?[\d.,]+) % terhadap shell \(peringatan > ([\d.,]+) %, blokir > ([\d.,]+) %\)\.$/, (name, v, w, b) => `Design ${{ Rock: "rock", Umpan: "ore", Nilai: "value" }[name]} is ${v}% relative to the shell (warning threshold >${w}%; blocking threshold >${b}%).`],
  [/^Desain mengikuti shell hingga ([\d.,]+) % di seluruh tumpukan \(titik terlemah (.+)\)\.$/, (v, s) => `Design follows the shell to ${v}% across the entire stack (weakest point ${translateCore(s, false)}).`],
  [/^Pada (.+), luas desain hanya ([\d.,]+) % dari luas shell asli di elevasi itu — offset dari satu titik acuan (tidak cocok dengan|mungkin kurang dari) lebar sebenarnya shell di sana\.(.*)$/, (sc, v, verb, tail) => `At ${translateCore(sc, false)}, design area is only ${v}% of the original shell area at that elevation — offset from a single reference point ${verb === "tidak cocok dengan" ? "does not match" : "may be narrower than"} the shell's true width there.${tail ? " This shell shape does not narrow to a single cone; reconciliation below should not be trusted at face value." : ""}`],
  [/^(Sudut inter-ramp|Sudut overall \(dengan ramp\)) ([\d.,]+)° (melampaui batas|hampir di batas|di dalam batas) ([\d.,]+)°(?: \(margin ([+−-]?[\d.,]+)°\))?\.$/, (what, v, st, l, m) => `${what === "Sudut inter-ramp" ? "Inter-ramp angle" : "Overall angle (with ramp)"} of ${v}° ${st === "melampaui batas" ? `exceeds the ${l}° limit (margin: ${m}°)` : st === "hampir di batas" ? `is near the ${l}° limit (margin: ${m}°)` : `is within the ${l}° limit`}.`],
  [/^(Sudut inter-ramp|Sudut overall \(dengan ramp\)) ([\d.,]+)°; belum ada batas\.$/, (what, v) => `${what === "Sudut inter-ramp" ? "Inter-ramp angle" : "Overall angle (with ramp)"} ${v}°; no limit set.`],
  [/^Dasar pit selebar ([+−-]?[\d.,]+) m; lebar kerja minimum ([+−-]?[\d.,]+) m\.$/, (v, l) => `Pit floor is ${v} m wide; minimum working width ${l} m.`],
  [/^bench (\d+) \((crest|toe), RL ([−-]?[\d.,]+)\)$/, (b, ct, rl) => `bench ${b} (${ct}, RL ${rl})`],
  [/^bench (\d+)\/(\d+)$/, (a, b) => `bench ${a}/${b}`],
  [/^bench (\d+)$/, (a) => `bench ${a}`],
  [/^Satu jalan menerus dari dasar ke puncak, ([\d.,]+) m dengan grade ([\d.,]+)%\.$/, (len, g) => `One continuous road from the floor to the crest, ${len} m at ${g}%.`],
  [/^Lebar jalan ([\d.,]+) m lebih sempit dari kebutuhan armada ([\d.,]+) m\.$/, (w, req) => `The road is ${w} m wide, narrower than the ${req} m the fleet needs.`],
  [/^(\d+) bench: seluruh kontur valid dan dinding tidak menggantung\.$/, (n) => `${n} benches: every outline is valid and no wall overhangs.`],
  [/^Kontur bukan poligon valid: (.+)$/, (why) => `Outline is not a valid polygon: ${why}`],
  [/^([A-Za-z0-9_-]+) t$/, (n) => `${n} t`],
  [/^(.+) — ([\d.,]+) facet\.$/, (f, n) => `${f} — ${n} facets.`],
  [/^([A-Za-z0-9_]+(?:, [A-Za-z0-9_]+)+)$/, (cols) => cols],
];
export const addPattern = (re, out) => patterns.push([re, out]);

function text(s, report = true, isHtml = false) {
  const m = s.match(/^(\s*)([\s\S]*?)(\s*)$/);
  if (!m[2] || !LETTERS.test(m[2])) return s;
  return m[1] + translateCore(m[2], report, isHtml) + m[3];
}

const SPLIT = /(<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>|<pre[\s\S]*?<\/pre>|<[^>]+>)/;   // <pre> holds the engine log: already English
const ATTR = /(\s(?:title|placeholder|aria-label|alt)=)("([^"]*)"|'([^']*)')/g;
export function tx(html) {
  return String(html).split(SPLIT).map((p, i) => (i % 2 ? (/^<pre/.test(p) ? p : p.replace(ATTR, (_m, a, _q, dq, sq) => {
    const q = dq !== undefined ? '"' : "'";
    const v = dq !== undefined ? dq : sq;
    return a + q + text(v, true, true) + q;
  })) : text(p, true, true))).join("");
}
export const t = (s) => text(String(s ?? ""), true, false);
