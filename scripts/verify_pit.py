"""
Independent geometric checks on a solved pit — they do not reuse the
solver's own precedence arcs, so a fault in the template cannot hide
behind itself.

1. Template slope: grow the closure of one block through the precedence
   template and measure the wall angle it produces in the cardinal and
   the diagonal direction. A template that is right along the grid axes
   can still be far too steep on the diagonals.

2. Pit walls: on the gridded pit surface, compare every mined column
   with every column within a search radius. The remaining ground at
   distance d may stand at most d * tan(slope) above the pit floor, plus
   one block of discretisation. Anything higher is a wall steeper than
   the design angle.

3. True cone: every in-pit block against its slope cone.

4. Schedule: every block must be mined in the same period as, or after,
   every block inside its true slope cone above it.

5. Design: on the benched face position, no local face may be steeper
   than the bench face angle, and no wall measured over several benches
   steeper than the overall angle.

Usage:
    python scripts/verify_pit.py projects/porphyry_synthetic/project.yaml
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pitopt.config import ProjectConfig
from pitopt.core.design import bench_geometry, design_grid, face_position, pit_shell
from pitopt.core.precedence import add_grid_indices, auto_bench_levels, effective_slope
from pitopt.core.verify import cone_check, design_check, schedule_check, wall_check
from pitopt.pipeline import load_elevation

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    args = ap.parse_args()
    cfg = ProjectConfig.from_yaml(args.config)
    dx, dz = cfg.block_model.dx, cfg.block_model.dz
    angle = cfg.slope.overall_angle_deg

    configured = cfg.slope.max_bench_levels or auto_bench_levels(angle, dx, dz)
    print(f"== 1. Template slope (design {angle} deg, block {dx} x {dz} m) ==")
    for levels in sorted({8, configured, 24, 36}):
        t = effective_slope(angle, dx, dz, levels)
        mark = "  <- this run" if levels == configured else ""
        print(f"  {levels:>2} levels  offsets {t['offsets']:>3}  axis {t['axis_deg']:5.1f} deg  diagonal {t['diagonal_deg']:5.1f} deg{mark}")

    out = Path(cfg.output.directory) / f"{cfg.name}_blocks.csv"
    blocks = add_grid_indices(pd.read_csv(out))
    blocks["in_pit"] = blocks["in_pit"].astype(bool)
    elevation = load_elevation(cfg)

    def show(result: dict) -> None:
        for key, value in result.items():
            print(f"  {key:<45} {value:,.2f}" if isinstance(value, float) else f"  {key:<45} {value:,}")

    print(f"\n== 2. Pit walls on the surface ({int(blocks.in_pit.sum()):,} blocks in pit) ==")
    show(wall_check(cfg, blocks, elevation))

    print(f"\n== 3. True {angle} deg cone on every in-pit block (1 block slack) ==")
    show(cone_check(cfg, blocks))

    if cfg.design.enabled:
        d = cfg.design
        geometry = bench_geometry(angle, d.bench_height, d.bench_face_angle_deg, d.berm_width)
        grid = design_grid(blocks, elevation, d.cell)
        face = face_position(pit_shell(blocks, blocks["in_pit"].to_numpy(), grid, geometry), grid)
        print("\n== 5. Benched design surface ==")
        show(design_check(face, float(grid.xs[1] - grid.xs[0]), geometry.face_angle_deg,
                          geometry.overall_angle_deg, geometry.bench_run))

    if "period" in blocks.columns:
        print("\n== 4. Schedule order against the true cone ==")
        show(schedule_check(cfg, blocks))


if __name__ == "__main__":
    main()
