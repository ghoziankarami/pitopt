"""
The command line — what `make example`, `make porphyry` and anyone scripting PitOpt actually call.

`run` must write the same results document the pipeline writes (so the CLI is not a second code path that could
drift), `validate` must report derived parameters and refuse a missing input, and `reblock` must regularise a
.DAT the same way the library does.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from pitopt.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_validate_reports_the_derived_parameters(capsys):
    assert main(["validate", "--config", str(ROOT / "projects/example_tin/project.yaml")]) == 0
    out = capsys.readouterr().out
    assert "cutoff" in out.lower() and "SN" in out


def test_validate_refuses_a_missing_block_model(tmp_path, capsys):
    project = tmp_path / "p"
    shutil.copytree(ROOT / "projects/example_tin", project)
    (project / "example_block_model.csv").unlink()
    code = main(["validate", "--config", str(project / "project.yaml")])
    assert code != 0 and "block model not found" in capsys.readouterr().out


def test_run_writes_the_same_answer_as_the_pipeline(tmp_path, capsys):
    """The regression gate's locked fixture is the pipeline's answer on this project; the CLI must reproduce it."""
    reference = sorted((ROOT / ".pytest_runs/example_tin").glob("*_results.json"))
    if not reference:
        pytest.skip("no generated example run")
    assert main(["run", "--config", str(ROOT / "projects/example_tin/project.yaml"), "--outdir", str(tmp_path), "--quiet"]) == 0
    assert "Outputs:" in capsys.readouterr().out
    got = json.loads(next(tmp_path.glob("*_results.json")).read_text())
    want = json.loads(reference[0].read_text())
    for key in ("value_undiscounted", "npv_plan", "rock_t", "ore_t", "final_shell"):
        assert got["kpis"][key] == pytest.approx(want["kpis"][key], rel=1e-9), key


def test_reblock_regularises_a_dat_file(tmp_path, capsys):
    from test_datfile_reblock import spec, sub_celled, write_dat

    from pitopt.core.reblock import reblock

    source = tmp_path / "model.dat"
    write_dat(sub_celled(), source)
    code = main(["reblock", str(source), "--out", str(tmp_path / "out"), "--name", "m", "--size", "10", "10", "4",
                 "--x", "EAST", "--y", "NORTH", "--z", "RL", "--size-cols", "_EAST", "_NORTH", "_RL",
                 "--grades", "ZIRCON", "--categories", "DOMAIN", "CLASS", "--density", "DENSITY",
                 "--normalise", "CLASS", r"\d+$", "--no-topo"])
    assert code == 0
    written = pd.read_csv(next((tmp_path / "out").glob("m*.csv")))
    library, _ = reblock(spec(source))
    assert len(written) == len(library)
    assert written["volume"].sum() == pytest.approx(library["volume"].sum())
    assert sorted(written["ZIRCON"].round(6)) == sorted(library["ZIRCON"].round(6))
