# Handover kredibilitas dan usability PitOpt

13 Oktober 2026. Plan: [PLAN_CREDIBILITY_USABILITY.md](PLAN_CREDIBILITY_USABILITY.md). Audit awal: [FOUNDATION_AUDIT_2026-10-13.md](FOUNDATION_AUDIT_2026-10-13.md). Implementasi dikerjakan di public dan private; publikasi source mengikuti branch perbaikan dan receipt handoff. Deployment produksi dikerjakan pemilik dari laptop lokal; task cloud ini tidak mempromosikan service.

## Hasil implementasi

- P1: SHA256 CSV/topografi, parameter resolved dan source engine mengikat hasil ke input. Status current/stale/unverified berlaku setelah restart. Hasil lama tetap tersimpan; stale ditolak, legacy dapat dibaca sebagai unverified tetapi ekspor/consumer turunan meminta rerun.
- P2: job dan konfirmasi run terikat project/scenario/versi selection. Respons lama, termasuk A→B→A, tidak menghapus draft baru. Save scenario tervalidasi, atomik dan eksklusif. Upload gagal, job gagal/cancel dan CLI export gagal mempertahankan file sebelumnya. Desain cached dan job Generate ditolak jika run optimasi diganti; Generate baru diperlukan.
- P3: input contract mencatat centroid, meter, density t/m³, grade basis, CRS/datum opsional dan identitas baris sumber; label 001/NA/NULL tetap literal. Tidak melakukan reproyeksi otomatis. Resource classification tetap deklarasi pengguna. Readiness/warnings menyatakan schedule dan NPV berbasis shell, material bench belum sepenuhnya dijadwalkan/dibiayai, dan bench seragam belum menerapkan sudut tiap domain.
- P4: oracle numerik dan lifecycle/browser checks lulus; removed-fix controls membuktikan kegagalan kode lama. Golden dibandingkan dengan fixture audit sebelumnya: **tidak ada perubahan numerik** pada tahap P1–P6 ini. Koreksi numerik audit sebelumnya tetap berlaku dan terdokumentasi.
- P5: launcher memeriksa package editable dan runtime imports dalam Python isolated mode, memilih interpreter yang mempunyai ensurepip/venv, memperbaiki environment tanpa menghapusnya, dan memverifikasi fingerprint contoh. Profil dependency Linux Python 3.12 serta petunjuk install tersedia.
- P6: evidence, fingerprint source, package, corpus dan cloud start instructions disimpan untuk review.

## Acceptance yang dijalankan

| Pemeriksaan | Public | Private |
| --- | --- | --- |
| Full pytest source akhir | 427 passed, 12 skipped (325.99s (0:05:25)) | 405 passed, 13 skipped (279.33s (0:04:39)) |
| Ruff dan pip check | Lulus | Lulus |
| Corpus emas/nikel/timah + fingerprint current | 3/3 lulus | 3/3 lulus |
| Upload CSV/DXF nyata EN/ID desktop/phone | 12/12 lulus | 12/12 lulus |
| Optimasi dari tombol UI ID desktop | 3/3 lulus | 3/3 lulus |
| Native CSV/XLSX/PDF/DXF readback | 3/3 lulus | 3/3 lulus |
| Wheel/sdist dan isolated installed-wheel smoke | Lulus; seluruh 40 aset | Lulus; seluruh 40 aset |
| Interrupted source install | Repair, sentinel dipertahankan, example current dan HTTP ready | Sama |

Full-suite skips adalah kondisi fixture yang tidak berlaku; daftar tepat ada di log `-ra`. Private tidak memprovisikan dua kasus Porphyry demo. Tidak ada skip karena browser tidak tersedia. Native readback berarti format file dibuka oleh reader, bukan acceptance Surpac/Datamine atau perangkat desktop native.

Negative controls tambahan: 3 tes konteks job gagal dengan run.js HEAD, 2 tes desain gagal dengan design/core.js HEAD, 4 tes freshness/download gagal saat guard dimatikan, serta tes cached-design dan publication Generate masing-masing gagal dengan DesignService HEAD. Tes baru cached design memeriksa result/plan/export HTTP 409 setelah run diganti dan Generate sukses memulihkan akses. Log negatif memang mencatat failed dan tidak dihitung sebagai kegagalan suite implementasi akhir.

