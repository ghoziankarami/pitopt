# PitOpt foundation audit — 2026-10-13

This increment follows the supplied foundation-stabilization plan's F0/F1/F2/F5 priorities: reproduce incorrect numbers or lost data, fix small owners, and verify real uploaded CSVs. It does not certify GeoSuite or migrate its UI/Domain engine.

Baseline for this checkout: `b2d92a2fbb91d458c513b9fdad80cbadb31eb590`. Changes are local reviewable working-tree edits; HEAD alone does not identify the modified source.

## Changes

- Block loader rejects missing/nonfinite coordinates, grades, dimensions and density; negative grade sentinels; nonpositive material volume; duplicate centroids; and explicitly mapped missing columns. Zero grade stays valid. Numeric-looking domain/class identifiers retain leading zeroes.
- Economics supports `kgm3` (kg metal per in-situ m³) and `gm3` (g metal per in-situ m³). Rock/product density does not multiply these metal masses. Marginal cutoff uses the same native basis. UI choices now use the engine's `gpt` spelling and remove the unsupported `fraction` option.
- Whole-block schedules close periods before plant or movement capacity is exceeded. Oversized blocks and exhausted horizons produce explicit errors, rather than overloading the final period. Cash and NPV follow the actual tagged blocks, including waste costs.
- Uploads are staged and inspected before atomic replacement. Interrupted, malformed, empty and nonfinite-inspection uploads retain the original input.
- Scenario selection clears old state immediately and rejects late config/result callbacks from a superseded selection. Unsolved projects do not request missing result files.
- Unavailable nested wall diagnostics and undefined cutoffs serialize as JSON null instead of aborting report export.

## Intentional numerical change

The bundled tin example's undiscounted pit value stays 30,452,369.360192895. Plan NPV changes from 25,719,640.005322233 to 25,728,212.84131956 (+8,572.835997327), because whole-block capacity and cash timing are corrected. Final RF remains 0.6. Tagged cash now reconciles with planned cash with zero difference. The locked fixture records these schedule, period-surface and sensitivity changes explicitly; its assertions remain enabled.

## Dataset evidence

Orebit.id CC BY 4.0 dataset revision: `7f4cd96f0e521c16e40826aa232cbf760938d1dc`.

| Dataset | Original assay rows | Missing grade rows omitted from estimator (never converted to zero) | Derived test blocks | Native basis |
| --- | ---: | ---: | ---: | --- |
| 01-emas-epitermal | 11,526 | 103 | 1,665 | gpt; gold priced per oz |
| 02-nikel-laterit | 8,278 | 41 | 6,529 | mass_percent |
| 03-timah-placer | 5,990 | 0 | 3,402 | kgm3 |

Raw collar/survey/assay/lithology files remain unchanged. The audit helper desurveys assay midpoints using the dataset's documented generator convention, assigns nearest assayed midpoint grades/density, and writes source-row/hole IDs and distance into the fixture CSV. These are unbounded nearest-neighbour software-test fixtures, not resource estimates. They carry no resource classification. Source SHA256 values, assumptions, method and dataset revision are recorded in per-model manifests.

Topography is a linear TIN over synthetic collar elevations, exported as DXF 3DFACEs inside the collar convex hull. This is synthetic test terrain, not surveyed terrain. Clipping uses centroids/whole cells, not validated filled volumes. Economic and geotechnical inputs are explicit testing assumptions.

Both implementations run all three fixtures and independently read back native metal mass, rock mass, per-period block cash, discounted NPV and hard plant capacity. The planned cash in Excel is compared to JSON; each 11-page PDF is opened and rendered; final mining DXFs contain nonempty 3DFACE geometry.

Actual browser controls upload CSV and topography, select the native unit and sales unit, create the project, and read it back in EN/ID at 1440×900 and 390×844. Each implementation has 12 upload/create cases, plus three optimisation jobs started through the real parameter/run controls (ID desktop). Phone/EN cases exercise upload/create, not every optimisation combination. Browser JavaScript/console failures are checked. Delayed A→B config/result tests fail on the original store and pass with the guard.

