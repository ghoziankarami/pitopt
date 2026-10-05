# PitOpt

[![CI](https://github.com/ghoziankarami/pitopt/actions/workflows/ci.yml/badge.svg)](https://github.com/ghoziankarami/pitopt/actions/workflows/ci.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

PitOpt is a local application for open-pit planning studies. It reads a block
model, applies economic and slope assumptions, and produces pit shells,
pushbacks, a mining sequence, and preliminary bench and ramp geometry.

Use the [read-only demo](https://pitopt.orebit.id) to explore synthetic examples,
or install the application to work with your own data. Local project files are
processed on your computer.

![Results for the synthetic porphyry example](docs/images/screenshot-summary.png)

## What it does

| Step | Inputs and outputs |
| --- | --- |
| Prepare data | CSV block models with configurable column mapping; optional DXF or XYZ topography. |
| Calculate shells | Maximum-closure optimisation using NetworkX preflow-push at several revenue factors. |
| Compare plans | Discounted pit-by-pit analysis, pushbacks, capacity-based scheduling, and price sensitivity. |
| Review geometry | Benches, berms, ramps, sector slope checks, and reconciliation with the selected shell. |
| Export | Excel and PDF reports, DXF surfaces, and an interactive 3D view. |

The browser interface supports English and Indonesian. A command-line interface
is included; MCP integration is optional.

## Install

Requirements: Python 3.10 or newer and Git. On Linux or WSL, Python's
`venv` package must also be installed. Windows support is through WSL 2;
native Windows is not supported.

### macOS or Linux

Check `python3 --version` first. If it is older than 3.10, install a supported
version from [python.org](https://www.python.org/downloads/).

```bash
git clone https://github.com/ghoziankarami/pitopt.git
cd pitopt
bash scripts/start_ui.sh
```

### Windows with WSL 2 / Ubuntu

Install WSL using [Microsoft's guide](https://learn.microsoft.com/en-us/windows/wsl/install).
Then run these commands in Ubuntu:

```bash
sudo apt update
sudo apt install -y git python3-venv
git clone https://github.com/ghoziankarami/pitopt.git
cd pitopt
bash scripts/start_ui.sh
```

The first launch creates `.venv`, installs dependencies, generates the synthetic
porphyry data, and runs the tin example. Setup needs an internet connection;
duration depends on your computer and connection. Open
[http://127.0.0.1:8765](http://127.0.0.1:8765) if the browser does not open.

Keep the terminal open while working. Press **Ctrl+C** to stop the server.
For later sessions, run `bash scripts/start_ui.sh` from the same folder.

Without Git, [download the source ZIP](https://github.com/ghoziankarami/pitopt/archive/refs/heads/main.zip),
extract it, and run `bash scripts/start_ui.sh` in the extracted folder.
See [installation and troubleshooting](docs/INSTALLATION.md) for other options.

## First project

In the application, choose **Manage → New project** (or **Kelola → Proyek baru**).
Upload a CSV block model and, if available, topography. Review the detected
coordinates, block dimensions, prices, costs, recoveries, and slopes before
running a calculation. Values filled by the application are assumptions.

To run the bundled tin example from a terminal:

```bash
source .venv/bin/activate
python -m pitopt validate --config projects/example_tin/project.yaml
python -m pitopt run --config projects/example_tin/project.yaml
```

Results are written under `outputs/`. Copy `projects/example_tin/` when creating
a project configuration; its YAML file documents the available settings.

## Limitations

PitOpt is a research and strategic-planning prototype. The maximum-closure
solver optimises the supplied discrete graph; that does not establish the
accuracy of the geology, slope discretisation, costs, schedule, or design.

Scheduling uses sequence heuristics. Design geometry may differ from the shell
used for economic calculations. NetworkX graphs can require substantial memory
on large models. Read the [release audit](docs/RELEASE_AUDIT.md) and
[technical limitations](docs/TECHNICAL.md#what-this-is-not) before using results
in a study. Outputs need independent mining, economic, and geotechnical review.

## Repository and documentation

| Path | Contents |
| --- | --- |
| `pitopt/core/` | Optimisation, economics, scheduling, and design calculations. |
| `pitopt/io/`, `pitopt/ui/` | Imports, exports, local server, and browser interface. |
| `projects/` | Synthetic example configurations and input data. |
| `tests/`, `benchmarks/` | Regression checks and independent solver comparisons. |
| `scripts/` | Launchers and data-generation utilities. |
| `docs/` | Installation, methodology, technical reference, and release audit. |

- [Installation](docs/INSTALLATION.md)
- [Technical reference](docs/TECHNICAL.md)
- [Calculation methodology in Indonesian](docs/METODOLOGI.md)
- [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

## License and citation

The original code is licensed under [MIT](LICENSE). Bundled fonts and MineLib
benchmark data retain their separate licences and credits in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Use [CITATION.cff](CITATION.cff) when citing the software.

## Ringkasan Bahasa Indonesia

PitOpt membantu studi awal perencanaan tambang terbuka dari model blok hingga
shell pit, urutan penambangan, dan geometri bench/ramp. Coba demo dengan data
sintetis, atau ikuti instalasi di atas untuk memakai data sendiri. Periksa semua
asumsi dan batasan; hasilnya memerlukan tinjauan teknis independen.
