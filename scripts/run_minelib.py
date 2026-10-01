"""
Validate the solver against a MineLib benchmark instance.

MineLib publishes real deposits as a pre-valued block model plus an
explicit precedence graph, so this bypasses pitopt's valuation and slope
modules entirely and exercises only the maximum-closure solve. That makes
it an independent check: if the pit comes out right here, the solver and
its graph convention are sound regardless of how the economics or the
cone template behave.

Usage:
    python scripts/run_minelib.py benchmarks/minelib_zuck_small zuck_small
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from pitopt.core.solver import solve_max_closure

ROOT = Path(__file__).resolve().parent.parent

BLOCK_COLS = ["id", "x", "y", "z", "cost", "value", "rock_tonnes", "ore_tonnes"]


def load_blocks(path: Path) -> pd.DataFrame:
    blocks = pd.read_csv(path, sep=r"\s+", header=None, names=BLOCK_COLS)
    blocks["block_value"] = blocks["value"] - blocks["cost"]
    return blocks


def load_precedence_arcs(path: Path) -> np.ndarray:
    arcs: list[tuple[int, int]] = []
    with open(path) as f:
        for line in f:
            parts = line.split()
            block, count = int(parts[0]), int(parts[1])
            arcs.extend((block, int(p)) for p in parts[2:2 + count])
    return np.asarray(arcs, dtype=np.int64)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("instance_dir")
    ap.add_argument("instance_name")
    args = ap.parse_args()

    instance = ROOT / args.instance_dir
    name = args.instance_name

    blocks = load_blocks(instance / f"{name}.blocks")
    arcs = load_precedence_arcs(instance / f"{name}.prec")
    print(f"[{name}] {len(blocks):,} blocks, {len(arcs):,} precedence arcs")

    in_pit = solve_max_closure(blocks["block_value"].to_numpy(), arcs)

    print(f"[{name}] Blocks in pit : {in_pit.sum():,} / {len(blocks):,}")
    print(f"[{name}] Rock tonnes   : {blocks.loc[in_pit, 'rock_tonnes'].sum():,.0f}")
    print(f"[{name}] Pit value     : {blocks.loc[in_pit, 'block_value'].sum():,.0f}")
    print(f"[{name}] Value if all  : {blocks['block_value'].sum():,.0f}  (pit must be >= this)")

    by_bench = blocks[in_pit].groupby("z").size()
    print("\nBlocks per bench (z increases downward in this dataset):")
    print(by_bench.to_string())


if __name__ == "__main__":
    main()
