"""
Overall slope angle, with and without the haul road.

The overall angle is the wall angle from the floor to the crest with every
berm counted in. It is flatter than the inter-ramp angle wherever the road
crosses, because the road takes a berm's place at a width wider than the
berm and the wall has to stand back by the difference:

    OSA(bearing) = atan( depth / (wall width + crossings * (road - berm)) )

Two numbers are produced for each sector and kept apart. The measured one
reads the wall width and the road crossings off the geometry that was
actually built, along rays from the floor's centre. The analytic one is the
closed form from the sector's own bench parameters. On a regular pit they
agree; where they do not, the gap is reported instead of being averaged
away, because it says the wall is not doing what the parameters intended.
The worst angle in a sector decides its status: the steepest wall is the one
that has to meet the limit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .config import DesignLimitsConfig
from .parameters import SectorGeometry, angle_status
from .ramp import AZIMUTHS, Ramp, RingTable
from .stack import BenchStack


@dataclass
class SectorOSA:
    name: str
    osa_no_ramp_deg: float               # steepest angle in the sector, road ignored
    osa_deg: float                       # steepest angle in the sector with the road
    worst_azimuth_deg: float
    crossings_max: int                   # most times the road crosses one bearing in the sector
    analytic_no_ramp_deg: float          # closed form from the sector's bench parameters
    osa_max_deg: float | None
    status: str

    @property
    def analytic_gap_deg(self) -> float:
        """Measured minus analytic, road ignored."""
        return self.osa_no_ramp_deg - self.analytic_no_ramp_deg

    @property
    def margin_deg(self) -> float | None:
        return None if self.osa_max_deg is None else self.osa_max_deg - self.osa_deg


def sector_mask(sector: SectorGeometry, azimuths: np.ndarray) -> np.ndarray:
    length = (sector.azimuth_to - sector.azimuth_from) % 360.0 or 360.0
    return ((azimuths - sector.azimuth_from) % 360.0) < length


def crossings(ramp: Ramp, azimuths: np.ndarray) -> np.ndarray:
    """How many times the road passes each bearing.

    The road's bearing keeps counting past 360 as it goes round, so a
    bearing is crossed once per turn: every segment of the polyline that
    spans a bearing, plus a whole number of turns, is one crossing."""
    if len(ramp.azimuth) < 2:
        return np.zeros(len(azimuths), dtype=int)
    a, b = ramp.azimuth[:-1], ramp.azimuth[1:]
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    low_turn, high_turn = int(math.floor(lo.min() / 360.0)) - 1, int(math.ceil(hi.max() / 360.0)) + 1
    count = np.zeros(len(azimuths), dtype=int)
    for turn in range(low_turn, high_turn + 1):
        shifted = (azimuths + 360.0 * turn)[:, None]
        count += ((shifted > lo[None, :]) & (shifted <= hi[None, :])).sum(axis=1)
    return count


def sector_osa(stack: BenchStack, ramp: Ramp | None, top: RingTable, floor: RingTable,
               limits: DesignLimitsConfig) -> list[SectorOSA]:
    depth = stack.benches[0].crest_rl - stack.benches[-1].toe_rl
    width = top.radius - floor.radius                          # wall width at each bearing, berms included
    n = len(stack.benches)
    cross = crossings(ramp, AZIMUTHS) if ramp is not None else np.zeros(len(AZIMUTHS), dtype=int)
    road = ramp.sizing.width_m if ramp is not None else 0.0

    out = []
    for sector in stack.sectors:
        mask = sector_mask(sector, AZIMUTHS) & np.isfinite(width)
        if not mask.any():
            continue
        extra = cross * max(0.0, road - sector.berm_width)
        without = np.degrees(np.arctan2(depth, width[mask]))
        with_road = np.degrees(np.arctan2(depth, width[mask] + extra[mask]))
        worst = int(np.argmax(with_road))
        analytic = math.degrees(math.atan2(depth, sector.toe_offset(n - 1)))
        out.append(SectorOSA(
            sector.name, float(without.max()), float(with_road[worst]), float(AZIMUTHS[mask][worst]),
            int(cross[mask].max()), analytic, sector.osa_max_deg,
            angle_status(float(with_road[worst]), sector.osa_max_deg, limits.warn_margin_deg),
        ))
    return out
