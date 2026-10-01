"""Command-line entry point: pit optimisation driven by a YAML project file."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ProjectConfig
from .core.economics import marginal_cutoff_grades, product_margin
from .core.precedence import auto_bench_levels, effective_slope
from .io.console import format_report, summarise_pit
from .pipeline import run


def _cmd_run(args: argparse.Namespace) -> int:
    cfg = ProjectConfig.from_yaml(args.config)
    if args.outdir:
        cfg.output.directory = str(Path(args.outdir).resolve())

    result = run(cfg, verbose=not args.quiet)

    print()
    print(format_report(result.report, cfg.economics))
    print()
    print(summarise_pit(result.report, result.depth, cfg.economics))
    print()
    print("Outputs:")
    for label, path in result.outputs.items():
        print(f"  {label:<20} {path}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    cfg = ProjectConfig.from_yaml(args.config)

    problems = []
    if not Path(cfg.block_model.path).exists():
        problems.append(f"block model not found: {cfg.block_model.path}")
    if cfg.surface.path and not Path(cfg.surface.path).exists():
        problems.append(f"surface not found: {cfg.surface.path}")

    econ = cfg.economics
    print(f"Project        : {cfg.name}")
    print(f"Block model    : {cfg.block_model.path}")
    print(f"Surface        : {cfg.surface.path or '(none — full model treated as rock)'}")
    print(f"Block size     : {cfg.block_model.dx} x {cfg.block_model.dy} x {cfg.block_model.dz}")
    bm = cfg.block_model
    levels = cfg.slope.max_bench_levels or auto_bench_levels(cfg.slope.overall_angle_deg, min(bm.dx, bm.dy), bm.dz)
    achieved = effective_slope(cfg.slope.overall_angle_deg, min(bm.dx, bm.dy), bm.dz, levels)
    print(
        f"Slope          : {cfg.slope.overall_angle_deg} deg design, template {levels} bench levels "
        f"({'auto' if cfg.slope.max_bench_levels is None else 'fixed'})"
    )
    print(f"  achieved     : {achieved['axis_deg']:.1f} deg along grid axes, {achieved['diagonal_deg']:.1f} deg on diagonals")
    if achieved["diagonal_deg"] > cfg.slope.overall_angle_deg + 5:
        problems.append(
            f"diagonal walls reach {achieved['diagonal_deg']:.1f} deg against a {cfg.slope.overall_angle_deg} deg design — "
            "raise slope.max_bench_levels or leave it unset"
        )
    print(f"Revenue factors: {cfg.shells.revenue_factors}")
    print(f"Grade basis    : {econ.grade_basis}")
    print("Products       :")
    cutoffs = marginal_cutoff_grades(econ, 1.0, cfg.block_model.density)
    for product in econ.products:
        margin = product_margin(econ, product, 1.0)
        print(
            f"  {product.name:<12} price {product.price:>9,.2f}  recovery {product.plant_recovery:.3f}"
            f"  net margin/t {margin:>9,.2f}  cutoff {cutoffs[product.name]:.4f}"
        )
    feed_cost = econ.processing_cost_per_volume + cfg.block_model.density * econ.processing_cost_per_tonne
    if feed_cost <= 0:
        print("  (no ore-level processing cost, so cutoff is zero — the pit limit is set")
        print("   by whether revenue covers mining and rehabilitation, not by grade)")

    if problems:
        print("\nProblems:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nConfig OK.")
    return 0


def _cmd_reblock(args: argparse.Namespace) -> int:
    from .core.reblock import ReblockSpec, reblock, write_outputs

    spec = ReblockSpec(
        source=args.source,
        x=args.x, y=args.y, z=args.z,
        size_x=args.size_cols[0] if args.size_cols else None,
        size_y=args.size_cols[1] if args.size_cols else None,
        size_z=args.size_cols[2] if args.size_cols else None,
        parent=tuple(args.parent) if args.parent else None,
        grades=args.grades or [],
        categories=args.categories or [],
        density=args.density,
        target=tuple(args.size),
        normalise=dict(args.normalise or []),
    )
    blocks, summary = reblock(spec)
    written = write_outputs(blocks, spec, args.out, args.name, surface=not args.no_topo)

    print(f"Source            : {args.source}")
    print(f"Parent block      : {' x '.join(f'{v:g}' for v in summary['parent_size'].values())} m")
    print("Grid origin       : " + "  ".join(f"{k.upper()} {v:,.3f}" for k, v in summary["origin"].items()))
    print(f"Reblocked to      : {summary['blocks']:,} blocks of {' x '.join(f'{v:g}' for v in spec.target)} m")
    print(f"Volume source     : {summary['source_volume']:,.1f} m3")
    print(f"Volume reblocked  : {summary['output_volume']:,.1f} m3  "
          f"(difference {summary['output_volume'] - summary['source_volume']:+,.3f})")
    print(f"Grades weighted by: {summary['grade_weighting']}")
    table = summary["source_volume_by_category"]
    if table is not None:
        print("\nSource volume by " + " x ".join(spec.categories) + " (reconcile against the published resource):")
        print(table.to_frame("volume_m3").to_string(float_format=lambda v: f"{v:,.1f}"))
    for label, path in written.items():
        print(f"{label:<18}: {path}")

    import json

    record = {
        "source": Path(args.source).name,
        "parent_size": summary["parent_size"],
        "target": list(spec.target),
        "origin": summary["origin"],
        "blocks": summary["blocks"],
        "source_volume": summary["source_volume"],
        "output_volume": summary["output_volume"],
        "grade_weighting": summary["grade_weighting"],
        "categories": list(spec.categories),
        "source_volume_by_category": (
            table.reset_index().rename(columns={"volume": "volume_m3"}).to_dict("records") if table is not None else []
        ),
        "partial_fill_below_half": float((blocks["FILL"] < 0.5).mean()),
    }
    reblock_json = Path(args.out) / f"{args.name}_reblock.json"
    reblock_json.write_text(json.dumps(record, indent=2))
    print(f"{'reblock summary':<18}: {reblock_json}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pitopt", description="Open-pit ultimate pit limit optimisation (preflow-push)")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="solve the pit and write DXF/CSV outputs")
    run_parser.add_argument("--config", required=True, help="project YAML file")
    run_parser.add_argument("--outdir", help="override the output directory from the config")
    run_parser.add_argument("--quiet", action="store_true", help="suppress progress output")
    run_parser.set_defaults(func=_cmd_run)

    validate_parser = sub.add_parser("validate", help="check the config and report derived parameters")
    validate_parser.add_argument("--config", required=True, help="project YAML file")
    validate_parser.set_defaults(func=_cmd_validate)

    ui_parser = sub.add_parser("ui", help="start the local web UI")
    ui_parser.add_argument("--root", default=".", help="project root containing projects/")
    ui_parser.add_argument("--port", type=int, default=8765)
    ui_parser.add_argument("--no-browser", action="store_true")
    ui_parser.add_argument("--public-host", default=None, help="hostname(s) a reverse proxy forwards as Host, e.g. pitopt.orebit.id")
    ui_parser.add_argument("--demo", action="store_true", help="read-only public showcase: block every mutating request except the bench-design screens")
    ui_parser.set_defaults(func=lambda a: (__import__("pitopt.ui.server", fromlist=["serve"]).serve(a.root, a.port, not a.no_browser, a.public_host, a.demo), 0)[1])

    reblock_parser = sub.add_parser(
        "reblock", help="regularise a sub-celled / finely estimated block model (CSV or .DAT) to mining blocks"
    )
    reblock_parser.add_argument("source", help="block model: CSV, or self-describing fixed-width .DAT")
    reblock_parser.add_argument("--out", required=True, help="output directory")
    reblock_parser.add_argument("--name", default="model", help="output file prefix")
    reblock_parser.add_argument("--size", nargs=3, type=float, required=True, metavar=("DX", "DY", "DZ"), help="target block size")
    reblock_parser.add_argument("--x", default="X")
    reblock_parser.add_argument("--y", default="Y")
    reblock_parser.add_argument("--z", default="Z")
    reblock_parser.add_argument("--size-cols", nargs=3, metavar=("SX", "SY", "SZ"), help="per-block size columns")
    reblock_parser.add_argument("--parent", nargs=3, type=float, metavar=("PX", "PY", "PZ"), help="fixed source block size")
    reblock_parser.add_argument("--grades", nargs="*", help="grade columns to average")
    reblock_parser.add_argument("--categories", nargs="*", help="categorical columns (domain, class)")
    reblock_parser.add_argument("--density", help="density column; grades are then mass-weighted")
    reblock_parser.add_argument(
        "--normalise", nargs=2, action="append", metavar=("COLUMN", "REGEX"),
        help="strip a pattern from a categorical column first, e.g. --normalise CLASS '\\d+$'",
    )
    reblock_parser.add_argument("--no-topo", action="store_true", help="skip the top-of-model surface DXF")
    reblock_parser.set_defaults(func=_cmd_reblock)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
