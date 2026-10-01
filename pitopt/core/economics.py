"""
Block valuation with destination selection, over one or many products.

Each block is valued twice — as plant feed and as waste — and takes the
better of the two. That `max(ore, waste)` step is what puts a marginal
cutoff into the pit optimisation: a block only carries plant cost if
processing it actually pays, so barren material inside the shell is
valued as waste. Valuing every block as ore instead charges processing on
material that would never see the plant, which understates the deposit
and shrinks the pit.

Mining and rehabilitation are charged on every block that comes out,
ore or waste. They are therefore *not* part of the ore-versus-waste
comparison — they cancel — which is why the cutoff below depends only on
processing, selling and revenue.

Revenue is scaled by `revenue_factor` (the Whittle / RAF parameterisation)
so the same routine drives every nested shell. The destination decision is
re-made at each factor, which is correct: a block that is marginal ore at
RF 1.0 is waste at RF 0.6.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import GRADE_DIVISOR, VOLUME_BASES, EconomicsConfig, ProductConfig

ORE, WASTE = 1, 0


def _recovered_tonnes(
    df: pd.DataFrame, product: ProductConfig, econ: EconomicsConfig, recovered_volume: np.ndarray, recovered_mass: np.ndarray
) -> np.ndarray:
    """Saleable tonnes of one product, after mining and plant recovery."""
    grade_fraction = df[product.grade_col].to_numpy() / GRADE_DIVISOR[econ.grade_basis]
    if econ.grade_basis in VOLUME_BASES:
        in_situ = recovered_volume * grade_fraction * product.density
    else:
        in_situ = recovered_mass * grade_fraction
    return in_situ * product.plant_recovery


def product_margin(econ: EconomicsConfig, product: ProductConfig, revenue_factor: float = 1.0) -> float:
    """
    Net margin per saleable tonne of one product: price less selling and
    less that product's own processing cost.

    A product's processing cost is netted off its price rather than
    treated as a cost the grade has to cover, because it is charged per
    tonne of product, not per tonne of ore. A product with a positive
    margin adds value at any grade; one with a negative margin destroys
    value however rich the block is.
    """
    unit = product.per_tonne
    net = (revenue_factor * product.price - product.selling_cost_per_tonne) * unit
    if product.density > 0:
        net -= product.selling_cost_per_volume / product.density
    return net * (1.0 - econ.royalty_rate) - product.processing_cost_per_tonne * unit


def marginal_cutoff_grades(econ: EconomicsConfig, revenue_factor: float = 1.0, rock_density: float = 1.0) -> dict:
    """
    Grade at which each product alone would cover the *ore-level*
    processing cost — the cost charged per tonne or cubic metre of plant
    feed, irrespective of what is recovered from it.

    Where there is no such ore-level cost, the cutoff is zero: any block
    with a positive-margin product in it is worth processing, and the pit
    limit is then set by whether revenue covers mining and rehabilitation,
    not by grade. Mining and rehabilitation never enter the cutoff — they
    are paid on ore and waste alike, so they cancel from the comparison.

    With several products these are indicative only. The destination
    decision is made on total block value, so a block below every single
    product cutoff can still pay once the products are combined.
    """
    feed_cost = econ.processing_cost_per_volume + rock_density * econ.processing_cost_per_tonne
    feed_cost *= 1.0 + econ.dilution

    cutoffs = {}
    for product in econ.products:
        margin = product_margin(econ, product, revenue_factor)
        if margin <= 0:
            cutoffs[product.name] = float("inf")
            continue
        if feed_cost <= 0:
            cutoffs[product.name] = 0.0
            continue

        payable_per_unit = product.plant_recovery * margin
        if econ.grade_basis in VOLUME_BASES:
            payable_per_unit *= product.density
        else:
            payable_per_unit *= rock_density

        cutoffs[product.name] = (feed_cost / payable_per_unit) * GRADE_DIVISOR[econ.grade_basis]
    return cutoffs


def value_blocks(df: pd.DataFrame, econ: EconomicsConfig, revenue_factor: float = 1.0) -> pd.DataFrame:
    """
    Adds tonnage/value columns to a standardised block model.

    Columns added:
      volume         in-situ block volume
      rock_tonnes    in-situ tonnes (everything mined)
      ore_tonnes     diluted tonnes to the plant if the block is sent there
      <NAME>_tonnes  saleable tonnes of each product
      revenue        gross revenue if processed
      value_ore      block value if processed
      value_waste    block value if dumped (mining + rehabilitation only)
      value          max of the two — what the optimiser maximises
      destination    1 = ore, 0 = waste
    """
    out = df.copy()

    # A reblocked model may carry partly-filled cells at the model edge;
    # its own volume column is the material actually there, and the
    # nominal cell size would overstate both tonnes and volumetric costs.
    if "volume" in out.columns:
        volume = out["volume"].to_numpy()
    else:
        volume = (out["dx"] * out["dy"] * out["dz"]).to_numpy()
    rock_tonnes = volume * out["density"].to_numpy()

    recovered_volume = volume * econ.mining_recovery
    recovered_mass = rock_tonnes * econ.mining_recovery
    ore_tonnes = recovered_mass * (1.0 + econ.dilution)
    ore_volume = recovered_volume * (1.0 + econ.dilution)

    revenue = np.zeros(len(out))
    product_cost = np.zeros(len(out))
    for product in econ.products:
        tonnes = _recovered_tonnes(out, product, econ, recovered_volume, recovered_mass)
        out[f"{product.name}_tonnes"] = tonnes

        unit = product.per_tonne
        gross = tonnes * revenue_factor * product.price * unit
        selling = tonnes * product.selling_cost_per_tonne * unit
        if product.density > 0:
            selling += (tonnes / product.density) * product.selling_cost_per_volume

        revenue += (gross - selling) * (1.0 - econ.royalty_rate)
        product_cost += tonnes * product.processing_cost_per_tonne * unit

    plant_cost = ore_tonnes * econ.processing_cost_per_tonne + ore_volume * econ.processing_cost_per_volume
    mining_cost = rock_tonnes * econ.mining_cost_per_tonne + volume * econ.mining_cost_per_volume
    if econ.mining_cost_increment_per_m:
        reference = econ.mining_cost_reference_rl
        if reference is None:
            reference = float((out["z"] + out["dz"] / 2).max())
        depth = np.clip(reference - out["z"].to_numpy(), 0.0, None)
        mining_cost = mining_cost + rock_tonnes * econ.mining_cost_increment_per_m * depth
    rehab_cost = rock_tonnes * econ.rehabilitation_cost_per_tonne + volume * econ.rehabilitation_cost_per_volume
    fixed_cost = mining_cost + rehab_cost

    value_ore = revenue - product_cost - plant_cost - fixed_cost
    value_waste = -fixed_cost

    # Material outside the ore domains cannot be routed to the plant at
    # all, whatever it assays — overburden and bedrock are not feed.
    if "is_ore_domain" in out.columns:
        outside = ~out["is_ore_domain"].to_numpy(dtype=bool)
        value_ore = np.where(outside, value_waste, value_ore)

    out["volume"] = volume
    out["rock_tonnes"] = rock_tonnes
    out["ore_tonnes"] = ore_tonnes
    out["revenue"] = revenue
    out["value_ore"] = value_ore
    out["value_waste"] = value_waste
    out["value"] = np.maximum(value_ore, value_waste)
    out["destination"] = np.where(value_ore > value_waste, ORE, WASTE)
    return out
