# pitopt

Open-pit strategic mine planning. Block model (CSV) and topography (DXF)
in; out come the nested revenue-factor shells, the discounted pit-by-pit
analysis, the final pit chosen on NPV, its pushbacks, a period-by-period
mine plan, a benched pit design, price sensitivity — as an Excel report,
DXF surfaces and an interactive 3D viewer.

Every shell is solved as a maximum closure with NetworkX preflow-push,
which returns the **exact** optimum — confirmed against an unrelated
max-flow solver and by brute force (see Validation). What is approximate
is everything around it: the slope template, one overall angle, and a
schedule that follows a specified sequence rather than optimising every
block. Read "What this is not" before taking a number to a study.

**Live demo:** [pitopt.orebit.id](https://pitopt.orebit.id) — a read-only
showcase on the bundled synthetic tin project. It shows the shells,
schedule and bench design already computed; it cannot run a new
optimisation, upload data, or touch any project file (asking it to
answers 403 with a link back here). To run it on your own data, follow
Quick start below — it is the same app, running on your own machine.

## License and intended use

Original PitOpt code is MIT-licensed. Fonts (OFL-1.1) and MineLib benchmark
files (CC BY-SA-3.0) retain separate licenses; see THIRD_PARTY_NOTICES.md.
This is a strategic planning and research prototype with synthetic examples.
An optimum of the discrete graph is not a certified resource/reserve estimate,
a geotechnically approved pit, or an optimal production schedule.
See docs/RELEASE_AUDIT.md for the release audit and known numerical limitations.

## Quick start

```bash
make setup          # .venv + pip install -e . (adds the `pitopt` command)
make test           # smoke tests
make example        # small synthetic tin model        -> outputs/example_tin/
make porphyry       # synthetic porphyry (pipe orebody -> bowl pit)
make verify         # independent geometric checks on the porphyry result
make help           # every target
```

Or directly:

```bash
pitopt validate --config projects/example_tin/project.yaml
pitopt run --config projects/example_tin/project.yaml
```

Input is a block model (CSV) and a topography surface (DXF). Each run
writes to `outputs/<project>/`:

| Output | Contents |
|---|---|
| `<name>_report.xlsx` | Report workbook: Summary, Input, Parameters, Pit by Pit (RAF, with discounted best/worst NPV and the selected final pit), Pushback Selection, Pushbacks, Schedule (plan), Schedule (best case), Schedule (worst case), Sensitivity, Bench Summary, Figures — with native Excel charts |
| `<name>_report.pdf` | The same, as a paginated report with warnings and the assumptions page |
| `<name>_3d_viewer.html` | Interactive 3D: topography, the design pit shell (bowl), the final face position, each pushback and each end-of-period surface togglable, vertical-exaggeration buttons |
| `<name>_pit_shell.dxf` | **Pit shell** — the benched design bowl, not clipped by topography |
| `<name>_pit_face_position.dxf` | **Face position** — the bowl clipped by topography: the ground after the final pit is mined |
| `<name>_period_NN_end.dxf` | **Period mine plan**: face position at the end of every period (year) |
| `<name>_pushback_NN_end.dxf` | Face position at the end of every pushback |
| `<name>_shell_rfXXX.dxf` | One surface per shell, with `output.dxf_surface_all_shells: true` |
| `<name>_blocks.csv` | Block model with `in_pit` (final pit shell), `in_design`, `in_rf1_pit`, `shell`, `pushback`, `strip`, `period`, `destination`, tonnes and value per block |
| `<name>_pit_by_pit.csv` | One row per revenue factor, with discounted NPV |
| `<name>_3d_pit.png`, `_design_section.png`, `_pushback_plan.png`, `_pushback_section.png`, `_period_plan.png`, `_review.png` | Report figures, also embedded in the Excel and PDF |

Every 3D figure states its vertical exaggeration, and the pushback
section is drawn at true scale as well as exaggerated. A shallow pit on
auto-scaled axes looks like a canyon; the reader has to be told which one
they are looking at.

`make bundle` writes the whole system — code, configs, docs — into
`dist/pitopt_source_bundle.md` as a single file for handing to a new
session or reviewer. Data files are listed, not inlined.

The product requirements for the app built on this engine are in
[`docs/PRD.md`](docs/PRD.md).

Calculation rules end to end, with worked example, independent validation, audit scores and the improvement list: [`docs/METODOLOGI.md`](docs/METODOLOGI.md) (Indonesian).

## Web UI

**Windows:** double-click `PitOpt.bat` (starts the server in WSL and opens the browser; close the window to stop). Edit `DISTRO` in the file if your WSL distro is not `Ubuntu-24.04`.
**Linux/macOS:** `./PitOpt.command`. First launch creates `.venv` automatically.

```bash
make ui                      # or: pitopt ui --root . --port 8765
```

Serves a local single-user app on `127.0.0.1` (standard library HTTP server, no extra dependencies). It reads every `projects/*/*.yaml` as a scenario and the `<name>_results.json` / `_surfaces.npz` the engine writes on each run.

**Putting it behind a reverse proxy** (e.g. to host a read-only showcase, as with the live demo above): the server still binds only to `127.0.0.1`; a reverse proxy (nginx, Caddy) in front terminates TLS and forwards to it. Two flags matter here — `pitopt ui --public-host your.domain --demo`:
- `--public-host` (or `PITOPT_PUBLIC_HOST`) adds the proxy's hostname to the Host/Origin allowlist the server otherwise reserves for `127.0.0.1`/`localhost`; without it every proxied request is refused with 403.
- `--demo` (or `PITOPT_DEMO=1`) makes the instance read-only: every POST is refused — no run, upload, delete, rename or save — except the bench-design screens, which only rebuild an already-solved shell in memory and never touch disk. Point it at a project whose data you are fine publishing (the bundled `example_tin` is meant for exactly this).

**Your own data:** open **Kelola / Manage → + Proyek baru / New project**. Upload a block model (CSV) and, optionally, a topography (DXF, or CSV XYZ). Other formats (e.g. a fixed-width `.DAT`) are converted first with `pitopt reblock` on the command line. The wizard detects the coordinate columns and the block size from the centres, lists the domain and resource-class values for you to tick, and asks for prices, costs, recoveries, slope and either plant capacity or mine life. Nothing is filled in silently: what you type is marked INPUT, whatever you leave at the wizard default is marked ASUMSI on the Parameter screen. A sub-celled or mixed-size model is flagged and the wizard shows a **Reblock** step: pick the mining block size (and the parent size if the file has no size columns), the grade columns to average, and it writes `<file>_reblocked_blocks.csv` (grades weighted by mass, dominant domain/class, exact volume, partly filled edge cells carried in a `volume` column) and shows the volume reconciliation before you continue; a topography that does not overlap the model is flagged as a coordinate-system mismatch. Files are stored under `projects/<name>/data/` and never leave the machine.

**Language:** the ID | EN switch in the header changes every screen, chart label, dialog and number/date format between Indonesian and English (the choice is remembered). Text you wrote yourself — project and scenario names, notes in `provenance` — is shown as written. The English dictionary is `pitopt/ui/static/i18n/en.json`; text without an entry stays Indonesian and `tests/test_i18n.py` checks the entries.

**Managing projects:** **Kelola / Manage** in the header also holds *New project*, and renames the project or the current scenario (display names only; folders keep their names) and deletes a scenario or a whole project. A delete shows every file and its size first, warns when a `raw/` folder is included, requires typing the name to confirm, refuses while that project is running, and never removes an output folder another scenario still uses.

**Block model viewer:** *Model Blok* shows the run's block model as plan slices per bench or E–W / N–S sections, coloured by grade, value, tonnes, domain, class, destination, shell, pushback or period, with a hover read-out. The colour scale spans the whole model so slices are comparable.

**Consistency check:** `tests/test_results_consistency.py` recomputes, independently of the engine, block values from the README formula, pit/pushback/period totals from the exported block model, NPV from the period cash flows, the break-even from the sensitivity curve, and the plan-view rasters, for every run in `outputs/`. The UI shows only numbers taken from `<name>_results.json`.

Cash flow per period is allocated proportionally across bench runs (so results do not depend on input row order); the block model's `period` column is a whole-block assignment of the same sequence. Totals agree; a single period can differ, and the size of that difference is reported on the Rencana Periode screen when it exceeds 2%.

Screens: Ringkasan, Pit by Pit, Pit Final (choose a shell and re-run), Pushback, Rencana Periode, Desain, Sensitivitas, 3D & Penampang (Plotly, vertical exaggeration, section lines), Parameter (with provenance badges, live derived values, save/duplicate scenario), Jalankan (progress + log), Bandingkan, Ekspor (selective zip).

Edited parameters never overwrite a scenario: changes are saved as a new `projects/<project>/<name>.yaml`. One optimisation runs at a time. The server only reads and writes inside the project root.

## Your own project

Every project is a folder under `projects/` holding its config, its
raw data (`raw/`, git-ignored) and any prepared data (`data/`,
git-ignored). Copy `projects/example_tin/` — its `project.yaml` is the
fully commented template — point it at your files and edit the
parameters. Column names are mapped in the config, so exports from
Surpac, Datamine, Vulcan, GEMS or Leapfrog load without renaming
anything.

```yaml
block_model:
  path: data/resource_model.csv
  x_col: XC          # block CENTROID coordinates, not corners
  y_col: YC
  z_col: ZC
  grade_col: CU_PCT
  dx: 10.0
  dy: 10.0
  dz: 10.0
  density: 2.7

surface:
  path: data/topo.dxf
  format: dxf        # 3DFACE, MESH, POLYLINE contours or POINT all work
```

A CSV topography can be converted first:

```bash
python scripts/csv_surface_to_dxf.py topo.csv topo.dxf --cell 10
```

`python -m pitopt validate --config your.yaml` checks the files resolve
and prints the derived marginal cutoff grade — worth running before every
optimisation, because a cutoff that looks wrong means a parameter is wrong.

## How blocks are valued

Economics is expressed as a list of **products**. A single-metal deposit
has one; a mineral sands or polymetallic deposit has several, each with
its own price, recovery and processing cost. That separation matters
whenever products differ in value — combining zircon at 1,400/t and
ilmenite at 280/t into one "grade" would price five tonnes of the cheap
one as if it were a tonne of the dear one.

Each block is valued twice, as plant feed and as waste, and takes the
better of the two:

```
volume        = dx * dy * dz          (or the model's own volume column)
rock_tonnes   = volume * density
ore_tonnes    = rock_tonnes * mining_recovery * (1 + dilution)

per product:
  recovered_t = in_situ * mining_recovery * plant_recovery
  margin_t    = price - selling_cost - processing_cost_per_tonne(product)

value_as_ore   = SUM(recovered_t * margin_t) * (1 - royalty)
               - ore_tonnes * processing_cost_per_tonne      (per tonne of FEED)
               - mining_cost - rehabilitation_cost
value_as_waste = -(mining_cost + rehabilitation_cost)

block_value    = max(value_as_ore, value_as_waste)
```

Three things in that are easy to get wrong and are worth stating plainly:

**The `max` is what creates a cutoff grade.** A block only carries plant
cost if processing it actually pays, so barren material inside the shell
is valued as waste. Valuing every block as ore — a common shortcut —
charges processing on material that would never see the plant, which
understates the deposit and shrinks the pit.

**Mining and rehabilitation are charged on ore and waste alike**, so they
cancel out of the ore-versus-waste comparison. They set the pit *limit*
but never the cutoff.

**A product's own processing cost comes off its price, not out of the
grade.** It is charged per tonne of product, not per tonne of feed, so
it belongs in the margin. Treating it as a feed cost invents a cutoff
that is not there — in the bundled mineral sands project it produced a
break-even grade of 46% in a deposit whose richest block is 8.7%.

The cutoff therefore depends only on the feed-level processing cost:

```
cutoff = (1 + dilution) * feed_cost / (plant_recovery * margin_t * (1 - royalty))
```

Where there is no feed-level cost the cutoff is zero: any block holding a
positive-margin product is worth processing, and the pit limit is set
purely by whether revenue covers mining and rehabilitation.

Both per-tonne and per-volume cost forms exist, and are summed, because
the industry quotes both — hard rock in dollars per tonne, alluvial and
dredging operations in dollars per cubic metre. Grades likewise can be
`mass_percent`, `volume_percent`, `ppm` or `gpt`; mineral sands are
normally reported by volume.

## Strategic planning workflow

The run follows the standard nested-shell workflow (Whittle's
methodology, used the same way in Datamine NPVS, Deswik and Micromine):

```
1 Nested shells      ultimate pit re-solved over the revenue factors (RAF)
2 Pit by pit         every shell scheduled at plant capacity and discounted,
                     best case (shell by shell) and worst case (bench by bench)
3 Final pit          chosen on DISCOUNTED NPV — not on RF 1.0
4 Pushbacks          mining stages inside the final pit
5 Mine plan          pushbacks scheduled by period (specified case or strips)
6 Pit design         benched walls: pit shell (bowl) and face positions
```

**Why not RF 1.0.** The RF 1.0 shell maximises *undiscounted* cash. Its
outer shells add value only after their waste has been paid for, years
earlier; once cash is discounted they lose value, and the NPV-optimal pit
is smaller — commonly around RF 0.6–0.9. `final_pit.criterion` picks which
NPV to maximise (average of best and worst by default) and
`final_pit.tolerance` takes the smallest shell within that fraction of the
maximum, because the top of the curve is flat and the smaller pit carries
less capital and price risk for almost the same value.

**Pushbacks, periods and the mine plan.** A pushback is a *stage* — a
large, contiguous volume of the final pit worked for typically one to two
years. A period is *time* — normally a year — and the mine plan is the
period-by-period schedule: which pushbacks are active, tonnes, cash flow,
and the pit surface at the end of each period. One pushback usually spans
more than one period and consecutive pushbacks overlap; one pushback per
period is just the case where the duration is set to one period.

How many pushbacks (first one set wins):

| Setting | Rule |
|---|---|
| `count: 3` | manual: exactly that many |
| `duration_years: 2` | manual: count = mine life / duration |
| `duration_years: auto` (default) | duration = `target_duration_years` (1.5; practice is 1–2 years), lengthened if the final pit is too deep to sink through at `max_vertical_advance_m` per year (hard rock ~60–100 m/y, soft ground more); count = mine life / duration, capped at `max_pushbacks` |

The mine life itself is either an input or a result: set
`schedule.ore_capacity` and the life follows, or set `schedule.periods` and
the plant rate follows (final pit feed / periods). `schedule.period_years`
sets the length of a period for discounting.

How the pushbacks are cut (`pushbacks.method`):

- `shells` — the pushback boundaries are chosen among the shells inside
  the final pit. Every split into the required number of pushbacks is
  scheduled; splits where a pushback is under `min_tonnes` (default: one
  period of feed) or more than `max_narrow` of its area is narrower than
  `min_width` are rejected, and the best specified-case NPV among the
  rest wins. The *Pushback Selection* sheet lists every candidate.
- `strips` — for shallow, elongated deposits (mineral sands, alluvials).
  The final pit is cut into working strips `strip_width` wide advancing
  along its long axis (direction chosen for NPV), and consecutive strips
  are grouped into the pushbacks so each carries an equal share of plant
  feed — balanced tonnage between stages being the standard sizing
  criterion.

**Every sequence is slope-feasible by construction, not by luck.** The
specified case gives each block a start time *t = benches below the top +
lag × (pushback − 1)*; a slope predecessor is at least one bench higher and
in the same or an earlier pushback, so its *t* is always smaller. Strips
use an advancing face that leans back at the wall angle, *s_eff = s − z /
tan(angle)*; any predecessor inside the cone has an *s_eff* no larger than
the block below it. Both are asserted in the tests against the solver's
precedence arcs.

## Pit design: pit shell and face position

The optimiser returns a block-stepped shell. A pit is built to
geotechnical geometry — bench height, bench face angle, berm width —
whose combined effect is the overall slope:

```
overall = atan( H / (H / tan(face angle) + berm) )
```

`design:` sets the bench height and face angle; leave `berm_width` unset
and it is sized so the benches honour `slope.overall_angle_deg`, so the
optimiser and the design agree. From the optimised floor, the walls are
rebuilt on a fine grid (`design.cell`) as a benched cone, with the toe of
every wall on the edge of the optimised floor (the usual convention, so the
design always contains the shell's floor):

```
shell(x) = min over floor points p of  floor(p) + bench_profile(|x - p|)
```

That gives two different surfaces, and both are written:

- **Pit shell** (`_pit_shell.dxf`) — the excavation itself: floor and
  benched walls, *not* clipped by topography. This is the bowl.
- **Face position** (`_pit_face_position.dxf`, and every `_period_NN_end`
  and `_pushback_NN_end`) — the bowl clipped by topography, i.e. the ground
  that exists once that pit, period or pushback has been mined.

Rebuilding the walls moves material relative to the optimiser shell, so the
design is reconciled against it (Summary sheet). On a real mineral-sands
pit tested during development: 5 m benches at 45° with a 3.66 m berm give
exactly 30.0° overall, and the design moves rock +1.2%, ore +0.1%, value
−2.0% against the shell — the usual order of a design-to-shell
reconciliation. Small pits and coarse blocks reconcile
worse (the synthetic tin example: rock +15%), because the wall material the
block steps left behind is a larger share of the pit. The surface is
computed exactly with one Euclidean distance transform per floor level.

**Why a pit is not always a bowl.** The pit follows the orebody. A pipe or
massive orebody (a porphyry) gives the familiar deep cone — `make
porphyry` shows it — while a thin, flat-lying sheet like a mineral-sands
deposit gives a broad, flat-floored excavation whose only "bowl" is at the
perimeter walls. The algorithm is the same exact optimum in both cases;
the shape difference is geology. Mining engineering texts say the same:
for shallow flat-lying deposits the pit follows the orebody and is worked
by strip methods.

## Verification

`make verify` (`scripts/verify_pit.py`) checks a result independently of
the solver's own precedence template:

1. the wall angle the template actually produces, along the grid axes and
   on the diagonals;
2. every pair of columns on the pit surface against the design angle;
3. every in-pit block against its true slope cone;
4. every scheduled block against the blocks in its cone;
5. the benched design surface: no local face steeper than the bench face
   angle, no wall over several benches steeper than the overall angle.
   On the bundled tin example the steepest face is 65.00° against a 65°
   design.

It found two real defects that are now fixed: a fixed 8-bench template on
flat 10 x 10 x 1 m blocks let diagonal walls stand at 40° against a 30°
design (the template is now sized from the block shape — `pitopt validate`
prints the achieved angle), and Inferred blocks were deleted from the
model rather than kept as waste, so the pit could strip them for free.

`make cross-check` (`scripts/cross_check_solver.py`) re-solves the same
graph with Boykov-Kolmogorov, a max-flow algorithm sharing no code with
preflow-push, and brute-forces tiny models where every closed set can be
enumerated. On the bundled tin example (1,800 blocks, 33,265 arcs) both
solvers return the same 1,165 blocks to the cent.

## Pit-by-pit table (bundled tin example)

Every shell is valued at the planning price and scheduled at plant
capacity, best case and worst case, then discounted:

```
  RF    Rock Mt   Value (undisc.)    NPV best   NPV worst   NPV average
 0.50     0.87       30,306,647    25,761,107  25,443,833    25,602,470
 0.60     0.89       30,452,369    25,870,591  25,543,967    25,707,279   <- final pit
 0.70     0.95       30,611,998    25,990,523  25,644,424    25,817,473
 0.80     1.02       30,750,741    26,094,762  25,729,929    25,912,346
 0.90     1.03       30,754,838    26,097,840  25,732,668    25,915,254
 1.00     1.05       30,764,228    26,104,895  25,737,695    25,921,295   <- undiscounted & average NPV peak
```

Undiscounted value peaks at RF 1.00 by construction. Worst-case NPV peaks
at RF 0.94 and average at RF 0.96; the final pit is the smallest shell
within 1% of that peak — RF 0.94 moves 20% less rock than RF 1.00 for 1.0%
less average NPV than the peak.

## Slope precedence

Precedence is the usual fixed cone template on a regular block model:
block b's predecessors are the blocks above whose horizontal offset is
within `levels_above * dz / tan(slope_angle)`.

Two details make it usable at scale:

- **The template is reduced.** Because the cone radius grows linearly
  with level, most higher-level offsets are sums of lower ones and are
  already enforced transitively. Keeping only irreducible offsets cuts a
  636-offset cone to 29 with an identical closure — a 22x reduction in
  arcs. The caveat: a transitive chain needs its intermediate block to
  exist, so where the model is clipped against steep topography one path
  can be left unconstrained at the crest edge. Pass
  `reduce_template=False` to `build_precedence` if crest position has to
  be exact on rugged ground.
- **Arc generation is vectorised** over the grid rather than looping per
  block, which is the difference between seconds and hours at 10^5+ blocks.

Per-domain angles are supported via `slope.domain_angles` plus a
`domain_col` in the block model, keyed on the block's own domain.

## Applicability

The algorithm is commodity-agnostic: every step works on per-block
economic value and slope geometry. What differs between commodities is
how a block is valued, and that is configuration.

| Deposit / commodity | Status | How |
|---|---|---|
| Base metals (Cu, Zn, Pb, Ni sulphide), tin | ✅ | `mass_percent`, price per t or per lb |
| Precious metals (Au, Ag) | ✅ | `gpt`, `price_unit: oz` |
| Polymetallic, co- and by-products | ✅ | several `products`, each with its own price, recovery and cost |
| Mineral sands, alluvials | ✅ | `volume_percent`, costs per m3, `pushbacks.method: strips` |
| Iron ore, bauxite, manganese, Ni laterite | ⚠️ | one price per tonne of product; quality-dependent pricing and blending to spec are not modelled |
| Coal | ⚠️ | product = coal tonnes, overburden/interburden = waste, strips; calorific-value pricing and quality blending are not modelled |
| Oxide + sulphide gold (heap leach vs mill) | ⚠️ | one process destination per project |
| Underground | ❌ | open pit only |
| Rotated block models | ❌ | rotate to an axis-aligned grid first |
| More than ~500k blocks | ❌ | in-memory `networkx` limit; swap the solver for MineFlow |

Data: CSV with any column names (mapped in the config), self-describing
fixed-width `.DAT` (widths read from its own header), sub-celled or finely
estimated models via `pitopt reblock`, topography as DXF, CSV XYZ, or the
top of the model.

## Preparing a model: `pitopt reblock`

Resource models rarely run as delivered. `pitopt reblock` regularises any
sub-celled or finely estimated model (CSV or `.DAT`) onto mining blocks:

```bash
pitopt reblock "raw/model.DAT" --out data --name mine --size 10 10 5 \
    --x EAST --y NORTH --z RL --size-cols _EAST _NORTH _RL \
    --grades CU AU --categories DOMAIN CLASS --normalise CLASS '[0-9]+$'
```

- The target grid is anchored on the parent-block grid. Anchoring on the
  outermost sub-cell can put the grid half a parent block out of step and
  double-count volume; any cell that ends up over-full aborts the run.
- Grades are averaged by volume, or by mass when `--density` is given.
- Categorical fields take the value holding the most volume in the cell;
  `--normalise` strips a pattern first so that sub-divided labels
  (TERTUNJUK1, TERTUNJUK2) count as one category.
- Volume is conserved exactly, and source volume is tabulated by the
  categories for reconciliation against the published resource.
- A top-of-model topography DXF is written alongside, for models whose
  own topography file is unusable.

## Bundled projects and data

| Folder | What it is |
|---|---|
| `projects/example_tin/` | Small synthetic tin model + DXF topography; `project.yaml` is the commented template. Runs in seconds. |
| `projects/porphyry_synthetic/` | Synthetic porphyry copper deposit under rolling topography (`make porphyry` generates it) — the pipe-shaped case, giving a deep bowl pit. |
| `benchmarks/minelib_zuck_small/` | A published MineLib benchmark with its own precedence graph — validates the solver alone. |

## Model size

The maximum-closure solve keeps one graph edge per precedence arc, so memory grows with blocks x arcs per block (steeper cones and finer blocks mean more arcs). Measured on the synthetic porphyry at 230,164 blocks (10.3 million arcs at 35-45 degrees, 10 shells, 20 periods, all outputs): 26 minutes and a peak of 9.5 GB on an 8-core, 9 GB machine (it completed, with the operating system swapping); verification 0/0/0. A run is therefore checked before it starts (`pitopt/core/limits.py`): if the estimate does not fit in the memory available, it stops with the numbers and what to change, instead of being killed by the operating system. Ways to fit a bigger deposit: reblock to a larger mining block (doubling the size in all three directions cuts the blocks eight-fold), clip the model to the area around the deposit, or use a machine with more memory. `PITOPT_SKIP_MEMORY_CHECK=1` overrides the check.

## Layout

```
pitopt/                    the package (pip install -e .)
  cli.py                   pitopt run | validate | reblock | ui
  config.py                typed project config, YAML loader, validation
  pipeline.py              load -> shells -> pit by pit -> final pit -> pushbacks -> schedule -> design -> verify -> outputs
  mcp_server.py            MCP server (python -m pitopt.mcp_server)
  core/                    the algorithms, no file I/O
    economics.py           block valuation, destination, marginal cutoff, price units, depth cost
    precedence.py          slope cone template, vectorised arcs, achieved-angle check
    solver.py              preflow-push maximum closure
    shells.py              nested revenue-factor shells
    planning.py            discounted pit by pit, final pit, pushback selection
    schedule.py            specified / strip / best / worst sequences, period filling, NPV
    design.py              bench geometry, pit shell (bowl), face position, reconciliation
    sensitivity.py         fixed-pit price sensitivity, break-even
    pitsurface.py          block-stepped surfaces, depth, closure check
    reblock.py             regularise sub-celled / fine models
    verify.py              independent wall / cone / schedule / design checks
  io/                      file formats in and out
    blockmodel.py          block model CSV with column mapping
    datfile.py             self-describing fixed-width .DAT reader (used by reblock)
    dxf.py                 DXF surface read / write
    excel.py, pdf.py       reports
    viz.py, plot.py        figures, interactive 3D viewer
    results.py             <name>_results.json — the single source the UI reads
    console.py             console tables
  ui/                      local web app (stdlib HTTP server + vanilla ES modules, no build step)
    server.py              JSON API, job runner, project management, block slices
    onboard.py             upload inspection, column guessing, project creation
    static/                index.html, css/, js/ (views/ per screen), i18n/en.json, fonts/
projects/                  one folder per project: project.yaml (+ scenario yamls), data/, raw/
benchmarks/                solver validation data (MineLib)
scripts/                   make_synthetic_deposit.py, csv_surface_to_dxf.py   (data)
                           verify_pit.py, cross_check_solver.py, run_minelib.py (validation)
                           bundle_source.py, start_ui.sh                       (tooling)
tests/                     pytest: engine, onboarding, UI server, and independent consistency
                           checks of results.json / Excel / PDF / DXF / CSV against each other
docs/                      PRD.md, claude_design_prompt.md, design/ (UI prototype from Claude Design)
PitOpt.bat, PitOpt.command double-click launchers for the UI
.github/workflows/ci.yml   ruff + pytest + example run
outputs/, dist/            generated, git-ignored
```

Development: `make setup` (venv + editable install with test/dev extras), `make check` (ruff + pytest).

## MCP server

```bash
python -m pitopt.mcp_server
```

```json
{
  "mcpServers": {
    "pit-optimizer": {
      "command": "/absolute/path/to/pit-optimization-mcp/.venv/bin/python",
      "args": ["-m", "pitopt.mcp_server"]
    }
  }
}
```

Tools: `load_project`, `set_product_price`, `set_costs`, `set_slope`,
`set_revenue_factors`, `run_pit_optimization`, `get_pit_report`,
`get_bench_summary`.

## Validation

Correctness here is not assumed, because a wrong sign or a reversed cut
convention produces an *inverted* pit with no error message.

- `tests/test_pipeline_smoke.py` asserts pit behaviour rather than fixed
  numbers: cone shape (wider at surface than at depth), destination
  assignment either side of the cutoff, shell nesting, strip ratio
  monotonicity, and that value peaks at RF 1.0.
- `scripts/run_minelib.py` solves a published MineLib instance
  (`zuck_small`, a real deposit with its own precedence graph), bypassing
  valuation and slope entirely so only the closure solve is exercised.
  The pit value comes out above the take-everything value, which is only a necessary
  sanity check; it does not prove optimality.
- `scripts/cross_check_solver.py` solves the same graph with an unrelated
  max-flow algorithm (Boykov-Kolmogorov) and brute-forces small models;
  the pits are identical, block for block.
- `scripts/verify_pit.py` checks walls, true slope cones and the schedule
  order geometrically, without using the solver's template.
- The tests also assert that the specified and strip sequences never mine
  a block before one of its slope predecessors.

## What this is not

- **Not a block-level NPV-optimising scheduler.** The plan schedule fills
  periods to capacity along a specified pushback or strip sequence, and
  pushback selection searches over shell boundaries — but individual
  blocks are not re-sequenced by MILP, and ramps, haul distances and
  equipment are not modelled. Best and worst case bracket the plan.
- **Design is automated, not detailed.** Walls are benched to the given
  bench height, face angle and berm, but there are no ramps, no
  azimuth-dependent slopes, and the design uses one overall geometry even
  where the optimiser used per-domain angles. It is a first-pass design to
  reconcile against, not a replacement for detailed design and
  geotechnical review.
- **One destination.** Mill or waste. No stockpiles, no multiple process
  routes, no blending.
- **No grade uncertainty.** Single estimated model, deterministic. Grade
  risk needs conditional simulation across multiple realisations.
- **Prototype scale.** The graph is held in memory via `networkx`, fine
  into the low hundreds of thousands of blocks. For multi-million block
  models swap `core/solver.py` for [MineFlow](
  https://github.com/MineFlowCSM/MineFlow) (C++, implicit precedence,
  16M blocks in ~9s) — everything upstream still applies.
- **Costs are flat.** No haulage-distance or depth-dependent mining cost,
  which in a deep pit matters.

For a public demo, set `PITOPT_DEFAULT_PROJECT=porphyry_synthetic` to open the
porphyry example on every initial visit, including browsers with a saved selection.
The default is used only in demo mode and only when that project has results.
Generated inputs (`projects/porphyry_synthetic/data/`) and results (`outputs/porphyry/`)
are git-ignored: deploying the repository alone does not deploy the porphyry demo.
Generate and solve it with `make porphyry` on a machine with sufficient memory,
then copy both directories to the server before enabling the default.
