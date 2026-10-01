"""
A run writes into a staging directory and is promoted only when it finishes.

A run that is cancelled or fails part way must leave the previous result
exactly as it was. Writing straight into the results folder cannot promise
that: the results file and the block table are written at different times, so
a run stopped between them leaves a folder that disagrees with itself (the
block table of the new run beside the results document of the old one).

Promotion moves the new files over the old one by one, each an atomic
rename, and the results document last, because that is the file the UI keys
off. Files of the old run that the new run did not write are removed after.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def staging_dir(final: Path, token: str) -> Path:
    return final.parent / f".{final.name}.staging-{token}"


def promote(staging: Path, final: Path, name: str, directory: str) -> None:
    """Move a finished run from `staging` into `final`. `directory` is the value the results document should
    record for its output folder (it recorded the staging path while the run was in progress)."""
    final.mkdir(parents=True, exist_ok=True)
    results = staging / f"{name}_results.json"
    if results.exists():
        doc = json.loads(results.read_text())
        doc.get("params", {}).get("output", {})["directory"] = directory
        results.write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False))

    new = sorted(staging.iterdir(), key=lambda f: f.name == results.name)      # the results document goes last
    for entry in new:
        os.replace(entry, final / entry.name)
    written = {entry.name for entry in new}
    for stale in final.glob(f"{name}_*"):
        if stale.name not in written and stale.is_file():
            stale.unlink()
    shutil.rmtree(staging, ignore_errors=True)


def discard(staging: Path) -> None:
    shutil.rmtree(staging, ignore_errors=True)
