"""
End-to-end run: block model + topography in, pit shells out.

Order matters here. Blocks above topography are dropped before anything
else so they can never be "mined"; precedence is built once against the
remaining blocks since slope geometry doesn't care about price; then each
revenue factor is valued and solved against that one graph.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from scipy import ndimage

from .config import ProjectConfig
from .core.cancel import CancelToken
from .core.design import bench_geometry, design_grid, face_position, pit_shell, reconcile, shell_for_display
from .core.design_detail.builder import build_design
from .core.limits import check_solver_memory
from .core.pitsurface import check_pit_closure, pit_depth_stats, pit_surface_grid
from .core.planning import pit_by_pit_npv, pushback_labels, select_final_pit, select_pushbacks
from .core.precedence import add_grid_indices, auto_bench_levels, build_precedence, cone_offsets
from .core.schedule import group_strips, schedule_production, schedule_summary, specified_sequence, strip_sequence
from .core.sensitivity import breakeven_price_factor, price_sensitivity
from .core.shells import run_nested_shells
from .io import dxf
from .io.blockmodel import load_block_model, write_block_model


@dataclass
class PitResult:
    blocks: pd.DataFrame
    report: pd.DataFrame
    depth: dict
    closure: dict
    nesting_violations: int
    outputs: dict
    schedule: pd.DataFrame | None = None
    schedule_worst: pd.DataFrame | None = None
    sensitivity: pd.DataFrame | None = None
    sensitivity_by_product: pd.DataFrame | None = None
    bench: pd.DataFrame | None = None
    pushbacks: pd.DataFrame | None = None
    schedule_best: pd.DataFrame | None = None
    pushback_candidates: pd.DataFrame | None = None
    final_shell: int = 0
    final_rf: float = 1.0
    final_reason: str = ""
    plan_label: str = ""
    pushback_reason: str = ""
    design: dict | None = None
    design_geometry: object | None = None
    verification: dict | None = None
    design_detail: object | None = None       # DesignDetail when design.detail is enabled (F-DES-6)


def load_elevation(cfg: ProjectConfig) -> Callable | None:
    surface = cfg.surface
    if not surface.path:
        return None
    if surface.format.lower() == "dxf":
        return dxf.read_surface(surface.path)
    points = pd.read_csv(surface.path)[[surface.x_col, surface.y_col, surface.z_col]].to_numpy(dtype=float)
    return dxf.elevation_from_points(points)


def clip_to_surface(blocks: pd.DataFrame, elevation: Callable | None) -> pd.DataFrame:
    """Drop blocks whose centroid sits above ground — air, not rock."""
    if elevation is None:
        return blocks
    surface_z = np.asarray(elevation(blocks["x"].to_numpy(), blocks["y"].to_numpy()), dtype=float)
    below = blocks["z"].to_numpy() <= surface_z
    if not below.any():
        raise ValueError(
            "Every block sits above the supplied surface — check that the block model and "
            "surface share a coordinate system and elevation datum."
        )
    return blocks[below].reset_index(drop=True)



ASSUMPTIONS = [
    "Ultimate pit and nested shells only — undiscounted optimisation. The schedule is a "
    "capacity-filled sequence over those shells, not an NPV-optimised one.",
    "The best-case schedule mines shell by shell and is an NPV ceiling: it ignores minimum "
    "mining width, ramp access and the cost of working narrow pushbacks.",
    "Slope is a single overall angle applied in every direction. No azimuth variation, no ramp "
    "allowance, no bench/berm geometry. The result is an optimisation shell, not a pit design.",
    "One destination per block — plant or waste. No stockpiles, no blending, no alternative "
    "process routes.",
    "Grades are taken as estimated, with no allowance for grade uncertainty. Grade risk needs "
    "conditional simulation across multiple realisations.",
    "Costs are flat: no haulage-distance or depth-dependent mining cost.",
    "Revenue factors re-optimise the pit; the sensitivity holds the pit fixed. They answer "
    "different questions and should not be read as one series.",
]


def bench_summary(blocks: pd.DataFrame, in_pit: np.ndarray, econ) -> pd.DataFrame:
    """Ore, waste and product by elevation — how the pit stacks up bench by bench."""
    pit = blocks[in_pit]
    is_ore = pit["destination"].to_numpy() == 1
    frame = pit.assign(
        ore_t=np.where(is_ore, pit["ore_tonnes"], 0.0),
        waste_t=np.where(~is_ore, pit["rock_tonnes"], 0.0),
    )
    aggregation = {
        "blocks": ("value", "size"),
        "volume": ("volume", "sum"),
        "ore_tonnes": ("ore_t", "sum"),
        "waste_tonnes": ("waste_t", "sum"),
        "value": ("value", "sum"),
    }
    summary = frame.groupby("bench").agg(**aggregation)
    for product in econ.products:
        column = f"{product.name}_tonnes"
        summary[column] = frame.loc[is_ore].groupby("bench")[column].sum()
    summary = summary.fillna(0.0).sort_index(ascending=False).reset_index()
    if "dz" in blocks.columns:
        summary.insert(1, "rl", summary["bench"].map(blocks.groupby("bench")["z"].mean()))
    return summary


def _stack_sensitivity(combined, per_product):
    if combined is None:
        return per_product
    combined = combined.assign(product="ALL")
    return combined if per_product is None else pd.concat([combined, per_product], ignore_index=True)


def _ultimate_row(result: PitResult):
    """The selected final pit's row of the pit-by-pit table."""
    return result.report.iloc[result.final_shell - 1]


