# Install PitOpt

Choose the path that matches what you want to do:

- **Try the interface without installing:** open the [PitOpt live demo](https://pitopt.orebit.id). It uses synthetic data, is read-only, and cannot run an optimisation or save changes.
- **Run PitOpt on your computer:** follow the local setup below. The included tin and porphyry projects are synthetic examples.

## Requirements

- Python **3.10 or newer**
- Internet access for the first dependency installation
- macOS or Linux; Windows users need **WSL 2 with Ubuntu 24.04**. Native Windows is not supported.

Check your Python version before installing:

```bash
python3 --version
```

## Fastest local setup: launch the web app

Clone the repository and start the included launcher:

```bash
git clone https://github.com/ghoziankarami/pitopt.git
cd pitopt
bash PitOpt.command
```

On first launch, PitOpt creates `.venv` and installs the application and its dependencies. Allow a few minutes for this step. The launcher then starts the local server and opens `http://127.0.0.1:8765` in your browser. Keep the terminal window open while the app is running; press **Ctrl+C** to stop it.

### Windows with WSL 2

If needed, install WSL by following [Microsoft's WSL setup guide](https://learn.microsoft.com/en-us/windows/wsl/install), choosing Ubuntu 24.04. Open Ubuntu once to finish its first-run setup, then install Git and Python's virtual-environment support:

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip
```

Clone the repository inside Ubuntu:

```bash
git clone https://github.com/ghoziankarami/pitopt.git
cd pitopt
```

The simplest option is to start it in that Ubuntu terminal as shown below. If you prefer the Windows launcher, open this WSL folder in File Explorer using `\\wsl.localhost\Ubuntu-24.04\home\<your-linux-user>\pitopt`, then run `PitOpt.bat`. The launcher starts PitOpt inside WSL and opens the local UI in your browser.

Or start it directly in an Ubuntu WSL terminal:

```bash
cd ~/pitopt
bash scripts/start_ui.sh
```

The included Windows launcher targets the WSL distribution named `Ubuntu-24.04`. If yours has another name, edit `DISTRO` near the top of `PitOpt.bat`, or use the WSL terminal command above.

## Manual setup: command line or web app

These commands work in macOS, Linux, and Ubuntu on WSL:

```bash
git clone https://github.com/ghoziankarami/pitopt.git
cd pitopt
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

If your Linux installation does not include the `venv` module, install the matching system package first (for Ubuntu, `sudo apt install python3-venv`). Then repeat the environment-creation command.

Confirm that the CLI is available and validate the bundled synthetic tin project:

```bash
python -m pitopt --help
python -m pitopt validate --config projects/example_tin/project.yaml
```

Run the example optimisation:

```bash
python -m pitopt run --config projects/example_tin/project.yaml
```

Generated reports and surfaces are written under `outputs/`, which is excluded from Git. To start the web interface instead, run:

```bash
python -m pitopt ui --root . --port 8765
```

Then open [http://127.0.0.1:8765](http://127.0.0.1:8765). Stop the server with **Ctrl+C** in the terminal.

## Optional dependencies

The standard install above is enough for the CLI and local web interface.

```bash
python -m pip install -e ".[dev]"  # tests, lint, and packaging tools
python -m pip install -e ".[mcp]"  # optional MCP server integration
```

`make setup` installs both optional groups. Run `make help` to see available project tasks.

## Troubleshooting

- **`python3: command not found` or Python is older than 3.10:** install Python 3.10+ for your operating system and rerun the version check.
- **`No module named venv`:** on Ubuntu/WSL, install `python3-venv` for the active Python version, then recreate `.venv`.
- **The browser page does not open:** open `http://127.0.0.1:8765` manually and check that the launcher terminal is still running.
- **Port 8765 is already in use:** stop the other process or start the server on another port, for example `python -m pitopt ui --root . --port 8766`.
- **A dependency installation fails:** check the Python version and internet connection, then activate `.venv` and retry `python -m pip install -e .`.

For project-file formats and input requirements, see [README: Input and output](../README.md#input-and-output), the [project requirements](PRD.md), and the [methodology](METODOLOGI.md). Keep project data local; read the [security guidance](../SECURITY.md) before exposing any instance to a network.
