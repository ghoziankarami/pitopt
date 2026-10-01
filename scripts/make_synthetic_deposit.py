"""
Generate a synthetic but geologically-coherent porphyry copper dataset in
the pipeline's standard formats: block model CSV + topography DXF.

The grades are invented, but the *structure* is not arbitrary. A porphyry
is zoned vertically by weathering, and that zoning is what drives both
the grade profile and the geotechnical domains:

  leached cap   0-60 m below surface   copper leached out, low grade,
                                       weak rock -> shallow slope angle
  supergene     60-150 m               copper redeposited, the enriched
                                       blanket, best grades
  primary       below 150 m            fresh sulphide, moderate grade,
                                       competent rock -> steep slope

Grade falls off radially from a central stock and is given multiplicative
lognormal noise, so the histogram is right-skewed the way real assay data
is rather than symmetric around a mean.

Coordinates are real-world UTM metres, the model extends well past the
economic limit so the pit closes inside it, and topography is a rolling
ridge rather than a flat plane — all things that only show up as problems
once a pipeline meets real data.

This is test data. It is not a resource model and no number in it means
anything about any real deposit.

Usage:
    python scripts/make_synthetic_deposit.py
    python scripts/make_synthetic_deposit.py --nx 80 --ny 80 --nz 34
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from pitopt.io.dxf import write_surface

ROOT = Path(__file__).resolve().parent.parent

EAST0, NORTH0 = 500_000.0, 9_150_000.0    # UTM 51S, southern hemisphere
BASE_RL = 1_150.0

LEACHED_BASE, SUPERGENE_BASE = 60.0, 150.0   # metres below surface

DOMAINS = {
    "OXIDE": {"density": 2.45, "grade_factor": 0.25},
    "TRANS": {"density": 2.65, "grade_factor": 1.80},
    "FRESH": {"density": 2.78, "grade_factor": 1.00},
}


def topography(east: np.ndarray, north: np.ndarray, extent: float) -> np.ndarray:
    """Rolling ridge — smooth, ~120 m of relief, no flat-plane shortcuts."""
    u = (east - EAST0) / extent
    v = (north - NORTH0) / extent
    return (
        BASE_RL
        + 55.0 * np.sin(2.2 * np.pi * u) * np.cos(1.6 * np.pi * v)
        + 30.0 * np.cos(3.4 * np.pi * v)
        + 18.0 * np.sin(4.1 * np.pi * u + 1.0)
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nx", type=int, default=64, help="blocks along easting")
    ap.add_argument("--ny", type=int, default=64, help="blocks along northing")
    ap.add_argument("--nz", type=int, default=30, help="benches")
    ap.add_argument("--dx", type=float, default=20.0)
    ap.add_argument("--dy", type=float, default=20.0)
    ap.add_argument("--dz", type=float, default=15.0)
    ap.add_argument("--core-grade", type=float, default=1.05, help="peak Cu percent at the stock axis")
    ap.add_argument("--radius", type=float, default=230.0, help="grade shell decay radius, metres")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--outdir", default="projects/porphyry_synthetic/data")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    out_dir = ROOT / args.outdir
    out_dir.mkdir(parents=True, exist_ok=True)

    extent = args.nx * args.dx
    east = EAST0 + np.arange(args.nx) * args.dx
    north = NORTH0 + np.arange(args.ny) * args.dy

    # Topography first: the model hangs below it, and the weathering zones
    # follow depth below surface rather than absolute elevation.
    mesh_e, mesh_n = np.meshgrid(east, north, indexing="ij")
    topo = topography(mesh_e, mesh_n, extent)

    top_rl = np.ceil(topo.max() / args.dz) * args.dz
    rl = top_rl - np.arange(args.nz) * args.dz

    grid_e, grid_n, grid_rl = np.meshgrid(east, north, rl, indexing="ij")
    surface_rl = topo[:, :, None]

    depth = surface_rl - grid_rl
    axis_e, axis_n = EAST0 + extent / 2.0, NORTH0 + (args.ny * args.dy) / 2.0
    radial = np.hypot(grid_e - axis_e, grid_n - axis_n)

    zone = np.where(depth < LEACHED_BASE, "OXIDE", np.where(depth < SUPERGENE_BASE, "TRANS", "FRESH"))

    # Radial decay from the stock, fading with depth as the system closes off.
    shell = args.core_grade * np.exp(-((radial / args.radius) ** 2))
    shell *= np.exp(-np.clip(depth - SUPERGENE_BASE, 0.0, None) / 220.0)

    grade_factor = np.select(
        [zone == "OXIDE", zone == "TRANS"],
        [DOMAINS["OXIDE"]["grade_factor"], DOMAINS["TRANS"]["grade_factor"]],
        default=DOMAINS["FRESH"]["grade_factor"],
    )
    noise = rng.lognormal(mean=0.0, sigma=0.45, size=shell.shape)
    grade = np.clip(shell * grade_factor * noise, 0.0, None)

    density = np.select(
        [zone == "OXIDE", zone == "TRANS"],
        [DOMAINS["OXIDE"]["density"], DOMAINS["TRANS"]["density"]],
        default=DOMAINS["FRESH"]["density"],
    )

    blocks = pd.DataFrame(
        {
            "EAST": grid_e.ravel(),
            "NORTH": grid_n.ravel(),
            "RL": grid_rl.ravel(),
            "CU_PCT": np.round(grade.ravel(), 4),
            "DENSITY": density.ravel(),
            "DOMAIN": zone.ravel(),
        }
    )
    # Air blocks are not part of a resource model; the pipeline clips
    # against topography too, but a real export would not contain them.
    blocks = blocks[blocks["RL"] <= topography(blocks["EAST"], blocks["NORTH"], extent) + args.dz / 2.0]

    blocks_path = out_dir / "porphyry_blocks.csv"
    blocks.to_csv(blocks_path, index=False)

    topo_path = out_dir / "porphyry_topo.dxf"
    faces = write_surface(str(topo_path), east, north, topo, layer="TOPOGRAPHY")

    ore = blocks[blocks.CU_PCT > 0.15]
    print(f"Blocks written : {len(blocks):,} -> {blocks_path.name}")
    print(f"Topography     : {faces:,} faces, RL {topo.min():.0f}-{topo.max():.0f} -> {topo_path.name}")
    print(f"Extent         : {extent:.0f} x {args.ny * args.dy:.0f} m, {args.nz} benches of {args.dz:.0f} m")
    print(f"Block size     : {args.dx:.0f} x {args.dy:.0f} x {args.dz:.0f} m")
    print()
    print("Grade distribution (Cu %):")
    print(f"  all blocks   : mean {blocks.CU_PCT.mean():.3f}, p50 {blocks.CU_PCT.median():.3f}, max {blocks.CU_PCT.max():.3f}")
    print(f"  above 0.15%  : {len(ore):,} blocks, mean {ore.CU_PCT.mean():.3f}")
    print()
    print("By domain:")
    print(blocks.groupby("DOMAIN").agg(blocks=("CU_PCT", "size"), mean_cu=("CU_PCT", "mean"), density=("DENSITY", "first")).to_string())


if __name__ == "__main__":
    main()
