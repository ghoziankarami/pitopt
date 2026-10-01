"""Bring-your-own-data path: inspection, project creation, and refusal of invented inputs."""
import numpy as np
import pandas as pd
import pytest

from pitopt.config import ProjectConfig
from pitopt.ui import onboard


def _model(path, size=(10.0, 10.0, 5.0), n=6):
    xs, ys, zs = np.meshgrid(np.arange(n) * size[0] + 100, np.arange(n) * size[1] + 200, np.arange(n) * size[2] + 50, indexing="ij")
    pd.DataFrame({"EAST": xs.ravel(), "NORTH": ys.ravel(), "RL": zs.ravel(), "SN_PCT": 0.5, "ZONE": "A", "CLS": "Measured"}).to_csv(path, index=False)


def test_inspect_finds_columns_and_block_size(tmp_path):
    _model(tmp_path / "m.csv")
    info = onboard.inspect_file(tmp_path / "m.csv")
    assert info["guess"]["x"] == "EAST" and info["guess"]["z"] == "RL" and info["guess"]["domain"] == "ZONE"
    assert info["spacing"] == {"x": 10.0, "y": 10.0, "z": 5.0} and info["regular"]
    assert info["rows"] == 216


def test_irregular_grid_is_flagged(tmp_path):
    _model(tmp_path / "m.csv")
    df = pd.read_csv(tmp_path / "m.csv")
    df.loc[0, "EAST"] += 3.7
    df.loc[1, "EAST"] += 1.3
    df.to_csv(tmp_path / "m.csv", index=False)
    assert any("reblock" in w.lower() for w in onboard.inspect_file(tmp_path / "m.csv")["warnings"])


def _spec(**over):
    spec = {"title": "Uji", "block_model": {"file": "m.csv", "x_col": "EAST", "y_col": "NORTH", "z_col": "RL", "dx": 10, "dy": 10, "dz": 5, "density": 2.0},
            "economics": {"grade_basis": "mass_percent", "mining_cost_per_tonne": 2, "products": [{"name": "SN", "grade_col": "SN_PCT", "price": 100}]},
            "slope_angle": 45, "capacity": 1e6, "touched": ["slope_angle"]}
    spec.update(over)
    return spec


def test_created_project_loads_and_marks_untouched_as_assumption(tmp_path):
    slug, cfg = onboard.build_project(_spec())
    (tmp_path / "data").mkdir()
    _model(tmp_path / "data" / "m.csv")
    target = onboard.write_project(tmp_path, slug, cfg)
    loaded = ProjectConfig.from_yaml(str(target))
    assert loaded.schedule.enabled and loaded.economics.products[0].price == 100
    assert loaded.provenance["slope.overall_angle_deg"]["source"] == "input"
    assert loaded.provenance["schedule.discount_rate"]["source"] == "asumsi"


@pytest.mark.parametrize("patch,text", [
    ({"capacity": None}, "kapasitas"),
    ({"economics": {"products": []}}, "produk"),
    ({"block_model": {"file": "m.csv", "x_col": "EAST", "y_col": "NORTH", "z_col": "RL", "dx": 10, "dy": 10, "dz": 5}}, "Densitas"),
])
def test_missing_inputs_are_refused_not_defaulted(patch, text):
    with pytest.raises(ValueError, match=f"(?i){text}"):
        onboard.build_project(_spec(**patch))


def test_unsafe_file_names_are_rejected():
    with pytest.raises(ValueError):
        onboard.safe_name("payload.exe")
    assert onboard.safe_name("../../etc/blocks.csv") == "blocks.csv"


# ---- column mapping: guessed, never required to match; every guess can be overridden ----

def _write(tmp_path, columns: dict, name="m.csv"):
    pd.DataFrame(columns).to_csv(tmp_path / name, index=False)
    return tmp_path / name


