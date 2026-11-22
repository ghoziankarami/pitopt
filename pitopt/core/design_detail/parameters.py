"""
The numbers that describe one stretch of wall, and the angles they imply.

Everything here is closed-form and checked against a hand calculation in
the tests. Nothing touches a polygon: this module answers "what should the
wall be" so that the geometry modules only have to answer "where is it".

    run    = H / tan(face)                       horizontal width of one face
    berm   = criterion(H, face)                  catch bench, see BermConfig
    IRA    = atan( N H / (N run + berm) )        inter-ramp angle, N benches
                                                 between berms

The inter-ramp angle is the wall angle of a whole stack of benches with the
berms counted in and no ramp: it is what a geotechnical study gives an
allowable value for. The overall angle, which also counts the haul road,
needs a ramp and is computed where the ramp is built.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ...config import DesignConfig
from .config import BermConfig, SectorConfig

# Modified Ritchie catch-bench width, W = 0.2 H + 4.5 m. The relation was
# fitted to benches of roughly 15-30 m; above that the width is an
# extrapolation of the fit and the design says so.
RITCHIE_A, RITCHIE_B = 0.2, 4.5
RITCHIE_H_MAX = 30.0

OK, WARNING, BLOCKED = "OK", "PERINGATAN", "BLOKIR"


@dataclass(frozen=True)
class SectorGeometry:
    """One sector's fully resolved wall geometry — no field left unset."""

    name: str
    azimuth_from: float
    azimuth_to: float
    bench_height: float
    face_angle_deg: float
    berm_every_n: int
    berm_width: float
    berm_method: str
    ira_max_deg: float | None
    osa_max_deg: float | None

    @property
    def face_run(self) -> float:
        return self.bench_height / math.tan(math.radians(self.face_angle_deg))

    @property
    def ira_deg(self) -> float:
        return inter_ramp_angle_deg(self.bench_height, self.face_angle_deg, self.berm_width, self.berm_every_n)

    def crest_offset(self, k: int) -> float:
        """Horizontal distance of the crest of the k-th bench from the
        anchor, k = 0 being the anchor bench itself:
        k run + floor(k / N) berm."""
        return k * self.face_run + (k // self.berm_every_n) * self.berm_width

    def toe_offset(self, k: int) -> float:
        """Horizontal distance of that bench's toe: one face further in."""
        return self.crest_offset(k) + self.face_run


def berm_width(berm: BermConfig, bench_height: float, face_angle_deg: float, berm_every_n: int,
               overall_angle_deg: float) -> tuple[float, str | None]:
    """Berm width by the configured criterion, and a note when the criterion
    is being used outside the range it was derived for."""
    if berm.method == "manual":
        return float(berm.width), None
    if berm.method == "ritchie":
        note = None
        if bench_height > RITCHIE_H_MAX:
            note = (f"Ritchie berm criterion is fitted to benches up to about {RITCHIE_H_MAX:g} m; "
                    f"{bench_height:g} m is an extrapolation")
        return RITCHIE_A * bench_height + RITCHIE_B, note
    if berm.method == "ryan":
        return berm.ryan_a * bench_height + berm.ryan_b, None
    # slope: the berm that makes the inter-ramp angle equal the optimiser's
    # overall angle, so design and optimiser agree on the wall.
    run = bench_height / math.tan(math.radians(face_angle_deg))
    stack_run = berm_every_n * bench_height / math.tan(math.radians(overall_angle_deg))
    width = stack_run - berm_every_n * run
    if width < 0:
        raise ValueError(
            f"face angle {face_angle_deg:g} deg is flatter than the overall slope {overall_angle_deg:g} deg: "
            "no berm can make the benches honour it"
        )
    return width, None


def inter_ramp_angle_deg(bench_height: float, face_angle_deg: float, berm: float, berm_every_n: int) -> float:
    run = bench_height / math.tan(math.radians(face_angle_deg))
    return math.degrees(math.atan2(berm_every_n * bench_height, berm_every_n * run + berm))


def _domain_sectors_from_blocks(
    blocks: pd.DataFrame,
    in_pit: np.ndarray | None,
    domain_angles: dict,
    overall_angle_deg: float,
    n_bins: int = 36,
) -> list[tuple[SectorConfig, float]]:
    """Map spatial block domains around the pit centre to contiguous azimuth sectors."""
    sub = blocks.loc[in_pit] if in_pit is not None else blocks
    if sub.empty:
        return [(SectorConfig(name="Semua", azimuth_from=0.0, azimuth_to=360.0), overall_angle_deg)]

    cx, cy = float(sub["x"].mean()), float(sub["y"].mean())
    dx = sub["x"].to_numpy(dtype=float) - cx
    dy = sub["y"].to_numpy(dtype=float) - cy
    bearings = np.degrees(np.arctan2(dx, dy)) % 360.0
    bin_step = 360.0 / n_bins
    bin_ids = (bearings // bin_step).astype(int) % n_bins
    domains = sub["domain"].to_numpy()

    bin_labels: list[tuple[str, float] | None] = [None] * n_bins
    for b in range(n_bins):
        mask = bin_ids == b
        if not mask.any():
            continue
        dom = Counter(domains[mask]).most_common(1)[0][0]
        if dom in domain_angles:
            bin_labels[b] = (str(dom), float(domain_angles[dom]))
        else:
            bin_labels[b] = ("Semua", overall_angle_deg)

    populated = [i for i, v in enumerate(bin_labels) if v is not None]
    if not populated:
        return [(SectorConfig(name="Semua", azimuth_from=0.0, azimuth_to=360.0), overall_angle_deg)]
    for b in range(n_bins):
        if bin_labels[b] is None:
            nearest = min(populated, key=lambda p: min((p - b) % n_bins, (b - p) % n_bins))
            bin_labels[b] = bin_labels[nearest]

    runs: list[list] = []
    for b, label in enumerate(bin_labels):
        assert label is not None
        if runs and runs[-1][0] == label:
            runs[-1][2] = (b + 1) * bin_step
        else:
            runs.append([label, b * bin_step, (b + 1) * bin_step])

    if len(runs) > 1 and runs[0][0] == runs[-1][0]:
        runs[0][1] = runs[-1][1]
        runs.pop()

    if len(runs) == 1:
        label, _, _ = runs[0]
        return [(SectorConfig(name=label[0], azimuth_from=0.0, azimuth_to=360.0), label[1])]

    return [
        (SectorConfig(name=label[0], azimuth_from=az_from % 360.0, azimuth_to=az_to % 360.0 or 360.0), label[1])
        for label, az_from, az_to in runs
    ]


def resolve_sectors(
    design: DesignConfig,
    overall_angle_deg: float,
    domain_angles: dict | None = None,
    blocks: pd.DataFrame | None = None,
    in_pit: np.ndarray | None = None,
) -> tuple[list[SectorGeometry], list[str]]:
    """Every sector with each unset field filled from the design block.

    A project with no sectors is one sector all the way round, so the
    uniform pit is the same code path as the sectored one rather than a
    second implementation that could drift from it. When no manual sectors
    are configured and `domain_angles` is supplied, domains are mapped to
    sectors with their respective overall slope angles."""
    detail = design.detail
    limits = detail.limits
    if detail.sectors:
        configured = [(s, overall_angle_deg) for s in detail.sectors]
    elif domain_angles:
        if blocks is not None and "domain" in blocks.columns:
            configured = _domain_sectors_from_blocks(blocks, in_pit, domain_angles, overall_angle_deg)
        else:
            step = 360.0 / len(domain_angles)
            configured = [
                (SectorConfig(name=str(dom), azimuth_from=i * step, azimuth_to=(i + 1) * step), float(angle))
                for i, (dom, angle) in enumerate(domain_angles.items())
            ]
    else:
        configured = [(SectorConfig(name="Semua", azimuth_from=0.0, azimuth_to=360.0), overall_angle_deg)]

    sectors, notes = [], []
    for s, sector_overall in configured:
        height = s.bench_height if s.bench_height is not None else design.bench_height
        face = s.face_angle_deg if s.face_angle_deg is not None else design.bench_face_angle_deg
        n = s.berm_every_n_benches if s.berm_every_n_benches is not None else detail.berm_every_n_benches
        criterion = s.berm or detail.berm
        width, note = berm_width(criterion, height, face, n, sector_overall)
        if note:
            notes.append(f"{s.name or 'sector'}: {note}")
        sectors.append(SectorGeometry(
            name=s.name or f"S{len(sectors) + 1}", azimuth_from=s.azimuth_from, azimuth_to=s.azimuth_to,
            bench_height=height, face_angle_deg=face, berm_every_n=n, berm_width=width, berm_method=criterion.method,
            ira_max_deg=s.ira_max_deg if s.ira_max_deg is not None else limits.ira_max_deg,
            osa_max_deg=s.osa_max_deg if s.osa_max_deg is not None else limits.osa_max_deg,
        ))
    return sectors, notes


def angle_status(value_deg: float, limit_deg: float | None, warn_margin_deg: float) -> str:
    """OK / warning / blocked for a wall angle against its allowable value.

    A wall designed 0.1 degree inside its limit has no tolerance left for
    the survey and the excavator, so the margin counts as a warning; a
    wall over the limit is blocked. With no limit given there is nothing
    to fail and the answer is OK."""
    if limit_deg is None:
        return OK
    if value_deg > limit_deg:
        return BLOCKED
    if limit_deg - value_deg < warn_margin_deg:
        return WARNING
    return OK
