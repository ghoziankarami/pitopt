"""
Price sensitivity on the designed pit.

This is a different question from the revenue-factor shells, and the two
are easy to confuse:

  RAF shells      re-optimise the pit at each price. They answer "how big
                  a pit would I design if the price were different?"

  sensitivity     holds the pit fixed and re-values it. It answers "I have
                  committed to this pit — what happens to it if price
                  moves?" That is the decision-relevant one once a design
                  is chosen, because the pit outline is not re-cut every
                  time the market moves.

The destination decision is still re-made at each price, since a block
that is marginal feed at the planning price becomes waste below it, and
the plant would not be fed material that loses money.

NPV is recomputed on the same mining sequence, so the schedule is held
constant and only the cash flow moves.
"""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from ..config import EconomicsConfig
from .economics import ORE, value_blocks
from .schedule import schedule_production


def _flexed(econ: EconomicsConfig, factor: float, products: list[str] | None) -> EconomicsConfig:
    flexed = copy.deepcopy(econ)
    for product in flexed.products:
        if products is None or product.name in products:
            product.price *= factor
    return flexed


def price_sensitivity(
    blocks: pd.DataFrame,
    in_pit: np.ndarray,
    econ: EconomicsConfig,
    factors: list[float],
    ore_capacity: float,
    total_capacity: float | None = None,
    discount_rate: float = 0.10,
    capacity_basis: str = "tonnes",
    products: list[str] | None = None,
    order: np.ndarray | None = None,
) -> pd.DataFrame:
    """
    Re-value and re-schedule the fixed pit across a range of price factors.

    `products` limits the flex to named products, for the one-at-a-time
    case; leave it None to move every price together.
    """
    rows = []
    for factor in factors:
        revalued = value_blocks(blocks, _flexed(econ, factor, products))
        revalued["shell"] = blocks["shell"].to_numpy()

        pit = revalued[in_pit]
        is_ore = pit["destination"].to_numpy() == ORE
        schedule = schedule_production(
            revalued, in_pit, ore_capacity, total_capacity, discount_rate, capacity_basis=capacity_basis, order=order
        )

        rows.append(
            {
                "price_factor": factor,
                "value": float(pit["value"].sum()),
                "npv": float(schedule["discounted_cash_flow"].sum()),
                "ore_tonnes": float(pit.loc[is_ore, "ore_tonnes"].sum()),
                "waste_tonnes": float(pit.loc[~is_ore, "rock_tonnes"].sum()),
                "periods": int(schedule["period"].max()),
                "blocks_as_ore": int(is_ore.sum()),
            }
        )
    return pd.DataFrame(rows)


def breakeven_price_factor(sensitivity: pd.DataFrame, column: str = "value") -> float:
    """Price factor at which the fixed pit's value crosses zero, linearly
    interpolated between the bracketing cases. NaN if it never crosses in
    the range tested."""
    ordered = sensitivity.sort_values("price_factor")
    factors = ordered["price_factor"].to_numpy()
    values = ordered[column].to_numpy()

    for i in range(len(values) - 1):
        if values[i] <= 0 <= values[i + 1]:
            span = values[i + 1] - values[i]
            if span == 0:
                return float(factors[i])
            return float(factors[i] + (factors[i + 1] - factors[i]) * (-values[i] / span))
    return float("nan")
