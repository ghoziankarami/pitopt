# Product Requirements Document (PRD) — PitOpt v2 (Production Open-Source)

**Status:** Canonical Product Scope & Vision
**Target:** Production-Grade Open-Source Open-Pit Mine Optimizer, Scheduler & Practical Bench Designer
**Lisensi:** MIT

---

## 1. Visi & Posisi Produk

`PitOpt` adalah mesin dan aplikasi web lokal (*offline-first*) untuk **optimasi cangkang tambang terbuka (*open-pit shell optimization*)**, **pemilihan pit final & *pushback***, **penjadwalan produksi multi-periode**, **rekonsiliasi desain jenjang (*bench*) praktis + jalan angkut (*haul ramp*)**, serta **pelaporan teknis dapat diaudit (PDF, CSV, DXF 3D, HTML 3D interaktif)**.

Berbeda dari prototipe demo akademik yang hanya bekerja pada satu dataset contoh, **PitOpt v2 Production Open-Source** dirancang agar insinyur tambang (*mine planner*), geolog sumber daya, akademisi, dan tim konsultan dapat:
1. Mengimpor model blok nyata dari **GeoSuite Resource** (`Resource.html`) maupun perangkat lunak industri umum (`.csv` / `.dat` sub-cell / `.dxf` topografi) tanpa pra-pemrosesan manual di luar aplikasi.
2. Menjalankan optimasi *exact maximum-weight closure* berskala ratusan ribu blok dengan penjaga memori lintas platform (Linux, macOS, Windows asli tanpa wajib WSL) dan kecepatan solver terakselerasi.
3. Membedakan secara jujur antara **nilai cangkang blok optimasi (*optimiser shell*)**, **desain jenjang raster**, dan **desain praktis poligon + *ramp*** beserta jadwal produksi dan NPV masing-masing.
4. Mengaudit setiap parameter melalui sistem **Provenance 3-status (`input`, `terukur`, `asumsi`)** dan **5 pemeriksaan verifikasi independen** yang tidak bergantung pada struktur internal solver.

---

## 2. Persona & Alur Kerja Utama

| Persona | Kebutuhan Utama | Alur Kerja di PitOpt |
|---|---|---|
| **Perencana Tambang (*Mine Planning Engineer*)** | Menentukan batas pit final (RF 1.0 atau puncak NPV), membagi *pushback* yang memenuhi lebar kerja minimum, menjadwalkan bijih/waste per tahun, dan mengekspor kontur DXF ke CAD. | `Quick Pit / Proyek Baru` -> `Validasi & Reblock` -> `Run Optimasi` -> `Pushback & Rencana` -> `Desain Detail (Ramp)` -> `Ekspor DXF/PDF`. |
| **Geolog Sumber Daya (*Resource Geologist*)** | Menguji *Reasonable Prospects for Eventual Economic Extraction* (RPEEE — JORC / KCMI / NI 43-101) langsung dari ekspor CSV GeoSuite Resource dengan saringan kelas keyakinan (`Measured`, `Indicated` sebagai bijih; `Inferred` tetap digali sebagai batuan penutup/waste). | `Impor CSV GeoSuite Resource` -> `Saring Sentinel -999 / Kelas Keyakinan` -> `Cangkang Bersarang RF 0.40–1.20` -> `Laporan PDF Audit`. |
| **Peneliti & Pengembang Otomasi / AI** | Mengintegrasikan optimasi pit ke dalam skrip Python, CLI, atau agen AI melalui protokol MCP (*Model Context Protocol*) dengan kontrak JSON deterministik. | `pitopt validate` -> `pitopt run` / `pitopt mcp` (`PitOptCommands`). |

---

## 3. Persyaratan Fungsional Utama (Prototype -> Production Open-Source)

