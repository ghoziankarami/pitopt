"""
The optimiser and the detailed pit design are separate modules, and this keeps them so.

    pitopt/core/*                 the optimiser: valuation, precedence, solver, shells, planning, schedule
    pitopt/core/design_detail/    the detailed design (F-DES-6): its own config, geometry, ramp, validation

The design takes the optimiser's *result* — a block table with an in-pit mask — and never reaches into how it was
made, so it can be developed, tested, or pointed at a shell from elsewhere without touching the optimiser; and the
optimiser does not know the design exists beyond one hook. Read from the source (every import statement), not
by importing, so a violation fails here before it is ever run.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "pitopt"
DESIGN = ROOT / "core" / "design_detail"

# What the design package may import from the rest of PitOpt: the project's parameters and the shared
# cancellation token. Nothing from the optimiser itself.
DESIGN_MAY_IMPORT = {"pitopt.config", "pitopt.core.cancel"}

# Where the optimiser side is allowed to touch the design: the one pipeline hook, the design's exporter and its
# UI service. pitopt.config re-exports the design's parameter classes so ProjectConfig stays one description.
MAY_IMPORT_DESIGN = {"pitopt.pipeline", "pitopt.config", "pitopt.io.design_export", "pitopt.io.results",
                     "pitopt.ui.design_service"}


def module_name(path: Path) -> str:
    parts = path.relative_to(ROOT.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imports(path: Path) -> set[str]:
    """Absolute names of every pitopt module a file imports, including imports inside functions."""
    here = module_name(path).split(".")
    package = here if path.name == "__init__.py" else here[:-1]
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                name = ".".join(base + ([node.module] if node.module else []))
            else:
                name = node.module or ""
            if name.startswith("pitopt"):
                found.add(name)
                found.update(f"{name}.{a.name}" for a in node.names)          # `from pkg import module`
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith("pitopt"))
    return found


def is_design(name: str) -> bool:
    return name == "pitopt.core.design_detail" or name.startswith("pitopt.core.design_detail.")


def test_the_design_package_imports_nothing_from_the_optimiser():
    bad = {}
    for path in DESIGN.glob("*.py"):
        outside = {n for n in imports(path) if not is_design(n) and n not in DESIGN_MAY_IMPORT
                   and not any(n.startswith(f"{allowed}.") for allowed in DESIGN_MAY_IMPORT)}
        if outside:
            bad[path.name] = sorted(outside)
    assert not bad, f"the design package reaches into the optimiser: {bad}"


def test_only_the_hook_the_exporter_and_the_ui_service_use_the_design():
    bad = {}
    for path in ROOT.rglob("*.py"):
        name = module_name(path)
        if is_design(name):
            continue
        if any(is_design(n) for n in imports(path)) and name not in MAY_IMPORT_DESIGN:
            bad[name] = sorted(n for n in imports(path) if is_design(n))
    assert not bad, f"modules outside the allowed hooks import the design: {bad}"


def test_the_optimisers_core_never_imports_the_design():
    for path in (ROOT / "core").glob("*.py"):
        assert not any(is_design(n) for n in imports(path)), f"{path.name} imports the detailed design"


def test_the_design_config_module_stands_alone():
    """Its parameter classes are imported by pitopt.config, so they must import nothing from PitOpt at all —
    otherwise the two would import each other."""
    assert not {n for n in imports(DESIGN / "config.py") if n.startswith("pitopt")}


def test_the_boundary_check_itself_sees_a_violation():
    """A guard that can never fail proves nothing: feed it a file that breaks the rule."""
    sample = DESIGN / "_boundary_probe.py"
    sample.write_text("from ..solver import solve\n")
    try:
        assert "pitopt.core.solver" in imports(sample)
    finally:
        sample.unlink()
