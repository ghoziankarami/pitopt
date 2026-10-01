"""
Slope precedence: which blocks must come out before a given block can.

The pattern is the usual fixed cone template on a regular block model —
block b's predecessors are the blocks in the benches above whose
horizontal offset falls inside the slope cone,
    offset <= (levels_above * dz) / tan(slope_angle)

Two things make this usable on a real model rather than a toy:

1. The template is *reduced*. Because the cone radius grows linearly with
   level, most higher-level offsets are just sums of lower-level ones and
   are already enforced transitively (b -> b+u -> b+u+w). Keeping only
   the irreducible offsets typically cuts the arc count by an order of
   magnitude with an identical closure. Set reduce_template=False for the
   literal full cone.

   Caveat worth knowing: a transitive chain needs its intermediate block
   to exist. Where the model has been clipped against steep topography an
   intermediate cell can be missing, which leaves that one path
   unconstrained at the crest edge. Use the full template if your
   topography is rugged and the crest position has to be exact.

2. Arc generation is vectorised over the grid instead of looping per
   block, which is the difference between seconds and hours at 10^5+
   blocks.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

MAX_LOOKUP_CELLS = 200_000_000
TEMPLATE_REACH_BLOCKS = 3


def auto_bench_levels(slope_angle_deg: float, dx: float, dz: float, minimum: int = 8) -> int:
    """
    How many benches the cone template has to span.

    The cone at n benches up has radius n * dz / tan(slope). Until that
    radius reaches the diagonal neighbour (dx * sqrt 2), diagonal walls are
    only constrained through two axis steps chained together, which makes
    them much steeper than the design angle. The fixed "8 levels" rule of
    thumb assumes roughly cubic blocks; on flat blocks — 10 m wide, 1 m
    high — 8 levels reach 14 m and leave the diagonal at ~40 degrees for a
    30 degree design. Sizing the template to reach a few blocks out keeps
    every direction within a couple of degrees of the target.
    """
    tan = math.tan(math.radians(slope_angle_deg))
    return max(minimum, int(math.ceil(TEMPLATE_REACH_BLOCKS * dx * tan / dz)))


def effective_slope(
    slope_angle_deg: float, dx: float, dz: float, max_levels: int, reduce_template: bool = True, height: int = 36
) -> dict:
    """
    Wall angle the template actually produces, measured by growing the
    closure of a single block `height` benches up and reading off how far
    it spreads along the grid axis and along the diagonal.
    """
    offsets = cone_offsets(slope_angle_deg, dx, dx, dz, max_levels, reduce_template)
    reach = int(height * dz / math.tan(math.radians(min(slope_angle_deg, 89.0))) / dx) + 4
    size = 2 * reach + 1
    required = np.zeros((height + 1, size, size), dtype=bool)
    required[0, reach, reach] = True
    for k in range(height):
        layer = np.argwhere(required[k])
        if not len(layer):
            continue
        for level, di, dj in offsets:
            if k + level > height:
                continue
            ii, jj = layer[:, 0] + di, layer[:, 1] + dj
            ok = (ii >= 0) & (ii < size) & (jj >= 0) & (jj < size)
            required[k + level, ii[ok], jj[ok]] = True

    top = np.argwhere(required[height]) - reach
    rise = height * dz
    axis = top[top[:, 1] == 0][:, 0]
    diagonal = top[top[:, 0] == top[:, 1]][:, 0]
    axis_run = float(np.abs(axis).max()) * dx if len(axis) else 0.0
    diagonal_run = float(np.abs(diagonal).max()) * dx * math.sqrt(2) if len(diagonal) else 0.0
    return {
        "offsets": len(offsets),
        "axis_deg": math.degrees(math.atan2(rise, axis_run)) if axis_run else 90.0,
        "diagonal_deg": math.degrees(math.atan2(rise, diagonal_run)) if diagonal_run else 90.0,
    }


def cone_offsets(
    slope_angle_deg: float, dx: float, dy: float, dz: float, max_levels: int, reduce_template: bool = True
) -> list[tuple[int, int, int]]:
    """Offsets (levels_up, di, dj) forming the precedence cone, optionally
    reduced to the irreducible generating set."""
    tan_slope = math.tan(math.radians(slope_angle_deg))
    full: list[tuple[int, int, int]] = []
    for n in range(1, max_levels + 1):
        radius = (n * dz) / tan_slope
        ri, rj = int(math.ceil(radius / dx)), int(math.ceil(radius / dy))
        for di in range(-ri, ri + 1):
            for dj in range(-rj, rj + 1):
                if math.hypot(di * dx, dj * dy) <= radius:
                    full.append((n, di, dj))

    if not reduce_template:
        return full

    cone = set(full)
    keep: list[tuple[int, int, int]] = []
    reachable: set[tuple[int, int, int]] = set()
    for offset in sorted(full, key=lambda o: (o[0], abs(o[1]) + abs(o[2]))):
        if offset in reachable:
            continue
        keep.append(offset)
        additions = {offset} | {
            (r[0] + offset[0], r[1] + offset[1], r[2] + offset[2]) for r in reachable
        }
        reachable |= {a for a in additions if a[0] <= max_levels and a in cone}
    return keep


def _lattice_index(values: pd.Series, step: pd.Series) -> np.ndarray:
    """Integer lattice index of each centre, measured from the lowest centre.

    Dividing the absolute coordinate by the block size (`round(x / dx)`) is not safe: centres that sit at
    half-block offsets from zero (x = 1010 with dx = 20) land exactly on .5, where round-half-to-even sends
    neighbours to the same integer or leaves gaps, and centres off the zero lattice (x = 650227.9, dx = 10)
    are shifted from their true position. Measuring from the lowest centre is exact for any origin. The
    offset added back keeps the index close to coordinate / size, so bench numbers stay familiar."""
    v = values.to_numpy(dtype=float)
    d = float(step.iloc[0])
    lo = float(v.min())
    return (np.floor((v - lo) / d + 0.5 + 1e-9) + np.floor(lo / d + 0.5)).astype(int)


def add_grid_indices(df: pd.DataFrame) -> pd.DataFrame:
    """Integer grid indices (bench, gi, gj) from centroid coordinates."""
    out = df.copy()
    out["gi"] = _lattice_index(out["x"], out["dx"])
    out["gj"] = _lattice_index(out["y"], out["dy"])
    out["bench"] = _lattice_index(out["z"], out["dz"])
    return out


def build_precedence(
    df: pd.DataFrame,
    slope_angle_deg: float,
    max_levels: int | None = None,
    reduce_template: bool = True,
    domain_angles: dict | None = None,
) -> np.ndarray:
    """
    Returns an (n_arcs, 2) int array of (block, predecessor) index pairs,
    indexed against df's positional order.

    With `domain_angles` and a 'domain' column present, each domain gets
    its own cone angle — the block's own domain decides the angle applied
    to it, which is the usual convention for geotechnical domains.
    """
    dx, dy, dz = float(df["dx"].iloc[0]), float(df["dy"].iloc[0]), float(df["dz"].iloc[0])
    bench = df["bench"].to_numpy()
    gi, gj = df["gi"].to_numpy(), df["gj"].to_numpy()

    b0, i0, j0 = bench.min(), gi.min(), gj.min()
    nb, ni, nj = bench.max() - b0 + 1, gi.max() - i0 + 1, gj.max() - j0 + 1
    if nb * ni * nj > MAX_LOOKUP_CELLS:
        raise MemoryError(
            f"Block model bounding box is {nb}x{ni}x{nj} cells — too sparse for the dense grid lookup. "
            "Trim the model extent or switch to a sparse precedence build."
        )

    lookup = np.full(nb * ni * nj, -1, dtype=np.int64)
    bi, ii, jj = bench - b0, gi - i0, gj - j0
    flat = (bi * ni + ii) * nj + jj
    lookup[flat] = np.arange(len(df))

    if domain_angles and "domain" in df.columns:
        groups = [
            (np.flatnonzero(df["domain"].to_numpy() == dom), float(angle))
            for dom, angle in domain_angles.items()
        ]
        covered = np.concatenate([g[0] for g in groups]) if groups else np.array([], dtype=int)
        rest = np.setdiff1d(np.arange(len(df)), covered)
        if len(rest):
            groups.append((rest, slope_angle_deg))
    else:
        groups = [(np.arange(len(df)), slope_angle_deg)]

    arcs: list[np.ndarray] = []
    for rows, angle in groups:
        if len(rows) == 0:
            continue
        levels = max_levels or auto_bench_levels(angle, min(dx, dy), dz)
        offsets = cone_offsets(angle, dx, dy, dz, levels, reduce_template)
        rb, ri_, rj_ = bi[rows], ii[rows], jj[rows]
        for level, di, dj in offsets:
            tb, ti, tj = rb + level, ri_ + di, rj_ + dj
            valid = (tb < nb) & (ti >= 0) & (ti < ni) & (tj >= 0) & (tj < nj)
            if not valid.any():
                continue
            target = lookup[(tb[valid] * ni + ti[valid]) * nj + tj[valid]]
            hit = target >= 0
            if hit.any():
                arcs.append(np.column_stack([rows[valid][hit], target[hit]]))

    if not arcs:
        return np.empty((0, 2), dtype=np.int64)
    return np.vstack(arcs)
