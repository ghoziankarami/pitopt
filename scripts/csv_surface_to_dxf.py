"""
Convert an XYZ point CSV (DEM export, drone/LiDAR dump, survey pickups)
into a DXF 3DFACE surface, so a CSV topography can feed the DXF-first
pipeline without a round trip through a CAD package.

Points are gridded to a regular mesh before triangulation; set --cell to
match the source spacing. Gaps outside the data footprint are left as
holes rather than being extrapolated into a surface that was never
surveyed.

Usage:
    python scripts/csv_surface_to_dxf.py topo.csv topo.dxf --cell 10
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from scipy.interpolate import griddata

from pitopt.io.dxf import write_surface


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_csv")
    ap.add_argument("output_dxf")
    ap.add_argument("--x-col", default="X")
    ap.add_argument("--y-col", default="Y")
    ap.add_argument("--z-col", default="Z")
    ap.add_argument("--cell", type=float, default=10.0, help="output grid cell size")
    ap.add_argument("--layer", default="TOPOGRAPHY")
    args = ap.parse_args()

    df = pd.read_csv(args.input_csv)
    xy = df[[args.x_col, args.y_col]].to_numpy(dtype=float)
    z = df[args.z_col].to_numpy(dtype=float)

    xs = np.arange(xy[:, 0].min(), xy[:, 0].max() + args.cell, args.cell)
    ys = np.arange(xy[:, 1].min(), xy[:, 1].max() + args.cell, args.cell)
    mesh_x, mesh_y = np.meshgrid(xs, ys, indexing="ij")
    grid_z = griddata(xy, z, (mesh_x, mesh_y), method="linear")

    faces = write_surface(args.output_dxf, xs, ys, grid_z, layer=args.layer)
    print(f"Wrote {faces:,} faces over a {len(xs)}x{len(ys)} grid -> {args.output_dxf}")


if __name__ == "__main__":
    main()
