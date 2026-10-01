"""
Turn a solved pit into a surface.

The deliverable a planner or surveyor can actually use is a surface, not
a column of booleans: for every x/y column the pit surface sits at the
base of the lowest block taken out of that column, and reverts to
original topography wherever nothing was mined. Walls appear on their own
as the step between neighbouring columns, and the surface ties into the
natural ground at the crest, so it can be draped straight over the topo
in any design package.

Grid resolution is the block size — the surface is as detailed as the
model that produced it, and no smoother. Bench faces will look blocky at
coarse block sizes; that is honest, not an artifact to be polished out
before a design is put on it.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd


def pit_surface_grid(
    blocks: pd.DataFrame, in_pit: np.ndarray, elevation: Callable | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Returns (xs, ys, grid_z): 1-D node coordinates and the (len(xs), len(ys))
    elevation grid, NaN where there is neither topography nor model.
    """
    dx = float(blocks["dx"].iloc[0])
    dy = float(blocks["dy"].iloc[0])
    dz = float(blocks["dz"].iloc[0])

    gi, gj = blocks["gi"].to_numpy(), blocks["gj"].to_numpy()
    gi_values = np.arange(gi.min(), gi.max() + 1)
    gj_values = np.arange(gj.min(), gj.max() + 1)
    # true centre coordinates: the lowest column's centre plus whole blocks (never `index * size`, which
    # moves the surface by up to half a block whenever the model origin is not a multiple of the block size)
    x_first = float(blocks.loc[blocks["gi"] == gi.min(), "x"].min())
    y_first = float(blocks.loc[blocks["gj"] == gj.min(), "y"].min())
    xs, ys = x_first + (gi_values - gi.min()) * dx, y_first + (gj_values - gj.min()) * dy

    grid_z = np.full((len(gi_values), len(gj_values)), np.nan)

    if elevation is not None:
        mesh_x, mesh_y = np.meshgrid(xs, ys, indexing="ij")
        grid_z = np.asarray(elevation(mesh_x.ravel(), mesh_y.ravel()), dtype=float).reshape(mesh_x.shape)
    else:
        tops = blocks.groupby(["gi", "gj"])["z"].max() + dz / 2.0
        for (i, j), top in tops.items():
            grid_z[i - gi_values[0], j - gj_values[0]] = top

    if in_pit.any():
        floors = blocks[in_pit].groupby(["gi", "gj"])["z"].min() - dz / 2.0
        idx_i = floors.index.get_level_values(0).to_numpy() - gi_values[0]
        idx_j = floors.index.get_level_values(1).to_numpy() - gj_values[0]
        grid_z[idx_i, idx_j] = floors.to_numpy()

    return xs, ys, grid_z


def check_pit_closure(blocks: pd.DataFrame, in_pit: np.ndarray) -> dict:
    """
    Does the pit close inside the block model, or run into its edges?

    A pit that reaches the bottom bench or a lateral limit of the model is
    constrained by where the model stops, not by economics — the true
    optimum lies outside the data. That makes the tonnes and the pit
    outline understatements, and it is a modelling problem to fix before
    the result is used, not a result to report. Standard practice is to
    extend the model (even with barren blocks) until the pit closes
    within it.
    """
    if not in_pit.any():
        return {"closed": True, "on_bottom": 0, "on_sides": 0}

    pit = blocks[in_pit]
    on_bottom = int((pit["bench"] == blocks["bench"].min()).sum())
    on_sides = int(
        (
            (pit["gi"] == blocks["gi"].min())
            | (pit["gi"] == blocks["gi"].max())
            | (pit["gj"] == blocks["gj"].min())
            | (pit["gj"] == blocks["gj"].max())
        ).sum()
    )
    return {"closed": on_bottom == 0 and on_sides == 0, "on_bottom": on_bottom, "on_sides": on_sides}


def pit_depth_stats(blocks: pd.DataFrame, in_pit: np.ndarray, elevation: Callable | None = None) -> dict:
    """Crest/toe elevations and maximum depth — the numbers that get
    quoted about a pit before anything else."""
    if not in_pit.any():
        return {"crest_rl": float("nan"), "toe_rl": float("nan"), "max_depth": 0.0}

    pit = blocks[in_pit]
    dz = float(blocks["dz"].iloc[0])
    toe_rl = float(pit["z"].min() - dz / 2.0)

    if elevation is not None:
        crest = np.asarray(elevation(pit["x"].to_numpy(), pit["y"].to_numpy()), dtype=float)
        crest_rl = float(np.nanmax(crest))
    else:
        crest_rl = float(pit["z"].max() + dz / 2.0)

    return {"crest_rl": crest_rl, "toe_rl": toe_rl, "max_depth": crest_rl - toe_rl}
