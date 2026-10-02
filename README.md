# PitOpt

[![CI](https://github.com/ghoziankarami/pitopt/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ghoziankarami/pitopt/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

PitOpt is an open-source Python application for **strategic open-pit mine planning**. It turns block models and topographic surfaces into nested pit shells, pushbacks, period schedules, and first-pass bench designs, with a local web interface and CSV, DXF, Excel, and PDF outputs.

## What it does

- Builds nested revenue-factor pit shells using a maximum-closure formulation solved with NetworkX preflow-push.
- Compares shells by discounted value and selects a final pit using configurable criteria.
- Creates pushbacks and period schedules from configured sequences.
- Produces a first-pass benched design, interactive 3D viewer, and tabular and CAD exports.
- Includes synthetic tin and porphyry examples, plus a separately licensed MineLib solver benchmark.

PitOpt solves the maximum-closure problem exactly for the graph and block values supplied to it. Independent solver comparisons and exhaustive small-graph tests are included in the repository. The mining results also depend on the quality of the input model and the assumptions described under [scope and limitations](#scope-and-limitations).

**Live demo:** [pitopt.orebit.id](https://pitopt.orebit.id) — a read-only showcase using synthetic data. It cannot run an optimisation or save project changes.

## Install and run

PitOpt requires **Python 3.10 or newer**. It runs on macOS and Linux; on Windows, use **WSL 2 with Ubuntu 24.04**. Native Windows is not currently supported. See the detailed [installation guide](docs/INSTALLATION.md) for first-run setup and troubleshooting.

### Start the local web app

Clone or download this repository, then run the launcher for your system:

```bash
git clone https://github.com/ghoziankarami/pitopt.git
cd pitopt
bash PitOpt.command          # macOS or Linux
```

On first launch, PitOpt creates a local `.venv` and installs its dependencies; this can take a few minutes and requires an internet connection. The launcher opens the app at [http://127.0.0.1:8765](http://127.0.0.1:8765). Keep the terminal window open while using PitOpt; press **Ctrl+C** there to stop it.

On Windows, install WSL 2 and the **Ubuntu-24.04** distribution, then run `PitOpt.bat` from the repository folder. Alternatively, start it from an Ubuntu WSL terminal with `bash scripts/start_ui.sh`.

### Run the synthetic example from the command line

After cloning the repository, create an environment and install PitOpt:

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS, Linux, or WSL
python -m pip install --upgrade pip
python -m pip install -e .
python -m pitopt validate --config projects/example_tin/project.yaml
python -m pitopt run --config projects/example_tin/project.yaml
```

The example writes reports and surfaces under `outputs/` (ignored by Git). To use the local web app after this setup, run `python -m pitopt ui --root . --port 8765`, then open [http://127.0.0.1:8765](http://127.0.0.1:8765). The app runs only on your computer by default.

For development and tests, install `python -m pip install -e ".[dev]"`. For the optional MCP integration, use `python -m pip install -e ".[mcp]"`. `make setup` installs both. Run `make help` for other tasks; `make example` runs the small tin fixture, `make porphyry` creates and runs the larger synthetic porphyry example, and `make verify` checks its geometry.

## Input and output

Each project is configured with a YAML file. The included [tin project configuration](projects/example_tin/project.yaml) demonstrates a block model in CSV and a topographic surface in DXF. Copy it to create a project, then point its paths and column names at your data.

Typical outputs include:

- Nested pit shells and a final pit surface (`.dxf`)
- Pushback and period-end surfaces (`.dxf`)
- A block-level results table and pit-by-pit values (`.csv`)
- Summary workbooks (`.xlsx`), PDF reports, and an interactive 3D viewer (`.html`)

Run `pitopt validate --config path/to/project.yaml` before an optimisation to check input files and derived parameters. See the [project requirements](docs/PRD.md) and [methodology](docs/METODOLOGI.md) for configuration and calculation details.

## Scope and limitations

PitOpt covers strategic pit optimisation, sequence-based scheduling, and first-pass bench design. It provides a transparent, reproducible workflow for evaluating assumptions and comparing scenarios.

- **Optimisation:** the maximum-closure solver returns the optimum for the encoded graph. Geological interpretation, block values, and slope precedence are determined by the supplied model and configuration.
- **Scheduling:** periods follow configured pushback or strip sequences. PitOpt does not solve a globally optimal block-by-block production schedule.
- **Geotechnical design:** the generated bench geometry is a first-pass design. Domain-specific slope constraints, detailed ramps, and geotechnical sign-off require separate engineering work.
- **Reconciliation:** the included porphyry example demonstrates why shell, design, schedule, and NPV must be reconciled. Its design contains more material than its shell, and some schedule periods exceed configured capacity.

PitOpt does not estimate or certify mineral resources or reserves, approve a mine plan, or replace operational and geotechnical review. The [release audit](docs/RELEASE_AUDIT.md) provides test evidence and quantified limitations.

## Validation and development

Install the development dependencies with `python -m pip install -e ".[dev]"`, then run:

```bash
ruff check .
pytest
```

The tests include small-graph exhaustive checks, comparisons with independent solvers, a MineLib benchmark, pipeline regression cases, and UI/API tests. GitHub Actions runs the suite on Python 3.10 and 3.12.

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md); submit synthetic fixtures only, and include provenance and license notices for third-party material. Report security issues according to [SECURITY.md](SECURITY.md), not in a public issue.

## FAQ

### Is PitOpt open source?

Yes. PitOpt's original code is available under the MIT License. The included MineLib benchmark data and IBM Plex fonts retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### Is the calculated pit optimum exact?

The maximum-closure solver finds the exact optimum for the encoded graph and capacities. The result's relevance to a mine plan depends on block values, precedence constraints, geological inputs, and economic assumptions.

### Can I use the results for mine approval or operations?

PitOpt is designed for strategic analysis and scenario comparison. Resource/reserve reporting, geotechnical approval, detailed design, and operational scheduling require qualified independent work.

### Does the online demo accept my data?

No. The [live demo](https://pitopt.orebit.id) uses synthetic data and is read-only. Run PitOpt locally to work with your own models.

## Privacy and hosted demos

The normal app is a local, single-user tool. It is not an authenticated multi-user service. Keep project data local; do not expose a normal server instance to the Internet. A hosted showcase must use `--demo`, a separate synthetic-only project root, TLS, and request limits. See the [security guidance](SECURITY.md).

## License

PitOpt's original code is licensed under the [MIT License](LICENSE). Bundled MineLib benchmark data and IBM Plex fonts retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
