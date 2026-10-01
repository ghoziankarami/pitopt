"""
Cross-check the preflow-push solve against an unrelated max-flow algorithm.

The maximum closure is unique in value, so any correct min-cut solver on
the same graph must return a pit of exactly the same value — and, when
the optimum is unique, exactly the same blocks. Boykov-Kolmogorov (from
networkx) uses a different flow algorithm from preflow-push, so agreement means
the graph construction, the cut reading and the solver are all right.

A brute-force check is added on a tiny random model, where every closed
set can be enumerated, so the claim "exact optimum" is tested directly.

Usage:
    python scripts/cross_check_solver.py projects/porphyry_synthetic/project.yaml
"""
from __future__ import annotations

import argparse
import itertools
import time
from pathlib import Path

import networkx as nx
import numpy as np
from networkx.algorithms.flow import boykov_kolmogorov

from pitopt.config import ProjectConfig
from pitopt.core.economics import value_blocks
from pitopt.core.precedence import add_grid_indices, build_precedence
from pitopt.core.solver import solve_max_closure
from pitopt.io.blockmodel import load_block_model
from pitopt.pipeline import clip_to_surface, load_elevation

ROOT = Path(__file__).resolve().parent.parent


def networkx_closure(values: np.ndarray, arcs: np.ndarray) -> np.ndarray:
    graph = nx.DiGraph()
    big = float(np.abs(values).sum()) + 1.0
    for i in np.flatnonzero(values > 0):
        graph.add_edge("s", int(i), capacity=float(values[i]))
    for i in np.flatnonzero(values < 0):
        graph.add_edge(int(i), "t", capacity=float(-values[i]))
    graph.add_nodes_from(range(len(values)))
    graph.add_edges_from((int(b), int(p), {"capacity": big}) for b, p in arcs)
    graph.add_nodes_from(["s", "t"])
    _, (source_side, _) = nx.minimum_cut(graph, "s", "t", flow_func=boykov_kolmogorov)
    in_pit = np.zeros(len(values), dtype=bool)
    in_pit[[n for n in source_side if n != "s"]] = True
    return in_pit


def brute_force(seed: int = 1) -> None:
    """Enumerate every subset of a tiny 2-bench model, keep the closed
    ones, and confirm the solver finds the best."""
    rng = np.random.default_rng(seed)
    upper, lower = 6, 4
    values = rng.normal(0, 10, upper + lower)
    arcs = []
    for b in range(lower):
        for u in range(b, b + 3):
            arcs.append((upper + b, u))
    arcs = np.array(arcs)
    best = -np.inf
    for mask in itertools.product([0, 1], repeat=upper + lower):
        chosen = np.array(mask, dtype=bool)
        if all(not chosen[b] or chosen[p] for b, p in arcs):
            best = max(best, values[chosen].sum())
    solved = values[solve_max_closure(values, arcs)].sum()
    assert np.isclose(best, solved), (best, solved)
    print(f"  brute force over {2 ** (upper + lower):,} subsets: best closure {best:.4f} = preflow-push {solved:.4f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--revenue-factor", type=float, default=1.0)
    args = ap.parse_args()

    print("== Exactness on a model small enough to enumerate ==")
    for seed in range(1, 6):
        brute_force(seed)

    cfg = ProjectConfig.from_yaml(args.config)
    blocks = load_block_model(cfg.block_model, cfg.economics)
    elevation = load_elevation(cfg)
    if elevation is not None:
        blocks = clip_to_surface(blocks, elevation)
    blocks = add_grid_indices(blocks)
    arcs = build_precedence(blocks, cfg.slope.overall_angle_deg, cfg.slope.max_bench_levels,
                            domain_angles=cfg.slope.domain_angles)
    values = value_blocks(blocks, cfg.economics, args.revenue_factor)["value"].to_numpy()

    print(f"\n== {cfg.name}: {len(values):,} blocks, {len(arcs):,} arcs, RF {args.revenue_factor} ==")
    t = time.time()
    pseudo = solve_max_closure(values, arcs)
    print(f"  preflow-push      : {pseudo.sum():,} blocks, value {values[pseudo].sum():,.2f}  ({time.time() - t:.1f}s)")
    t = time.time()
    other = networkx_closure(values, arcs)
    print(f"  boykov-kolmogorov : {other.sum():,} blocks, value {values[other].sum():,.2f}  ({time.time() - t:.1f}s)")
    differ = int((pseudo != other).sum())
    print(f"  blocks that differ: {differ:,}  value difference {values[pseudo].sum() - values[other].sum():,.4f}")
    print("  AGREE" if np.isclose(values[pseudo].sum(), values[other].sum()) else "  DISAGREE")


if __name__ == "__main__":
    main()