def headline_pairs(cfg: ProjectConfig, result: PitResult) -> list:
    row = _ultimate_row(result)
    pairs = [
        ("Final pit", f"shell {result.final_shell}, RF {result.final_rf:.2f} — {result.final_reason}"),
        ("Undiscounted value", f"{row.value:,.0f}"),
        ("Total volume", f"{row.volume / 1e6:,.2f} Mm3"),
        ("Rock mined", f"{row.rock_tonnes / 1e6:,.2f} Mt"),
        ("Plant feed", f"{row.ore_tonnes / 1e6:,.2f} Mt"),
        ("Waste", f"{row.waste_tonnes / 1e6:,.2f} Mt (strip ratio {row.strip_ratio:,.2f})"),
    ]
    for product in cfg.economics.products:
        pairs.append((product.name.title(), f"{row[f'{product.name}_tonnes']:,.0f} t"))
    pairs += [
        ("Crest RL", f"{result.depth['crest_rl']:,.1f}"),
        ("Toe RL", f"{result.depth['toe_rl']:,.1f}"),
        ("Maximum depth", f"{result.depth['max_depth']:,.1f} m"),
    ]
    if result.design is not None:
        g = result.design_geometry
        dsg = result.design
        pairs.append((
            "Pit design",
            f"benches {g.bench_height:g} m, face {g.face_angle_deg:g} deg, berm {g.berm_width:.2f} m "
            f"(overall {g.overall_angle_deg:.1f} deg)",
        ))
        pairs.append((
            "Design vs optimiser shell",
            f"rock {dsg['rock_tonnes_change']:+.1%}, ore {dsg['ore_tonnes_change']:+.1%}, value {dsg['value_change']:+.1%} "
            f"(design value {dsg['design']['value']:,.0f})",
        ))
    at_one = result.report[np.isclose(result.report["revenue_factor"], 1.0)]
    if len(at_one) and result.final_shell != int(at_one["shell"].iloc[0]):
        one = at_one.iloc[0]
        pairs.append((
            "RF 1.00 pit (max undiscounted)",
            f"value {one.value:,.0f}, {one.rock_tonnes / 1e6:,.2f} Mt rock — not selected: its outer shells "
            "add undiscounted value but lose discounted value",
        ))
    if result.schedule is not None:
        summary = schedule_summary(result.schedule)
        pairs.append(("Mining plan", result.plan_label))
        pairs.append(("Pushback count", result.pushback_reason))
        pairs.append(("Mine life", f"{summary['periods']} periods"))
        pairs.append((f"NPV @ {cfg.schedule.discount_rate:.0%} (plan)", f"{summary['npv']:,.0f}"))
        low = schedule_summary(result.schedule_worst)["npv"] if result.schedule_worst is not None else None
        high = schedule_summary(result.schedule_best)["npv"] if result.schedule_best is not None else None
        if high is not None:
            pairs.append(("NPV bracket", (f"{low:,.0f} worst case — " if low is not None else "") + f"{high:,.0f} best case"))
    if result.sensitivity is not None:
        breakeven = breakeven_price_factor(result.sensitivity)
        if breakeven == breakeven:
            pairs.append(("Break-even price", f"{breakeven:.1%} of planning price"))
    return pairs


def headline_frame(cfg: ProjectConfig, result: PitResult) -> pd.DataFrame:
    return pd.DataFrame(headline_pairs(cfg, result), columns=["Item", "Value"])


def parameter_pairs(cfg: ProjectConfig) -> list:
    econ = cfg.economics
    pairs = [
        ("Block model", Path(cfg.block_model.path).name),
        ("Surface", Path(cfg.surface.path).name if cfg.surface.path else "(none)"),
        ("Block size", f"{cfg.block_model.dx} x {cfg.block_model.dy} x {cfg.block_model.dz} m"),
        ("Density", f"{cfg.block_model.density} t/m3"),
        ("Resource classes", ", ".join(cfg.block_model.include_classes) or "all"),
        ("Ore domains", ", ".join(cfg.block_model.ore_domains) or "all"),
        ("Slope", f"{cfg.slope.overall_angle_deg} deg, template {cfg.slope.max_bench_levels or 'auto'} bench levels"),
        ("Grade basis", econ.grade_basis),
        ("Mining recovery", f"{econ.mining_recovery:.1%}"),
        ("Dilution", f"{econ.dilution:.1%}"),
        ("Mining cost", f"{econ.mining_cost_per_volume:,.2f}/m3 + {econ.mining_cost_per_tonne:,.2f}/t"),
        ("Rehabilitation", f"{econ.rehabilitation_cost_per_volume:,.2f}/m3 + {econ.rehabilitation_cost_per_tonne:,.2f}/t"),
        ("Processing (feed)", f"{econ.processing_cost_per_volume:,.2f}/m3 + {econ.processing_cost_per_tonne:,.2f}/t"),
        ("Royalty", f"{econ.royalty_rate:.1%}"),
    ]
    for product in econ.products:
        pairs.append(
            (
                f"Product: {product.name}",
                f"price {product.price:,.2f}/t, plant recovery {product.plant_recovery:.1%}, "
                f"processing {product.processing_cost_per_tonne:,.2f}/t, "
                f"selling {product.selling_cost_per_tonne:,.2f}/t + {product.selling_cost_per_volume:,.2f}/m3",
            )
        )
    pairs.append(("Revenue factors", ", ".join(f"{rf:g}" for rf in sorted(cfg.shells.revenue_factors))))
    fp = cfg.final_pit
    pairs.append(("Final pit rule", f"RF {fp.revenue_factor:.2f} fixed" if fp.revenue_factor else
                  f"max {fp.criterion}-case NPV, smallest shell within {fp.tolerance:.0%}"))
    pb = cfg.pushbacks
    if pb.method == "strips":
        pairs.append(("Pushbacks", f"strips {pb.strip_width:g} m, axis {pb.strip_axis}, direction {pb.strip_direction}"))
    else:
        pairs.append(("Pushbacks", f"up to {pb.max_pushbacks} from shells, min width {pb.min_width:g} m "
                      f"(max {pb.max_narrow:.0%} narrower), bench lag {pb.bench_lag_m:g} m"))
    if cfg.schedule.enabled:
        unit = "t" if cfg.schedule.basis == "tonnes" else "m3"
        pairs.append(("Plant capacity", f"{cfg.schedule.ore_capacity:,.0f} {unit}/period"))
        if cfg.schedule.total_capacity:
            pairs.append(("Mining capacity", f"{cfg.schedule.total_capacity:,.0f} {unit}/period"))
        pairs.append(("Discount rate", f"{cfg.schedule.discount_rate:.1%}"))
    return pairs


