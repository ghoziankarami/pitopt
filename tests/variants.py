"""
Synthetic deposits that cover the kinds of data a real project brings, so the independent consistency checks
run against more than one commodity on every machine — not only where someone happened to have a client's
model in outputs/.

Each variant is small (a few thousand blocks) but differs from the bundled tin example in exactly the ways that
break a pipeline in practice:

  gold_oz       grade in g/t priced per troy ounce, a density column that varies by weathering, local mine-grid
                coordinates that go negative, no topography file (the model's own top is the ground), haulage
                cost rising with depth, and the detailed pit design switched on.
  ree_ppm       two products in ppm priced per kilogram, resource classes (Inferred must earn nothing but still
                be dug), a non-ore domain (bedrock is never feed), costs charged per cubic metre, and a DXF
                topography (a TIN of 3DFACEs, the usual survey deliverable) that cuts into the model's top.
  sands_vol     heavy-mineral sand graded in volume per cent with two products, mined in strips and scheduled
                by volume, with a CSV (not DXF) topography.

None of the numbers mean anything about a real deposit. They are chosen so each has an economic pit that closes
inside its model, which is what lets every downstream check run.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from pitopt.io.dxf import write_surface

RF = [0.4, 0.6, 0.8, 1.0, 1.2]


def _grid(nx: int, ny: int, nz: int, size: float, dz: float, x0: float, y0: float, top: float):
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    x = x0 + (ix.ravel() + 0.5) * size
    y = y0 + (iy.ravel() + 0.5) * size
    z = top - (iz.ravel() + 0.5) * dz
    return x, y, z


def _write(root: Path, name: str, blocks: pd.DataFrame, config: dict, surface: pd.DataFrame | None = None) -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    blocks.to_csv(folder / "blocks.csv", index=False)
    if surface is not None:
        surface.to_csv(folder / "surface.csv", index=False)
    path = folder / "project.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    return path


def gold_oz(root: Path) -> Path:
    rng = np.random.default_rng(11)
    x, y, z = _grid(26, 22, 16, 20.0, 10.0, x0=-260.0, y0=-220.0, top=160.0)
    r = np.hypot(x, y * 1.3)
    depth = 160.0 - z
    grade = 2.4 * np.exp(-(r / 55.0) ** 2) * np.exp(-((depth - 50.0) / 45.0) ** 2) * rng.lognormal(0.0, 0.25, len(x))
    density = np.where(depth < 30.0, 2.35, 2.72)
    blocks = pd.DataFrame({"E": x, "N": y, "RL": z, "AU_GPT": grade.round(3), "SG": density,
                           "XINC": 20.0, "YINC": 20.0, "ZINC": 10.0})
    config = {
        "project": {"name": "gold_oz", "title": "Variant — gold g/t per oz"},
        "block_model": {"path": "blocks.csv", "x_col": "E", "y_col": "N", "z_col": "RL", "density_col": "SG",
                        "dx_col": "XINC", "dy_col": "YINC", "dz_col": "ZINC"},
        "economics": {"grade_basis": "gpt", "mining_recovery": 0.95, "dilution": 0.05, "royalty_rate": 0.04,
                      "mining_cost_per_tonne": 3.2, "mining_cost_increment_per_m": 0.015, "processing_cost_per_tonne": 24.0,
                      "products": [{"name": "AU", "grade_col": "AU_GPT", "price": 2300.0, "price_unit": "oz",
                                    "plant_recovery": 0.92, "selling_cost_per_tonne": 12.0}]},
        "slope": {"overall_angle_deg": 45.0},
        "design": {"bench_height": 10.0, "bench_face_angle_deg": 70.0, "cell": 2.5,
                   "detail": {"enabled": True, "berm": {"method": "slope"}, "ramp": {"width_m": 20.0, "grade_pct": 9.0},
                              "limits": {"min_mining_width_m": 30.0},
                              "grade_classes": {"grade_col": "AU_GPT", "breaks": [0.5, 1.5, 3.0],
                                                "names": ["Waste", "Rendah", "Menengah", "Tinggi"]}}},
        "shells": {"revenue_factors": RF},
        "final_pit": {"criterion": "average", "tolerance": 0.01},
        "pushbacks": {"method": "shells", "max_pushbacks": 3, "min_width": 40.0},
        "schedule": {"enabled": True, "ore_capacity": 400_000.0, "basis": "tonnes", "discount_rate": 0.08},
        "sensitivity": {"enabled": True, "price_factors": [0.8, 1.0, 1.2]},
        "output": {"directory": "out", "write_3d": False, "dxf_surface_periods": False, "dxf_surface_pushbacks": False},
    }
    return _write(root, "gold_oz", blocks, config)


def ree_ppm(root: Path) -> Path:
    rng = np.random.default_rng(23)
    x, y, z = _grid(22, 22, 8, 25.0, 5.0, x0=410_000.0, y0=7_300_000.0, top=240.0)
    depth = 240.0 - z
    u = (x - x.mean()) / 150.0
    v = (y - y.mean()) / 150.0
    domain = np.where(depth < 15.0, "CLAY", np.where(depth < 30.0, "SAPROLITE", "BEDROCK"))
    richness = np.exp(-1.6 * (u ** 2 + v ** 2)) * np.where(domain == "BEDROCK", 0.05, 1.0) * rng.lognormal(0.0, 0.3, len(x))
    ndpr = (2600.0 * richness).round(1)
    dy = (120.0 * richness).round(2)
    cls = np.where(np.hypot(u, v) < 0.8, "Measured", np.where(np.hypot(u, v) < 1.4, "Indicated", "Inferred"))
    blocks = pd.DataFrame({"X": x, "Y": y, "Z": z, "NDPR_PPM": ndpr, "DY_PPM": dy, "DOMAIN": domain, "CLASS": cls})
    gx = np.linspace(x.min() - 12.5, x.max() + 12.5, 31)
    gy = np.linspace(y.min() - 12.5, y.max() + 12.5, 31)
    sx, sy = np.meshgrid(gx, gy, indexing="ij")
    ground = 238.0 + 3.0 * np.sin((sx - gx[0]) / 90.0) * np.cos((sy - gy[0]) / 110.0)      # rolling, cuts the top bench
    config = {
        "project": {"name": "ree_ppm", "title": "Variant — REE ppm per kg"},
        "block_model": {"path": "blocks.csv", "dx": 25.0, "dy": 25.0, "dz": 5.0, "density": 1.9,
                        "domain_col": "DOMAIN", "class_col": "CLASS", "include_classes": ["Measured", "Indicated"],
                        "ore_domains": ["CLAY", "SAPROLITE"]},
        "surface": {"path": "topo.dxf", "format": "dxf"},
        "economics": {"grade_basis": "ppm", "mining_recovery": 0.97, "dilution": 0.03, "royalty_rate": 0.05,
                      "mining_cost_per_volume": 4.0, "rehabilitation_cost_per_volume": 1.5, "processing_cost_per_tonne": 30.0,
                      "products": [{"name": "NDPR", "grade_col": "NDPR_PPM", "price": 75.0, "price_unit": "kg", "plant_recovery": 0.55},
                                   {"name": "DY", "grade_col": "DY_PPM", "price": 350.0, "price_unit": "kg", "plant_recovery": 0.5}]},
        "slope": {"overall_angle_deg": 35.0},
        "design": {"bench_height": 5.0, "bench_face_angle_deg": 55.0, "cell": 2.5},
        "shells": {"revenue_factors": RF},
        "final_pit": {"criterion": "average", "tolerance": 0.01},
        "pushbacks": {"method": "shells", "max_pushbacks": 3, "min_width": 50.0},
        "schedule": {"enabled": True, "ore_capacity": 300_000.0, "basis": "tonnes", "discount_rate": 0.1},
        "output": {"directory": "out", "write_3d": False, "dxf_surface_periods": False, "dxf_surface_pushbacks": False},
    }
    path = _write(root, "ree_ppm", blocks, config)
    write_surface(str(path.parent / "topo.dxf"), gx, gy, ground, layer="TOPO")
    return path


def sands_vol(root: Path) -> Path:
    rng = np.random.default_rng(37)
    nx, ny, nz, size, dz = 40, 20, 6, 25.0, 2.0
    x, y, z = _grid(nx, ny, nz, size, dz, x0=0.0, y0=0.0, top=30.0)
    gx = np.linspace(0.0, nx * size, 41)
    gy = np.linspace(0.0, ny * size, 21)
    sx, sy = np.meshgrid(gx, gy, indexing="ij")
    ground = 30.0 - 1.5 * np.sin(sx / 180.0) - 0.8 * np.cos(sy / 120.0)
    surface = pd.DataFrame({"X": sx.ravel(), "Y": sy.ravel(), "Z": ground.ravel().round(3)})
    band = (np.exp(-((y - ny * size / 2) / 70.0) ** 2) * np.exp(-((x - nx * size / 2) / 330.0) ** 4)
            * (0.6 + 0.4 * np.sin(x / 150.0) ** 2))
    depth = 30.0 - z
    band *= (depth > 4.0) & (depth < 10.0)            # barren overburden above, clay basement below
    zr = (4.5 * band * rng.lognormal(0.0, 0.2, len(x))).round(3)
    il = (7.0 * band * rng.lognormal(0.0, 0.2, len(x))).round(3)
    blocks = pd.DataFrame({"X": x, "Y": y, "Z": z, "ZIRCON": zr, "ILMENITE": il})
    config = {
        "project": {"name": "sands_vol", "title": "Variant — mineral sands vol %"},
        "block_model": {"path": "blocks.csv", "dx": size, "dy": size, "dz": dz, "density": 1.7},
        "surface": {"path": "surface.csv", "format": "csv"},
        "economics": {"grade_basis": "volume_percent", "mining_recovery": 0.97, "dilution": 0.03,
                      "mining_cost_per_volume": 2.0, "rehabilitation_cost_per_volume": 0.8, "processing_cost_per_volume": 4.0,
                      "products": [{"name": "ZIRCON", "grade_col": "ZIRCON", "price": 1400.0, "density": 4.6,
                                    "plant_recovery": 0.9, "processing_cost_per_tonne": 120.0},
                                   {"name": "ILMENITE", "grade_col": "ILMENITE", "price": 280.0, "density": 4.7,
                                    "plant_recovery": 0.9}]},
        "slope": {"overall_angle_deg": 30.0},
        "design": {"bench_height": 2.0, "bench_face_angle_deg": 45.0, "cell": 2.5},
        "shells": {"revenue_factors": RF},
        "final_pit": {"criterion": "average", "tolerance": 0.01},
        "pushbacks": {"method": "strips", "strip_width": 100.0, "count": 3},
        "schedule": {"enabled": True, "ore_capacity": 60_000.0, "basis": "volume", "discount_rate": 0.1},
        "output": {"directory": "out", "write_3d": False, "dxf_surface_periods": False, "dxf_surface_pushbacks": False},
    }
    return _write(root, "sands_vol", blocks, config, surface)


VARIANTS = {"gold_oz": gold_oz, "ree_ppm": ree_ppm, "sands_vol": sands_vol}
