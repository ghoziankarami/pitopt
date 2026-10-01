"""
Production scheduling over the nested shells.

The shells are the pushbacks. Because every shell is a closed set — a
block can only be in a shell if all of its slope predecessors are too —
mining shell 1 to completion, then shell 2, and so on, is always
precedence-feasible. Ordering bench-downward inside each shell keeps it
feasible at the bench level as well, since a block's predecessors are by
definition above it.

Three sequences are available. The first two bracket the NPV; the third
is the one a mineral sands or other shallow, elongated deposit is actually
mined by:

  specified   pushback by pushback with a bench lag (specified_sequence) —
              the standard buildable case, between best and worst.

  best case   shell by shell, bench down inside each. Takes the highest
              value first, so it is the NPV ceiling — and it is not
              buildable as-is, because it ignores minimum mining width
              and the equipment cost of working many narrow pushbacks.

  worst case  bench by bench across the whole pit, ignoring shells. Every
              bench is stripped in full before the next begins, so waste
              is paid for long before the ore under it is reached. That
              is the NPV floor.

  strip       panels of a set width advancing along the deposit, with a
              face that slopes back at the wall angle — one contiguous
              working area, as a dry-mining or dredge operation runs.
              See strip_sequence for why it is always slope-feasible.

A buildable schedule lands between best and worst. Quoting the best case alone is the
standard way these numbers get oversold; the gap between them is the
prize a proper pushback design is competing for.

Periods are filled to a throughput limit on plant feed, and optionally to
a separate limit on total material moved. Cash flow is discounted at the
end of each period.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .economics import ORE


def _sequence(blocks: pd.DataFrame, in_pit: np.ndarray, by_shell: bool) -> np.ndarray:
    """Row order in which blocks are mined. Bench descending is what makes
    the order precedence-feasible; the shell key decides whether pushbacks
    are respected or the pit is taken in flat slices."""
    pit = blocks[in_pit]
    keys = (["shell", "bench"] if by_shell else ["bench"]) + ["x", "y"]
    ascending = ([True, False] if by_shell else [False]) + [True, True]
    return pit.sort_values(keys, ascending=ascending, kind="stable").index.to_numpy()


def strip_sequence(
    blocks: pd.DataFrame,
    in_pit: np.ndarray,
    width: float,
    face_angle_deg: float,
    axis: str = "auto",
    reverse: bool = False,
) -> tuple[np.ndarray, pd.Series, str]:
    """
    Strip (panel) mining order: the pit is taken in strips `width` wide,
    advancing along one axis, with the working face sloping back at the
    wall angle.

    Each block gets an effective advance position

        s_eff = s - z / tan(face_angle)

    where s is its distance along the advance direction. Deeper blocks
    fall further behind, so the face leans back instead of standing
    vertical against unmined ground. This is what keeps the sequence
    feasible, and not by luck: any block inside another block's slope cone
    sits at most dz / tan(angle) further forward and dz higher, which gives
    it an s_eff no larger than the lower block's. Taking strips of s_eff in
    order, bench downward inside each strip, can therefore never mine a
    block before one above it.

    `axis` "auto" advances along the pit's long dimension — for an
    elongated alluvial deposit, the direction a strip operation actually
    moves. Returns (order, panel per block, axis used).
    """
    pit = blocks[in_pit]
    if axis == "auto":
        axis = "y" if np.ptp(pit["y"].to_numpy()) >= np.ptp(pit["x"].to_numpy()) else "x"
    position = pit[axis].to_numpy()
    s = (position.max() - position) if reverse else (position - position.min())
    s_eff = s - pit["z"].to_numpy() / np.tan(np.radians(face_angle_deg))
    panel = np.floor((s_eff - s_eff.min()) / width).astype(int) + 1

    frame = pit.assign(_panel=panel, _s=s_eff)
    ordered = frame.sort_values(["_panel", "bench", "_s", "x", "y"], ascending=[True, False, True, True, True], kind="stable")
    return ordered.index.to_numpy(), pd.Series(panel, index=pit.index), axis


def specified_sequence(blocks: pd.DataFrame, in_pit: np.ndarray, pushback: np.ndarray, lag_benches: int) -> np.ndarray:
    """
    Whittle's specified case: pushbacks mined in order, each bench down,
    with pushback k+1 allowed to start once pushback k is `lag_benches`
    ahead of it.

    Each block gets a start time  t = (benches below the top) + lag * (pushback - 1).
    A slope predecessor sits at least one bench higher and in the same or
    an earlier pushback (the pushbacks are nested closures), so its t is
    strictly smaller — the sequence is feasible for any lag. A lag larger
    than the pit depth reproduces the best case; a lag of zero mines the
    pushbacks bench by bench together, close to the worst case.
    """
    pit = blocks[in_pit]
    top = int(pit["bench"].max())
    pb = pushback[in_pit]
    t = (top - pit["bench"].to_numpy()) + lag_benches * (pb - 1)
    frame = pit.assign(_t=t, _pb=pb)
    return frame.sort_values(["_t", "_pb", "x", "y"], kind="stable").index.to_numpy()


def group_strips(order: np.ndarray, panel: pd.Series, feed: pd.Series, count: int) -> pd.Series:
    """
    Group consecutive strips into `count` pushbacks of roughly equal plant
    feed. Cuts fall only on strip boundaries, in mining order, so every
    pushback is a contiguous band of whole strips — balanced tonnage
    between stages is the standard pushback-sizing criterion.
    """
    strips = panel.loc[order]
    per_strip = feed.loc[order].groupby(strips.to_numpy(), sort=False).sum()
    cumulative = per_strip.cumsum().to_numpy()
    total = cumulative[-1] if len(cumulative) else 0.0
    count = max(1, min(count, len(per_strip)))
    if total <= 0:
        groups = np.minimum(np.arange(len(per_strip)) * count // max(len(per_strip), 1) + 1, count)
    else:
        groups = np.minimum(np.floor((cumulative - per_strip.to_numpy() / 2) / total * count).astype(int) + 1, count)
    mapping = dict(zip(per_strip.index, groups))
    return panel.map(mapping).astype(int)


def schedule_production(
    blocks: pd.DataFrame,
    in_pit: np.ndarray,
    ore_capacity: float,
    total_capacity: float | None = None,
    discount_rate: float = 0.10,
    max_periods: int = 100,
    by_shell: bool = True,
    capacity_basis: str = "tonnes",
    order: np.ndarray | None = None,
) -> pd.DataFrame:
    """
    Fill periods in mining order up to capacity and discount the cash flow.

    ore_capacity   plant throughput per period, in tonnes or cubic metres
    total_capacity optional limit on all material moved per period
    capacity_basis "tonnes" or "volume" — which column the limits apply to
    order          explicit mining order (e.g. from strip_sequence); when
                   None, pushback order (by_shell) or bench order is used

    Returns one row per period.
    """
    feed_column = "ore_tonnes" if capacity_basis == "tonnes" else "volume"
    moved_column = "rock_tonnes" if capacity_basis == "tonnes" else "volume"

    if order is None:
        order = _sequence(blocks, in_pit, by_shell)
    pit = blocks.loc[order]

    is_ore = (pit["destination"].to_numpy() == ORE).astype(float)
    feed = pit[feed_column].to_numpy() * is_ore
    moved = pit[moved_column].to_numpy()
    value = pit["value"].to_numpy()

    # A block belongs to the period in which it starts: the cumulative
    # feed (and material moved) before it, divided by the capacity. This is
    # the sequential fill written as a cumulative sum, so a candidate
    # sequence can be scheduled in milliseconds during pushback search.
    started_feed = np.cumsum(feed) - feed
    period_index = np.floor(started_feed / ore_capacity).astype(int) + 1
    if total_capacity:
        started_moved = np.cumsum(moved) - moved
        period_index = np.maximum(period_index, np.floor(started_moved / total_capacity).astype(int) + 1)
    period_index = np.minimum(period_index, max_periods)

    # Within one bench of one stage the order of blocks is not a planning
    # decision — the bench is worked as a whole — so where a period boundary
    # cuts a bench, its cash is split in proportion to the feed on each side
    # rather than by whichever blocks happen to sort first. Without this the
    # NPV would depend on the row order of the input file.
    stage = pit["pushback"].to_numpy() if "pushback" in pit.columns else pit["shell"].to_numpy() if "shell" in pit.columns else np.zeros(len(pit))
    bench = pit["bench"].to_numpy()
    new_run = np.ones(len(pit), dtype=bool)
    new_run[1:] = (bench[1:] != bench[:-1]) | (stage[1:] != stage[:-1])
    run = np.cumsum(new_run) - 1
    run_value = np.bincount(run, weights=value)
    run_feed = np.bincount(run, weights=feed)
    run_moved = np.bincount(run, weights=moved)
    share = np.where(run_feed[run] > 0, feed / np.where(run_feed[run] > 0, run_feed[run], 1.0),
                     moved / np.where(run_moved[run] > 0, run_moved[run], 1.0))
    cash = run_value[run] * share

    scheduled = pit.assign(period=period_index, _is_ore=is_ore.astype(bool), _cash=cash)
    product_columns = [c for c in scheduled.columns if c.endswith("_tonnes") and c not in ("rock_tonnes", "ore_tonnes")]

    aggregation = {
        "blocks": ("value", "size"),
        "volume": ("volume", "sum"),
        "rock_tonnes": ("rock_tonnes", "sum"),
        "cash_flow": ("_cash", "sum"),
    }
    report = scheduled.groupby("period").agg(**aggregation)

    ore_only = scheduled[scheduled["_is_ore"]]
    report["ore_tonnes"] = ore_only.groupby("period")["ore_tonnes"].sum()
    report["ore_volume"] = ore_only.groupby("period")["volume"].sum()
    for column in product_columns:
        report[column] = ore_only.groupby("period")[column].sum()
    report = report.fillna(0.0)

    report["waste_tonnes"] = report["rock_tonnes"] - ore_only.groupby("period")["rock_tonnes"].sum().reindex(report.index).fillna(0.0)
    report["strip_ratio"] = np.where(report["ore_tonnes"] > 0, report["waste_tonnes"] / report["ore_tonnes"], np.nan)

    periods = report.index.to_numpy()
    report["discount_factor"] = 1.0 / (1.0 + discount_rate) ** periods
    report["discounted_cash_flow"] = report["cash_flow"] * report["discount_factor"]
    report["cumulative_cash_flow"] = report["cash_flow"].cumsum()
    report["npv"] = report["discounted_cash_flow"].cumsum()
    report = report.reset_index()
    # Period each block is mined in, keyed on the block model's own index —
    # what the per-period surfaces and the sequence check are built from.
    report.attrs["block_period"] = pd.Series(period_index, index=order)
    return report


def schedule_summary(schedule: pd.DataFrame) -> dict:
    return {
        "periods": int(schedule["period"].max()),
        "total_cash_flow": float(schedule["cash_flow"].sum()),
        "npv": float(schedule["discounted_cash_flow"].sum()),
        "ore_tonnes": float(schedule["ore_tonnes"].sum()),
        "waste_tonnes": float(schedule["waste_tonnes"].sum()),
        "volume": float(schedule["volume"].sum()),
    }
