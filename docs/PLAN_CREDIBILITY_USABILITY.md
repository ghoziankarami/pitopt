# Plan kredibilitas dan usability PitOpt

Tanggal 13 Oktober 2026. Eksekusi di checkout cloud yang sudah tersedia; tidak membuat worktree. Baseline dan perbaikan audit sebelumnya dipertahankan. Publik dan privat divalidasi terpisah; tidak merge/deploy otomatis.

| Increment | Perubahan dan owner | Kriteria keluar |
| --- | --- | --- |
| P1: identitas/freshness | fingerprint SHA256 input, parameter resolved, versi/source engine; results writer, server dan seluruh consumer hasil/export | edit CSV/topografi/parameter -> hasil stale; restart/reopen tetap stale; rerun -> current; file lama tetap tersedia tetapi ekspor stale ditolak; format lama terbaca dengan status unverified yang jelas |
| P2: lifetime job/project | owner project/scenario pada job, konfirmasi run terikat konteks, respons/promotion lama ditolak; scenario save tervalidasi dan atomik | A -> B selama job A tidak menimpa B; source berubah selama run tidak dipromosikan; failed/duplicate save tidak merusak scenario valid |
| P3: kontrak data/desain | input units/density/CRS/source identities; eksplisit shell-vs-design economic basis dan per-domain geotechnical readiness | kontrak dan batas yang belum didukung tampil pada hasil; tidak ada klaim desain/jadwal operasional yang belum direkonsiliasi; perbaikan angka/geometri hanya dengan reproduksi dan independent oracle |
| P4: evidence numerik | known answers, removed-fix controls, corpus emas/nikel/timah Orebit beserta TIN sintetis dan readback native | massa/logam/cash/NPV/capacity sesuai oracle; input asli tidak diubah; conditional skips dan native device checks dilaporkan |
| P5: instalasi dan distribusi | launcher non-destructive, deteksi dependensi nyata, instalasi interrupted bisa dilanjutkan; package smoke outside checkout | clean wheel install dan source launch lulus; metadata versi/dependensi tersedia; contoh hanya dianggap siap bila input/parameter sesuai |
| P6: handover | source fingerprints, plan status, logs, dataset revision, tested/unrun matrix, reusable cloud instructions | reviewer dapat mengulang checks; source dan artifact yang diuji jelas; draft save dibedakan dari publication |

Urutan eksekusi P1 -> P2 -> P3 -> P4/P5 -> P6. Semua requirement yang dapat diselesaikan di cloud dikerjakan. Validasi geoteknik/ekonomi nyata dan native Windows/macOS menggunakan data/mesin yang sesuai; cloud tidak dianggap bukti tersebut. Hindari rewrite algoritma tanpa gap yang terbukti, perubahan schema major tanpa migration tests, normalisasi klasifikasi sumber daya otomatis, atau klaim NN fixture sebagai estimasi geologi tervalidasi.

Tes wajib per increment: assertion behavior baru; tes harus gagal jika guard dihapus; affected existing suites; browser actual controls bila UI berubah. Gate akhir: lint, full pytest, named Orebit corpus, export readback dan clean installed-wheel smoke. Workload besar yang sudah valid dapat dipakai ulang bila engine/input/parameter tidak berubah; rebuild diperlukan bila fingerprint berubah.

Status akhir: P1–P6 diimplementasikan dan acceptance cloud selesai. Bukti dan batas yang belum diterima ada di [HANDOVER_CREDIBILITY_USABILITY.md](HANDOVER_CREDIBILITY_USABILITY.md); sign-off operasional bukan hasil plan ini.
