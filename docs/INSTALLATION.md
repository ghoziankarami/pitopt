# Install PitOpt

Try the [live workspace](https://pitopt.orebit.id/demo) first: it uses a synthetic case study and is read-only. To run PitOpt on your own computer with your own block models, follow the steps for your platform. Setup installs everything the first time you launch it.

**Requirements**

- **Python 3.10 or newer** — check with `python3 --version` (Windows: `py -3 --version`). The Python that ships with macOS is too old; install a current one from [python.org](https://www.python.org/downloads/) or with `brew install python`.
- **Git** — or use the ZIP download described below.

## Windows (native)

1. Install Python 3.10+ from [python.org](https://www.python.org/downloads/). Tick **Add python.exe to PATH** during setup.
2. Install [Git for Windows](https://git-scm.com/download/win), or download the ZIP.
3. Open PowerShell or Command Prompt in the folder where you want PitOpt and run:

   ```bat
   git clone https://github.com/ghoziankarami/pitopt.git && cd pitopt && PitOpt.bat
   ```

   Or double-click `PitOpt.bat` in the extracted `pitopt` folder.

`PitOpt.bat` creates a local `.venv`, installs PitOpt, runs the bundled examples, and opens <http://127.0.0.1:8765>. Keep the window open while you work; press **Ctrl+C** to stop. Check the launcher without starting the app: `PitOpt.bat --check-only`.

## macOS

1. [Download the ZIP](https://github.com/ghoziankarami/pitopt/archive/refs/heads/main.zip) and extract it, or clone the repository.
2. In Terminal, from the `pitopt` folder, run:

   ```bash
   bash PitOpt.command
   ```

   Or double-click **PitOpt.command** in Finder.

If macOS blocks the launcher, Control-click `PitOpt.command`, choose **Open**, and confirm. Keep the Terminal window open while using PitOpt; press **Ctrl+C** to stop.

## Linux

1. Install Python 3.10+, Git, and the `venv` package (on Debian/Ubuntu: `sudo apt install -y git python3-venv`).
2. From the folder where you want PitOpt, run:

   ```bash
   git clone https://github.com/ghoziankarami/pitopt.git && cd pitopt && bash scripts/start_ui.sh
   ```

The browser opens at <http://127.0.0.1:8765>. Press **Ctrl+C** to stop. Use `bash scripts/start_ui.sh --check-only` to verify the setup without starting the app.

## Start it again later

Open a terminal in the `pitopt` folder and run the launcher for your platform (`PitOpt.bat`, `bash PitOpt.command`, or `bash scripts/start_ui.sh`). Setup is skipped once it has completed.

## Choose another port

- Windows: `set PITOPT_PORT=8770` before `PitOpt.bat`
- macOS / Linux: `PITOPT_PORT=8770 bash PitOpt.command` or `bash scripts/start_ui.sh 8770`

## Troubleshooting

| Symptom | Fix |
|---|---|
| `PitOpt needs Python 3.10 or newer` | Install a newer Python (see Requirements) and run the launcher again. |
| macOS: "cannot be opened because it is from an unidentified developer" | Control-click `PitOpt.command`, choose **Open**, confirm. |
| Windows: `python` opens the Microsoft Store | Install Python from python.org and tick **Add python.exe to PATH**, or use the `py` launcher. |
| `Address already in use` | Another instance is running, or another app uses port 8765. Choose another port (above). |
| Install was interrupted or packages are broken | Delete the `.venv` folder and launch again; setup reruns. |
| `Model too large for this machine` | The model exceeds this machine's memory budget; see "Model size" in [TECHNICAL.md](TECHNICAL.md#model-size). |

Still stuck? [Open an issue](https://github.com/ghoziankarami/pitopt/issues/new/choose) and include the launcher output.

## Run an example from the command line

With the environment activated (`source .venv/bin/activate`, or `.venv\Scripts\activate` on Windows):

```bash
python -m pitopt validate --config projects/example_tin/project.yaml
python -m pitopt run --config projects/example_tin/project.yaml
```

Reports and surfaces are written to `outputs/`. To start the web app from an activated environment: `python -m pitopt ui --root . --port 8765`.

## Optional development tools

```bash
python -m pip install -e ".[dev]"   # tests, lint, packaging tools
python -m pip install -e ".[mcp]"   # optional MCP integration for AI assistants
```

Before exposing a local instance to a network, read [SECURITY.md](../SECURITY.md). The bundled `example_tin` and `porphyry_synthetic` projects contain synthetic data only.

## Reproducible dependency profile

For the dependency versions tested on Linux with Python 3.12:

```bash
PITOPT_CONSTRAINTS="$PWD/requirements-tested-py312.txt" NO_BROWSER=1 bash scripts/start_ui.sh
```

Other Python versions and operating systems need their own acceptance checks; these pins are not a universal platform certification. A saved run without a fingerprint stays readable as unverified; rerun it before exporting or using derived designs.
