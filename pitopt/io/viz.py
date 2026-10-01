"""
Report figures: topography against the optimum pit, and the pushbacks.

Every 3D figure states its vertical exaggeration in the title. A shallow
pit drawn with auto-scaled axes looks like a canyon, and the same pit at
true scale looks like nothing at all — neither is misleading as long as
the reader is told which one they are looking at. The cross-section is
always drawn alongside so the true geometry is on the page.

A pushback is one non-empty shell increment inside the ultimate pit
(RF <= 1.0). Empty shells — factors too low for anything to pay — get no
number, so pushbacks run 1..n without gaps. Shells beyond RF 1.0 are price
upside, not mining phases.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _mpl():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def pushback_limit(revenue_factors: list[float]) -> int:
    """Index of the last shell that is part of the ultimate pit."""
    factors = sorted(revenue_factors)
    inside = [n for n, rf in enumerate(factors, start=1) if rf <= 1.0 + 1e-9]
    return inside[-1] if inside else len(factors)


def assign_pushbacks(blocks: pd.DataFrame, revenue_factors: list[float]) -> tuple[pd.DataFrame, dict[int, float]]:
    """Adds a `pushback` column (0 = not in the ultimate pit) and returns
    the revenue factor behind each pushback number."""
    factors = sorted(revenue_factors)
    last = pushback_limit(factors)
    shells = sorted(s for s in blocks["shell"].unique() if 0 < s <= last)
    mapping = {shell: n for n, shell in enumerate(shells, start=1)}
    out = blocks.copy()
    out["pushback"] = out["shell"].map(mapping).fillna(0).astype(int)
    return out, {n: factors[shell - 1] for shell, n in mapping.items()}


def pushback_columns(blocks: pd.DataFrame) -> pd.DataFrame:
    """Per x/y column, the earliest pushback that reaches it — what a plan
    view of the pushback sequence shows."""
    pit = blocks[blocks["pushback"] > 0]
    return pit.groupby(["gi", "gj"], as_index=False).agg(
        x=("x", "first"), y=("y", "first"), pushback=("pushback", "min"), floor=("z", "min")
    )


def _plain_axis(axis) -> None:
    from matplotlib.ticker import FuncFormatter

    axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))


def exaggeration(xs: np.ndarray, ys: np.ndarray, grid_z: np.ndarray) -> float:
    """Vertical exaggeration that makes relief visible without turning the
    pit into a spike: aim for relief at about a quarter of the plan width."""
    span = max(float(np.ptp(xs)), float(np.ptp(ys)), 1.0)
    relief = max(float(np.nanmax(grid_z) - np.nanmin(grid_z)), 1.0)
    return float(np.clip(round(0.25 * span / relief), 1, 50))


def render_pit_3d(
    xs: np.ndarray, ys: np.ndarray, topo: np.ndarray, pit: np.ndarray, path: str, title: str
) -> float:
    """Topography (wire) over the optimum pit surface (solid). Returns the
    vertical exaggeration used."""
    plt = _mpl()
    ve = exaggeration(xs, ys, topo)
    mx, my = np.meshgrid(xs, ys, indexing="ij")
    stride = max(1, int(max(len(xs), len(ys)) / 120))

    fig = plt.figure(figsize=(12, 7.5))
    ax = fig.add_subplot(111, projection="3d")
    depth = np.where(np.isfinite(topo - pit), topo - pit, 0.0)
    colours = plt.cm.copper_r(np.clip(depth / max(np.nanmax(depth), 1e-9), 0, 1))
    ax.plot_surface(mx, my, pit, facecolors=colours, rstride=stride, cstride=stride, linewidth=0, antialiased=False, shade=True)
    ax.plot_wireframe(mx, my, topo, rstride=stride * 4, cstride=stride * 4, color="#2a6f97", linewidth=0.3, alpha=0.5)

    ax.set_box_aspect((np.ptp(xs), np.ptp(ys), max(np.nanmax(topo) - np.nanmin(pit), 1.0) * ve))
    _plain_axis(ax.xaxis)
    _plain_axis(ax.yaxis)
    ax.tick_params(labelsize=7)
    ax.set_xlabel("Easting", labelpad=10)
    ax.set_ylabel("Northing", labelpad=14)
    ax.set_zlabel("RL")
    ax.view_init(elev=32, azim=-128)
    ax.set_title(f"{title} — topography (blue wire) and optimum pit, vertical exaggeration {ve:.0f}x")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return ve


def render_plan(
    columns: pd.DataFrame, value_column: str, path: str, title: str, legend: str, labels: dict[int, str] | None = None
) -> None:
    """Plan view of a per-column integer attribute (pushback, period)."""
    plt = _mpl()
    from matplotlib.colors import BoundaryNorm, ListedColormap

    labels = labels or {}
    n = int(columns[value_column].max()) if len(columns) else 1
    cmap = ListedColormap(plt.cm.viridis(np.linspace(0.05, 0.95, n)))
    norm = BoundaryNorm(np.arange(0.5, n + 1.5), n)

    fig, ax = plt.subplots(figsize=(9, 10))
    sc = ax.scatter(columns["x"], columns["y"], c=columns[value_column], cmap=cmap, norm=norm, s=6, marker="s", linewidths=0)
    step = max(1, int(np.ceil(n / 12)))
    ticks = list(range(1, n + 1, step))
    bar = fig.colorbar(sc, ax=ax, ticks=ticks, shrink=0.7)
    bar.ax.set_yticklabels([labels.get(i, str(i)) for i in ticks])
    bar.set_label(legend)
    ax.set_aspect("equal")
    ax.set_xlabel("Easting")
    ax.set_ylabel("Northing")
    _plain_axis(ax.xaxis)
    _plain_axis(ax.yaxis)
    ax.tick_params(axis="x", labelrotation=35, labelsize=8)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def period_columns(blocks: pd.DataFrame) -> pd.DataFrame:
    """Per x/y column, the period in which mining first reaches it."""
    mined = blocks[blocks["period"] > 0]
    return mined.groupby(["gi", "gj"], as_index=False).agg(x=("x", "first"), y=("y", "first"), period=("period", "min"))


def render_pushback_section(blocks: pd.DataFrame, path: str, title: str) -> None:
    """Section through the column line holding the most in-pit blocks,
    drawn twice: at true scale, and exaggerated so the phases are legible."""
    plt = _mpl()
    pit = blocks[blocks["pushback"] > 0]
    if pit.empty:
        return
    last = int(pit["pushback"].max())
    line = pit.groupby("gi").size().idxmax()
    section = blocks[blocks["gi"] == line]
    mined = section[section["pushback"] > 0]
    left = section.drop(mined.index)

    relief = max(float(section["z"].max() - section["z"].min()), 1.0)
    ve = float(np.clip(round(0.2 * float(np.ptp(section["y"])) / relief), 1, 50))

    fig, axes = plt.subplots(2, 1, figsize=(14, 7.5), gridspec_kw={"height_ratios": [1, 3]})
    for ax, scale in zip(axes, (1.0, ve)):
        ax.scatter(left["y"], left["z"], s=4, c="#d0d0d0", marker="s", linewidths=0, label="not mined")
        sc = ax.scatter(mined["y"], mined["z"], s=4, c=mined["pushback"], cmap="viridis", vmin=1, vmax=max(last, 2), marker="s", linewidths=0)
        ax.set_aspect(scale)
        ax.set_ylabel("RL")
        _plain_axis(ax.xaxis)
        ax.set_title(f"Section E {float(section['x'].iloc[0]):,.0f} — " + ("true scale" if scale == 1.0 else f"vertical exaggeration {scale:.0f}x"))
    axes[-1].set_xlabel("Northing")
    fig.colorbar(sc, ax=axes, shrink=0.8, label="Pushback")
    fig.suptitle(f"{title} — pushbacks in section")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def render_design_section(
    xs: np.ndarray, ys: np.ndarray, topo: np.ndarray, bowl: np.ndarray, face: np.ndarray,
    optimiser: np.ndarray, path: str, title: str, geometry,
) -> None:
    """Section across the pit's short axis through its deepest point:
    topography, the optimiser's block-stepped shell, the benched design
    bowl and the face position — at true scale, and zoomed onto the
    tallest wall so the benches are readable."""
    plt = _mpl()
    depth = np.where(np.isfinite(face), topo - face, 0.0)
    ci, cj = np.unravel_index(np.nanargmax(depth), depth.shape)
    across_x = np.ptp(xs) <= np.ptp(ys)          # cut across the short axis
    if across_x:
        pos, t, b, f, o, label = xs, topo[:, cj], bowl[:, cj], face[:, cj], optimiser[:, cj], f"Section N {ys[cj]:,.0f}"
        centre, axis_name = ci, "Easting"
    else:
        pos, t, b, f, o, label = ys, topo[ci], bowl[ci], face[ci], optimiser[ci], f"Section E {xs[ci]:,.0f}"
        centre, axis_name = cj, "Northing"

    # Tallest wall: from the deepest point walk outward to the crest on
    # whichever side climbs higher.
    mined = f < t - 0.01
    left = centre
    while left > 0 and mined[left - 1]:
        left -= 1
    right = centre
    while right < len(pos) - 1 and mined[right + 1]:
        right += 1
    rise_left, rise_right = t[left] - f[centre], t[right] - f[centre]
    crest = left if rise_left >= rise_right else right
    wall_height = max(rise_left, rise_right)
    run = wall_height / np.tan(np.radians(geometry.overall_angle_deg))

    fig, axes = plt.subplots(2, 1, figsize=(14, 8.5), gridspec_kw={"height_ratios": [1, 2]})
    for ax, zoom in zip(axes, (False, True)):
        ax.plot(pos, t, color="#6b8e23", linewidth=1.2, label="Topography")
        ax.plot(pos, b, color="#1f77b4", linestyle="--", linewidth=1.2, label="Pit shell (design bowl)")
        ax.plot(pos, o, color="#888888", linewidth=0.9, drawstyle="steps-mid", label="Optimiser shell (blocks)")
        ax.fill_between(pos, f, t, where=mined, color="#e9c46a", alpha=0.5, label="Mined")
        ax.plot(pos, f, color="#b5651d", linewidth=1.8, label="Face position")
        ax.set_ylabel("RL")
        _plain_axis(ax.xaxis)
        if zoom:
            a, z = sorted((pos[crest], pos[crest] + (run * 1.4 if crest == left else -run * 1.4)))
            ax.set_xlim(a - 0.2 * run, z + 0.2 * run)
            ax.set_ylim(f[centre] - 2, t[crest] + geometry.bench_height)
            ax.set_aspect(1.0)
            ax.set_title(
                f"Wall detail at true scale — {wall_height:.0f} m wall; benches {geometry.bench_height:g} m, "
                f"face {geometry.face_angle_deg:g} deg, berm {geometry.berm_width:.2f} m (overall {geometry.overall_angle_deg:.1f} deg)"
            )
        else:
            ax.set_ylim(np.nanmin(f) - 5, np.nanmax(t) + 5)
            ax.set_aspect(1.0)
            ax.set_title(f"{label} — true scale, through the deepest point")
        ax.legend(loc="lower right", fontsize=8)
    axes[-1].set_xlabel(axis_name)
    fig.suptitle(f"{title} — pit shell (bowl) vs face position")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_interactive_3d(
    xs: np.ndarray,
    ys: np.ndarray,
    topo: np.ndarray,
    pit: np.ndarray,
    shell_surfaces: list[tuple[str, np.ndarray]],
    path: str,
    title: str,
    pit_label: str = "Final pit",
) -> None:
    """Self-contained HTML: rotate, zoom, toggle each pushback shell. The
    vertical exaggeration can be changed live from the aspect buttons."""
    import plotly.graph_objects as go

    step = max(1, int(max(len(xs), len(ys)) / 150))
    sx, sy = xs[::step], ys[::step]

    def cut(grid: np.ndarray) -> np.ndarray:
        return grid[::step, ::step].T

    fig = go.Figure()
    fig.add_trace(go.Surface(x=sx, y=sy, z=cut(topo), name="Topography", colorscale="Blues", opacity=0.35, showscale=False, showlegend=True))
    for label, grid in shell_surfaces:
        fig.add_trace(go.Surface(x=sx, y=sy, z=cut(grid), name=label, colorscale="Viridis", showscale=False, visible="legendonly", showlegend=True))
    fig.add_trace(go.Surface(x=sx, y=sy, z=cut(pit), name=pit_label, colorscale="YlOrBr", showscale=False, showlegend=True))

    ve = exaggeration(xs, ys, topo)
    span = max(float(np.ptp(xs)), float(np.ptp(ys)), 1.0)
    relief = max(float(np.nanmax(topo) - np.nanmin(pit)), 1.0)

    def aspect(v: float) -> dict:
        return {"x": float(np.ptp(xs)) / span, "y": float(np.ptp(ys)) / span, "z": relief * v / span}

    fig.update_layout(
        title=f"{title} — {pit_label}, pushbacks and end-of-period surfaces (click legend to toggle)",
        scene={"aspectmode": "manual", "aspectratio": aspect(ve), "xaxis_title": "Easting", "yaxis_title": "Northing", "zaxis_title": "RL"},
        updatemenus=[
            {
                "type": "buttons",
                "direction": "right",
                "x": 0.0,
                "y": 1.08,
                "buttons": [
                    {"label": f"VE {v:g}x", "method": "relayout", "args": [{"scene.aspectratio": aspect(v)}]}
                    for v in (1, 5, ve, 2 * ve)
                ],
            }
        ],
        legend={"itemsizing": "constant"},
        margin={"l": 0, "r": 0, "t": 60, "b": 0},
    )
    fig.write_html(path, include_plotlyjs="cdn")


def pushback_table(blocks: pd.DataFrame, labels: dict[int, str], products: list[str]) -> pd.DataFrame:
    """Incremental tonnes and value per pushback, at the planning price."""
    rows = []
    cumulative_value = 0.0
    for n, text in sorted(labels.items()):
        phase = blocks[blocks["pushback"] == n]
        ore = phase[phase["destination"] == 1]
        rock_t = float(phase["rock_tonnes"].sum())
        waste_t = rock_t - float(ore["rock_tonnes"].sum())
        ore_t = float(ore["ore_tonnes"].sum())
        value = float(phase["value"].sum())
        cumulative_value += value
        row = {
            "pushback": n,
            "definition": text,
            "blocks": len(phase),
            "volume": float(phase["volume"].sum()),
            "ore_tonnes": ore_t,
            "waste_tonnes": waste_t,
            "strip_ratio": waste_t / ore_t if ore_t > 0 else float("nan"),
            "value": value,
            "cumulative_value": cumulative_value,
            "value_per_tonne_mined": value / rock_t if rock_t > 0 else 0.0,
        }
        for name in products:
            row[f"{name}_tonnes"] = float(ore[f"{name}_tonnes"].sum())
        rows.append(row)
    return pd.DataFrame(rows)


def input_summary(blocks: pd.DataFrame, grade_columns: list[str], elevation_grid: np.ndarray | None) -> pd.DataFrame:
    """What went in: extents, block counts and grade by domain and class."""
    rows = [
        ("Blocks used", f"{len(blocks):,}", ""),
        ("Easting range", f"{blocks['x'].min():,.1f} – {blocks['x'].max():,.1f}", "m"),
        ("Northing range", f"{blocks['y'].min():,.1f} – {blocks['y'].max():,.1f}", "m"),
        ("RL range", f"{blocks['z'].min():,.2f} – {blocks['z'].max():,.2f}", "m"),
        ("Block size", f"{blocks['dx'].iloc[0]:g} x {blocks['dy'].iloc[0]:g} x {blocks['dz'].iloc[0]:g}", "m"),
        ("Total volume", f"{blocks['volume'].sum():,.0f}", "m3"),
        ("Total tonnes", f"{blocks['rock_tonnes'].sum():,.0f}", "t"),
    ]
    if elevation_grid is not None and np.isfinite(elevation_grid).any():
        rows.append(("Topography RL", f"{np.nanmin(elevation_grid):,.2f} – {np.nanmax(elevation_grid):,.2f}", "m"))
    frame = pd.DataFrame(rows, columns=["Item", "Value", "Unit"])

    groups = [c for c in ("domain", "resource_class") if c in blocks.columns]
    if groups:
        weights = blocks["volume"].to_numpy()
        stats = []
        for keys, part in blocks.groupby(groups):
            keys = keys if isinstance(keys, tuple) else (keys,)
            record = dict(zip(groups, keys))
            record["blocks"] = len(part)
            record["volume"] = float(part["volume"].sum())
            for column in grade_columns:
                w = part["volume"].to_numpy()
                record[f"{column} (vol-weighted)"] = float(np.average(part[column], weights=w)) if w.sum() > 0 else 0.0
            stats.append(record)
        del weights
        return pd.concat([frame, pd.DataFrame([{}]), pd.DataFrame(stats)], ignore_index=True)
    return frame
