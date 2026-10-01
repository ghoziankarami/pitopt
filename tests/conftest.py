"""
A self-contained engine run for the consistency tests.

The checks in test_results_consistency / test_outputs_consistency / test_independent_algorithms run against every
finished run they can find: whatever is in outputs/, plus one run of the bundled example generated here. That
keeps a fresh checkout (and CI) honest without needing a earlier `make example`. The generated run is cached in
.pytest_runs/ and rebuilt only when the engine source or the example inputs change.
"""
import hashlib
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / ".pytest_runs"


def _key() -> str:
    h = hashlib.sha256()
    files = (sorted(ROOT.glob("pitopt/**/*.py")) + sorted((ROOT / "projects/example_tin").glob("*.*"))
             + [ROOT / "tests/variants.py"])
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def pytest_configure(config):
    marker = RUNS / "key.txt"
    key = _key()
    if marker.exists() and marker.read_text() == key:
        return
    from pitopt.config import ProjectConfig
    from pitopt.pipeline import run

    shutil.rmtree(RUNS, ignore_errors=True)
    cfg = ProjectConfig.from_yaml(str(ROOT / "projects/example_tin/project.yaml"))
    cfg.output.directory = str(RUNS / "example_tin")
    run(cfg, verbose=False, context={"project": "example_tin", "scenario": "project"})

    # The data-variety runs (tests/variants.py): other commodities, grade bases and data shapes, so the same
    # independent checks run on more than tin wherever the suite runs.
    import sys

    sys.path.insert(0, str(ROOT / "tests"))
    from variants import VARIANTS

    for name, make in VARIANTS.items():
        cfg = ProjectConfig.from_yaml(str(make(RUNS / "_src")))
        cfg.output.directory = str(RUNS / name)
        run(cfg, verbose=False, context={"project": name, "scenario": "project"})
    marker.write_text(key)


def discover_runs() -> list[Path]:
    return sorted(ROOT.glob("outputs/*/*_results.json")) + sorted(ROOT.glob(".pytest_runs/*/*_results.json"))


def run_id(path: Path) -> str:
    return f"{path.parent.parent.name.strip('.')}/{path.parent.name}"
