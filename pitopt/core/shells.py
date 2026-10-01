"""
Nested pit shells by revenue factor (the Whittle / RAF parameterisation).

The price is scaled by each revenue factor and the pit re-solved. Low
factors isolate the highest-value core (the natural first pushback),
RF 1.0 is the ultimate pit at the planning price, and factors above 1.0
show how much the shell would grow if price ran higher — the standard
basis for pushback selection and price sensitivity.

Every shell is *reported* at the planning price, not at the factor that
generated it. The revenue factor decides which blocks are in the shell;
the mine would still be operated at the real price, so that is what the
tonnes, grades and cash flow have to be quoted at. Reporting each shell
at its own inflated price would make the table incomparable row-to-row
and would always flatter the largest factor.

The precedence graph is independent of price, so it is built once and
reused across every factor; only valuation and the solve repeat.

Shells are mathematically nested — a higher factor can only add blocks.
A violation would point to a numerical problem, so it is counted and
surfaced rather than quietly smoothed over.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import EconomicsConfig
from .economics import ORE, value_blocks
from .solver import solve_max_closure


def _shell_stats(planning: pd.DataFrame, in_pit: np.ndarray, econ: EconomicsConfig, rf: float) -> dict:
    """Tonnes, grade and cash flow for one shell, all at the planning price."""
    pit = planning[in_pit]
    is_ore = pit["destination"].to_numpy() == ORE
    ore = pit[is_ore]

    volume = float(pit["volume"].sum())
    rock_tonnes = float(pit["rock_tonnes"].sum())
    ore_volume = float(ore["volume"].sum())
    ore_tonnes = float(ore["ore_tonnes"].sum())
    waste_tonnes = rock_tonnes - float(ore["rock_tonnes"].sum())

    stats = {
        "revenue_factor": rf,
        "blocks": int(in_pit.sum()),
        "volume": volume,
        "rock_tonnes": rock_tonnes,
        "ore_volume": ore_volume,
        "ore_tonnes": ore_tonnes,
        "waste_tonnes": waste_tonnes,
        "strip_ratio": waste_tonnes / ore_tonnes if ore_tonnes > 0 else float("nan"),
        "revenue": float(ore["revenue"].sum()),
        "value": float(pit["value"].sum()),
    }
    for product in econ.products:
        stats[f"{product.name}_tonnes"] = float(ore[f"{product.name}_tonnes"].sum())
    return stats


def run_nested_shells(
    df: pd.DataFrame, arcs: np.ndarray, econ: EconomicsConfig, revenue_factors: list[float],
    on_progress=None,
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """
    Returns (blocks, report, nesting_violations).

    blocks: the block model valued at the planning price, plus
        shell    smallest shell index containing the block (1-based; 0 = in no shell)
        in_pit   in the RF 1.0 ultimate pit, or the largest shell if 1.0 was not run
    report: one row per revenue factor — the pit-by-pit table.
    """
    factors = sorted(revenue_factors)
    planning = value_blocks(df, econ, revenue_factor=1.0)

    shell = np.zeros(len(df), dtype=int)
    ultimate: np.ndarray | None = None
    previous = np.zeros(len(df), dtype=bool)
    rows, violations = [], 0

    for n, rf in enumerate(factors, start=1):
        valued = planning if rf == 1.0 else value_blocks(df, econ, revenue_factor=rf)
        in_pit = solve_max_closure(valued["value"].to_numpy(), arcs)

        violations += int((previous & ~in_pit).sum())
        shell[(shell == 0) & in_pit] = n
        previous = in_pit

        rows.append(_shell_stats(planning, in_pit, econ, rf))
        if on_progress:
            on_progress(n, len(factors))
        if rf == 1.0:
            ultimate = in_pit

    blocks = planning
    blocks["shell"] = shell
    blocks["in_pit"] = ultimate if ultimate is not None else (shell > 0)
    return blocks, pd.DataFrame(rows), violations
