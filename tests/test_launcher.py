"""Tests for cross-platform PitOpt launchers (PitOpt.bat, scripts/start_ui.sh, and `pitopt ui`)."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PITOPT_BAT = ROOT / "PitOpt.bat"
START_UI_SH = ROOT / "scripts" / "start_ui.sh"


def test_pitopt_bat_prefers_native_python_before_wsl_fallback():
    text = PITOPT_BAT.read_text(encoding="utf-8")
    venv_idx = text.index(r".venv\Scripts\python.exe")
    py_launcher_idx = text.index("py -3 -c")
    python_idx = text.index("python -c")
    wsl_idx = text.index("where wsl.exe")
    assert venv_idx < py_launcher_idx < python_idx < wsl_idx


def test_pitopt_bat_checks_port_and_supports_safe_browser_and_wsl_fallback():
    text = PITOPT_BAT.read_text(encoding="utf-8")
    assert "8765" in text
    assert "connect_ex" in text
    assert "NO_BROWSER" in text
    assert "--no-browser" in text
    assert "-m pitopt ui" in text
    assert "Ubuntu-24.04" in text


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_start_ui_sh_check_only_exits_zero():
    proc = subprocess.run(
        ["bash", str(START_UI_SH), "--check-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "check-only OK" in proc.stdout
    assert "port=8765" in proc.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_start_ui_sh_rejects_invalid_port():
    for bad_port in ("0", "70000", "abc"):
        proc = subprocess.run(
            ["bash", str(START_UI_SH), "--check-only", "--port", bad_port],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0
        assert "invalid port" in proc.stderr.lower()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_start_ui_sh_detects_busy_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    busy_port = sock.getsockname()[1]
    try:
        check_proc = subprocess.run(
            ["bash", str(START_UI_SH), "--check-only", "--port", str(busy_port)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert check_proc.returncode == 0, check_proc.stderr + check_proc.stdout
        assert f"port={busy_port} (in-use)" in check_proc.stdout

        run_proc = subprocess.run(
            ["bash", str(START_UI_SH), "--port", str(busy_port)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, "NO_BROWSER": "1"},
            check=False,
        )
        assert run_proc.returncode != 0
        assert "already in use" in run_proc.stderr.lower()
    finally:
        sock.close()


def test_python_m_pitopt_ui_help():
    proc = subprocess.run(
        [sys.executable, "-m", "pitopt", "ui", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "--port" in proc.stdout
    assert "--no-browser" in proc.stdout
    assert "--root" in proc.stdout
