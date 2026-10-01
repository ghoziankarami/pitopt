"""
The checks that say whether a design can be built and defended.

Five headline validations, each returning findings with a status of OK,
warning or blocked:

    ira               inter-ramp angle per sector against its limit
    osa               overall angle per sector against its limit, ramp counted
    reconciliation    tonnes, ore and value of the design against the shell
    ramp              the road is one continuous path, as wide as the fleet needs
    self_intersection no bench outline crosses itself and no wall overhangs

and two more: `min_width` for the floor, and `shape_fit`, which is not in
the PRD's original five. It exists because the offset construction
(build_bench_stack, PRD F-DES-6) never looks at the shell again once the
anchor outline is taken: every bench's wall is the last bench's wall
moved out by a fixed, formula-derived distance, nothing else. That
matches a shell that is one cone widening steadily from its floor to its
crest (porphyry, most hard-rock open pits — confirmed by comparing every
bench's own area against the shell's at the same elevation: never below
about 104% of it on the bundled porphyry example, i.e. the design is
always at least as wide as the true shell there). It is wrong for a
shell whose footprint balloons at a middle elevation and pinches at both
ends — a wide, shallow, undulating deposit such as mineral-sands strip
mining, or a stratiform seam — because offsetting outward from a floor
or crest that is a sliver of the shell's true width never catches up to
it. Found by running the engine against a real mineral-sands mine's shell:
the practical design came out 96.8% smaller than the shell (the existing
raster design agrees with the shell to +1.6% on the same run), and the
worst bench there tracks the shell at 6.3% of its true area — no berm or
grade tuning fixes that, because the fault is the shape, not a number.

`shape_fit` catches this directly: at every bench, on both the toe and
the crest, it compares that ring's own area against the shell's true
footprint area at the matching elevation, and reports the bench and
side where the two agree the least. Below `SHAPE_WARN_RATIO` the design
may fall short of the shell's true width somewhere up the wall; below
`SHAPE_BLOCK_RATIO` it does not fit a single-cone offset at all, and the
reconciliation figures that follow should not be trusted without reading
this finding first. `source` on `design.detail` (final_shell today, PRD
F-DES-6 leaves pushback for later) is a separate question from whether
the shape itself fits.

A finding names what it checked, where, the value and the limit, so the
report can say why and not only that. Statuses are stored, not
recomputed later: what was written to a file is what was decided.
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely import is_valid_reason

from .angles import SectorOSA
from .config import DesignLimitsConfig
from .footprint import ShellFit
from .parameters import BLOCKED, OK, WARNING
from .ramp import Ramp
from .reconcile import Reconciliation
from .stack import BenchStack

CHECKS = ("shape_fit", "ira", "osa", "reconciliation", "ramp", "self_intersection", "min_width")
_RANK = {OK: 0, WARNING: 1, BLOCKED: 2}

# A bench's own area (toe or crest), as a fraction of the shell's true footprint area at the matching
# elevation — the worst such ratio anywhere in the stack. Calibrated against the three real shells on hand:
# the bundled porphyry example never dips below ~104% (the design is always a little larger than the shell
# there, which is what a correctly-widening cone should do), the bundled tin example's worst point is ~87%
# (a mild edge effect near its floor), and a real mineral-sands mine's shell — the shape this check exists
# for — falls to 6.3%. WARN and BLOCK sit between the good pair and the bad one with visible margin either
# side; revisit if a legitimate shell is ever found to sit inside that gap.
SHAPE_WARN_RATIO = 0.7
SHAPE_BLOCK_RATIO = 0.4


@dataclass
class Finding:
    check: str
    scope: str                            # a sector, a bench, a metric; "" for the whole design
    status: str
    message: str
    value: float | None = None
    limit: float | None = None


@dataclass
class Validation:
    findings: list[Finding]

    def status(self, check: str | None = None) -> str:
        """Worst status of one check, or of all of them."""
        chosen = [f.status for f in self.findings if check is None or f.check == check]
        return max(chosen, key=_RANK.__getitem__, default=OK)

    def by_check(self) -> dict[str, str]:
        return {c: self.status(c) for c in CHECKS}

    def problems(self) -> list[Finding]:
        return [f for f in self.findings if f.status != OK]


def _angle(check: str, sector, value: float, limit: float | None, status: str, label: str) -> Finding:
    if limit is None:
        return Finding(check, sector, OK, f"{label} {value:.1f} deg, no limit set", value, None)
    margin = limit - value
    verb = {OK: "within", WARNING: "within the margin of", BLOCKED: "over"}[status]
    return Finding(check, sector, status, f"{label} {value:.1f} deg is {verb} the {limit:g} deg limit ({margin:+.1f} deg)",
                   value, limit)


def _shape_fit_finding(fit: ShellFit) -> Finding:
    status = BLOCKED if fit.ratio < SHAPE_BLOCK_RATIO else WARNING if fit.ratio < SHAPE_WARN_RATIO else OK
    where = f"bench {fit.bench} ({fit.side}, RL {fit.rl:g})"
    if status == OK:
        message = f"the design tracks the shell within {fit.ratio:.0%} everywhere; worst at {where}"
    else:
        verb = "falls short of" if status == WARNING else "does not fit"
        message = (f"at {where} the design covers {fit.design_area_m2:,.0f} m2 against {fit.shell_area_m2:,.0f} m2 "
                   f"the shell actually reaches there ({fit.ratio:.0%}); the offset construction {verb} the "
                   f"shell's true width at this elevation"
                   + ("; treat the reconciliation below with that in mind" if status == BLOCKED else ""))
    # scope carries the same "bench N (side, RL x)" a UI needs to render this without re-parsing the English
    # message, the same convention self_intersection's findings use for their own "bench N" scope.
    return Finding("shape_fit", where, status, message, fit.ratio, SHAPE_BLOCK_RATIO if status == BLOCKED else SHAPE_WARN_RATIO)


def validate(stack: BenchStack, angles, osa: list[SectorOSA], ramp: Ramp | None, floor_width_m: float,
             reconciliation: Reconciliation | None, limits: DesignLimitsConfig,
             shape_fit: ShellFit | None = None) -> Validation:
    findings: list[Finding] = []

    if shape_fit is not None:
        findings.append(_shape_fit_finding(shape_fit))

    for a in angles:
        findings.append(_angle("ira", a.name, a.ira_deg, a.ira_max_deg, a.status, "inter-ramp angle"))
    for o in osa:
        findings.append(_angle("osa", o.name, o.osa_deg, o.osa_max_deg, o.status, "overall angle with the ramp"))

    if reconciliation is not None:
        for metric, label in (("rock_tonnes", "rock"), ("ore_tonnes", "ore"), ("value", "value")):
            change, status = reconciliation.change_pct(metric), reconciliation.status(metric)
            if change != change:                                            # nan: the shell holds none of it
                continue
            limit = reconciliation.block_pct if status == BLOCKED else reconciliation.warn_pct
            findings.append(Finding("reconciliation", label, status,
                                    f"{label} of the design is {change:+.1f}% against the shell (warning beyond "
                                    f"{reconciliation.warn_pct:g}%, blocked beyond {reconciliation.block_pct:g}%)", change, limit))

    if ramp is None:
        findings.append(Finding("ramp", "", OK, "no ramp requested"))
    else:
        if ramp.broken:
            findings.append(Finding("ramp", f"bench {ramp.broken.bench}", BLOCKED, f"the ramp is broken: {ramp.broken.reason}"))
        else:
            findings.append(Finding("ramp", "", OK, f"one continuous road from the floor to the crest, "
                                                    f"{ramp.horizontal_length_m:,.0f} m at {ramp.sizing.grade_pct:g}%"))
        if not ramp.sizing.width_ok:
            findings.append(Finding("ramp", "", WARNING, f"the road is {ramp.sizing.width_m:g} m wide, narrower than the "
                                                         f"{ramp.sizing.required_width_m:g} m the fleet needs",
                                    ramp.sizing.width_m, ramp.sizing.required_width_m))

    tolerance = limits.tolerance_m
    invalid = [b for b in stack.benches if not (b.crest.is_valid and b.toe.is_valid)]
    for b in invalid:
        why = "; ".join(is_valid_reason(g) for g in (b.crest, b.toe) if not g.is_valid)
        findings.append(Finding("self_intersection", f"bench {b.index}", BLOCKED, f"outline is not a valid polygon: {why}"))
    overhangs = [f"bench {a.index}/{b.index}" for a, b in zip(stack.benches, stack.benches[1:])
                 if a.toe.is_valid and b.crest.is_valid and not a.toe.buffer(tolerance).contains(b.crest)]
    for where in overhangs:
        findings.append(Finding("self_intersection", where, BLOCKED, "the wall overhangs: a bench sits outside the one above it"))
    if ramp is not None:
        for bench, strip in ramp.strips.items():
            if not strip.is_valid:
                findings.append(Finding("self_intersection", f"bench {bench}", BLOCKED, "the road strip is not a valid polygon"))
    if not invalid and not overhangs and all(s.is_valid for s in (ramp.strips.values() if ramp else [])):
        findings.append(Finding("self_intersection", "", OK,
                                f"{len(stack.benches)} benches: every outline is valid and no wall overhangs"))

    minimum = limits.min_mining_width_m
    findings.append(Finding("min_width", "floor", OK if floor_width_m >= minimum else BLOCKED,
                            f"the floor is {floor_width_m:.1f} m wide against a {minimum:g} m minimum mining width",
                            floor_width_m, minimum))
    return Validation(findings)
