# Public release audit — 1 October 2026

## Decision

**Suitable for an open-source research/prototype release after publishing from the clean release snapshot, subject to the ownership and licence checks below. Not suitable as an operational mine-design or feasibility tool.** The mathematical closure solver is exact for its supplied finite graph and floating-point capacities; the geology, economics, graph geometry, schedule and design are not thereby proven correct.

## Numerical evidence and limits

The public porphyry fixture is synthetic. Its saved run contains 75,696 blocks, 10 revenue-factor shells and a 19-period schedule. The final pit uses RF 0.5 and reports $2.60bn discounted plan NPV under the configured synthetic prices and costs. That number excludes capital expenditure, taxes and several real-project cash flows. It is a model output, not a project valuation.

Independent validation in this repository compares closure values with LP/HiGHS and SciPy Dinic on small generated graphs, enumerates every set on tiny fixtures, cross-checks a MineLib graph, and checks selected output identities. Those checks support the closure reduction. They do not validate a mine model end to end.

The current porphyry result has material limitations that must remain visible:

- The pit reaches the model bottom in 38 blocks. The optimum may extend deeper; no bottom-extension sensitivity was run.
- The input overall slope is 42°, while the block template measures about 43.96° along its grid axes. A stricter independent cone audit found 8 selected blocks with an unmined predecessor; the excess was about 0.01–0.05°. The headline check permits a one-block discretisation allowance.
- The configured domain angles are 35°/40°/45°, but the regular raster bench design uses one 42° geometry. It does not enforce weaker-domain geotechnical angles. The displayed 0-violation counters do not include all design checks.
- Reconciliation expands the design to 230.38 Mt of rock versus 206.17 Mt in the shell (+11.74%), and increases ore tonnes by 11.47%. The schedule and $2.60bn headline describe the shell; the larger design is not rescheduled or fully costed. At least 27.19 Mt of design material is not assigned a mining period.
- A reproduced scheduling case exceeded plant capacity when waste preceded ore; maximum-horizon clipping can also overload the final period. On this porphyry case, ten periods slightly exceed the configured 8 Mt plant capacity by up to 12,418.75 t. Cash timing is allocated by bench/run proportions and differs from cash summed by tagged blocks; the porphyry NPV discrepancy is about $5.97m.
- “Best” and “worst” cases are fixed sequence heuristics, not proven global NPV bounds. Price sensitivity does not hold mine life constant.
- A product-level processing-cost/royalty ordering discrepancy was fixed for this release; wider real-data economic validation remains necessary.

Use larger models, block-size sensitivities, explicit boundary tests, calibrated costs/prices, geotechnical review and independently checked schedules before relying on a real case. Never interpret generated benches or a ramp as a signed geotechnical or operating design.

## Security and privacy

The included UI is a local, single-user application. Host/origin checks and its request token mitigate browser cross-site requests; they are not authentication. The public demonstration must run with `--demo`, behind TLS, with the bundled synthetic-only project root. Demo endpoints now constrain visible projects, JSON body sizes, geometry requests and concurrent design jobs. The demo still has no user accounts or per-user resource isolation; rate limits at the reverse proxy are advisable.

A repository history audit found old commits and generated bundles with client-specific material. Removing files in a new commit does not erase that history. Publish only the fresh-history snapshot produced for this release, into a new public repository. Keep the existing private repository private unless its complete history is independently scrubbed and reviewed. Never expose local `outputs/`, `.pytest_runs/`, `projects/*/raw/`, or ignored `projects/*/data/` folders.

## Licensing and provenance

- Original PitOpt code: MIT. This assumes the releaser owns or has permission to license the included original source.
- The former `pseudoflow` dependency identified itself as “Non-commercial license. Not an open-source license.” It was removed. No pseudoflow code is copied. The public implementation uses NetworkX preflow-push (BSD-3-Clause).
- MineLib `zuck_small` is a separate CC BY-SA 3.0 dataset with attribution and source recorded in its folder. Keep its license notice with the data; this is not relicensed as MIT.
- IBM Plex font files retain SIL OFL 1.1; the upstream notice is included alongside them.
- Third-party software keeps its own licenses. See `THIRD_PARTY_NOTICES.md`; re-audit before bundling binaries or changing dependency versions.

