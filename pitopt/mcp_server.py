"""
MCP server wrapping pitopt, so a pit run can be driven from an MCP client
(Claude Desktop, Claude Code, anything else that speaks MCP).

It is a thin layer over the same pipeline the CLI uses — a project YAML
in, DXF/CSV out — with the run result kept in memory so the report can be
queried afterwards without re-solving.

Setup:
    pip install -e ".[mcp]"
    pitopt run --config projects/example_tin/project.yaml   # confirm it works first
    python -m pitopt.mcp_server                                  # stdio transport

Claude Desktop config (claude_desktop_config.json):
    "mcpServers": {
      "pit-optimizer": {
        "command": "/absolute/path/to/pit-optimization-mcp/.venv/bin/python",
        "args": ["-m", "pitopt.mcp_server"]
      }
    }

Written against `mcp` v2.x (MCPServer). On `mcp<2` the same class is
FastMCP at mcp.server.fastmcp.FastMCP — swap the import, nothing else
changes.

Single-user by design: state lives in one module-level object, which is
fine for one client talking to one server process and not intended for
concurrent use.
"""
from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer

from .config import ProjectConfig
from .core.economics import marginal_cutoff_grades
from .io.console import format_report, summarise_pit
from .pipeline import PitResult, run

mcp = MCPServer("pit-optimizer")


@dataclass
class Session:
    config: ProjectConfig | None = None
    result: PitResult | None = None


session = Session()


@mcp.tool()
def load_project(config_path: str) -> str:
    """Load a pitopt project YAML (see projects/example_tin/project.yaml) and report the
    resolved parameters, including the derived marginal cutoff grade."""
    cfg = ProjectConfig.from_yaml(config_path)
    session.config = cfg
    session.result = None
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


@mcp.tool()
def set_product_price(product_name: str, price: float) -> str:
    """Override one product's price, keeping every other parameter as
    loaded. The usual way to run a price-sensitivity case without editing
    the project file."""
    if session.config is None:
        return "No project loaded — call load_project first."
    for product in session.config.economics.products:
        if product.name.upper() == product_name.upper():
            previous = product.price
            product.price = price
            session.config.validate()
            session.result = None
            return f"{product.name} price {previous:,.2f} -> {price:,.2f}."
    available = ", ".join(p.name for p in session.config.economics.products)
    return f"No product named {product_name!r}. Available: {available}"


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
    if session.config is None:
        return "No project loaded — call load_project first."
    econ = session.config.economics
    for name, value in (
        ("mining_cost_per_volume", mining_cost_per_volume),
        ("mining_cost_per_tonne", mining_cost_per_tonne),
        ("rehabilitation_cost_per_volume", rehabilitation_cost_per_volume),
        ("processing_cost_per_tonne", processing_cost_per_tonne),
    ):
        if value is not None:
            setattr(econ, name, value)
    session.config.validate()
    session.result = None
    return "Costs updated."


@mcp.tool()
def set_slope(overall_angle_deg: float, max_bench_levels: int | None = None) -> str:
    """Override the overall slope angle. Leave max_bench_levels unset so
    the precedence template is sized from the block shape."""
    if session.config is None:
        return "No project loaded — call load_project first."
    session.config.slope.overall_angle_deg = overall_angle_deg
    session.config.slope.max_bench_levels = max_bench_levels
    session.config.validate()
    session.result = None
    return f"Slope set to {overall_angle_deg} deg, template levels {max_bench_levels or 'auto'}."


@mcp.tool()
def set_revenue_factors(revenue_factors: list[float]) -> str:
    """Set the revenue factors for the nested shells. RF 1.0 is the
    ultimate pit at the planning price; include it to get one."""
    if session.config is None:
        return "No project loaded — call load_project first."
    session.config.shells.revenue_factors = revenue_factors
    session.config.validate()
    session.result = None
    return f"Revenue factors set to {revenue_factors}."


@mcp.tool()
def run_pit_optimization() -> str:
    """Solve every revenue-factor shell for the loaded project and write
    the DXF pit surface, CSV block model and pit-by-pit report."""
    if session.config is None:
        return "No project loaded — call load_project first."

    result = run(session.config, verbose=False)
    session.result = result

    econ = session.config.economics
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


@mcp.tool()
def get_pit_report() -> str:
    """Return the pit-by-pit table from the most recent run."""
    if session.result is None:
        return "No pit solved yet — call run_pit_optimization first."
    return format_report(session.result.report, session.config.economics)


@mcp.tool()
def get_bench_summary() -> str:
    """Per-bench breakdown of the ultimate pit: blocks, ore and waste
    tonnes, and mill grade by elevation."""
    if session.result is None:
        return "No pit solved yet — call run_pit_optimization first."

    blocks = session.result.blocks
    pit = blocks[blocks["in_pit"]]
    is_ore = pit["destination"] == 1
    summary = (
        pit.assign(
            ore_t=pit["ore_tonnes"].where(is_ore, 0.0),
            waste_t=pit["rock_tonnes"].where(~is_ore, 0.0),
        )
        .groupby("bench")
        .agg(blocks=("value", "size"), ore_tonnes=("ore_t", "sum"), waste_tonnes=("waste_t", "sum"), value=("value", "sum"))
        .sort_index(ascending=False)
    )
    return summary.to_string()


if __name__ == "__main__":
    mcp.run()
