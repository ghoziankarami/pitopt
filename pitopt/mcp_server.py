# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Orebit (Ghozian Islam Karami)
"""
MCP server wrapping pitopt, so a pit run can be driven from an MCP client
(Claude Desktop, Claude Code, anything else that speaks MCP).

It is a thin layer over the same pipeline the CLI uses — a project YAML
in, DXF/CSV out — with the run result kept in memory so the report can be
queried afterwards without re-solving.

Setup:
    pip install -e ".[mcp]"
    pitopt run --config projects/example_tin/project.yaml   # confirm it works first
    python -m pitopt.mcp_server                             # stdio transport

Claude Desktop config (claude_desktop_config.json):
    "mcpServers": {
      "pit-optimizer": {
        "command": "/absolute/path/to/pit-optimization-mcp/.venv/bin/python",
        "args": ["-m", "pitopt.mcp_server"]
      }
    }

Written against `mcp` v2.x (MCPServer). On `mcp<2` the same class is
FastMCP at mcp.server.fastmcp.FastMCP — swap the import, nothing else
changes. When the optional `mcp` extra is not installed, importing this
module still succeeds so `PitOptCommands` and the tool functions can be
used and tested directly in Python.

Single-user by design: state lives in one module-level object, which is
fine for one client talking to one server process and not intended for
concurrent use.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer
    except ImportError:
        class MCPServer:  # pragma: no cover - fallback when optional [mcp] extra is absent
            def __init__(self, name: str) -> None:
                self.name = name

            def tool(self):
                def decorator(fn):
                    return fn

                return decorator

            def run(self) -> None:
                raise ImportError(
                    "The 'mcp' package is required to run the MCP server. "
                    "Install with: pip install -e '.[mcp]'"
                )

from .config import ProjectConfig
from .core.economics import marginal_cutoff_grades
from .core.limits import check_solver_memory
from .core.precedence import auto_bench_levels, cone_offsets
from .core.reblock import ReblockSpec, reblock, write_outputs
from .io.blockmodel import load_block_model
from .io.console import format_report, summarise_pit
from .pipeline import PitResult, clip_to_surface, load_elevation, run
from .provenance import fingerprint
from .ui.design_service import build_design

mcp = MCPServer("pit-optimizer")


@dataclass
class Session:
    config: ProjectConfig | None = None
    result: PitResult | None = None


class PitOptCommands:
    """Stateful command handler backing the PitOpt MCP tools."""

    def __init__(self, session: Session | None = None) -> None:
        self.session = session if session is not None else Session()

    def load_project(self, config_path: str) -> str:
        """Load a pitopt project YAML and report resolved parameters."""
        cfg = ProjectConfig.from_yaml(config_path)
        self.session.config = cfg
        self.session.result = None
        econ = cfg.economics
        return (
            f"Project '{cfg.name}' loaded.\n"
            f"Block model: {cfg.block_model.path}\n"
            f"Surface: {cfg.surface.path or '(none)'}\n"
            f"Slope: {cfg.slope.overall_angle_deg} deg, template levels {cfg.slope.max_bench_levels or 'auto'}\n"
            f"Revenue factors: {cfg.shells.revenue_factors}\n"
            f"Products: {', '.join(p.name for p in econ.products)}\n"
            f"Single-product cutoffs at RF 1.0: {marginal_cutoff_grades(econ, 1.0)}"
        )

    def set_product_price(self, product_name: str, price: float) -> str:
        """Override one product's price with atomic staging validation."""
        if self.session.config is None:
            return "No project loaded — call load_project first."
        staged = copy.deepcopy(self.session.config)
        for product in staged.economics.products:
            if product.name.upper() == product_name.upper():
                previous = product.price
                product.price = price
                staged.validate()
                self.session.config = staged
                self.session.result = None
                return f"{product.name} price {previous:,.2f} -> {price:,.2f}."
        available = ", ".join(p.name for p in self.session.config.economics.products)
        return f"No product named {product_name!r}. Available: {available}"

    def set_costs(
        self,
        mining_cost_per_volume: float | None = None,
        mining_cost_per_tonne: float | None = None,
        rehabilitation_cost_per_volume: float | None = None,
        processing_cost_per_tonne: float | None = None,
    ) -> str:
        """Override block-level costs with atomic staging validation."""
        if self.session.config is None:
            return "No project loaded — call load_project first."
        staged = copy.deepcopy(self.session.config)
        econ = staged.economics
        for name, value in (
            ("mining_cost_per_volume", mining_cost_per_volume),
            ("mining_cost_per_tonne", mining_cost_per_tonne),
            ("rehabilitation_cost_per_volume", rehabilitation_cost_per_volume),
            ("processing_cost_per_tonne", processing_cost_per_tonne),
        ):
            if value is not None:
                setattr(econ, name, value)
        staged.validate()
        self.session.config = staged
        self.session.result = None
        return "Costs updated."

    def set_slope(self, overall_angle_deg: float, max_bench_levels: int | None = None) -> str:
        """Override the overall slope angle with atomic staging validation."""
        if self.session.config is None:
            return "No project loaded — call load_project first."
        staged = copy.deepcopy(self.session.config)
        staged.slope.overall_angle_deg = overall_angle_deg
        staged.slope.max_bench_levels = max_bench_levels
        staged.validate()
        self.session.config = staged
        self.session.result = None
        return f"Slope set to {overall_angle_deg} deg, template levels {max_bench_levels or 'auto'}."

    def set_revenue_factors(self, revenue_factors: list[float]) -> str:
        """Set the revenue factors for nested shells with atomic staging validation."""
        if self.session.config is None:
            return "No project loaded — call load_project first."
        staged = copy.deepcopy(self.session.config)
        staged.shells.revenue_factors = revenue_factors
        staged.validate()
        self.session.config = staged
        self.session.result = None
        return f"Revenue factors set to {revenue_factors}."

    def validate_loaded_project(self) -> str:
        """Run pre-flight validation on the currently loaded project."""
        if self.session.config is None:
            return "No project loaded — call load_project first."
        cfg = self.session.config
        cfg.validate()
        blocks = clip_to_surface(load_block_model(cfg.block_model), load_elevation(cfg))
        bm = cfg.block_model
        levels = cfg.slope.max_bench_levels or auto_bench_levels(
            cfg.slope.overall_angle_deg, min(bm.dx, bm.dy), bm.dz
        )
        offsets = cone_offsets(cfg.slope.overall_angle_deg, bm.dx, bm.dy, bm.dz, levels)
        mem = check_solver_memory(len(blocks), len(blocks) * len(offsets))
        return (
            f"Validated '{cfg.name}': "
            f"{mem['blocks']} blocks, memory estimate {mem['need_gb']:.2f} GB."
        )

    def run_pit_optimization(self) -> str:
        """Solve every revenue-factor shell for the loaded project and write outputs."""
        if self.session.config is None:
            return "No project loaded — call load_project first."

        result = run(self.session.config, verbose=False)
        self.session.result = result

        econ = self.session.config.economics
        lines = [
            format_report(result.report, econ),
            "",
            summarise_pit(result.report, result.depth, econ),
            "",
            "Outputs:",
        ]
        lines += [f"  {label}: {path}" for label, path in result.outputs.items()]
        if not result.closure["closed"]:
            lines.append(
                f"\nWARNING: pit not closed inside the model "
                f"({result.closure['on_bottom']} blocks on the bottom bench, "
                f"{result.closure['on_sides']} on a lateral limit) — tonnes are understated."
            )
        if result.nesting_violations:
            lines.append(f"\nWARNING: {result.nesting_violations} block(s) broke shell nesting — check numerics.")
        return "\n".join(lines)

    def get_pit_report(self) -> str:
        """Return the pit-by-pit table from the most recent run."""
        if self.session.result is None or self.session.config is None:
            return "No pit solved yet — call run_pit_optimization first."
        return format_report(self.session.result.report, self.session.config.economics)

    def get_bench_summary(self) -> str:
        """Per-bench breakdown of the ultimate pit."""
        if self.session.result is None:
            return "No pit solved yet — call run_pit_optimization first."

        blocks = self.session.result.blocks
        pit = blocks[blocks["in_pit"]]
        is_ore = pit["destination"] == 1
        summary = (
            pit.assign(
                ore_t=pit["ore_tonnes"].where(is_ore, 0.0),
                waste_t=pit["rock_tonnes"].where(~is_ore, 0.0),
            )
            .groupby("bench")
            .agg(
                blocks=("value", "size"),
                ore_tonnes=("ore_t", "sum"),
                waste_tonnes=("waste_t", "sum"),
                value=("value", "sum"),
            )
            .sort_index(ascending=False)
        )
        return summary.to_string()

    def build_detail_design(
        self,
        bench_height: float | None = None,
        berm_width_m: float | None = None,
        bench_face_angle_deg: float | None = None,
        ramp_width_m: float | None = None,
        ramp_grade_pct: float | None = None,
    ) -> str:
        """Build a detailed bench-and-ramp design from the solved pit shell."""
        if self.session.config is None:
            return "No project loaded — call load_project first."
        if self.session.result is None:
            return "No pit solved yet — call run_pit_optimization first."

        staged = copy.deepcopy(self.session.config)
        staged.design.detail.enabled = True
        if bench_height is not None:
            staged.design.bench_height = bench_height
        if bench_face_angle_deg is not None:
            staged.design.bench_face_angle_deg = bench_face_angle_deg
        if berm_width_m is not None:
            staged.design.detail.berm.method = "manual"
            staged.design.detail.berm.width = berm_width_m
        if ramp_width_m is not None:
            staged.design.detail.ramp.enabled = True
            staged.design.detail.ramp.width_m = ramp_width_m
        if ramp_grade_pct is not None:
            staged.design.detail.ramp.grade_pct = ramp_grade_pct
        staged.validate()

        in_pit = self.session.result.blocks["in_pit"].to_numpy()
        detail = build_design(self.session.result.blocks, in_pit, staged)
        self.session.config = staged
        self.session.result.design_detail = detail

        lines = [
            f"Detailed design built for '{staged.name}':",
            f"  Benches: {len(detail.stack.benches)} ({detail.floor_rl:.1f} to {detail.crest_rl:.1f} mRL)",
            f"  Floor width: {detail.floor_width_m:.1f} m" + (" (widened)" if detail.floor_widened else ""),
            f"  Ramp: {'enabled' if detail.ramp is not None else 'disabled'}",
        ]
        if detail.validation is not None:
            lines.append(f"  Validation: {detail.validation.status}")
        if detail.reconciliation is not None:
            lines.append(
                f"  Reconciliation: rock {detail.reconciliation.change_pct('rock_tonnes'):+.2f}%, "
                f"ore {detail.reconciliation.change_pct('ore_tonnes'):+.2f}%"
            )
        if detail.warnings:
            lines.append("  Warnings: " + "; ".join(detail.warnings))
        return "\n".join(lines)

    def reblock_model(
        self,
        source: str,
        target_dx: float,
        target_dy: float,
        target_dz: float,
        x: str = "X",
        y: str = "Y",
        z: str = "Z",
        size_cols: list[str] | None = None,
        parent: list[float] | None = None,
        grades: list[str] | None = None,
        categories: list[str] | None = None,
        density: str | None = None,
        out_dir: str | None = None,
        name: str = "model",
        write_surface: bool = False,
    ) -> str:
        """Regularise a sub-celled or finely estimated block model into mining blocks."""
        spec = ReblockSpec(
            source=source,
            x=x,
            y=y,
            z=z,
            size_x=size_cols[0] if size_cols and len(size_cols) == 3 else None,
            size_y=size_cols[1] if size_cols and len(size_cols) == 3 else None,
            size_z=size_cols[2] if size_cols and len(size_cols) == 3 else None,
            parent=(float(parent[0]), float(parent[1]), float(parent[2])) if parent and len(parent) == 3 else None,
            grades=list(grades or []),
            categories=list(categories or []),
            density=density,
            target=(float(target_dx), float(target_dy), float(target_dz)),
        )
        blocks, summary = reblock(spec)
        lines = [
            f"Reblocked {source} -> {summary['blocks']:,} blocks of {target_dx:g} x {target_dy:g} x {target_dz:g} m",
            f"  Source volume: {summary['source_volume']:,.1f} m3",
            f"  Output volume: {summary['output_volume']:,.1f} m3",
            f"  Grade weighting: {summary['grade_weighting']}",
        ]
        if out_dir:
            written = write_outputs(blocks, spec, out_dir, name, surface=write_surface)
            for label, path in written.items():
                lines.append(f"  {label}: {path}")
        return "\n".join(lines)

    def audit_provenance(self) -> str:
        """Audit parameter provenance (input/terukur/asumsi) and run fingerprint."""
        if self.session.config is None:
            return "No project loaded — call load_project first."

        cfg = self.session.config
        prov = cfg.provenance or {}
        by_source: dict[str, list[tuple[str, str]]] = {}
        for path, info in sorted(prov.items()):
            if isinstance(info, dict):
                src = str(info.get("source", "unknown"))
                note = str(info.get("note") or info.get("ref") or "")
            else:
                src = str(info)
                note = ""
            by_source.setdefault(src, []).append((path, note))

        lines = [f"Provenance audit for '{cfg.name}':"]
        if not by_source:
            lines.append("  No explicit provenance entries recorded.")
        else:
            for src, entries in sorted(by_source.items()):
                lines.append(f"  [{src}] ({len(entries)}):")
                for path, note in entries:
                    suffix = f" — {note}" if note else ""
                    lines.append(f"    - {path}{suffix}")

        try:
            fp = fingerprint(cfg)
            lines.append(f"  Fingerprint sha256: {fp['sha256'][:16]}...")
            lines.append(f"  Parameters sha256: {fp['parameters_sha256'][:16]}...")
            lines.append(f"  Engine sha256: {fp['engine_sha256'][:16]}...")
        except OSError as exc:
            lines.append(f"  Fingerprint unavailable: {exc}")

        return "\n".join(lines)