### FR-1. Interoperabilitas Input & Reblocking (`IO`)
- Menerima berkas CSV dengan baris komentar provenance `#` (standar ekspor GeoSuite Resource) pada model blok maupun permukaan topografi.
- Mendeteksi nilai sentinel blok belum terestimasi (`-999`) saat inspeksi unggahan (`inspect_csv`) dan menyediakan opsi penyaringan / penanganan eksplisit atau penolakan terarah sebelum optimasi.
- Menyediakan *reblocking* konservatif berbasis volume penuh dan rata-rata tertimbang massa (`pitopt/core/reblock.py`) untuk model sub-cell / ukuran blok campuran.

### FR-2. Mesin Ilmiah, Geoteknik & Ekonomi (`CORE` & `DESIGN`)
- **Valuasi Blok Multi-Produk & 6 Basis Kadar:** Mendukung `mass_percent`, `volume_percent`, `ppm`, `gpt`, `kgm3`, `gm3`, kenaikan biaya gali per meter kedalaman (`mining_cost_increment_per_m`), royalti, biaya rehabilitasi, dilusi, dan *mining recovery*.
- **Kemiringan Lereng Per-Domain & Sektor (`GEO-01`):** Menerapkan sudut lereng per-domain (`slope.domain_angles`) tidak hanya pada graf precedence blok, tetapi juga pada pembangunan geometri jenjang (*bench design*) dan pelaporan rekonsiliasi.
- **Penjadwalan & Keekonomian Desain Praktis (`GEO-02`):** Menyediakan jadwal produksi dan NPV berbasis **desain praktis (`in_design`)** berdampingan dengan jadwal cangkang blok (`in_pit`), sehingga selisih *stripping* akibat pelebaran jenjang dan jalan angkut terukur dalam NPV.
- **Diagnostik Kemiringan 3-Bench & Permukaan (`GEO-03`):** Memastikan pengukuran kemiringan 3-jenjang (`steepest_over_3_benches_deg`) memisahkan artefak tangga lantai pit (*floor-step*) dari kemiringan dinding sebenarnya.
- **Akselerasi Solver Skala Besar (`PERF-01`):** Menyediakan jalur solver *maximum-flow* terakselerasi C/SciPy (`scipy.sparse.csgraph.maximum_flow` / *warm-start* monotonik antar-RF) yang menurunkan waktu hitung dan jejak memori pada model >100.000 blok dengan hasil identik 100% terhadap `networkx.preflow_push`.

### FR-3. Antarmuka Pengguna, Quick Pit & Aksesibilitas (`UI`)
- **Quick Pit Estimation Mode (`QCK-01`):** Alur ringkas 1-layar untuk pengguna baru (pilih sampel / unggah CSV -> validasi instan -> jalankan -> ringkasan eksekutif & 3D).
- **Paritas Bahasa ID/EN (`UI-01`):** Seluruh 23 tampilan mendukung Bahasa Indonesia dan Bahasa Inggris secara utuh tanpa string yang bocor atau kunci yang hilang.
- **Responsif & WCAG 2.2 AA (`UI-02`):** Tata letak responsif pada mobile (`375px`), tablet (`768px`), dan desktop (`1440px`) dengan navigasi papan ketik dan kontras warna terverifikasi.

### FR-4. Pelaporan, Ekspor Offline & Otomasi MCP (`IO`, `MCP`, `REL`)
- **Self-Contained 3D HTML (`REP-01`):** `<name>_3d_viewer.html` menyematkan bundel Plotly lokal sehingga dapat dibuka 100% offline di komputer lapangan/tambang tanpa internet.
- **Laporan PDF Eksekutif & Audit (`REP-01`):** Sampul profesional berstandar Orebit, tabel provenance parameter, pit-by-pit, jadwal, penampang dinding skala 1:1, dan verifikasi independen.
- **Server MCP & Facade Otomasi (`MCP-01`):** Kompatibel dengan pustaka `mcp` v1 (`FastMCP`) maupun v2 (`MCPServer`), memakai *staging* konfigurasi atomik, dan mengekspos alat `validate_loaded_project` serta ringkasan desain.
- **Peluncur Asli Lintas Platform (`SYS-01`, `REL-01`):** Berjalan langsung di macOS, Linux, dan Windows asli (tanpa ketergantungan keras pada WSL2 `Ubuntu-24.04`) dengan deteksi RAM lintas platform.
