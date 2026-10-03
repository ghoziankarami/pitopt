# Install PitOpt

The fastest way to try PitOpt is the [live demo](https://pitopt.orebit.id). It uses synthetic data and is read-only. To run PitOpt on your own computer, use the quick-start steps below; setup installs everything automatically the first time you launch it.

Requirements: **Python 3.10 or newer** (check with `python3 --version`) and, except for the ZIP route, **Git**. The `python3` that ships with macOS is 3.9 and is too old: install a current one from [python.org](https://www.python.org/downloads/) or with `brew install python`.

## macOS: download and click

1. [Download the latest ZIP](https://github.com/ghoziankarami/pitopt/archive/refs/heads/main.zip) and extract it.
2. Open the extracted `pitopt-main` folder and double-click **PitOpt.command**.
3. Wait a few minutes for the first-time setup (it also runs the synthetic tin example). PitOpt opens in your browser at [http://127.0.0.1:8765](http://127.0.0.1:8765).

If macOS blocks the launcher, Control-click `PitOpt.command`, choose **Open**, and confirm. Keep its Terminal window open while using PitOpt; press **Ctrl+C** to stop it.

## macOS or Linux: one terminal command

Install Python 3.10 or newer and Git, then paste this one line into Terminal:

```bash
git clone https://github.com/ghoziankarami/pitopt.git && cd pitopt && bash PitOpt.command
```

The launcher creates a local `.venv`, installs PitOpt, and opens the browser. Keep the terminal open while using the app; press **Ctrl+C** to stop it.

## Windows: one-time WSL setup, then one command

PitOpt runs on Windows through WSL 2 with Ubuntu 24.04. Install it using [Microsoft's WSL guide](https://learn.microsoft.com/en-us/windows/wsl/install), then open the Ubuntu app and paste:

```bash
sudo apt update && sudo apt install -y git python3-venv && git clone https://github.com/ghoziankarami/pitopt.git && cd pitopt && bash scripts/start_ui.sh
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) in your browser. Keep the Ubuntu terminal open while using PitOpt; press **Ctrl+C** to stop it. Native Windows is not supported.

## Start it again later

Open a terminal in the `pitopt` folder and run `bash PitOpt.command` (macOS/Linux) or `bash scripts/start_ui.sh` (WSL). Setup is skipped once it has completed.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `PitOpt needs Python 3.10 or newer` | Install a newer Python (see Requirements) and run the launcher again. |
| macOS: "cannot be opened because it is from an unidentified developer" | Control-click `PitOpt.command`, choose **Open**, confirm. |
| `Address already in use` | PitOpt is already running, or another app uses port 8765. Start on another port: `bash scripts/start_ui.sh 8770`. |
| The install was interrupted or packages are broken | Delete the `.venv` folder and launch again; setup reruns. |
| `Model too large for this machine` | The model is too large for this machine; see "Model size" in [TECHNICAL.md](TECHNICAL.md#model-size). |

Still stuck? [Open an issue](https://github.com/ghoziankarami/pitopt/issues/new/choose) with the terminal output.

## Run an example from the command line

After installing through one of the steps above, open a terminal in the `pitopt` folder and activate the environment:

```bash
source .venv/bin/activate
python -m pitopt validate --config projects/example_tin/project.yaml
python -m pitopt run --config projects/example_tin/project.yaml
```

Generated reports and surfaces are written to `outputs/`. To start the web app from an activated environment, run `python -m pitopt ui --root . --port 8765`.

## Optional development tools

```bash
python -m pip install -e ".[dev]"  # tests, lint, and packaging tools
python -m pip install -e ".[mcp]"  # optional MCP integration
```

See [project requirements](PRD.md) for input formats and [security guidance](../SECURITY.md) before exposing a local instance to a network. The included tin and porphyry projects contain synthetic data.