MAX_DXF_FACETS = 200_000     # per final surface; a 3DFACE is ~150 bytes of DXF and ~5 kB once parsed


def run_notes(cfg: ProjectConfig, result: PitResult) -> dict:
    notes = {
        "final_pit_shell": result.final_shell,
        "final_pit_revenue_factor": result.final_rf,
        "final_pit_reason": result.final_reason,
        "mining_plan": result.plan_label,
        "pushback_count_rule": result.pushback_reason,
        "blocks_in_model": len(result.blocks),
        "blocks_in_final_pit": int(result.blocks["in_pit"].sum()),
        "pit_closed_within_model": result.closure["closed"],
        "blocks_on_bottom_bench": result.closure["on_bottom"],
        "blocks_on_lateral_limit": result.closure["on_sides"],
        "shell_nesting_violations": result.nesting_violations,
    }
    if result.schedule is not None:
        notes.update({f"schedule_{k}": v for k, v in schedule_summary(result.schedule).items()})
    return notes


def collect_warnings(cfg: ProjectConfig, result: PitResult) -> list:
    warnings = []
    if not result.closure["closed"]:
        warnings.append(
            f"Pit is not closed inside the block model: {result.closure['on_bottom']:,} blocks sit on the "
            f"bottom bench and {result.closure['on_sides']:,} on a lateral limit. The shell is cut off by the "
            "model extent rather than by economics, so tonnes and the pit outline are understated. Extend the "
            "model until the pit closes within it."
        )
    candidates = result.pushback_candidates
    if candidates is not None and len(candidates) and not candidates["practical"].any():
        warnings.append(
            f"No split of the final pit into {int(candidates['pushbacks'].iloc[0])} shell pushbacks meets the "
            f"minimum mining width and tonnage ({len(candidates)} candidates tried); the least narrow split was "
            "used. Consider fewer pushbacks or strip mining for this deposit."
        )
    if result.nesting_violations:
        warnings.append(
            f"{result.nesting_violations:,} blocks left a larger shell — nested shells should only grow. "
            "Check for numerical problems before relying on the shell sequence."
        )
    if result.sensitivity is not None:
        breakeven = breakeven_price_factor(result.sensitivity)
        if breakeven == breakeven and breakeven > 0.85:
            warnings.append(
                f"The pit stops paying at {breakeven:.1%} of the planning price — a fall of only "
                f"{(1 - breakeven):.1%} wipes out its value. Check the price assumption carefully."
            )
    return warnings


def _arc_upper_bound(cfg: ProjectConfig, blocks: pd.DataFrame) -> int:
    """Precedence arcs if no block were cut by the model edge: template size for each block's own slope angle."""
    bm, slope = cfg.block_model, cfg.slope

    def template(angle: float) -> int:
        levels = slope.max_bench_levels or auto_bench_levels(angle, min(bm.dx, bm.dy), bm.dz)
        return len(cone_offsets(angle, bm.dx, bm.dy, bm.dz, levels))

    if slope.domain_angles and "domain" in blocks.columns:
        counts = blocks["domain"].value_counts()
        listed = sum(int(counts.get(d, 0)) * template(a) for d, a in slope.domain_angles.items())
        rest = len(blocks) - sum(int(counts.get(d, 0)) for d in slope.domain_angles)
        return listed + rest * template(slope.overall_angle_deg)
    return len(blocks) * template(slope.overall_angle_deg)


