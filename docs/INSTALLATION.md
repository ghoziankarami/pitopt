# Install PitOpt

The fastest way to try PitOpt is the [live demo](https://pitopt.orebit.id). It uses synthetic data and is read-only. To run PitOpt on your own computer, use the quick-start steps below; setup installs everything automatically the first time you launch it.

## macOS: download and click

1. [Download the latest ZIP](https://github.com/ghoziankarami/pitopt/archive/refs/heads/main.zip) and extract it.
2. Open the extracted `pitopt-main` folder and double-click **PitOpt.command**.
3. Wait a few minutes for the first-time setup. PitOpt opens in your browser at [http://127.0.0.1:8765](http://127.0.0.1:8765).

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