commands = PitOptCommands()
session = commands.session


@mcp.tool()
def load_project(config_path: str) -> str:
    """Load a pitopt project YAML (see projects/example_tin/project.yaml) and report the
    resolved parameters, including the derived marginal cutoff grade."""
    return commands.load_project(config_path)


@mcp.tool()
def set_product_price(product_name: str, price: float) -> str:
    """Override one product's price, keeping every other parameter as
    loaded. The usual way to run a price-sensitivity case without editing
    the project file."""
    return commands.set_product_price(product_name, price)


@mcp.tool()
def set_costs(
    mining_cost_per_volume: float | None = None,
    mining_cost_per_tonne: float | None = None,
    rehabilitation_cost_per_volume: float | None = None,
    processing_cost_per_tonne: float | None = None,
) -> str:
    """Override the block-level costs. Mining and rehabilitation are
    charged on every block mined, ore or waste; processing only on plant
    feed. Leave an argument out to keep the loaded value."""
    return commands.set_costs(
        mining_cost_per_volume=mining_cost_per_volume,
        mining_cost_per_tonne=mining_cost_per_tonne,
        rehabilitation_cost_per_volume=rehabilitation_cost_per_volume,
        processing_cost_per_tonne=processing_cost_per_tonne,
    )


@mcp.tool()
def set_slope(overall_angle_deg: float, max_bench_levels: int | None = None) -> str:
    """Override the overall slope angle. Leave max_bench_levels unset so
    the precedence template is sized from the block shape."""
    return commands.set_slope(overall_angle_deg, max_bench_levels=max_bench_levels)


