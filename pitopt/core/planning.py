"""
Strategic pit planning, following the standard nested-shell workflow
(Whittle's methodology, used the same way in Datamine NPVS, Deswik and
Micromine):

  1. Nested shells — the ultimate pit re-solved over a range of revenue
     factors (shells.py).
  2. Pit-by-pit analysis — every shell is *scheduled and discounted*, once
     in the best-case order (shell by shell) and once in the worst-case
     order (bench by bench). This is the pit-by-pit graph.
  3. Final pit selection — on discounted value, not on RF 1.0. The RF 1.0
     shell maximises undiscounted cash flow; once cash is discounted, the
     outer shells' waste is paid for years before their ore arrives, and
     the NPV-optimal pit is smaller — commonly somewhere around RF 0.6-0.9.
  4. Pushback selection — a small number of the shells inside the final pit
     are chosen as pushback boundaries. The aim is a specified-case NPV as
     close to the best case as the pushbacks' practical constraints allow:
     each pushback big enough to be a real mining stage, and wide enough
     to operate in.
  5. Specified case — pushbacks mined in order with a bench lag
     (schedule.specified_sequence). This is the schedule reported as the
     plan; best and worst case bracket it.

For shallow, elongated deposits (mineral sands, alluvials) step 4 is
replaced by strips: the final pit is taken in panels advancing along the
deposit, which is how those operations are actually run.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from scipy import ndimage

from .schedule import schedule_production, schedule_summary, specified_sequence


def _npv(blocks, mask, capacity, total_capacity, rate, basis, *, by_shell=True, order=None) -> tuple[float, int]:
    schedule = schedule_production(
        blocks, mask, capacity, total_capacity, rate, by_shell=by_shell, capacity_basis=basis, order=order
    )
    summary = schedule_summary(schedule)
    return summary["npv"], summary["periods"]


def pit_by_pit_npv(
    blocks: pd.DataFrame,
    report: pd.DataFrame,
    capacity: float,
    total_capacity: float | None,
    discount_rate: float,
    basis: str,
    on_progress=None,
) -> pd.DataFrame:
    """Adds discounted best / worst case NPV to the pit-by-pit table."""
    shell = blocks["shell"].to_numpy()
    rows = []
    total = len(report)
    for n, _rf in enumerate(report["revenue_factor"], start=1):
        if on_progress:
            on_progress(n, total)
        mask = (shell > 0) & (shell <= n)
        if not mask.any():
            rows.append({"npv_best": 0.0, "npv_worst": 0.0, "periods": 0})
            continue
        best, periods = _npv(blocks, mask, capacity, total_capacity, discount_rate, basis, by_shell=True)
        worst, _ = _npv(blocks, mask, capacity, total_capacity, discount_rate, basis, by_shell=False)
        rows.append({"npv_best": best, "npv_worst": worst, "periods": periods})
    extra = pd.DataFrame(rows)
    out = report.reset_index(drop=True).copy()
    out["shell"] = np.arange(1, len(out) + 1)
    out["npv_best"] = extra["npv_best"]
    out["npv_worst"] = extra["npv_worst"]
    out["npv_average"] = (extra["npv_best"] + extra["npv_worst"]) / 2.0
    out["periods"] = extra["periods"]
    return out


def select_final_pit(
    table: pd.DataFrame, criterion: str = "average", tolerance: float = 0.0, revenue_factor: float | None = None
) -> tuple[int, str]:
    """
    Choose the final pit shell from the discounted pit-by-pit table.

    criterion  which NPV to maximise: best | worst | average. The average
               of best and worst is the usual stand-in for a specified
               schedule that has not been built yet.
    tolerance  take the *smallest* shell within this fraction of the
               maximum. The top of the NPV curve is usually flat, and the
               smaller pit earns almost the same value with less capital
               at risk and less exposure to price — standard practice is to
               stop where the curve flattens, not at its last increment.
    """
    if revenue_factor is not None:
        match = table.index[np.isclose(table["revenue_factor"], revenue_factor)]
        if not len(match):
            raise ValueError(f"final_pit.revenue_factor {revenue_factor} is not one of the shells run")
        n = int(table.loc[match[0], "shell"])
        return n, f"fixed at RF {revenue_factor:.2f} by configuration"

    column = {"best": "npv_best", "worst": "npv_worst", "average": "npv_average"}[criterion]
    values = table[column].to_numpy()
    best_value = values.max()
    if best_value <= 0:
        raise ValueError("No shell has a positive discounted NPV — there is no economic pit at these inputs.")
    eligible = np.flatnonzero(values >= best_value * (1.0 - tolerance))
    n = int(table["shell"].iloc[eligible.min()])
    peak = int(table["shell"].iloc[int(values.argmax())])
    reason = f"maximum {criterion}-case NPV"
    if n != peak:
        reason = (
            f"smallest shell within {tolerance:.0%} of the maximum {criterion}-case NPV "
            f"(peak at RF {table['revenue_factor'].iloc[peak - 1]:.2f})"
        )
    return n, reason


def narrow_fraction(blocks: pd.DataFrame, mask: np.ndarray, min_width: float) -> float:
    """Share of a pushback's plan area narrower than the minimum mining
    width, measured by morphological opening with a square the size of that
    width: whatever the square cannot fit into is too narrow to work."""
    if not mask.any():
        return 0.0
    dx = float(blocks["dx"].iloc[0])
    gi, gj = blocks["gi"].to_numpy(), blocks["gj"].to_numpy()
    i0, j0 = gi.min(), gj.min()
    plan = np.zeros((gi.max() - i0 + 1, gj.max() - j0 + 1), dtype=bool)
    plan[gi[mask] - i0, gj[mask] - j0] = True
    size = max(1, int(round(min_width / dx)))
    kept = ndimage.binary_opening(plan, structure=np.ones((size, size)))
    return 1.0 - kept.sum() / plan.sum()


def select_pushbacks(
    blocks: pd.DataFrame,
    final_shell: int,
    capacity: float,
    total_capacity: float | None,
    discount_rate: float,
    basis: str,
    max_pushbacks: int = 5,
    min_tonnes: float = 0.0,
    min_width: float = 0.0,
    max_narrow: float = 0.30,
    lag_benches: int = 10,
    exact_count: int | None = None,
) -> tuple[list[int], pd.DataFrame]:
    """
    Choose which shells inside the final pit become pushback boundaries.

    Every combination of up to `max_pushbacks` boundaries — or exactly
    `exact_count` when the number of pushbacks is fixed — is tried (the
    final shell is always the last one). A combination is practical when
    every pushback moves at least `min_tonnes` and no more than
    `max_narrow` of its area is narrower than `min_width`. Among the
    practical ones, the specified-case NPV decides. Candidates that fail a
    constraint are kept in the returned table so the reason a seemingly
    better split was rejected is visible.
    """
    shell = blocks["shell"].to_numpy()
    tonnes = blocks["rock_tonnes"].to_numpy()
    occupied = [n for n in range(1, final_shell + 1) if (shell == n).any()]
    interior = [n for n in occupied if n != final_shell]

    if exact_count is not None:
        exact_count = max(1, min(exact_count, len(occupied)))
        cut_counts = [exact_count - 1]
    else:
        cut_counts = range(0, min(max_pushbacks, len(occupied)))

    candidates = []
    for k in cut_counts:
        for cuts in combinations(interior, k):
            boundaries = list(cuts) + [final_shell]
            pushback = np.zeros(len(blocks), dtype=int)
            previous = 0
            ok, narrowest, smallest = True, 0.0, float("inf")
            for index, boundary in enumerate(boundaries, start=1):
                ring = (shell > previous) & (shell <= boundary)
                pushback[ring] = index
                ring_tonnes = float(tonnes[ring].sum())
                smallest = min(smallest, ring_tonnes)
                narrow = narrow_fraction(blocks, ring, min_width) if min_width > 0 else 0.0
                narrowest = max(narrowest, narrow)
                if ring_tonnes < min_tonnes or narrow > max_narrow:
                    ok = False
                previous = boundary
            mask = pushback > 0
            order = specified_sequence(blocks, mask, pushback, lag_benches)
            npv, periods = _npv(blocks, mask, capacity, total_capacity, discount_rate, basis, order=order)
            candidates.append(
                {
                    "boundaries": boundaries,
                    "pushbacks": len(boundaries),
                    "npv_specified": npv,
                    "smallest_pushback_tonnes": smallest,
                    "worst_narrow_fraction": narrowest,
                    "practical": ok,
                    "periods": periods,
                }
            )

    table = pd.DataFrame(candidates).sort_values("npv_specified", ascending=False).reset_index(drop=True)
    practical = table[table["practical"]]
    chosen = practical.iloc[0] if len(practical) else table.sort_values(
        ["worst_narrow_fraction", "npv_specified"], ascending=[True, False]
    ).iloc[0]
    selected = list(chosen["boundaries"])
    table["selected"] = table["boundaries"].apply(lambda b: b == selected)
    table["boundaries"] = table["boundaries"].apply(lambda b: ", ".join(str(x) for x in b))
    return selected, table


def pushback_labels(boundaries: list[int], shell: np.ndarray) -> np.ndarray:
    """Pushback number for every block from the chosen shell boundaries
    (0 = outside the final pit)."""
    pushback = np.zeros(len(shell), dtype=int)
    previous = 0
    for index, boundary in enumerate(boundaries, start=1):
        pushback[(shell > previous) & (shell <= boundary)] = index
        previous = boundary
    return pushback
