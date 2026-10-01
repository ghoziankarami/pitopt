"""
Regularise a sub-celled or finely-estimated block model into mining blocks.

Pit optimisation needs one regular grid: the slope precedence is a fixed
offset template. Resource models often are not — they are sub-celled
(parent blocks split at contacts), or estimated at a vertical resolution
that is an estimation artefact rather than a bench. This aggregates any
such model onto a regular grid of the chosen mining block size.

Rules, and why:

- The target grid is anchored on the *parent* block grid, not on absolute
  coordinates and not on the outermost sub-cell. Anchoring anywhere else
  lets a parent straddle two target cells and its volume be counted twice.
  Any target cell that ends up holding more volume than it can contain
  aborts the run — that is a grid misalignment, never a rounding issue.
- Grades are averaged by volume, or by mass when a density column is given
  (a mass-percent grade must be weighted by tonnes). Averaging by block
  count would let a small sub-cell outvote a parent.
- Categorical fields (domain, resource class) take the value holding the
  most volume in the cell: a mining block is mined as one thing. Labels
  that are sub-divisions of one category (TERTUNJUK1, TERTUNJUK2) can be
  normalised first so the category's volume is not split.
- Cells at the edge of the model are only partly filled; the real volume
  and fill fraction are written so tonnes stay honest.

Volume is conserved exactly and the source volume is tabulated by the
categorical fields, so the result can be reconciled against a published
resource table before anything is optimised.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class ReblockSpec:
    source: str
    x: str
    y: str
    z: str
    size_x: str | None = None          # per-block size columns (sub-celled models)
    size_y: str | None = None
    size_z: str | None = None
    parent: tuple[float, float, float] | None = None   # fixed size when there are no size columns
    grades: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    density: str | None = None
    target: tuple[float, float, float] = (10.0, 10.0, 5.0)
    # Pattern removed from a categorical field before the dominant value is
    # picked, e.g. {"CLASS": r"\d+$"} so TERTUNJUK1 and TERTUNJUK2 count
    # together as one class instead of splitting its volume.
    normalise: dict = field(default_factory=dict)


def _chunks(path: str, chunksize: int = 400_000):
    if path.lower().endswith(".dat"):
        from ..io.datfile import read_dat

        return read_dat(path, chunksize=chunksize)
    return pd.read_csv(path, chunksize=chunksize)


def _sizes(chunk: pd.DataFrame, spec: ReblockSpec) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if spec.size_x and spec.size_y and spec.size_z:
        return (chunk[spec.size_x].to_numpy(float), chunk[spec.size_y].to_numpy(float), chunk[spec.size_z].to_numpy(float))
    if spec.parent is None:
        raise ValueError("give block-size columns or a fixed parent block size")
    n = len(chunk)
    return tuple(np.full(n, s) for s in spec.parent)


def _origin(spec: ReblockSpec) -> tuple[dict, dict]:
    """Lower edge of the parent grid, stepped down to cover every block."""
    edges = {"x": np.inf, "y": np.inf, "z": np.inf}
    parent_edges = {"x": np.inf, "y": np.inf, "z": np.inf}
    parent_size = {"x": 0.0, "y": 0.0, "z": 0.0}
    for chunk in _chunks(spec.source):
        sx, sy, sz = _sizes(chunk, spec)
        for key, centre, width in (("x", chunk[spec.x].to_numpy(float), sx),
                                   ("y", chunk[spec.y].to_numpy(float), sy),
                                   ("z", chunk[spec.z].to_numpy(float), sz)):
            edges[key] = min(edges[key], float((centre - width / 2).min()))
            parent_size[key] = max(parent_size[key], float(width.max()))
            is_parent = width == parent_size[key]
            if is_parent.any():
                parent_edges[key] = min(parent_edges[key], float((centre[is_parent] - width[is_parent] / 2).min()))
    origin = {}
    for key, step in zip("xyz", spec.target):
        anchor = parent_edges[key] if np.isfinite(parent_edges[key]) else edges[key]
        origin[key] = anchor - max(np.ceil((anchor - edges[key]) / step), 0.0) * step
    return origin, parent_size


def reblock(spec: ReblockSpec) -> tuple[pd.DataFrame, dict]:
    """Returns (regular blocks, summary). Output columns keep the source
    names for coordinates, grades and categories, plus `volume` and `FILL`."""
    origin, parent_size = _origin(spec)
    tx, ty, tz = spec.target
    parts, source_volume, tables = [], 0.0, []
    weight_name = "mass" if spec.density else "volume"

    for chunk in _chunks(spec.source):
        sx, sy, sz = _sizes(chunk, spec)
        volume = sx * sy * sz
        source_volume += float(volume.sum())
        weight = volume * chunk[spec.density].to_numpy(float) if spec.density else volume

        cell = pd.DataFrame({
            "gi": np.floor((chunk[spec.x].to_numpy(float) - origin["x"]) / tx).astype(int),
            "gj": np.floor((chunk[spec.y].to_numpy(float) - origin["y"]) / ty).astype(int),
            "gk": np.floor((chunk[spec.z].to_numpy(float) - origin["z"]) / tz).astype(int),
            "volume": volume,
            "_w": weight,
        })
        for g in spec.grades:
            cell[f"_g_{g}"] = weight * chunk[g].to_numpy(float)
        if spec.density:
            cell["_mass"] = weight
        for c in spec.categories:
            values = chunk[c].astype(str)
            if c in spec.normalise:
                values = values.str.replace(spec.normalise[c], "", regex=True)
            cell[c] = values.str.strip().to_numpy()

        sums = [c for c in cell.columns if c == "volume" or c.startswith("_")]
        numeric = cell.groupby(["gi", "gj", "gk"], as_index=False)[sums].sum()
        shares = [cell.groupby(["gi", "gj", "gk", c], as_index=False)["volume"].sum() for c in spec.categories]
        parts.append((numeric, shares))
        if spec.categories:
            tables.append(cell.groupby(spec.categories)["volume"].sum())

    numeric = pd.concat([p[0] for p in parts]).groupby(["gi", "gj", "gk"], as_index=False).sum()
    blocks = numeric
    for index, c in enumerate(spec.categories):
        share = pd.concat([p[1][index] for p in parts]).groupby(["gi", "gj", "gk", c], as_index=False)["volume"].sum()
        winner = share.sort_values("volume", ascending=False).drop_duplicates(["gi", "gj", "gk"])[["gi", "gj", "gk", c]]
        blocks = blocks.merge(winner, on=["gi", "gj", "gk"], how="left")

    blocks["FILL"] = blocks["volume"] / (tx * ty * tz)
    if (blocks["FILL"] > 1.0001).any():
        raise ValueError(
            f"{int((blocks['FILL'] > 1.0001).sum()):,} target cells hold more volume than they can "
            f"(max fill {blocks['FILL'].max():.3f}) — the target grid is not aligned with the source grid"
        )

    out = pd.DataFrame({
        spec.x: origin["x"] + (blocks["gi"] + 0.5) * tx,
        spec.y: origin["y"] + (blocks["gj"] + 0.5) * ty,
        spec.z: origin["z"] + (blocks["gk"] + 0.5) * tz,
    })
    for g in spec.grades:
        out[g] = np.where(blocks["_w"] > 0, blocks[f"_g_{g}"] / blocks["_w"], 0.0)
    if spec.density:
        out[spec.density] = np.where(blocks["volume"] > 0, blocks["_mass"] / blocks["volume"], 0.0)
    for c in spec.categories:
        out[c] = blocks[c]
    out["FILL"] = blocks["FILL"]
    out["volume"] = blocks["volume"]

    by_category = pd.concat(tables).groupby(level=list(range(len(spec.categories)))).sum() if tables else None
    summary = {
        "source_volume": source_volume,
        "output_volume": float(out["volume"].sum()),
        "blocks": len(out),
        "origin": origin,
        "parent_size": parent_size,
        "grade_weighting": weight_name,
        "source_volume_by_category": by_category,
    }
    return out, summary


def top_surface(blocks: pd.DataFrame, spec: ReblockSpec) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Top of the model per column (the top face of the highest block) —
    a stand-in topography when no usable surface was supplied."""
    tx, ty, tz = spec.target
    x, y, z = blocks[spec.x].to_numpy(), blocks[spec.y].to_numpy(), blocks[spec.z].to_numpy()
    xs, ys = np.unique(x), np.unique(y)
    xs = np.arange(xs.min(), xs.max() + tx / 2, tx)
    ys = np.arange(ys.min(), ys.max() + ty / 2, ty)
    gi = np.round((x - xs[0]) / tx).astype(int)
    gj = np.round((y - ys[0]) / ty).astype(int)
    grid = np.full((len(xs), len(ys)), np.nan)
    tops = pd.DataFrame({"gi": gi, "gj": gj, "z": z}).groupby(["gi", "gj"])["z"].max() + tz / 2
    grid[tops.index.get_level_values(0), tops.index.get_level_values(1)] = tops.to_numpy()
    return xs, ys, grid


def write_outputs(blocks: pd.DataFrame, spec: ReblockSpec, out_dir: str, name: str, surface: bool = True) -> dict:
    from ..io.dxf import write_surface

    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    written = {"blocks": str(path / f"{name}_blocks.csv")}
    blocks.round(6).to_csv(written["blocks"], index=False)
    if surface:
        xs, ys, grid = top_surface(blocks, spec)
        written["topo"] = str(path / f"{name}_topo.dxf")
        write_surface(written["topo"], xs, ys, grid, layer="TOPOGRAPHY")
    return written