@mcp.tool()
def set_revenue_factors(revenue_factors: list[float]) -> str:
    """Set the revenue factors for the nested shells. RF 1.0 is the
    ultimate pit at the planning price; include it to get one."""
    return commands.set_revenue_factors(revenue_factors)


@mcp.tool()
def validate_loaded_project() -> str:
    """Run pre-flight validation on the currently loaded project without running the solver."""
    return commands.validate_loaded_project()


@mcp.tool()
def run_pit_optimization() -> str:
    """Solve every revenue-factor shell for the loaded project and write
    the DXF pit surface, CSV block model and pit-by-pit report."""
    return commands.run_pit_optimization()


@mcp.tool()
def get_pit_report() -> str:
    """Return the pit-by-pit table from the most recent run."""
    return commands.get_pit_report()


@mcp.tool()
def get_bench_summary() -> str:
    """Per-bench breakdown of the ultimate pit: blocks, ore and waste
    tonnes, and mill grade by elevation."""
    return commands.get_bench_summary()


@mcp.tool()
def build_detail_design(
    bench_height: float | None = None,
    berm_width_m: float | None = None,
    bench_face_angle_deg: float | None = None,
    ramp_width_m: float | None = None,
    ramp_grade_pct: float | None = None,
) -> str:
    """Build a detailed bench-and-ramp design from the currently solved pit shell."""
    return commands.build_detail_design(
        bench_height=bench_height,
        berm_width_m=berm_width_m,
        bench_face_angle_deg=bench_face_angle_deg,
        ramp_width_m=ramp_width_m,
        ramp_grade_pct=ramp_grade_pct,
    )


@mcp.tool()
def reblock_model(
    source: str,
    target_dx: float,
    target_dy: float,
    target_dz: float,
    x: str = "X",
    y: str = "Y",
    z: str = "Z",
    size_cols: list[str] | None = None,
    parent: list[float] | None = None,
    grades: list[str] | None = None,
    categories: list[str] | None = None,
    density: str | None = None,
    out_dir: str | None = None,
    name: str = "model",
    write_surface: bool = False,
) -> str:
    """Regularise a sub-celled or finely estimated block model into mining blocks."""
    return commands.reblock_model(
        source=source,
        target_dx=target_dx,
        target_dy=target_dy,
        target_dz=target_dz,
        x=x,
        y=y,
        z=z,
        size_cols=size_cols,
        parent=parent,
        grades=grades,
        categories=categories,
        density=density,
        out_dir=out_dir,
        name=name,
        write_surface=write_surface,
    )


@mcp.tool()
def audit_provenance() -> str:
    """Audit parameter provenance (input/terukur/asumsi) and run fingerprint for the loaded project."""
    return commands.audit_provenance()


def main() -> int:
    mcp.run()
    return 0


if __name__ == "__main__":
    mcp.run()
