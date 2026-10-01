"""
Quick-look review figure: the pit surface next to the pit-by-pit curves.

Not a deliverable — the DXF and CSVs are. This exists so a run can be
sanity-checked at a glance before anything is opened in a design package:
a pit that came out inverted, truncated at the model edge, or with a
value curve peaking away from RF 1.0 is obvious here and easy to miss in
a table.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def write_review_plot(
    xs: np.ndarray, ys: np.ndarray, grid_z: np.ndarray, report: pd.DataFrame, path: str, title: str
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(13.5, 5.5))

    ax = fig.add_subplot(121, projection="3d")
    mesh_x, mesh_y = np.meshgrid(xs, ys, indexing="ij")
    ax.plot_surface(mesh_x, mesh_y, grid_z, cmap="copper", linewidth=0, antialiased=True, rstride=1, cstride=1)
    ax.set_xlabel("Easting")
    ax.set_ylabel("Northing")
    ax.set_zlabel("RL")
    ax.set_title(f"{title} — final pit surface")
    ax.view_init(elev=30, azim=-125)

    ax2 = fig.add_subplot(122)
    rf = report["revenue_factor"]
    ax2.bar(rf, report["ore_tonnes"] / 1e6, width=0.006, color="#c9a227", label="Ore Mt")
    ax2.bar(rf, report["waste_tonnes"] / 1e6, width=0.006, bottom=report["ore_tonnes"] / 1e6, color="#9aa5b1", label="Waste Mt")
    ax2.set_xlabel("Revenue factor")
    ax2.set_ylabel("Tonnes (Mt)")

    ax3 = ax2.twinx()
    if "npv_best" in report:
        ax3.plot(rf, report["npv_best"] / 1e6, "o-", color="#1f77b4", label="NPV best case")
        ax3.plot(rf, report["npv_worst"] / 1e6, "s-", color="#d62728", label="NPV worst case")
        ax3.plot(rf, report["npv_average"] / 1e6, "--", color="#555555", label="NPV average")
        ax3.set_ylabel("Discounted NPV (millions)")
        title = "Pit by pit — discounted NPV and tonnes"
    else:
        ax3.plot(rf, report["value"] / 1e6, "o-", color="#1f77b4", label="Undiscounted value")
        ax3.set_ylabel("Value at planning price (millions)")
        title = "Pit by pit — value and tonnes"
    if "final_pit" in report and report["final_pit"].any():
        chosen = float(rf[report["final_pit"]].iloc[0])
        ax3.axvline(chosen, color="#2a9d8f", linewidth=2, alpha=0.7)
        ax3.annotate(f"final pit RF {chosen:.2f}", (chosen, ax3.get_ylim()[1]), textcoords="offset points",
                     xytext=(4, -14), color="#2a9d8f", fontsize=9)
    lines = ax2.get_legend_handles_labels()
    more = ax3.get_legend_handles_labels()
    ax3.legend(lines[0] + more[0], lines[1] + more[1], loc="upper left", fontsize=8)
    ax2.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