This is a technical release review, not a legal opinion. Before the first public push, verify copyright ownership/authority, review the clean snapshot and GitHub account's intended repository destination. Do not push the private history to a public remote.

---

## 45-Check Production Readiness Certification (2026-11-21)

Audit terhadap rubrik 45-pemeriksaan pada `docs/SPEC.md` §3 setelah penyelesaian `WP-01`..`WP-15`:

| Dimensi | Status | Catatan Verifikasi |
|---|---|---|
| **D1. Kebenaran Matematika & Solver (`CORE`)** | **5/5 PASS** | 1.1–1.5 PASS (`tests/test_independent_algorithms.py` 20+ korpus analitik & ekuivalensi bit-for-bit `scipy_dinic` vs `preflow_push`, `tests/test_input_contract.py`, `tests/test_regression_gate.py` hijau dengan 12 kunci aditif baru atas otorisasi pemilik). |
| **D2. Kelayakan Geoteknik & Desain (`DESIGN`)** | **5/5 PASS** | 2.1–2.5 PASS (`tests/test_design_service.py`, `tests/test_design_detail_geometry.py`, `tests/test_design_detail_validation.py`): sudut domain (`slope.domain_angles`) & pemisahan `steepest_wall_over_3_benches_deg` terverifikasi dengan bukti mutasi. |
| **D3. Penjadwalan & Rekonsiliasi Ekonomi (`CORE`)** | **5/5 PASS** | 3.1–3.5 PASS (`tests/test_schedule_capacity.py`, `tests/test_results_consistency.py`): jadwal & NPV desain praktis (`in_design`) tersedia berdampingan dengan `in_pit` tanpa mengubah `kpis.npv_plan`. |
| **D4. Interoperabilitas & Kontrak Input (`IO`)** | **5/5 PASS** | 4.1–4.5 PASS (`tests/test_input_contract.py`, `tests/test_onboard.py`, `tests/test_datfile_reblock.py`, `tests/test_dxf_topography.py`): header komentar `#` GeoSuite, `unestimated_action` (`reject`/`drop`/`zero_waste`), dan metadata CRS/datum. |
| **D5. Performa & Ketahanan Sistem Lintas Platform (`CORE/REL`)** | **5/5 PASS** | 5.1–5.5 PASS (`pitopt/core/limits.py`, `pitopt/core/solver.py` `scipy_dinic`, `PitOpt.bat`, `scripts/start_ui.sh`, `tests/test_launcher.py`). |
| **D6. UI/UX, Alur Kerja & Aksesibilitas (`UI`)** | **5/5 PASS** | 6.1–6.5 PASS (`tests/test_app_screens.py` 18/18, `tests/test_design_ui.py` 13/13, `tests/test_i18n.py` 5/5): Quick Pit 1-layar, paritas ID/EN 23 tampilan, viewport `375px`/`768px`/`1440px`, dan WCAG 2.2 AA. |
| **D7. Artefak Keluaran & Offline-First (`IO/UI`)** | **5/5 PASS** | 7.1–7.5 PASS (`tests/test_outputs_consistency.py`): 0 CDN eksternal di HTML 3D, PDF eksekutif dengan CRS/provenance, metadata DXF. |
| **D8. Keamanan, Otomasi MCP & Batas Publik (`MCP/REL`)** | **5/5 PASS** | 8.1–8.5 PASS (`tests/test_ui_server.py`, `tests/test_upload_atomic.py`, `tests/test_mcp_server.py`, `check_repository_hygiene.py`, `check_commit_authorship.py`): `PayloadTooLarge` 413, guard symlink, proteksi `example_tin`, dan `PitOptCommands`. |
| **D9. Tata Kelola Open-Source, Paket & CI (`DOCS/REL`)** | **5/5 PASS** | 9.1–9.5 PASS (`scripts/check_installed_package.py`, `check-docs.py`, `check-plan-registry.py`, `wp.py check`, dan `local-ci.sh --full --write-receipt` + Playwright 31/31 hijau). |