@pytest.mark.parametrize("names,expect", [
    (("Easting", "Northing", "Elevation"), ("Easting", "Northing", "Elevation")),
    (("x", "y", "z"), ("x", "y", "z")),
    (("XC", "YC", "ZC"), ("XC", "YC", "ZC")),
    (("EAST_M", "NORTH_M", "RL_M"), (None, None, None)),        # unrecognised: the user maps by hand
])
def test_coordinate_guess_or_manual(tmp_path, names, expect):
    grid = np.meshgrid(np.arange(4) * 10.0, np.arange(4) * 10.0, np.arange(3) * 5.0, indexing="ij")
    path = _write(tmp_path, {names[0]: grid[0].ravel(), names[1]: grid[1].ravel(), names[2]: grid[2].ravel(), "CU": 1.0})
    info = onboard.inspect_file(path)
    assert (info["guess"]["x"], info["guess"]["y"], info["guess"]["z"]) == expect
    assert any("manual" in w.lower() for w in info["warnings"]) == (expect[0] is None)
    assert set(info["numeric"]) >= {names[0], "CU"}                    # every column stays selectable


def test_size_columns_and_class_are_recognised(tmp_path):
    grid = np.meshgrid(np.arange(3) * 10.0, np.arange(3) * 10.0, np.arange(2) * 5.0, indexing="ij")
    path = _write(tmp_path, {"X": grid[0].ravel(), "Y": grid[1].ravel(), "Z": grid[2].ravel(), "XINC": 10.0, "YINC": 10.0, "ZINC": 5.0,
                             "SG": 2.5, "LITHO": "a", "CATEGORY": "Measured", "AU_GPT": 1.2})
    g = onboard.inspect_file(path)["guess"]
    assert (g["dx"], g["dy"], g["dz"], g["density"], g["domain"], g["class"]) == ("XINC", "YINC", "ZINC", "SG", "LITHO", "CATEGORY")


def test_build_project_with_size_columns_needs_no_typed_size(tmp_path):
    spec = _spec()
    spec["block_model"] = {"file": "m.csv", "x_col": "X", "y_col": "Y", "z_col": "Z", "dx_col": "XINC", "dy_col": "YINC", "dz_col": "ZINC", "density_col": "SG"}
    slug, cfg = onboard.build_project(spec)
    assert cfg["block_model"]["dx_col"] == "XINC" and "dx" not in cfg["block_model"] and "density" not in cfg["block_model"]


def test_only_csv_and_dxf_are_accepted():
    for good in ("blocks.csv", "topo.DXF"):
        assert onboard.safe_name(good)
    for bad in ("model.dat", "model.txt", "x.xlsx", "x.zip"):
        with pytest.raises(ValueError):
            onboard.safe_name(bad)


def test_surface_dxf_is_inspected_and_empty_dxf_is_refused(tmp_path):
    import ezdxf

    doc = ezdxf.new()
    msp = doc.modelspace()
    for x in range(0, 30, 10):
        for y in range(0, 30, 10):
            msp.add_3dface([(x, y, 5), (x + 10, y, 5), (x + 10, y + 10, 6), (x, y + 10, 6)])
    doc.saveas(tmp_path / "t.dxf")
    info = onboard.inspect_file(tmp_path / "t.dxf")
    assert info["kind"] == "surface" and info["extent"]["z"] == [5.0, 6.0]
    empty = ezdxf.new()
    empty.saveas(tmp_path / "e.dxf")
    with pytest.raises(ValueError):
        onboard.inspect_file(tmp_path / "e.dxf")


# ---- reblock from the UI path ----