Orebit dataset `7f4cd96f0e521c16e40826aa232cbf760938d1dc`, CC BY 4.0, kredit Orebit.id: emas 1.665, nikel 6.529, timah 3.402 blok. Fixture nearest-neighbour assay dan TIN dari elevasi collar sintetis untuk acceptance software. Data asli tidak dimodifikasi; 103 assay emas dan 41 assay nikel kosong tidak dijadikan nol. Manifest tiap fixture menyimpan asumsi/checksum. Dataset validate/readme checks dan 5 unittest juga lulus. Readback membandingkan massa/logam native, cash blok per periode, NPV terdiskonto, hard plant capacity, schedule Excel, PDF 11 halaman yang dirender, serta DXF 3DFACE nonkosong.

## Cara mengulang

Dari checkout yang diuji:

```bash
export XDG_CACHE_HOME=/workspace/scratch/cache
export MPLCONFIGDIR=/workspace/scratch/matplotlib
export PLAYWRIGHT_BROWSERS_PATH=/workspace/scratch/browsers
export PITOPT_CHROMIUM_EXECUTABLE=/usr/bin/chromium
.venv/bin/python -m pip check
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -ra
# Jangan menjalankan dua pytest atas checkout yang sama saat conftest membangun fixtures.
.venv/bin/python /workspace/scratch/pitopt-audit/run_corpus.py
.venv/bin/python /workspace/scratch/pitopt-audit/browser_upload.py
```

Jalankan kedua corpus sebelum `readback_corpus.py`. Tunggu output generation selesai sebelum menjalankan suite yang membaca output. Launcher Linux: `PITOPT_CONSTRAINTS="$PWD/requirements-tested-py312.txt" NO_BROWSER=1 bash scripts/start_ui.sh 8765`. Aplikasi lokal; tidak ada service/deployment permanen dibuat. Hasil legacy akan meminta rerun sebelum ekspor. Python 3.12.14, Playwright 1.63 dan system Chromium 154 adalah profil cloud yang diuji.

Evidence tambahan berada di `/workspace/scratch/pitopt-audit/credibility/`: `evidence/`, `source-fingerprints.json`, `golden-review.json`, package public/private, clean wheel environments, dan launcher fixtures. Source fingerprint mengikat isi working tree, karena HEAD tidak memuat perubahan ini. Helper corpus dan artifact audit lama berada satu direktori di atasnya.

## Batas acceptance dan langkah berikutnya

Pengaman lifecycle, format data, kapasitas dan distribusi selesai untuk scope plan ini. **Sign-off desain tambang operasional belum tercapai.** NPV tetap shell economic basis; penjadwalan/costing material desain bench dan enforcement slope per domain belum diselesaikan. Keduanya perlu oracle serta acceptance geoteknik/ekonomi sebelum mengubah algoritma. CRS/datum dicatat dari deklarasi pengguna, tanpa transformasi atau sertifikasi klasifikasi sumber daya.

Trial besar Porphyry public dari audit awal selesai 75.696 blok/19 periode, ~19 menit dan peak RSS ~3,28 GiB. Diagnostic mencapai 45,19° pada bentang tiga bench terhadap input 42°, dan 38 pit blocks menyentuh batas model bawah. Trial itu **tidak diulang pada engine akhir** dan tidak diduplikasi di private; file legacy ditandai unverified dan tidak memenuhi gate current/export. Tes konsistensi yang masih membacanya tidak dianggap acceptance freshness baru.

Belum diuji: native Windows/WebView2, macOS/Safari, interoperability dalam aplikasi CAD/mining target, browser lain, dependency/platform di luar profil ini, estimasi resource tervalidasi, tuning benchmark p50/p95 dan restoration environment pada task baru. Urutan lanjut: oracle desain-domain/bench economics → rebuild Porphyry demo dengan fingerprint current sebelum release → dataset pengguna yang geologi/topografinya tervalidasi → acceptance native installer/interoperability → release candidate.

Cloud draft start instructions terbaru tersimpan (`requires_publish=true`), tanpa perubahan secret/domain atau daftar repo. Review, Save lalu Publish di environment settings untuk mengaktifkan snapshot. Draft save belum publish; publication/restoration baru tidak diklaim sudah lulus.
