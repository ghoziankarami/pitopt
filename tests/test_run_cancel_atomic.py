"""
Cancelling a run and the promise behind it (PRD F-RUN-4): stop without
damaging the previous result.

A cancelled or failed run must leave the results folder exactly as it was,
and a finished one must replace it whole. The failure this guards against is
a folder that disagrees with itself: the block table of a new run beside the
results document of the old one, which is what a run stopped between two
writes leaves behind.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
import yaml

from pitopt.core.cancel import Cancelled, CancelToken
from pitopt.ui.server import App
from pitopt.ui.staging import promote, staging_dir

ROOT = Path(__file__).resolve().parents[1]


def test_a_token_raises_only_once_cancelled():
    token = CancelToken()
    token.check()
    token.cancel()
    assert token.cancelled
    with pytest.raises(Cancelled):
        token.check()


def test_promotion_replaces_the_old_run_whole_and_puts_the_results_document_last(tmp_path):
    final, stage = tmp_path / "out", tmp_path / "stage"
    final.mkdir()
    stage.mkdir()
    (final / "pit_results.json").write_text("OLD")
    (final / "pit_blocks.csv").write_text("OLD")
    (final / "pit_only_in_old_run.dxf").write_text("OLD")
    (final / "someone_elses_file.txt").write_text("KEEP")
    (stage / "pit_blocks.csv").write_text("NEW")
    (stage / "pit_results.json").write_text(json.dumps({"params": {"output": {"directory": str(stage)}}}))

    promote(stage, final, "pit", "outputs/real")

    assert (final / "pit_blocks.csv").read_text() == "NEW"
    assert json.loads((final / "pit_results.json").read_text())["params"]["output"]["directory"] == "outputs/real"
    assert not (final / "pit_only_in_old_run.dxf").exists()          # a file of the old run the new one did not write
    assert (final / "someone_elses_file.txt").read_text() == "KEEP"   # anything not named after the run is not ours
    assert not stage.exists()


def test_staging_directories_sit_beside_the_result_and_are_hidden(tmp_path):
    stage = staging_dir(tmp_path / "outputs" / "base", "abc123")
    assert stage.parent == tmp_path / "outputs" and stage.name.startswith(".base.staging-")


@pytest.fixture()
def sandbox(tmp_path):
    """The bundled example in a temporary project root, with the slow outputs off, and a previous result."""
    project = tmp_path / "projects" / "example_tin"
    shutil.copytree(ROOT / "projects/example_tin", project, ignore=shutil.ignore_patterns("outputs"))
    raw = yaml.safe_load((project / "project.yaml").read_text())
    raw["output"] = {"directory": "outputs", "write_excel": False, "write_pdf": False, "write_3d": False,
                     "write_plot": False, "write_dxf": False}
    (project / "project.yaml").write_text(yaml.safe_dump(raw))
    out = project / "outputs"
    out.mkdir()
    name = raw["project"]["name"]
    (out / f"{name}_results.json").write_text("PREVIOUS RESULT")
    (out / f"{name}_blocks.csv").write_text("PREVIOUS BLOCKS")
    return App(tmp_path), out, name


def _wait(job, timeout=180):
    end = time.time() + timeout
    while job.finished is None and time.time() < end:          # finished is set last, after the log is written
        time.sleep(0.05)
    return job.status


def test_a_cancelled_run_leaves_the_previous_result_untouched(sandbox):
    app, out, name = sandbox
    job = app.start_run("example_tin", "project", {}, None)
    job.cancel.cancel()
    assert _wait(job) == "cancelled"
    assert (out / f"{name}_results.json").read_text() == "PREVIOUS RESULT"
    assert (out / f"{name}_blocks.csv").read_text() == "PREVIOUS BLOCKS"
    assert not [p for p in out.iterdir() if p.name.startswith(".")]     # no staging left behind
    assert "dibatalkan" in (out / f"{name}_run_cancelled.log").read_text()
    assert app.cancel_job(job.id).status == "cancelled"                 # cancelling again is harmless


def test_a_finished_run_replaces_the_result_whole_and_records_the_real_folder(sandbox):
    app, out, name = sandbox
    job = app.start_run("example_tin", "project", {}, None)
    assert _wait(job) == "done", job.error
    doc = json.loads((out / f"{name}_results.json").read_text())
    assert doc["meta"]["blocks"] > 0 and (out / f"{name}_blocks.csv").read_text().startswith("x,y,z")
    assert ".staging-" not in json.dumps(doc["params"]["output"])
    assert not [p for p in out.iterdir() if p.name.startswith(".")]


def test_a_failed_run_also_leaves_the_previous_result_untouched(sandbox):
    app, out, name = sandbox
    yml = out.parent / "project.yaml"
    raw = yaml.safe_load(yml.read_text())
    raw["block_model"]["path"] = "does_not_exist.csv"
    yml.write_text(yaml.safe_dump(raw))
    job = app.start_run("example_tin", "project", {}, None)
    assert _wait(job) == "error"
    assert (out / f"{name}_results.json").read_text() == "PREVIOUS RESULT"
    assert job.error and (out / f"{name}_run_error.log").exists()
