"""
Refuse a run that cannot fit in memory, before it starts, with a message that says what to change.

The maximum-closure solve holds one graph edge per precedence arc. Measured on a 230,164-block porphyry model
(10.3 million arcs at 35-45 degrees) the process peaked at 9.5 GB (26 minutes for the whole run, about two
minutes per shell solve). Without this check a model that is too big for the machine ends in the kernel
killing the process — no message, no results — so the estimate is made from the block count and the slope
template alone, before any large array exists.
"""
from __future__ import annotations

import ctypes
import os
import platform
import re
import subprocess

BYTES_PER_ARC = 620          # per arc of the template upper bound (edge blocks have fewer): 9.5 GB / 15.1 M measured
BYTES_PER_BLOCK = 4_000
SAFETY = 0.85                # leave the rest for the OS, the UI server and the reports


class ModelTooLarge(ValueError):
    """The precedence graph would not fit in the memory available."""


def _macos_available_memory_bytes() -> int | None:
    """Available (free + inactive + speculative + purgeable) RAM on macOS."""
    try:
        out = subprocess.check_output(["vm_stat"], text=True, timeout=2)
        page_match = re.search(r"page size of (\d+) bytes", out)
        page_size = int(page_match.group(1)) if page_match else 4096
        pages = 0
        for key in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"):
            m = re.search(rf"^{re.escape(key)}:\s+(\d+)\.", out, re.M)
            if m:
                pages += int(m.group(1))
        if pages > 0:
            return pages * page_size
    except Exception:
        pass
    try:
        return int(os.sysconf("SC_PHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (ValueError, OSError, AttributeError):
        return None


def _windows_available_memory_bytes() -> int | None:
    """Available physical RAM on native Windows via GlobalMemoryStatusEx."""
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
            return int(stat.ullAvailPhys)
    except Exception:
        pass
    return None


def available_memory_bytes() -> int | None:
    """Available physical memory across Linux/WSL (/proc/meminfo), macOS (vm_stat), and Windows."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    sys_name = platform.system()
    if sys_name == "Darwin":
        return _macos_available_memory_bytes()
    if sys_name == "Windows":
        return _windows_available_memory_bytes()
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (ValueError, OSError, AttributeError):
        return None


def estimate_solver_bytes(n_blocks: int, arcs_upper_bound: int) -> int:
    return int(arcs_upper_bound) * BYTES_PER_ARC + int(n_blocks) * BYTES_PER_BLOCK


def check_solver_memory(n_blocks: int, arcs_upper_bound: int, available: int | None = None) -> dict:
    """Raises ModelTooLarge when the estimate exceeds what is free; returns the estimate otherwise.
    Set PITOPT_SKIP_MEMORY_CHECK=1 to run anyway (for example with swap you know is large)."""
    need = estimate_solver_bytes(n_blocks, arcs_upper_bound)
    have = available if available is not None else available_memory_bytes()
    info = {"blocks": int(n_blocks), "arcs_upper_bound": int(arcs_upper_bound), "need_gb": need / 1e9,
            "available_gb": None if have is None else have / 1e9}
    if have is not None and need > SAFETY * have and not os.environ.get("PITOPT_SKIP_MEMORY_CHECK"):
        raise ModelTooLarge(
            f"Model too large for this machine: {n_blocks:,} blocks and up to {arcs_upper_bound:,} precedence arcs "
            f"needs about {need / 1e9:.1f} GB, {have / 1e9:.1f} GB is available. "
            "Reduce it: reblock to a larger block (doubling the block size in all three directions cuts the "
            "blocks eight-fold), clip the model to the area around the deposit, or run on a machine with more memory."
        )
    return info