def run(cfg: ProjectConfig, verbose: bool = True, log_fn: Callable[[str], None] | None = None,
        context: dict | None = None, cancel: CancelToken | None = None) -> PitResult:
    """
    Run the whole pipeline.

    log_fn      receives every progress line (the UI streams these); by
                default they are printed when `verbose`
    context     optional labels for the results file: {"project", "scenario"}
    cancel      a token; the run stops at the next progress line after it is set,
                raising Cancelled. Every stage reports progress, so that is at most
                one stage away
    """
    started = time.time()

    def log(message: str) -> None:
        if cancel is not None:
            cancel.check()
        if log_fn is not None:
            log_fn(message)
        if verbose:
            print(message)

    blocks = load_block_model(cfg.block_model, cfg.economics)
    log(f"Loaded {len(blocks):,} blocks from {Path(cfg.block_model.path).name}")
    as_waste = blocks.attrs.get("classes_as_waste", 0)
    if as_waste:
        log(f"{as_waste:,} blocks outside classes {cfg.block_model.include_classes} kept as waste (no revenue, still mined if in the pit)")

    elevation = load_elevation(cfg)
    if elevation is not None:
        before = len(blocks)
        blocks = clip_to_surface(blocks, elevation)
        log(f"Clipped to topography: {len(blocks):,} blocks below surface ({before - len(blocks):,} above ground removed)")

    blocks = add_grid_indices(blocks)

    check_solver_memory(len(blocks), _arc_upper_bound(cfg, blocks))

    arcs = build_precedence(
        blocks,
        slope_angle_deg=cfg.slope.overall_angle_deg,
        max_levels=cfg.slope.max_bench_levels,
        domain_angles=cfg.slope.domain_angles,
    )
    levels = cfg.slope.max_bench_levels or auto_bench_levels(
        cfg.slope.overall_angle_deg, min(cfg.block_model.dx, cfg.block_model.dy), cfg.block_model.dz
    )
    log(f"Precedence graph: {len(arcs):,} arcs at {cfg.slope.overall_angle_deg}deg over {levels} bench levels")

    solved, report, violations = run_nested_shells(
        blocks, arcs, cfg.economics, cfg.shells.revenue_factors,
        on_progress=lambda i, n: log(f"Shell {i}/{n} solved"),
    )
    log(f"Solved {len(cfg.shells.revenue_factors)} nested shells")
    if violations:
        log(f"WARNING: {violations:,} block(s) dropped out of a larger shell — shells should be nested, check numerics")
    solved["in_rf1_pit"] = solved["in_pit"]
    shell = solved["shell"].to_numpy()
    sched = cfg.schedule
    lag_benches = max(0, int(round(cfg.pushbacks.bench_lag_m / cfg.block_model.dz)))
    # Discount per period, so a period can be a quarter or two years.
    rate = (1.0 + sched.discount_rate) ** sched.period_years - 1.0
    feed_column = "ore_tonnes" if sched.basis == "tonnes" else "ore_volume"
    capacity = sched.ore_capacity
    if sched.enabled and sched.periods:
        # Mine life given: size the plant from the RF 1.0 pit for the shell
        # comparison, then re-size it on the final pit once that is chosen.
        at_one = report[np.isclose(report["revenue_factor"], 1.0)]
        reference = at_one.iloc[0] if len(at_one) else report.iloc[-1]
        capacity = float(reference[feed_column]) / sched.periods

    # Step 2-3: discounted pit-by-pit analysis, then the final pit is the
    # shell with the best discounted value — not automatically RF 1.0.
    candidates = None
    if sched.enabled:
        report = pit_by_pit_npv(
            solved, report, capacity, sched.total_capacity, rate, sched.basis,
            on_progress=lambda i, n: log(f"Pit by pit {i}/{n} scheduled"),
        )
        final_shell, final_reason = select_final_pit(
            report, cfg.final_pit.criterion, cfg.final_pit.tolerance, cfg.final_pit.revenue_factor
        )
    else:
        at_one = report.index[np.isclose(report["revenue_factor"], 1.0)]
        final_shell = int(at_one[0]) + 1 if len(at_one) else len(report)
        final_reason = "RF 1.00 (no schedule, so no discounted selection)"
        report = report.assign(shell=np.arange(1, len(report) + 1))
    final_rf = float(report["revenue_factor"].iloc[final_shell - 1])
    in_pit = (shell > 0) & (shell <= final_shell)
    solved["in_pit"] = in_pit
    report["final_pit"] = report["shell"] == final_shell
    log(f"Final pit: shell {final_shell} (RF {final_rf:.2f}) — {final_reason}")
    final_feed = float(report.iloc[final_shell - 1][feed_column])
    if sched.enabled and sched.periods:
        capacity = final_feed / sched.periods * (1.0 + 1e-9)
        unit = "t" if sched.basis == "tonnes" else "m3"
        log(f"Plant rate for a {sched.periods}-period life: {capacity:,.0f} {unit} per period")
    life = int(np.ceil(final_feed / capacity)) if sched.enabled and capacity > 0 else 0
    life_years = life * sched.period_years
    pb_cfg = cfg.pushbacks
    final_depth = float((solved.loc[in_pit, "z"].max() - solved.loc[in_pit, "z"].min()) + cfg.block_model.dz) if in_pit.any() else 0.0
    if pb_cfg.count:
        pushback_count = pb_cfg.count
        count_reason = f"{pb_cfg.count} (set manually)"
    elif life_years:
        if pb_cfg.duration_years == "auto":
            duration = max(pb_cfg.target_duration_years, final_depth / pb_cfg.max_vertical_advance_m)
            why = f"auto: target {pb_cfg.target_duration_years:g} y"
            if duration > pb_cfg.target_duration_years:
                why += f", lengthened to {duration:.1f} y so a {final_depth:.0f} m pit sinks at <= {pb_cfg.max_vertical_advance_m:g} m/y"
        else:
            duration = float(pb_cfg.duration_years)
            why = f"manual duration {duration:g} y"
        pushback_count = int(min(max(1, round(life_years / duration)), pb_cfg.max_pushbacks))
        count_reason = f"{pushback_count} ({why}; mine life {life_years:g} y)"
    else:
        pushback_count = None
        count_reason = "best specified-case NPV (no schedule)"
    log(f"Pushback count: {count_reason}")

    # Step 4: pushbacks inside the final pit.
    min_tonnes = cfg.pushbacks.min_tonnes if cfg.pushbacks.min_tonnes is not None else (
        capacity if sched.enabled and sched.basis == "tonnes" else 0.0
    )
    order = None
    strip_note = ""
    if cfg.pushbacks.method == "strips":
        face = min([cfg.slope.overall_angle_deg] + [float(a) for a in cfg.slope.domain_angles.values()])
        directions = {"auto": [False, True], "forward": [False], "reverse": [True]}[cfg.pushbacks.strip_direction]
        best = None
        for reverse in directions:
            candidate_order, panel, axis = strip_sequence(
                solved, in_pit, cfg.pushbacks.strip_width, face, cfg.pushbacks.strip_axis, reverse
            )
            npv = schedule_summary(schedule_production(
                solved, in_pit, capacity, sched.total_capacity, rate,
                sched.max_periods, capacity_basis=sched.basis, order=candidate_order,
            ))["npv"] if sched.enabled else 0.0
            if best is None or npv > best[0]:
                best = (npv, candidate_order, panel, axis, reverse)
        _, order, panel, axis, reverse = best
        direction = {("y", False): "south to north", ("y", True): "north to south",
                     ("x", False): "west to east", ("x", True): "east to west"}[(axis, reverse)]
        feed = solved.loc[panel.index, "ore_tonnes" if sched.basis == "tonnes" else "volume"] * (
            solved.loc[panel.index, "destination"] == 1
        )
        grouped = group_strips(order, panel, feed, pushback_count or 1)
        pushback = np.zeros(len(solved), dtype=int)
        pushback[grouped.index.to_numpy()] = grouped.to_numpy()
        strip = np.zeros(len(solved), dtype=int)
        strip[panel.index.to_numpy()] = panel.to_numpy()
        solved["strip"] = strip
        pb_labels = {}
        for n in sorted(set(grouped)):
            members = panel[grouped == n]
            pb_labels[n] = f"strips {members.min()}-{members.max()}"
        strip_note = (
            f"{len(pb_labels)} pushbacks of {panel.max()} strips x {cfg.pushbacks.strip_width:g} m, advancing {direction}"
        )
        log(f"Pushbacks: {strip_note} (" + "; ".join(f"PB{n} {t}" for n, t in pb_labels.items()) + ")")
    else:
        if sched.enabled:
            boundaries, candidates = select_pushbacks(
                solved, final_shell, capacity, sched.total_capacity, rate, sched.basis,
                cfg.pushbacks.max_pushbacks, min_tonnes, cfg.pushbacks.min_width, cfg.pushbacks.max_narrow, lag_benches,
                exact_count=pushback_count,
            )
        else:
            boundaries = [n for n in range(1, final_shell + 1) if (shell == n).any()]
        pushback = pushback_labels(boundaries, shell)
        factors = report["revenue_factor"].to_numpy()
        pb_labels = {i: f"to RF {factors[b - 1]:.2f}" for i, b in enumerate(boundaries, start=1)}
        order = specified_sequence(solved, in_pit, pushback, lag_benches)
        log(f"Pushbacks: {len(boundaries)} selected at shells {boundaries} (RF " + ", ".join(f"{factors[b - 1]:.2f}" for b in boundaries) + ")")
        if candidates is not None and not candidates["practical"].any():
            log(
                f"WARNING: none of the {len(candidates)} shell splits meets the minimum width / tonnage — "
                "the least narrow one was used. Fewer pushbacks, a smaller min_width, or strips may suit this deposit."
            )
    solved["pushback"] = pushback

    depth = pit_depth_stats(solved, in_pit, elevation)
    closure = check_pit_closure(solved, in_pit)
    if not closure["closed"]:
        log(
            f"WARNING: pit is not closed within the block model "
            f"({closure['on_bottom']:,} blocks on the bottom bench, {closure['on_sides']:,} on a lateral limit). "
            "The shell is cut off by the model extent, not by economics — tonnes and outline are understated. "
            "Extend the model until the pit closes inside it."
        )

    bench = bench_summary(solved, in_pit, cfg.economics)

    # Step 5: the plan schedule (specified case or strips), bracketed by the
    # best and worst case on the same final pit.
    schedule = schedule_best = schedule_worst = sensitivity = sensitivity_products = None
    if sched.enabled:
        common = (solved, in_pit, capacity, sched.total_capacity, rate, sched.max_periods)
        schedule = schedule_production(*common, capacity_basis=sched.basis, order=order)
        solved["period"] = schedule.attrs["block_period"].reindex(solved.index).fillna(0).astype(int)
        mined = solved[solved["period"] > 0]
        active = mined.groupby("period")["pushback"].agg(lambda v: ", ".join(f"PB{n}" for n in sorted(set(v))))
        schedule.insert(1, "pushbacks", schedule["period"].map(active).fillna(""))
        schedule.insert(2, "years", schedule["period"].map(
            lambda t: f"{(t - 1) * sched.period_years:g}-{t * sched.period_years:g}"
        ))
        schedule_best = schedule_production(*common, by_shell=True, capacity_basis=sched.basis)
        if sched.include_worst_case:
            schedule_worst = schedule_production(*common, by_shell=False, capacity_basis=sched.basis)
        plan_label = "strips" if cfg.pushbacks.method == "strips" else f"specified case, {lag_benches} bench lag"
        log(
            f"Schedule ({plan_label}): {schedule_summary(schedule)['periods']} periods, "
            f"NPV {schedule_summary(schedule)['npv']:,.0f}; best case {schedule_summary(schedule_best)['npv']:,.0f}"
            + (f", worst case {schedule_summary(schedule_worst)['npv']:,.0f}" if schedule_worst is not None else "")
        )

    if cfg.sensitivity.enabled and sched.enabled:
        sensitivity = price_sensitivity(
            solved, in_pit, cfg.economics, cfg.sensitivity.price_factors,
            capacity, sched.total_capacity, rate, sched.basis, order=order,
        )
        breakeven = breakeven_price_factor(sensitivity)
        log(f"Price sensitivity: {len(cfg.sensitivity.price_factors)} cases, break-even at price factor {breakeven:.3f}")

        if cfg.sensitivity.per_product and len(cfg.economics.products) > 1:
            frames = []
            for product in cfg.economics.products:
                frame = price_sensitivity(
                    solved, in_pit, cfg.economics, cfg.sensitivity.price_factors,
                    capacity, sched.total_capacity, rate, sched.basis,
                    products=[product.name], order=order,
                )
                frames.append(frame.assign(product=product.name))
            sensitivity_products = pd.concat(frames, ignore_index=True)

    out_dir = Path(cfg.output.directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict = {}

    csv_path = out_dir / f"{cfg.name}_blocks.csv"
    write_block_model(solved, str(csv_path))
    outputs["block_model_csv"] = str(csv_path)

    report_path = out_dir / f"{cfg.name}_pit_by_pit.csv"
    report.to_csv(report_path, index=False)
    outputs["report_csv"] = str(report_path)

    # Surfaces: with a bench design, every surface is built from the floor
    # with benched walls (pit shell = the bowl, face position = the bowl
    # clipped by topography); without one, the block-stepped shell is used.
    geometry = design_summary = None
    final_bowl = None
    if cfg.design.enabled:
        d = cfg.design
        geometry = bench_geometry(cfg.slope.overall_angle_deg, d.bench_height, d.bench_face_angle_deg, d.berm_width)
        grid = design_grid(solved, elevation, d.cell)
        xs, ys, topo = grid.xs, grid.ys, grid.topo

        def face_of(mask: np.ndarray) -> np.ndarray:
            return face_position(pit_shell(solved, mask, grid, geometry), grid)

        final_bowl = pit_shell(solved, in_pit, grid, geometry)
        final_face = face_position(final_bowl, grid)
        fraction, design_summary = reconcile(solved, in_pit, final_face, grid)
        solved["design_fraction"] = fraction.round(4)
        solved["in_design"] = fraction >= 0.5
        log(
            f"Pit design: benches {geometry.bench_height:g} m high, face {geometry.face_angle_deg:g} deg, "
            f"berm {geometry.berm_width:.2f} m -> overall {geometry.overall_angle_deg:.1f} deg; design vs shell: "
            f"rock {design_summary['rock_tonnes_change']:+.1%}, ore {design_summary['ore_tonnes_change']:+.1%}, "
            f"value {design_summary['value_change']:+.1%}"
        )
    else:
        xs, ys, topo = pit_surface_grid(solved, np.zeros(len(solved), dtype=bool), elevation)

        def face_of(mask: np.ndarray) -> np.ndarray:
            return pit_surface_grid(solved, mask, elevation)[2]

        final_face = face_of(in_pit)

    design_detail = None
    if cfg.design.enabled and cfg.design.detail.enabled:
        design_detail = build_design(solved, in_pit, cfg, raster=design_summary["design"] if design_summary else None)
        checks = design_detail.validation.by_check()
        log(f"Detailed design: {len(design_detail.stack.benches)} benches, anchor {cfg.design.detail.anchor}; "
            + ", ".join(f"{k} {v}" for k, v in checks.items()))
        if cfg.output.write_design_detail:
            from .io.design_export import write_all

            outputs.update(write_all(design_detail, cfg, out_dir, cfg.name, {"final_shell": final_shell, "final_rf": final_rf},
                                     solved, in_pit))

    stage_faces: dict = {}
    if "pushback" in solved.columns:
        stage = solved["pushback"].to_numpy()
        for n in range(1, int(stage.max()) + 1):
            stage_faces[("pushback", n)] = face_of((stage > 0) & (stage <= n))
    if "period" in solved.columns:
        period = solved["period"].to_numpy()
        for n in range(1, int(period.max()) + 1):
            stage_faces[("period", n)] = face_of((period > 0) & (period <= n))

    if cfg.output.write_dxf:
        cell = float(xs[1] - xs[0]) if len(xs) > 1 else 1.0
        # Two samples per bench face run are needed to show a bench at all: a coarser facet aliases the walls and
        # moved the exported volume 4% on a small pit. The deliverable surfaces (final face, shell) use that;
        # the many stage surfaces stay at 5 m to keep the files manageable.
        face_run = (geometry.bench_height / math.tan(math.radians(geometry.face_angle_deg))) if geometry is not None else 5.0
        step_fine = max(1, int(round((cfg.output.dxf_cell or min(5.0, face_run / 2)) / cell)))
        if not cfg.output.dxf_cell:                       # cap the size of the deliverable on big models (set dxf_cell to override)
            step_fine = max(step_fine, int(math.ceil(math.sqrt(2.0 * len(xs) * len(ys) / MAX_DXF_FACETS))))
        step_stage = max(1, int(round((cfg.output.dxf_cell or 5.0) / cell)))

        def write(path: Path, surface: np.ndarray, layer: str, clip: bool = True, step: int = step_stage) -> int:
            grid_z = surface
            if clip:
                disturbed = surface < topo - 0.01
                keep = ndimage.binary_dilation(disturbed, iterations=step) if disturbed.any() else disturbed
                grid_z = np.where(keep, surface, np.nan)
            return dxf.write_surface(str(path), xs[::step], ys[::step], grid_z[::step, ::step], layer=layer)

        face_path = out_dir / f"{cfg.name}_pit_face_position.dxf"
        faces = write(face_path, final_face, "PIT_FACE_POSITION", step=step_fine)
        outputs["pit_face_position_dxf"] = str(face_path)
        log(f"Pit face position: {faces:,} faces -> {face_path.name}")
        if final_bowl is not None:
            bowl_path = out_dir / f"{cfg.name}_pit_shell.dxf"
            write(bowl_path, shell_for_display(final_bowl, grid, geometry), "PIT_SHELL", clip=False, step=step_fine)
            outputs["pit_shell_dxf"] = str(bowl_path)

        for (kind, n), surface in stage_faces.items():
            if (kind == "period" and not cfg.output.dxf_surface_periods) or (
                kind == "pushback" and not cfg.output.dxf_surface_pushbacks
            ):
                continue
            path = out_dir / f"{cfg.name}_{kind}_{n:02d}_end.dxf"
            write(path, surface, f"{kind.upper()}_{n:02d}_END")
            outputs[f"{kind}_{n:02d}_dxf"] = str(path)
        log(f"Stage surfaces: {sum(1 for k in stage_faces if k[0] == 'period')} periods, "
            f"{sum(1 for k in stage_faces if k[0] == 'pushback')} pushbacks")

        if cfg.output.dxf_surface_all_shells:
            for n, rf in enumerate(sorted(cfg.shells.revenue_factors), start=1):
                shell_mask = (solved["shell"].to_numpy() > 0) & (solved["shell"].to_numpy() <= n)
                if not shell_mask.any():
                    continue
                xs_s, ys_s, grid_s = pit_surface_grid(solved, shell_mask, elevation)
                shell_path = out_dir / f"{cfg.name}_shell_rf{int(round(rf * 100)):03d}.dxf"
                dxf.write_surface(str(shell_path), xs_s, ys_s, grid_s, layer=f"SHELL_RF{int(round(rf * 100)):03d}")
                outputs[f"shell_rf{rf:.2f}_dxf"] = str(shell_path)

    if cfg.output.write_plot:
        from .io.plot import write_review_plot

        plot_path = out_dir / f"{cfg.name}_review.png"
        step = max(1, int(max(len(xs), len(ys)) / 200))
        write_review_plot(xs[::step], ys[::step], final_face[::step, ::step], report, str(plot_path), cfg.name)
        outputs["review_plot"] = str(plot_path)

    result = PitResult(
        blocks=solved,
        report=report,
        depth=depth,
        closure=closure,
        nesting_violations=violations,
        outputs=outputs,
        schedule=schedule,
        schedule_worst=schedule_worst,
        sensitivity=sensitivity,
        sensitivity_by_product=sensitivity_products,
        bench=bench,
        schedule_best=schedule_best,
        pushback_candidates=candidates,
        final_shell=final_shell,
        final_rf=final_rf,
        final_reason=final_reason,
        pushback_reason=count_reason,
        design=design_summary,
        design_geometry=geometry,
        design_detail=design_detail,
        plan_label=strip_note or f"{int(solved['pushback'].max())} pushbacks, specified case with {lag_benches} bench lag",
    )

    figures: list[tuple[str, str]] = []
    pushbacks = inputs = None
    if cfg.output.write_excel or cfg.output.write_pdf or cfg.output.write_3d:
        from .io import viz

        product_names = [p.name for p in cfg.economics.products]
        pushbacks = viz.pushback_table(solved, pb_labels, product_names)
        result.pushbacks = pushbacks
        write_block_model(solved, str(csv_path))

        pit_grid = final_face
        inputs = viz.input_summary(solved, [p.grade_col for p in cfg.economics.products], topo)

        path_3d = out_dir / f"{cfg.name}_3d_pit.png"
        ve = viz.render_pit_3d(xs, ys, topo, pit_grid, str(path_3d), cfg.name)
        figures.append((f"Topography and final pit face position (vertical exaggeration {ve:.0f}x)", str(path_3d)))

        if final_bowl is not None:
            section_path = out_dir / f"{cfg.name}_design_section.png"
            optimiser = pit_surface_grid(solved, in_pit, elevation)
            # optimiser shell resampled to the design grid by nearest column
            ox, oy, oz = optimiser
            ii = np.clip(np.searchsorted(ox, xs) , 0, len(ox) - 1)
            jj = np.clip(np.searchsorted(oy, ys), 0, len(oy) - 1)
            viz.render_design_section(xs, ys, topo, shell_for_display(final_bowl, grid, geometry), final_face,
                                      oz[ii][:, jj], str(section_path), cfg.name, geometry)
            figures.append(("Pit shell (design bowl) vs face position, in section", str(section_path)))

        columns = viz.pushback_columns(solved)
        if len(columns):
            labels = {n: f"PB{n} {text}" for n, text in pb_labels.items()}
            legend = "Strip" if cfg.pushbacks.method == "strips" else "Pushback"
            plan_path = out_dir / f"{cfg.name}_pushback_plan.png"
            viz.render_plan(columns, "pushback", str(plan_path), f"{cfg.name} — {legend.lower()}s, plan view", legend, labels)
            figures.append((f"{legend}s inside the final pit (RF {final_rf:.2f}), plan view", str(plan_path)))

            section_path = out_dir / f"{cfg.name}_pushback_section.png"
            viz.render_pushback_section(solved, str(section_path), cfg.name)
            figures.append((f"{legend}s in section, true scale and exaggerated", str(section_path)))

        if "period" in solved.columns and (solved["period"] > 0).any():
            period_path = out_dir / f"{cfg.name}_period_plan.png"
            viz.render_plan(
                viz.period_columns(solved), "period", str(period_path),
                f"{cfg.name} — mining sequence by period ({result.plan_label})", "Period (year)",
            )
            figures.append(("Mining sequence by period, plan view", str(period_path)))

        if "review_plot" in outputs:
            figures.append(("Pit by pit value and strip ratio", outputs["review_plot"]))
        for _label, path in figures:
            outputs[f"figure:{Path(path).stem}"] = path

        if cfg.output.write_3d:
            shell_grids = []
            if final_bowl is not None:
                shell_grids.append(("Pit shell — design bowl (not clipped by topography)", shell_for_display(final_bowl, grid, geometry)))
            if len(pb_labels) <= 12:
                for n, text in pb_labels.items():
                    shell_grids.append((f"Pushback {n} end ({text})", stage_faces[("pushback", n)]))
            for (kind, n), surface in stage_faces.items():
                if kind == "period":
                    shell_grids.append((f"End of period {n}", surface))
            html_path = out_dir / f"{cfg.name}_3d_viewer.html"
            viz.write_interactive_3d(
                xs, ys, topo, pit_grid, shell_grids, str(html_path), cfg.name,
                pit_label=f"Final pit face position (RF {final_rf:.2f})",
            )
            outputs["viewer_3d_html"] = str(html_path)
            log(f"Interactive 3D viewer -> {html_path.name}")

    if cfg.output.write_excel:
        from .io.excel import write_workbook

        excel_path = out_dir / f"{cfg.name}_report.xlsx"
        write_workbook(
            str(excel_path), cfg,
            summary=headline_frame(cfg, result),
            pit_by_pit=report,
            schedule=schedule if schedule is not None else pd.DataFrame(),
            schedule_worst=schedule_worst,
            sensitivity=_stack_sensitivity(sensitivity, sensitivity_products),
            bench=bench,
            run_notes=run_notes(cfg, result),
            schedule_best=schedule_best,
            pushback_candidates=candidates,
            pushbacks=pushbacks,
            inputs=inputs,
            figures=figures,
        )
        outputs["excel_report"] = str(excel_path)
        log(f"Excel workbook -> {excel_path.name}")

    if cfg.output.write_pdf:
        from .io.pdf import write_report

        pdf_path = out_dir / f"{cfg.name}_report.pdf"
        write_report(
            str(pdf_path), cfg.name,
            headline=headline_pairs(cfg, result),
            parameters=parameter_pairs(cfg),
            pit_by_pit=report,
            schedule=schedule if schedule is not None else pd.DataFrame(),
            sensitivity=sensitivity,
            pushbacks=pushbacks,
            figures=figures,
            warnings=collect_warnings(cfg, result),
            assumptions=ASSUMPTIONS,
            plan_label=result.plan_label,
        )
        outputs["pdf_report"] = str(pdf_path)
        log(f"PDF report -> {pdf_path.name}")

    if cfg.output.verify or cfg.output.write_results:
        verification = {}
        if cfg.output.verify:
            from .core.verify import run_all

            face_arr = final_face
            verification = run_all(
                cfg, solved, elevation, face=face_arr,
                cell=float(xs[1] - xs[0]) if len(xs) > 1 else None, geometry=geometry,
            )
            w, c, sch = verification["violations"]
            log(f"Verification: walls {w}, cone {c}, schedule {sch} violations")
            result.verification = verification

        if cfg.output.write_results:
            from .io.results import write_results

            optimiser = pit_surface_grid(solved, in_pit, elevation)
            ox, oy, oz = optimiser
            ii = np.clip(np.searchsorted(ox, xs), 0, len(ox) - 1)
            jj = np.clip(np.searchsorted(oy, ys), 0, len(oy) - 1)
            ctx = {
                "xs": xs, "ys": ys, "topo": topo, "face": final_face,
                "bowl": shell_for_display(final_bowl, grid, geometry) if final_bowl is not None else None,
                "stage_faces": stage_faces, "optimiser": oz[ii][:, jj],
                "verification": verification,
                "duration_s": round(time.time() - started, 1),
                "run_at": datetime.now().isoformat(timespec="seconds"),
                "engine_version": __import__("pitopt").__version__,
                **(context or {}),
            }
            results_path, _doc = write_results(cfg, result, ctx)
            outputs["results_json"] = results_path
            log(f"Results for the UI -> {Path(results_path).name}")

    return result