## Reproduction and evidence

The environment retains `/workspace/scratch/pitopt-audit/`: dependency pins, repeatable install/start instructions, corpus builders, real-control browser harness, readback harness, native packages, source fingerprints, logs and a consolidated report. These are local audit artifacts, not files published to a public repository.

Normal developer validation: activate `.venv`, run `ruff check .` and `python -m pytest -ra`. Browser validation uses the cloud's system Chromium 154 with Playwright 1.63; browser viewport emulation does not establish native Windows/WebView2 or macOS/Safari behavior. Installed-wheel smoke validation runs in clean environments outside either checkout.

## Remaining boundaries

This establishes a controlled source development/research workflow, not operational mine-design or feasibility sign-off. Model boundary truncation, discrete slope-template approximation, domain-angle versus uniform bench geometry, shell/design reconciliation and heuristic sequencing retain their documented limitations. The best/worst sequences are heuristics, not proven global NPV bounds. Oversized blocks require explicit reblocking or a larger capacity.

The Orebit drillhole-to-block path here tests fixtures independently; it does not certify the full GeoSuite Resource export → PitOpt contract, CRS/provenance roundtrip, source-file replacement freshness, geological interpolation, reserve classification or partial-cell geometry. These need separate focused acceptance work. Native desktop/device checks and real-project geotechnical/economic calibration are unrun. No merge, deployment or production publication is claimed.

## Large-model trial

Public checkout only: the unchanged default porphyry configuration completed successfully on 75,696 clipped blocks, ten revenue factors, sensitivity and design/export enabled, with 19 scheduled periods. Wall time was 1,139.27 seconds (about 19 minutes); peak child-process RSS was 3,437,832 KiB (about 3.28 GiB). This was one trial during concurrent tests on a cloud with a four-CPU quota and approximately 33 GiB memory; it is not p50/p95 or an isolated speed comparison.

Maximum planned plant feed was 7,999,730.55 t against 8,000,000 t capacity. Total tagged-versus-planned cash difference was 2.98e-8 USD (floating-point rounding). Independent wall/cone/sequence checks reported zero violations under their documented one-block allowance. The design diagnostic still measured 45.19475° over a 50 m/three-bench span against the input 42° overall angle, and 38 pit blocks touch the model bottom. These are explicit limitations, not an operational design sign-off. The large trial was not duplicated in the private checkout.

One public browser trial copied the porphyry output directory while its calculation was still exporting, so the temporary fixture lacked the result JSON and selected the tin example instead. This was diagnosed from the actual fixture contents. With complete artifacts, the same default-English/whole-UI test passes. The fixture now requires both results JSON and surface NPZ before copying; application assertions remain unchanged.

The broken-ramp browser assertion also now waits for the actual asynchronously restored finding after reload, rather than relying on a fixed 700 ms delay. It still requires the broken bench, reason and the displayed bench number. All 13 public design/browser cases pass with complete artifacts.

## Final checks

Full suite after all porphyry artifacts were complete: **408 passed, 12 skipped**, 413.12 s. No required failure remains.

Both checkouts pass lint, dependency checks, installed-wheel CLI/UI/Host checks and the three named Orebit corpus runs. The original-HEAD control fails 34 newly added input/capacity/upload assertions; the original selection store fails all three delayed-callback/state assertions. Expected-control failures are separate from passing final checks. Install script and startup instructions are saved in the cloud draft; publication and fresh-task restoration have not been performed.


## Follow-up plan execution

Lifecycle/freshness, cached-design guards, installer repair and final acceptance added after this audit are recorded in [HANDOVER_CREDIBILITY_USABILITY.md](HANDOVER_CREDIBILITY_USABILITY.md). Counts and limitations in this file describe the earlier audit stage.
