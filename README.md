# PitOpt

[![CI](https://github.com/ghoziankarami/pitopt/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ghoziankarami/pitopt/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Open-pit strategic mine planning from block models to nested pit shells, pushbacks, schedules, and first-pass bench designs.** PitOpt is an open-source research prototype written in Python, with a local web UI and CSV, DXF, Excel, and PDF outputs.

> **Research use only.** An optimal solution to the encoded graph does not validate the geological model, economic assumptions, slope constraints, schedule, or resulting design. Do not use PitOpt outputs as a certified resource or reserve estimate, an approved mine plan, or an operating design. Read the [release audit](docs/RELEASE_AUDIT.md) before relying on any result.

## What it does

- Builds nested revenue-factor pit shells using a maximum-closure formulation solved with NetworkX preflow-push.
- Compares shells by discounted value and selects a final pit using configurable criteria.
- Creates pushbacks and period schedules from configured sequences.
- Produces a first-pass benched design, interactive 3D viewer, and tabular and CAD exports.
- Includes synthetic tin and porphyry examples, plus a separately licensed MineLib solver benchmark.

The closure solver is exact for the finite graph and capacities supplied to it. The broader mining workflow is approximate: slope discretisation, scheduling heuristics, and design geometry introduce assumptions and known discrepancies. The [release audit](docs/RELEASE_AUDIT.md) documents them with measured examples.

**Live demo:** [pitopt.orebit.id](https://pitopt.orebit.id) — a read-only showcase using synthetic data. It cannot run an optimisation or save project changes.

## Quick start

Requires Python 3.10 or newer. From a terminal:

```bash
git clone https://github.com/ghoziankarami/pitopt.git
cd pitopt
python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pitopt validate --config projects/example_tin/project.yaml
python -m pitopt run --config projects/example_tin/project.yaml
```

The example writes generated reports and surfaces under `outputs/` (ignored by Git). The local web app is available at `http://127.0.0.1:8765`:

```bash
python -m pitopt ui --root . --port 8765
```

For a menu of common tasks, use `make help`. In particular, `make example` runs the small tin fixture; `make porphyry` generates and runs the larger synthetic porphyry model; and `make verify` runs additional geometric checks on that result.

## Input and output

Each project is configured with a YAML file. The included [tin project configuration](projects/example_tin/project.yaml) demonstrates a block model in CSV and a topographic surface in DXF. Copy it to create a project, then point its paths and column names at your data.

Typical outputs include:

- Nested pit shells and a final pit surface (`.dxf`)
- Pushback and period-end surfaces (`.dxf`)
- A block-level results table and pit-by-pit values (`.csv`)
- Summary workbooks (`.xlsx`), PDF reports, and an interactive 3D viewer (`.html`)

Run `pitopt validate --config path/to/project.yaml` before an optimisation to check input files and derived parameters. See the [project requirements](docs/PRD.md) and [methodology](docs/METODOLOGI.md) for configuration and calculation details.

## Accuracy and limitations

Treat outputs as screening and research results, not engineering sign-off. In particular:

- The graph optimum is only as valid as the block values and precedence graph supplied to the solver.
- The schedule follows configured pushback or strip sequences; it does not find a globally optimal block-by-block schedule.
- The design geometry does not enforce every geotechnical domain constraint used by the optimiser.
- The sample porphyry design contains more material than its shell, and parts of the schedule exceed configured capacity. Its displayed NPV is therefore not a fully reconciled project valuation.
- Real projects require independent checks of data, economics, geotechnical assumptions, boundary effects, schedule, and design.

See [docs/RELEASE_AUDIT.md](docs/RELEASE_AUDIT.md) for test evidence, quantified discrepancies, and deployment limitations.

## Validation and development

Install the development dependencies with `python -m pip install -e ".[dev]"`, then run:

```bash
ruff check .
pytest
```

The tests include small-graph exhaustive checks, comparisons with independent solvers, a MineLib benchmark, pipeline regression cases, and UI/API tests. GitHub Actions runs the suite on Python 3.10 and 3.12.

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md); submit synthetic fixtures only, and include provenance and license notices for third-party material. Report security issues according to [SECURITY.md](SECURITY.md), not in a public issue.

## Privacy and hosted demos

The normal app is a local, single-user tool. It is not an authenticated multi-user service. Keep project data local; do not expose a normal server instance to the Internet. A hosted showcase must use `--demo`, a separate synthetic-only project root, TLS, and request limits. See the [security guidance](SECURITY.md).

## License

PitOpt's original code is licensed under the [MIT License](LICENSE). Bundled MineLib benchmark data and IBM Plex fonts retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
