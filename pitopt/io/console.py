"""
Pit-by-pit reporting — the table the shell family exists to produce.

Every row is valued at the planning price, so the rows are comparable and
the value column peaks at the ultimate pit (RF 1.0) by construction: that
shell is, by definition, the block set that maximises value at that price.

What the table is actually for is the trade-off either side of that peak.
The inner shells (low RF) are the high-value core — small tonnage, low
strip, best grade — and are the natural first pushbacks. Moving outward,
each shell adds value more slowly while strip ratio climbs; where the
value curve flattens is where extra waste stops paying for itself. Shells
beyond RF 1.0 lose value at the planning price but show what the pit
would become if price ran higher, which is the price-sensitivity case.
"""
from __future__ import annotations

import pandas as pd

from ..config import EconomicsConfig


def format_report(report: pd.DataFrame, econ: EconomicsConfig) -> str:
    product_names = [p.name for p in econ.products]

    header = f"{'RF':>5} {'Blocks':>9} {'Rock Mt':>9} {'Ore Mt':>8} {'Waste Mt':>9} {'SR':>6}"
    for name in product_names:
        header += f" {name[:9] + ' t':>13}"
    header += f" {'Value':>16}"

    lines = [header, "-" * len(header)]
    for _, r in report.iterrows():
        line = (
            f"{r.revenue_factor:>5.2f} {int(r.blocks):>9,} {r.rock_tonnes / 1e6:>9.2f} "
            f"{r.ore_tonnes / 1e6:>8.2f} {r.waste_tonnes / 1e6:>9.2f} {r.strip_ratio:>6.2f}"
        )
        for name in product_names:
            line += f" {r[f'{name}_tonnes']:>13,.0f}"
        line += f" {r.value:>16,.0f}"
        lines.append(line)

    lines.append("")
    lines.append("Tonnes, product and value are quoted at the planning price for every shell.")
    return "\n".join(lines)


def summarise_pit(report: pd.DataFrame, depth: dict, econ: EconomicsConfig) -> str:
    """Summary of the selected final pit (or RF 1.0 when no selection ran)."""
    if "final_pit" in report and report["final_pit"].any():
        row = report[report["final_pit"]].iloc[0]
        basis = "chosen on discounted NPV" if "npv_best" in report else "RF 1.00, no schedule to discount"
        label = f"Final pit (RF {row.revenue_factor:.2f}, {basis})"
    else:
        at_one = report[report["revenue_factor"] == 1.0]
        row = at_one.iloc[0] if len(at_one) else report.loc[report["value"].idxmax()]
        label = f"Ultimate pit (RF {row.revenue_factor:.2f})"

    lines = [
        label,
        f"  Undiscounted value : {row.value:,.0f}",
        f"  Total volume       : {row.volume / 1e6:,.2f} Mm3",
        f"  Rock mined         : {row.rock_tonnes / 1e6:,.2f} Mt",
        f"  Plant feed         : {row.ore_tonnes / 1e6:,.2f} Mt ({row.ore_volume / 1e6:,.2f} Mm3)",
        f"  Waste              : {row.waste_tonnes / 1e6:,.2f} Mt (strip ratio {row.strip_ratio:.2f})",
    ]
    for product in econ.products:
        lines.append(f"  {product.name:<18} : {row[f'{product.name}_tonnes']:,.0f} t")
    lines += [
        f"  Crest RL           : {depth['crest_rl']:,.1f}",
        f"  Toe RL             : {depth['toe_rl']:,.1f}",
        f"  Maximum depth      : {depth['max_depth']:,.1f}",
    ]
    return "\n".join(lines)
