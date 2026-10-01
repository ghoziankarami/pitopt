"""
The self-describing .DAT reader, and a sub-celled model regularised through it.

The same sub-celled model is written twice — as CSV and as a fixed-width .DAT with a "<n> VARIABLES" header of
the kind Micromine exports — and reblocked both ways. The two results must be identical, volume must be
conserved exactly, and the mass-weighted grade of each mining block must be the one worked out by hand.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pitopt.core.reblock import ReblockSpec, reblock
from pitopt.io.datfile import clean_names, read_dat, read_header

FIELDS = [("EAST", "N", 12, 3), ("NORTH", "N", 13, 3), ("RL", "N", 10, 3), ("_EAST", "N", 8, 3), ("_NORTH", "N", 8, 3),
          ("_RL", "N", 8, 3), ("% ZIRCON", "N", 10, 4), ("DENSITY", "N", 8, 3), ("DOMAIN", "C", 10, 0), ("CLASS*", "C", 14, 0)]


def sub_celled() -> pd.DataFrame:
    """A 2 x 2 x 2 grid of 10 x 10 x 2 m parents; the first parent is split into eight 5 x 5 x 1 m sub-cells with
    their own grades and densities, as an estimate refined at a contact would be."""
    rows = []
    for i in range(2):
        for j in range(2):
            for k in range(2):
                cx, cy, cz = 5.0 + 10 * i, 5.0 + 10 * j, 1.0 + 2 * k
                if (i, j, k) == (0, 0, 0):
                    for a in (-2.5, 2.5):
                        for b in (-2.5, 2.5):
                            for c in (-0.5, 0.5):
                                g = 2.0 + a + b + c           # 2.0 +/- up to 5.5 across the sub-cells
                                rows.append((cx + a, cy + b, cz + c, 5.0, 5.0, 1.0, round(max(g, 0.1), 4),
                                             2.0 + 0.1 * (c > 0), "SAND", "TERUKUR"))
                else:
                    rows.append((cx, cy, cz, 10.0, 10.0, 2.0, 1.0 + i + j + k, 1.8, "SAND" if k == 0 else "CLAY",
                                 "TERTUNJUK1" if j == 0 else "TERTUNJUK2"))
    return pd.DataFrame(rows, columns=["EAST", "NORTH", "RL", "_EAST", "_NORTH", "_RL", "ZIRCON", "DENSITY", "DOMAIN", "CLASS"])


def write_dat(frame: pd.DataFrame, path) -> None:
    lines = ["", f"{len(FIELDS)}  VARIABLES"]
    for name, kind, width, dec in FIELDS:
        lines.append(f"{name:<10}{kind} {width:>3} {dec:>2}")
    for row in frame.itertuples(index=False):
        cells = []
        for value, (_name, kind, width, dec) in zip(row, FIELDS):
            cells.append(f"{value:>{width}.{dec}f}" if kind == "N" else f"{value:>{width}}")
        lines.append("".join(cells))
    path.write_text("\n".join(lines) + "\n")


def spec(source) -> ReblockSpec:
    return ReblockSpec(source=str(source), x="EAST", y="NORTH", z="RL", size_x="_EAST", size_y="_NORTH", size_z="_RL",
                       grades=["ZIRCON"], categories=["DOMAIN", "CLASS"], density="DENSITY", target=(10.0, 10.0, 4.0),
                       normalise={"CLASS": r"\d+$"})


def test_header_is_read_and_names_are_cleaned(tmp_path):
    path = tmp_path / "model.dat"
    write_dat(sub_celled(), path)
    fields, skip = read_header(str(path))
    assert [f.name for f in fields][:3] == ["EAST", "NORTH", "RL"] and skip == 2 + len(FIELDS)
    assert [f.kind for f in fields][-2:] == ["C", "C"] and fields[0].width == 12 and fields[6].decimals == 4
    assert clean_names([f.name for f in fields]) == ["EAST", "NORTH", "RL", "_EAST", "_NORTH", "_RL", "ZIRCON", "DENSITY",
                                                     "DOMAIN", "CLASS"]
    assert clean_names(["Shape Leng", "A", "A"]) == ["Shape_Leng", "A", "A_2"]


def test_data_reads_back_exactly_as_written(tmp_path):
    frame = sub_celled()
    path = tmp_path / "model.dat"
    write_dat(frame, path)
    back = read_dat(str(path))
    assert len(back) == len(frame)
    assert np.allclose(back[["EAST", "NORTH", "RL", "ZIRCON", "DENSITY"]].to_numpy(),
                       frame[["EAST", "NORTH", "RL", "ZIRCON", "DENSITY"]].to_numpy(), atol=1e-3)
    assert list(back["CLASS"].str.strip()) == list(frame["CLASS"])


def test_a_file_without_the_header_is_refused_readably(tmp_path):
    path = tmp_path / "plain.dat"
    path.write_text("EAST NORTH RL\n1 2 3\n")
    with pytest.raises(ValueError, match="VARIABLES"):
        read_header(str(path))


def test_reblocking_the_dat_and_the_csv_gives_the_same_model_and_conserves_volume(tmp_path):
    frame = sub_celled()
    csv, dat = tmp_path / "model.csv", tmp_path / "model.dat"
    frame.to_csv(csv, index=False)
    write_dat(frame, dat)
    a, sa = reblock(spec(csv))
    b, sb = reblock(spec(dat))

    source_volume = float((frame["_EAST"] * frame["_NORTH"] * frame["_RL"]).sum())
    assert sa["source_volume"] == pytest.approx(source_volume) and sb["source_volume"] == pytest.approx(source_volume)
    assert a["volume"].sum() == pytest.approx(source_volume) and b["volume"].sum() == pytest.approx(source_volume)

    key = ["EAST", "NORTH", "RL"]
    a, b = a.sort_values(key).reset_index(drop=True), b.sort_values(key).reset_index(drop=True)
    assert len(a) == len(b) == 4                                        # two 2 m parents per 4 m bench: 2 x 2 x 1
    assert np.allclose(a[key + ["ZIRCON", "volume"]].to_numpy(), b[key + ["ZIRCON", "volume"]].to_numpy(), atol=1e-3)
    assert list(a["CLASS"]) == list(b["CLASS"])


def test_the_mixed_block_takes_the_mass_weighted_grade_worked_by_hand(tmp_path):
    """Target cell (0,0): the split parent (eight 25 m3 sub-cells) under a whole 200 m3 parent (grade 2.0, 1.8 t/m3).
    grade = sum(g * V * rho) / sum(V * rho), computed here from the sub-cells directly."""
    frame = sub_celled()
    path = tmp_path / "model.csv"
    frame.to_csv(path, index=False)
    out, _ = reblock(spec(path))
    cell = frame[(frame["EAST"] < 10) & (frame["NORTH"] < 10)]
    mass = cell["_EAST"] * cell["_NORTH"] * cell["_RL"] * cell["DENSITY"]
    expected = float((cell["ZIRCON"] * mass).sum() / mass.sum())
    got = out[(out["EAST"] < 10) & (out["NORTH"] < 10)]
    assert len(got) == 1 and float(got["ZIRCON"].iloc[0]) == pytest.approx(expected, rel=1e-9)
    assert float(got["volume"].iloc[0]) == pytest.approx(400.0)           # 8 x 25 + 200
    classes = out.sort_values(["NORTH", "EAST"])["CLASS"].tolist()
    assert "TERTUNJUK" in classes                                       # the numbered labels counted as one class