def _subcelled(path):
    """Parents 20x20x10; every second parent is split into 2x2x2 sub-cells with its own grade."""
    rows = []
    for i in range(4):
        for j in range(4):
            for k in range(3):
                cx, cy, cz = 1000 + i * 20 + 10, 5000 + j * 20 + 10, 200 - k * 10 - 5
                if (i + j) % 2:
                    for a in (-5, 5):
                        for b in (-5, 5):
                            for c in (-2.5, 2.5):
                                rows.append((cx + a, cy + b, cz + c, 10, 10, 5, 2.0 + 0.1 * (a > 0), 1.0 + (b > 0) + (c > 0), "ORE1" if a > 0 else "ORE2"))
                else:
                    rows.append((cx, cy, cz, 20, 20, 10, 2.4, 0.5, "ORE1"))
    pd.DataFrame(rows, columns=["X", "Y", "Z", "SX", "SY", "SZ", "SG", "CU", "CLASS"]).to_csv(path, index=False)
    return sum(r[3] * r[4] * r[5] for r in rows)


def test_reblock_conserves_volume_and_weights_grades_by_mass(tmp_path):
    volume = _subcelled(tmp_path / "sub.csv")
    info = onboard.inspect_file(tmp_path / "sub.csv")
    assert not info["regular"]                                                   # the wizard offers reblock
    out = onboard.reblock_file(tmp_path, {
        "file": "sub.csv", "x": "X", "y": "Y", "z": "Z", "size_x": "SX", "size_y": "SY", "size_z": "SZ",
        "grades": ["CU"], "categories": ["CLASS"], "density": "SG", "target": [20, 20, 10], "strip_digits": ["CLASS"]})
    assert abs(out["volume_difference"]) < 1e-6 and abs(out["output_volume"] - volume) < 1e-6
    assert out["blocks"] == 48 and out["grade_weighting"] == "mass"
    assert out["inspect"]["regular"] and out["inspect"]["spacing"] == {"x": 20.0, "y": 20.0, "z": 10.0}
    table = pd.read_csv(tmp_path / out["file"])
    assert (table["FILL"] <= 1.0001).all() and set(table["CLASS"]) == {"ORE"}     # ORE1/ORE2 merged by the digit rule
    # mass-weighted grade of one split parent, recomputed by hand
    sub = pd.read_csv(tmp_path / "sub.csv")
    cell = sub[(sub.X.between(1020, 1040)) & (sub.Y.between(5000, 5020)) & (sub.Z.between(190, 200))]
    w = cell.SX * cell.SY * cell.SZ * cell.SG
    want = (w * cell.CU).sum() / w.sum()
    got = table[(table.X == 1030) & (table.Y == 5010) & (table.Z == 195)]["CU"].iloc[0]
    assert abs(got - want) < 1e-9


def test_reblock_refuses_unaligned_or_incomplete_input(tmp_path):
    _subcelled(tmp_path / "sub.csv")
    base = {"file": "sub.csv", "x": "X", "y": "Y", "z": "Z", "grades": ["CU"], "target": [20, 20, 10]}
    with pytest.raises(ValueError, match="parent"):
        onboard.reblock_file(tmp_path, base)                                     # no size columns and no parent size
    with pytest.raises(ValueError):
        onboard.reblock_file(tmp_path, {**base, "size_x": "SX", "size_y": "SY", "size_z": "SZ", "target": [0, 20, 10]})
    with pytest.raises(ValueError, match="tidak ada"):
        onboard.reblock_file(tmp_path, {**base, "x": "NOPE", "parent": [20, 20, 10]})


def test_reblocked_model_feeds_project_creation_with_volume_column(tmp_path):
    slug, cfg = onboard.build_project({**_spec(), "block_model": {
        "file": "m_reblocked_blocks.csv", "x_col": "X", "y_col": "Y", "z_col": "Z", "dx": 20, "dy": 20, "dz": 10, "density_col": "SG", "volume_col": "volume"}})
    assert cfg["block_model"]["volume_col"] == "volume"


def test_project_without_topography_is_created(tmp_path):
    """Topography is optional; the UI sends surface: null."""
    slug, cfg = onboard.build_project(_spec(surface=None))
    assert "surface" not in cfg
    (tmp_path / "data").mkdir()
    _model(tmp_path / "data" / "m.csv")
    assert ProjectConfig.from_yaml(str(onboard.write_project(tmp_path, slug, cfg))).surface.path is None


