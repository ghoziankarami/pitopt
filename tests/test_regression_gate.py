"""
A locked copy of the engine's answer, so a change that was meant to add
something cannot quietly move something else.

The other consistency tests assert *properties*: tonnes add up, no block
is mined before its cone, the design volume matches the exported surface.
Those catch a wrong result. They do not catch a result that is merely
different — a shifted wall, a berm sized by a new rule, one more bench in
the bowl. Every one of those is arithmetically self-consistent and every
one of those changes what a client is told the pit contains.

So this test pins the numbers themselves. It digests the whole results
document of the bundled example run into path -> value pairs and compares
them against a committed fixture. Large grids (the 3D surfaces, the plan
view) are digested to count/sum/min/max rather than element by element:
the fixture stays readable, and a surface that moves anywhere still moves
its sum.

Changing the engine's output is allowed — it is not allowed to be
accidental. When a change is intended, regenerate the fixture and the
diff in the commit shows exactly which numbers moved:

    PITOPT_UPDATE_GOLDEN=1 .venv/bin/pytest tests/test_regression_gate.py

A reviewer then reads that diff as the statement of what changed.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).parent / "golden" / "example_tin.json"

# Paths whose value is a property of *this* run rather than of the engine's
# answer: wall-clock time, absolute locations, file sizes that move with a
# library's own formatting. Pinning them would make the gate cry wolf.
VOLATILE = {
    "meta.run_at",
    "meta.duration_s",
    "meta.config_path",
    "meta.surfaces",
    "meta.engine_version",
    "params.block_model.path",
    "params.surface.path",
    "params.output.directory",
}
VOLATILE_PREFIXES = ("outputs[",)

# Lists longer than this are summarised instead of expanded. Ten revenue
# factors and a handful of schedule periods stay legible; a 150 x 150
# surface grid does not.
EXPAND_LIMIT = 64


def _numbers(value) -> list[float]:
    """Every finite number anywhere inside a nested list."""
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)] if math.isfinite(value) else []
    if isinstance(value, list):
        return [n for item in value for n in _numbers(item)]
    return []


def _summarise(value: list) -> dict:
    """A long array's fingerprint. The sum moves if any element moves; the
    count moves if the grid is resized; min and max move if the extremes
    shift, which is what a changed wall angle does first."""
    numbers = _numbers(value)
    if not numbers:
        return {"n": len(value), "finite": 0}
    return {
        "n": len(value),
        "finite": len(numbers),
        "sum": sum(numbers),
        "min": min(numbers),
        "max": max(numbers),
    }


def digest(document: dict) -> dict:
    """Flatten a results document to path -> comparable value."""
    flat: dict = {}

    def walk(value, path: str) -> None:
        if path in VOLATILE or path.startswith(VOLATILE_PREFIXES):
            return
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            if not value:                       # an empty list must not read as an absent key
                flat[path] = []
                return
            expandable = len(value) <= EXPAND_LIMIT and all(isinstance(i, (dict, str)) for i in value)
            if expandable:
                for index, item in enumerate(value):
                    walk(item, f"{path}[{index}]")
            else:
                flat[path] = _summarise(value)
        elif isinstance(value, float) and not math.isfinite(value):
            flat[path] = "nan"
        else:
            flat[path] = value

    walk(document, "")
    return flat


def _results() -> Path:
    """The example run conftest generates for every test session."""
    found = sorted(ROOT.glob(".pytest_runs/example_tin/*_results.json"))
    return found[0] if found else None


def _differences(expected: dict, actual: dict, rel: float = 1e-9, abs_: float = 1e-9) -> list[str]:
    out = []
    for key in sorted(set(expected) | set(actual)):
        if key not in actual:
            out.append(f"{key}: missing from this run (was {expected[key]!r})")
        elif key not in expected:
            out.append(f"{key}: new in this run ({actual[key]!r}) — regenerate the fixture if intended")
        else:
            out.extend(f"{key}.{d}" for d in _compare(expected[key], actual[key], rel, abs_))
    return out


def _compare(expected, actual, rel: float, abs_: float) -> list[str]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        return [f"{k}: {d}" for k in sorted(set(expected) | set(actual))
                for d in _compare(expected.get(k), actual.get(k), rel, abs_)]
    if isinstance(expected, bool) or isinstance(actual, bool) or not isinstance(expected, (int, float)):
        return [] if expected == actual else [f"{expected!r} -> {actual!r}"]
    if not isinstance(actual, (int, float)):
        return [f"{expected!r} -> {actual!r}"]
    if abs(expected - actual) <= max(abs_, rel * abs(expected)):
        return []
    return [f"{expected!r} -> {actual!r}"]


@pytest.mark.skipif(_results() is None, reason="no generated example run")
def test_engine_output_matches_the_locked_answer():
    current = digest(json.loads(_results().read_text()))

    if os.environ.get("PITOPT_UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n")
        pytest.skip(f"fixture regenerated: {GOLDEN.relative_to(ROOT)} — review the diff before committing")

    assert GOLDEN.exists(), f"no fixture at {GOLDEN.relative_to(ROOT)}; run with PITOPT_UPDATE_GOLDEN=1"
    differences = _differences(json.loads(GOLDEN.read_text()), current)
    assert not differences, (
        f"{len(differences)} value(s) moved against {GOLDEN.relative_to(ROOT)}:\n  "
        + "\n  ".join(differences[:40])
        + ("\n  ..." if len(differences) > 40 else "")
        + "\n\nIf the change is intended: PITOPT_UPDATE_GOLDEN=1 .venv/bin/pytest tests/test_regression_gate.py"
    )
