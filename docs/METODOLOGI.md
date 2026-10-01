# Metodologi dan batas validasi

Nilai blok dihitung dari grade, basis massa/volume, harga, recovery, dilusi,
royalti dan biaya eksplisit. Maximum closure direduksi ke minimum cut dan
menggunakan NetworkX preflow-push. Graf presedens merepresentasikan lereng
pada pusat blok, bukan bidang geoteknik kontinu.

Validasi independen meliputi LP HiGHS, Dinic scipy, enumerasi himpunan kecil,
Boykov–Kolmogorov, konservasi volume, pengecekan laporan, dan rekonsiliasi DXF.
Uji silang nilai optimum tidak membuktikan kebenaran asumsi input.

Jadwal adalah heuristik dengan urutan pushback yang ditetapkan; label best/worst
menyatakan dua urutan yang dihitung, bukan batas optimum global NPV.
Sensitivitas harga pada pit tetap tidak mengoptimasi ulang geometri.

Hasil porphyry sintetis yang diaudit: 75.696 blok, 10 shell, 19 periode,
RF final 0,5. Shell menyentuh dasar model pada 38 blok, sehingga batas pit
belum tertutup dan optimum lebih dalam belum diselidiki. Desain raster
menambah tonase batuan sekitar 11,74% terhadap shell dan feed sekitar 11,47%.
Overall angle input 42°, template efektif sekitar 43,96° sepanjang sumbu.
Angka 0 pelanggaran memakai toleransi/diskretisasi pemeriksaan yang tersedia;
bukan sertifikasi bahwa setiap permukaan memenuhi tepat 42°.

Semua grade, densitas, harga, recovery dan parameter geoteknik contoh adalah
sintetis/asumsi. Akurasi terhadap deposit nyata belum diukur. Penggunaan studi
nyata membutuhkan kalibrasi data, sensitivitas ukuran blok, model lebih luas,
validasi geoteknik dan pemeriksaan mandiri oleh tenaga kompeten.