# Headers as the common packages export them. Micromine is the one that bit: its block-size fields are the
# coordinate names with a leading underscore, and normalising the underscore away took "_EAST" for the easting.
EXPORTS = {
    "micromine": (["EAST", "NORTH", "RL", "_EAST", "_NORTH", "_RL", "AU", "DENSITY", "ZONE"],
                  ("EAST", "NORTH", "RL", "_EAST", "_NORTH", "_RL", "DENSITY", "ZONE")),
    "micromine_sizes_first": (["_EAST", "_NORTH", "_RL", "EAST", "NORTH", "RL", "AU"],
                              ("EAST", "NORTH", "RL", "_EAST", "_NORTH", "_RL", None, None)),
    "datamine": (["XC", "YC", "ZC", "XINC", "YINC", "ZINC", "AU", "DENSITY", "ROCKTYPE"],
                 ("XC", "YC", "ZC", "XINC", "YINC", "ZINC", "DENSITY", "ROCKTYPE")),
    "surpac": (["x_centre", "y_centre", "z_centre", "dim_x", "dim_y", "dim_z", "au", "sg"],
               ("x_centre", "y_centre", "z_centre", "dim_x", "dim_y", "dim_z", "sg", None)),
    "vulcan": (["centroid_x", "centroid_y", "centroid_z", "dim_x", "dim_y", "dim_z", "au", "density"],
               ("centroid_x", "centroid_y", "centroid_z", "dim_x", "dim_y", "dim_z", "density", None)),
    "leapfrog": (["X", "Y", "Z", "size_x", "size_y", "size_z", "Au_ppm", "Density", "Domain"],
                 ("X", "Y", "Z", "size_x", "size_y", "size_z", "Density", "Domain")),
    "deswik": (["XC", "YC", "ZC", "XSIZE", "YSIZE", "ZSIZE", "AU", "DENSITY"],
               ("XC", "YC", "ZC", "XSIZE", "YSIZE", "ZSIZE", "DENSITY", None)),
    "generic": (["Easting", "Northing", "Elevation", "Au_gpt", "Bulk_Density", "Lithology"],
                ("Easting", "Northing", "Elevation", None, None, None, "Bulk_Density", "Lithology")),
}


@pytest.mark.parametrize("package", EXPORTS)
def test_columns_are_guessed_from_real_export_headers(package):
    from pitopt.ui.onboard import _GUESS, _match

    columns, expected = EXPORTS[package]
    got = tuple(_match(columns, _GUESS[k]) for k in ("x", "y", "z", "dx", "dy", "dz", "density", "domain"))
    assert got == expected


def test_a_guess_is_only_a_suggestion_and_any_column_name_runs(tmp_path):
    """Names no package uses are not guessed — and a project mapping them explicitly still loads."""
    from pitopt.io.blockmodel import load_block_model

    pd.DataFrame({"koordinat_timur": [5.0, 15.0], "koordinat_utara": [5.0, 5.0], "elevasi_pusat": [2.5, 2.5],
                  "kadar_emas": [1.2, 0.3]}).to_csv(tmp_path / "m.csv", index=False)
    info = onboard.inspect_file(tmp_path / "m.csv")
    assert info["guess"]["x"] is None and info["warnings"]                   # asks the user instead of guessing wrong
    (tmp_path / "p.yaml").write_text(
        "project: {name: t}\nblock_model: {path: m.csv, x_col: koordinat_timur, y_col: koordinat_utara, z_col: elevasi_pusat,"
        " dx: 10, dy: 10, dz: 5, density: 2.6}\neconomics: {grade_basis: gpt, products: [{name: AU, grade_col: kadar_emas,"
        " price: 2300, price_unit: oz}]}\n")
    cfg = ProjectConfig.from_yaml(str(tmp_path / "p.yaml"))
    blocks = load_block_model(cfg.block_model, cfg.economics)
    assert list(blocks["x"]) == [5.0, 15.0] and list(blocks["kadar_emas"]) == [1.2, 0.3]
