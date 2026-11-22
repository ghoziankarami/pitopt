# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ghozi Ankarami and PitOpt contributors
"""
The engine's answers, recomputed by algorithms that share none of its code paths:

  * maximum closure by linear programming (HiGHS) and by another max-flow (Dinic, scipy), on precedence built
    from first principles (the full geometric cone, no template reduction)
  * the reduced precedence template against that full cone (same transitive closure)
  * an analytic inverted-cone pit: closed-form volume against the solver's
  * pit volumes from DXF geometry (triangulated topography minus pit surface) against block volumes

Synthetic data throughout, so the expected numbers do not depend on the engine.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import sparse
from scipy.optimize import linprog
from scipy.sparse.csgraph import maximum_flow

from pitopt.core.precedence import add_grid_indices, build_precedence
from pitopt.core.solver import solve_max_closure

ROOT = Path(__file__).resolve().parents[1]


# ---------- synthetic models and an independent precedence ----------

def grid(nx, ny, nz, dx=10.0, dy=10.0, dz=5.0, x0=1005.0, y0=2005.0, z0=100.0):
    gx, gy, gz = np.meshgrid(x0 + dx * np.arange(nx), y0 + dy * np.arange(ny), z0 + dz * np.arange(nz), indexing="ij")
    return add_grid_indices(pd.DataFrame({"x": gx.ravel(), "y": gy.ravel(), "z": gz.ravel(), "dx": dx, "dy": dy, "dz": dz}))


def random_values(df, seed, ore_fraction=0.15):
    rng = np.random.default_rng(seed)
    cx, cy = df["x"].mean(), df["y"].mean()
    radial = np.hypot(df["x"] - cx, df["y"] - cy) / (0.35 * (df["x"].max() - df["x"].min()))
    deep = (df["z"].max() - df["z"]) / (df["z"].max() - df["z"].min() + 1e-9)
    core = np.exp(-radial**2) * (0.4 + deep)
    values = np.where(core * rng.uniform(0.3, 1.7, len(df)) > 1 - ore_fraction * 2, rng.uniform(20, 120, len(df)), -rng.uniform(4, 12, len(df)))
    return values.astype(float)


def cone_predecessors(df, angle_deg, levels):
    """Full unreduced cone, straight from the geometry: block b needs every block up to `levels` benches
    above it whose centre is within n * dz / tan(angle) horizontally."""
    dx, dy, dz = float(df["dx"].iloc[0]), float(df["dy"].iloc[0]), float(df["dz"].iloc[0])
    index = {(g, h, k): n for n, (g, h, k) in enumerate(zip(df["gi"], df["gj"], df["bench"], strict=True))}
    tan = math.tan(math.radians(angle_deg))
    pairs = []
    for n, (i, j, k) in enumerate(zip(df["gi"], df["gj"], df["bench"], strict=True)):
        for level in range(1, levels + 1):
            radius = level * dz / tan
            ri, rj = int(math.ceil(radius / dx)), int(math.ceil(radius / dy))
            for di in range(-ri, ri + 1):
                for dj in range(-rj, rj + 1):
                    if math.hypot(di * dx, dj * dy) <= radius:
                        m = index.get((i + di, j + dj, k + level))
                        if m is not None:
                            pairs.append((n, m))
    return np.array(pairs, dtype=np.int64).reshape(-1, 2)


def closure_by_lp(values, arcs):
    """max sum v x, x_b <= x_p for every arc, 0 <= x <= 1. The constraint matrix is totally unimodular,
    so the LP optimum is integral: the true maximum closure."""
    n = len(values)
    m = len(arcs)
    rows = np.repeat(np.arange(m), 2)
    cols = arcs.ravel()
    data = np.tile([1.0, -1.0], m)
    a = sparse.csr_matrix((data, (rows, cols)), shape=(m, n))
    res = linprog(-values, A_ub=a, b_ub=np.zeros(m), bounds=(0, 1), method="highs")
    assert res.status == 0, res.message
    return -res.fun, res.x > 0.5


def closure_by_dinic(values, arcs, scale=1000):
    """max closure = sum of positives - min cut, by scipy's Dinic max-flow on integer capacities."""
    n = len(values)
    v = np.round(values * scale).astype(np.int64)
    src, snk = n, n + 1
    big = int(np.abs(v).sum()) + 1
    pos, neg = np.flatnonzero(v > 0), np.flatnonzero(v < 0)
    rows = np.concatenate([np.full(len(pos), src), neg, arcs[:, 0]])
    cols = np.concatenate([pos, np.full(len(neg), snk), arcs[:, 1]])
    caps = np.concatenate([v[pos], -v[neg], np.full(len(arcs), big)])
    g = sparse.csr_matrix((caps, (rows, cols)), shape=(n + 2, n + 2), dtype=np.int32 if big < 2**31 else np.int64)
    flow = maximum_flow(g, src, snk).flow_value
    return (int(v[pos].sum()) - flow) / scale


def total(values, mask):
    return float(values[mask].sum())


# ---------- 1. solver against LP and another max-flow ----------

@pytest.mark.parametrize("shape,angle,seed", [((10, 10, 6), 45, 1), ((12, 9, 8), 30, 2), ((14, 14, 8), 38, 3), ((9, 9, 12), 55, 4)])
def test_maximum_closure_matches_lp_and_dinic_on_independent_precedence(shape, angle, seed):
    df = grid(*shape)
    values = random_values(df, seed)
    levels = 8
    arcs_independent = cone_predecessors(df, angle, levels)
    lp_value, lp_pit = closure_by_lp(values, arcs_independent)
    dinic_value = closure_by_dinic(values, arcs_independent)
    engine_arcs = build_precedence(df, slope_angle_deg=angle, max_levels=levels)
    pit = solve_max_closure(values, engine_arcs)
    assert lp_value > 0, "test model has no economic pit"
    assert abs(total(values, pit) - lp_value) <= 1e-6 * lp_value, "engine pit value differs from the LP optimum"
    assert abs(dinic_value - lp_value) <= 2e-3 * max(1.0, lp_value), "two independent solvers disagree"
    # the engine's pit is feasible under the *independent* cone, not just under its own template
    assert not np.any(pit[arcs_independent[:, 0]] & ~pit[arcs_independent[:, 1]])
    # same pit up to ties: differing blocks all carry (near) zero net effect on the objective
    differ = pit != lp_pit
    assert abs(total(values, pit) - total(values, lp_pit)) < 1e-6 * lp_value or not differ.any()


def test_reduced_template_has_the_same_transitive_closure_as_the_full_cone():
    """build_precedence uses an irreducible generating set of the cone; the set of blocks any block
    ultimately requires must equal the full cone's."""
    for angle in (35, 45):
        df = grid(9, 9, 6)
        full = cone_predecessors(df, angle, 8)
        reduced = build_precedence(df, slope_angle_deg=angle, max_levels=8)

        def closure(arcs, n):
            adj = sparse.csr_matrix((np.ones(len(arcs)), (arcs[:, 0], arcs[:, 1])), shape=(n, n))
            reach = adj.copy()
            for _ in range(8):
                reach = ((reach + reach @ adj) > 0).astype(np.int8)
            return reach.tocsr()

        a, b = closure(full, len(df)), closure(reduced, len(df))
        assert (a != b).nnz == 0, f"closures differ at {angle} degrees"


# ---------- 2. an analytic pit ----------

def _cone_pit_volume(dx, dz, angle=45.0, r=40.0):
    n, nz = int(400 / dx) + 1, int(40 / dz)
    df = grid(n, n, nz, dx=dx, dy=dx, dz=dz, x0=0.0, y0=0.0, z0=0.0)
    ore = (df["bench"] == df["bench"].min()) & (np.hypot(df["x"] - 200.0, df["y"] - 200.0) <= r)
    levels = max(8, int(math.ceil(3 * dx * math.tan(math.radians(angle)) / dz)))
    pit = solve_max_closure(np.where(ore, 5000.0, -1.0), build_precedence(df, slope_angle_deg=angle, max_levels=levels))
    return df, ore, pit, float(pit.sum() * dx * dx * dz), levels


def test_inverted_cone_converges_to_the_closed_form():
    """A disk of ore at the bottom of a flat-topped model (ore pays for any stripping): the optimal pit is the
    frustum above it, V = pi*H/3*(R^2 + R*r + r^2), R = r + H/tan(angle). Slopes are measured between block
    centres, so a coarse grid gives a smaller pit; refining the blocks must close the gap to the closed form."""
    angle, r, height = 45.0, 40.0, 40.0
    big_r = r + height / math.tan(math.radians(angle))
    analytic = math.pi * height / 3 * (big_r**2 + big_r * r + r**2)
    errors = []
    for dx, dz in ((10.0, 5.0), (5.0, 2.5)):
        df, ore, pit, volume, levels = _cone_pit_volume(dx, dz, angle, r)
        errors.append((analytic - volume) / analytic)
        assert 0 < errors[-1] < 0.20, f"dx={dx}: {volume:,.0f} m3 vs closed form {analytic:,.0f} m3"
        if dx == 10.0:                                                # exact: the union of the cones above the ore
            arcs = cone_predecessors(df, angle, levels)
            needed = ore.to_numpy().copy()
            for _ in range(levels + 1):
                needed[arcs[:, 1][needed[arcs[:, 0]]]] = True
            assert np.array_equal(pit, needed)
    assert errors[1] < 0.75 * errors[0], f"refining did not converge: {errors}"
    assert errors[1] < 0.12


# ---------- 3. volumes from DXF geometry against block volumes ----------

def _faces(path):
    """(n, 4, 3) array of 3DFACE vertices, read straight from the DXF text. Parsing with ezdxf builds a Python
    object per facet (about 5 kB each): a 600,000-facet surface needed several GB, this needs tens of MB."""
    coords = {}
    faces = []
    current = None
    with open(path, encoding="utf-8", errors="replace") as f:
        it = iter(f)
        for code_line in it:
            value = next(it, "")
            code, value = code_line.strip(), value.strip()
            if code == "0":
                if current is not None and len(coords) >= 12:
                    faces.append([(coords[10 + k], coords[20 + k], coords[30 + k]) for k in range(4)])
                current, coords = (value if value == "3DFACE" else None), {}
            elif current == "3DFACE" and code.isdigit() and int(code) in (10, 11, 12, 13, 20, 21, 22, 23, 30, 31, 32, 33):
                coords[int(code)] = float(value)
    if current is not None and len(coords) >= 12:
        faces.append([(coords[10 + k], coords[20 + k], coords[30 + k]) for k in range(4)])
    return np.array(faces, dtype=float)


def _quad_area_and_centroid(q):
    """Plan area and true centroid of each facet. Triangles are written as 3DFACEs with a repeated last
    vertex, so the centroid must not count that vertex twice."""
    tri = np.all(q[:, 2, :] == q[:, 3, :], axis=1)
    p = q[:, :, :2]
    shoelace = 0.5 * np.abs((p[:, 0, 0] * p[:, 1, 1] - p[:, 1, 0] * p[:, 0, 1]) + (p[:, 1, 0] * p[:, 2, 1] - p[:, 2, 0] * p[:, 1, 1])
                            + (p[:, 2, 0] * p[:, 3, 1] - p[:, 3, 0] * p[:, 2, 1]) + (p[:, 3, 0] * p[:, 0, 1] - p[:, 0, 0] * p[:, 3, 1]))
    centre = np.where(tri[:, None], q[:, :3, :].mean(axis=1), q.mean(axis=1))
    return shoelace, centre


from conftest import discover_runs, run_id  # noqa: E402

RESULTS = discover_runs()


@pytest.mark.skipif(not RESULTS, reason="no runs in outputs/")
@pytest.mark.parametrize("path", RESULTS, ids=run_id)
def test_design_volume_from_dxf_geometry_matches_the_reported_design_volume(path):
    """Volume between the input topography (triangulated from its own DXF) and the exported pit surface,
    integrated over the surface facets, against the design volume the run reports (blocks weighted by the
    share of each block the design mines)."""
    from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator

    r = json.loads(path.read_text())
    name, folder = r["meta"]["name"], path.parent
    from pitopt.config import ProjectConfig

    cfg_path = r["meta"].get("config_path")
    topo_path = ProjectConfig.from_yaml(cfg_path).surface.path if cfg_path and Path(cfg_path).exists() else None
    if not topo_path or not Path(topo_path).exists():
        pytest.skip("no topography file for this run")
    topo_faces = _faces(topo_path) if topo_path.lower().endswith(".dxf") else None
    if topo_faces is None:
        pytest.skip("topography is not a DXF")
    pts = np.unique(topo_faces.reshape(-1, 3), axis=0)
    linear, nearest = LinearNDInterpolator(pts[:, :2], pts[:, 2]), NearestNDInterpolator(pts[:, :2], pts[:, 2])

    def topo(x, y):        # the model footprint reaches half a block past the topography's hull: hold the edge value
        z = linear(x, y)
        return np.where(np.isnan(z), nearest(x, y), z)

    blocks = pd.read_csv(folder / f"{name}_blocks.csv", usecols=["volume", "design_fraction"])
    designed = float((blocks["volume"] * blocks["design_fraction"]).sum())
    gap = next((c["model_topography_gap"] for c in r["qa"]["checks"] if "model_topography_gap" in c), {"unmodelled_volume": 0.0})
    # excavation the design makes = block material it mines + ground the model has no blocks for (reported by QA)
    expected_volume = designed + gap["unmodelled_volume"]
    for stem, tol in (("pit_shell", 0.03), ("pit_face_position", 0.03)):
        dxf = folder / f"{name}_{stem}.dxf"
        if not dxf.exists() or designed <= 0:
            continue
        q = _faces(dxf)
        area, centre = _quad_area_and_centroid(q)
        depth = topo(centre[:, 0], centre[:, 1]) - centre[:, 2]
        volume = float(np.nansum(np.where(depth > 0, depth, 0.0) * area))
        expected = expected_volume
        assert abs(volume - expected) / expected < tol, f"{stem}: DXF geometry {volume:,.0f} m3 vs blocks {designed:,.0f} + unmodelled {gap['unmodelled_volume']:,.0f} m3"


# ---------- 4. closed-form analytical known-answer oracles (6 grade bases, depth cost, classes/domains, byproduct, schedule NPV) ----------

_GRADE_DIVISOR = {
    "mass_percent": 100.0,
    "volume_percent": 100.0,
    "ppm": 1_000_000.0,
    "gpt": 1_000_000.0,
    "kgm3": 1_000.0,
    "gm3": 1_000_000.0,
}

_UNITS_PER_TONNE = {
    "t": 1.0,
    "kg": 1_000.0,
    "g": 1_000_000.0,
    "oz": 32_150.7466,
    "lb": 2_204.62262,
}


def _analytic_block_valuation(
    *,
    volume: float,
    rock_density: float,
    grade: float,
    grade_basis: str,
    price: float,
    price_unit: str,
    plant_recovery: float,
    product_density: float = 1.0,
    mining_recovery: float = 1.0,
    dilution: float = 0.0,
    royalty_rate: float = 0.0,
    mining_cost_per_tonne: float = 0.0,
    mining_cost_per_volume: float = 0.0,
    rehab_cost_per_tonne: float = 0.0,
    rehab_cost_per_volume: float = 0.0,
    processing_cost_per_tonne: float = 0.0,
    processing_cost_per_volume: float = 0.0,
    product_proc_cost_per_tonne: float = 0.0,
    selling_cost_per_tonne: float = 0.0,
    selling_cost_per_volume: float = 0.0,
    revenue_factor: float = 1.0,
) -> dict[str, float]:
    """Closed-form single-product block valuation from first principles."""
    rock_tonnes = volume * rock_density
    rec_vol = volume * mining_recovery
    rec_mass = rock_tonnes * mining_recovery
    ore_tonnes = rec_mass * (1.0 + dilution)
    ore_vol = rec_vol * (1.0 + dilution)

    frac = grade / _GRADE_DIVISOR[grade_basis]
    if grade_basis in ("kgm3", "gm3"):
        in_situ_product = rec_vol * frac
    elif grade_basis == "volume_percent":
        in_situ_product = rec_vol * frac * product_density
    else:
        in_situ_product = rec_mass * frac
    prod_tonnes = in_situ_product * plant_recovery

    unit = _UNITS_PER_TONNE[price_unit]
    gross = prod_tonnes * revenue_factor * price * unit
    selling = prod_tonnes * selling_cost_per_tonne * unit
    if product_density > 0:
        selling += (prod_tonnes / product_density) * selling_cost_per_volume
    revenue = (gross - selling) * (1.0 - royalty_rate)
    product_cost = prod_tonnes * product_proc_cost_per_tonne * unit
    plant_cost = ore_tonnes * processing_cost_per_tonne + ore_vol * processing_cost_per_volume
    fixed_cost = (
        rock_tonnes * (mining_cost_per_tonne + rehab_cost_per_tonne)
        + volume * (mining_cost_per_volume + rehab_cost_per_volume)
    )
    value_ore = revenue - product_cost - plant_cost - fixed_cost
    value_waste = -fixed_cost
    return {
        "prod_tonnes": prod_tonnes,
        "revenue": revenue,
        "value_ore": value_ore,
        "value_waste": value_waste,
        "value": max(value_ore, value_waste),
    }


@pytest.mark.parametrize(
    "grade_basis,price,price_unit,rock_density,product_density,grade_above,grade_below",
    [
        ("mass_percent", 9000.0, "t", 2.7, 1.0, 1.2, 0.2),
        ("volume_percent", 1400.0, "t", 1.7, 4.6, 2.5, 0.3),
        ("ppm", 75.0, "kg", 2.0, 1.0, 1200.0, 150.0),
        ("gpt", 2300.0, "oz", 2.6, 1.0, 1.5, 0.1),
        ("kgm3", 25000.0, "t", 1.8, 1.0, 3.0, 0.2),
        ("gm3", 75.0, "g", 1.9, 1.0, 2.0, 0.1),
    ],
)
def test_all_six_grade_bases_match_closed_form_valuation_and_cutoff(
    grade_basis, price, price_unit, rock_density, product_density, grade_above, grade_below
):
    """Closed-form verification of block valuation and marginal cutoff across all 6 grade bases."""
    from pitopt.config import EconomicsConfig, ProductConfig
    from pitopt.core.economics import ORE, WASTE, marginal_cutoff_grades, value_blocks

    rf = 0.85
    mining_rec = 0.95
    dilution = 0.05
    royalty = 0.04
    plant_rec = 0.88
    m_cost_t = 2.5
    m_cost_v = 1.0
    r_cost_t = 0.3
    r_cost_v = 0.2
    p_cost_t = 18.0
    p_cost_v = 2.0
    prod_proc_t = 0.5 if price_unit in ("t", "kg") else 0.02
    sell_t = 0.3 if price_unit in ("t", "kg") else 0.01
    sell_v = 5.0 if grade_basis == "volume_percent" else 0.0

    econ = EconomicsConfig(
        grade_basis=grade_basis,
        mining_recovery=mining_rec,
        dilution=dilution,
        royalty_rate=royalty,
        mining_cost_per_tonne=m_cost_t,
        mining_cost_per_volume=m_cost_v,
        rehabilitation_cost_per_tonne=r_cost_t,
        rehabilitation_cost_per_volume=r_cost_v,
        processing_cost_per_tonne=p_cost_t,
        processing_cost_per_volume=p_cost_v,
        products=[
            ProductConfig(
                name="PROD",
                grade_col="G",
                price=price,
                price_unit=price_unit,
                plant_recovery=plant_rec,
                density=product_density,
                processing_cost_per_tonne=prod_proc_t,
                selling_cost_per_tonne=sell_t,
                selling_cost_per_volume=sell_v,
            )
        ],
    )

    # Closed-form marginal cutoff grade
    unit = _UNITS_PER_TONNE[price_unit]
    net_per_unit = (rf * price - sell_t) * unit
    if product_density > 0:
        net_per_unit -= sell_v / product_density
    margin = net_per_unit * (1.0 - royalty) - prod_proc_t * unit
    feed_cost = (p_cost_v + rock_density * p_cost_t) * (1.0 + dilution)
    payable_per_unit = plant_rec * margin
    if grade_basis == "volume_percent":
        payable_per_unit *= product_density
    elif grade_basis not in ("kgm3", "gm3"):
        payable_per_unit *= rock_density
    expected_cutoff = (feed_cost / payable_per_unit) * _GRADE_DIVISOR[grade_basis]

    got_cutoff = marginal_cutoff_grades(econ, revenue_factor=rf, rock_density=rock_density)["PROD"]
    assert got_cutoff == pytest.approx(expected_cutoff, rel=1e-6)

    # Evaluate blocks above, below, and right around the cutoff
    dx, dy, dz = 10.0, 10.0, 5.0
    vol = dx * dy * dz
    grades = [grade_above, grade_below, expected_cutoff * (1.0 + 1e-4), expected_cutoff * (1.0 - 1e-4)]
    df = pd.DataFrame({
        "x": [0.0, 10.0, 20.0, 30.0],
        "y": [0.0, 0.0, 0.0, 0.0],
        "z": [100.0, 100.0, 100.0, 100.0],
        "dx": [dx] * 4,
        "dy": [dy] * 4,
        "dz": [dz] * 4,
        "density": [rock_density] * 4,
        "G": grades,
    })
    valued = value_blocks(df, econ, revenue_factor=rf)

    for idx, g in enumerate(grades):
        exp = _analytic_block_valuation(
            volume=vol,
            rock_density=rock_density,
            grade=g,
            grade_basis=grade_basis,
            price=price,
            price_unit=price_unit,
            plant_recovery=plant_rec,
            product_density=product_density,
            mining_recovery=mining_rec,
            dilution=dilution,
            royalty_rate=royalty,
            mining_cost_per_tonne=m_cost_t,
            mining_cost_per_volume=m_cost_v,
            rehab_cost_per_tonne=r_cost_t,
            rehab_cost_per_volume=r_cost_v,
            processing_cost_per_tonne=p_cost_t,
            processing_cost_per_volume=p_cost_v,
            product_proc_cost_per_tonne=prod_proc_t,
            selling_cost_per_tonne=sell_t,
            selling_cost_per_volume=sell_v,
            revenue_factor=rf,
        )
        assert valued["PROD_tonnes"].iloc[idx] == pytest.approx(exp["prod_tonnes"], rel=1e-6)
        assert valued["revenue"].iloc[idx] == pytest.approx(exp["revenue"], rel=1e-6)
        assert valued["value_ore"].iloc[idx] == pytest.approx(exp["value_ore"], rel=1e-6)
        assert valued["value_waste"].iloc[idx] == pytest.approx(exp["value_waste"], rel=1e-6)
        assert valued["value"].iloc[idx] == pytest.approx(exp["value"], rel=1e-6)

    assert valued["destination"].iloc[0] == ORE
    assert valued["destination"].iloc[1] == WASTE
    assert valued["destination"].iloc[2] == ORE
    assert valued["destination"].iloc[3] == WASTE


def _closure_by_bruteforce(values: np.ndarray, arcs: np.ndarray) -> tuple[float, np.ndarray]:
    """Exact exhaustive enumeration over all 2^n subsets (for small n <= 20)."""
    n = len(values)
    assert n <= 20
    masks = np.arange(1 << n, dtype=np.uint32)[:, None]
    bits = ((masks >> np.arange(n, dtype=np.uint32)) & 1).astype(bool)
    if len(arcs) > 0:
        feasible = ~np.any(bits[:, arcs[:, 0]] & ~bits[:, arcs[:, 1]], axis=1)
        bits = bits[feasible]
    totals = bits @ values
    best_idx = int(np.argmax(totals))
    return float(totals[best_idx]), bits[best_idx]


@pytest.mark.parametrize(
    "depth_inc,ref_rl,include_classes,ore_domains",
    [
        (0.0, None, [], []),
        (0.25, None, [], []),
        (0.25, 115.0, ["Measured", "Indicated"], []),
        (0.40, 120.0, ["Measured"], ["SAPROLITE"]),
    ],
)
def test_small_3d_deposit_bruteforce_and_dinic_with_depth_cost_classes_domains(
    tmp_path, depth_inc, ref_rl, include_classes, ore_domains
):
    """Exact brute-force & SciPy Dinic verification on a 3x2x3 3D deposit across combinations of
    mining_cost_increment_per_m > 0, include_classes, and ore_domains."""
    from pitopt.config import BlockModelConfig, EconomicsConfig, ProductConfig
    from pitopt.core.economics import value_blocks
    from pitopt.io.blockmodel import load_block_model

    # 3 x 2 x 3 = 18 blocks -> 2^18 = 262,144 subsets, solved exactly by brute force
    df_grid = grid(3, 2, 3, dx=10.0, dy=10.0, dz=10.0, x0=5.0, y0=5.0, z0=95.0)
    # Assign high grade at centre-bottom (gi=1, gj=0, bench=0), moderate at mid-bench, waste elsewhere
    grade = np.full(len(df_grid), 0.1)
    is_core = (df_grid["gi"] == 1) & (df_grid["gj"] == 0) & (df_grid["bench"] == 0)
    is_mid = (df_grid["gi"] == 1) & (df_grid["bench"] == 1)
    grade[is_core] = 5.0
    grade[is_mid] = 2.5

    # Give one mid-bench high-grade block Inferred class and one a non-ore domain to test waste-routing
    res_class = np.where((df_grid["gi"] == 1) & (df_grid["gj"] == 1) & (df_grid["bench"] == 1), "Inferred", "Measured")
    domain = np.where(df_grid["bench"] == 2, "OVERBURDEN", "SAPROLITE")

    csv_path = tmp_path / "small3d.csv"
    pd.DataFrame({
        "X": df_grid["x"],
        "Y": df_grid["y"],
        "Z": df_grid["z"],
        "AU_GPT": grade,
        "CLASS": res_class,
        "DOMAIN": domain,
    }).to_csv(csv_path, index=False)

    bm_cfg = BlockModelConfig(
        path=str(csv_path),
        dx=10.0,
        dy=10.0,
        dz=10.0,
        density=2.5,
        domain_col="DOMAIN",
        class_col="CLASS",
        include_classes=include_classes,
        ore_domains=ore_domains,
    )
    econ = EconomicsConfig(
        grade_basis="gpt",
        mining_cost_per_tonne=3.0,
        mining_cost_increment_per_m=depth_inc,
        mining_cost_reference_rl=ref_rl,
        processing_cost_per_tonne=20.0,
        products=[ProductConfig(name="AU", grade_col="AU_GPT", price=2000.0, price_unit="oz", plant_recovery=0.9)],
    )

    loaded = load_block_model(bm_cfg, econ)
    loaded = add_grid_indices(loaded)
    valued = value_blocks(loaded, econ)

    # Verify analytical depth-cost increment on every block
    effective_ref = float((loaded["z"] + loaded["dz"] / 2).max()) if ref_rl is None else ref_rl
    expected_depth = np.clip(effective_ref - loaded["z"].to_numpy(), 0.0, None)
    expected_waste_val = -valued["rock_tonnes"].to_numpy() * (3.0 + depth_inc * expected_depth)
    assert np.allclose(valued["value_waste"].to_numpy(), expected_waste_val, rtol=1e-6, atol=1e-9)

    # Blocks excluded by include_classes or ore_domains must receive zero revenue (value == value_waste)
    if include_classes:
        excluded_cls = ~loaded["resource_class"].isin(include_classes).to_numpy()
        assert np.allclose(valued["value"].to_numpy()[excluded_cls], valued["value_waste"].to_numpy()[excluded_cls], rtol=1e-6)
    if ore_domains:
        excluded_dom = ~loaded["domain"].isin(ore_domains).to_numpy()
        assert np.allclose(valued["value"].to_numpy()[excluded_dom], valued["value_waste"].to_numpy()[excluded_dom], rtol=1e-6)

    values = valued["value"].to_numpy()
    arcs_ind = cone_predecessors(valued, angle_deg=45.0, levels=3)
    arcs_eng = build_precedence(valued, slope_angle_deg=45.0, max_levels=3)

    bf_val, bf_pit = _closure_by_bruteforce(values, arcs_ind)
    dinic_val = closure_by_dinic(values, arcs_ind, scale=1000)
    eng_pit = solve_max_closure(values, arcs_eng)
    eng_val = total(values, eng_pit)

    assert eng_val == pytest.approx(bf_val, rel=1e-6, abs=1e-6)
    assert dinic_val == pytest.approx(bf_val, rel=1e-3, abs=1e-2)
    assert not np.any(eng_pit[arcs_ind[:, 0]] & ~eng_pit[arcs_ind[:, 1]])
    assert total(values, bf_pit) == pytest.approx(eng_val, rel=1e-6, abs=1e-6)


def test_multiproduct_byproduct_credit_lifts_marginal_block_into_optimal_pit():
    """Verify multi-product valuation with byproduct credits (zero extra product processing cost)
    against closed-form analytical value and show byproduct credit flips a marginal block to ORE."""
    from pitopt.config import EconomicsConfig, ProductConfig
    from pitopt.core.economics import ORE, WASTE, marginal_cutoff_grades, value_blocks

    # Primary: CU (mass_percent, $4/lb, plant_rec=0.85, proc=$0.1/lb)
    # Byproduct: AU_EQ_PCT (mass_percent, $50000/t, plant_rec=0.80, proc=$0.0/t — pure byproduct credit)
    econ = EconomicsConfig(
        grade_basis="mass_percent",
        mining_recovery=1.0,
        dilution=0.0,
        royalty_rate=0.05,
        mining_cost_per_tonne=2.0,
        processing_cost_per_tonne=15.0,
        products=[
            ProductConfig(name="CU", grade_col="CU_PCT", price=4.0, price_unit="lb", plant_recovery=0.85, processing_cost_per_tonne=0.1),
            ProductConfig(name="BYPROD", grade_col="BP_PCT", price=50000.0, price_unit="t", plant_recovery=0.80, processing_cost_per_tonne=0.0),
        ],
    )
    econ_primary_only = EconomicsConfig(
        grade_basis=econ.grade_basis,
        mining_recovery=econ.mining_recovery,
        dilution=econ.dilution,
        royalty_rate=econ.royalty_rate,
        mining_cost_per_tonne=econ.mining_cost_per_tonne,
        processing_cost_per_tonne=econ.processing_cost_per_tonne,
        products=[econ.products[0]],
    )

    cu_cutoff = marginal_cutoff_grades(econ, rock_density=2.7)["CU"]
    # Choose CU grade at 80% of standalone CU cutoff (would be WASTE alone), plus byproduct grade that makes it ORE
    cu_grade = 0.80 * cu_cutoff
    bp_grade = 0.02  # 0.02% -> 0.0002 * 0.8 * 50000 * 0.95 = $7.60/t extra net revenue

    df = pd.DataFrame({
        "x": [5.0],
        "y": [5.0],
        "z": [95.0],
        "dx": [10.0],
        "dy": [10.0],
        "dz": [10.0],
        "density": [2.7],
        "CU_PCT": [cu_grade],
        "BP_PCT": [bp_grade],
    })
    df = add_grid_indices(df)

    val_single = value_blocks(df, econ_primary_only)
    val_multi = value_blocks(df, econ)

    assert val_single["destination"].iloc[0] == WASTE
    assert val_multi["destination"].iloc[0] == ORE

    # Closed-form check for the combined block
    rock_t = 2700.0
    cu_t = rock_t * (cu_grade / 100.0) * 0.85
    bp_t = rock_t * (bp_grade / 100.0) * 0.80
    cu_rev = cu_t * 4.0 * _UNITS_PER_TONNE["lb"] * (1.0 - 0.05)
    bp_rev = bp_t * 50000.0 * (1.0 - 0.05)
    cu_pcost = cu_t * 0.1 * _UNITS_PER_TONNE["lb"]
    plant_cost = rock_t * 15.0
    mining_cost = rock_t * 2.0
    exp_val_ore = (cu_rev + bp_rev) - cu_pcost - plant_cost - mining_cost

    assert val_multi["CU_tonnes"].iloc[0] == pytest.approx(cu_t, rel=1e-6)
    assert val_multi["BYPROD_tonnes"].iloc[0] == pytest.approx(bp_t, rel=1e-6)
    assert val_multi["value_ore"].iloc[0] == pytest.approx(exp_val_ore, rel=1e-6)
    assert val_multi["value"].iloc[0] == pytest.approx(exp_val_ore, rel=1e-6)

    pit = solve_max_closure(val_multi["value"].to_numpy(), build_precedence(val_multi, slope_angle_deg=45.0))
    assert bool(pit[0]) is True


@pytest.mark.parametrize("capacity_basis,ore_cap,total_cap", [
    ("tonnes", 300.0, 500.0),
    ("tonnes", 250.0, None),
    ("volume", 150.0, 250.0),
])
def test_schedule_production_npv_matches_manual_year_by_year_discounting(capacity_basis, ore_cap, total_cap):
    """Verify capacity-constrained schedule_production NPV and per-period cash flows against
    manual year-by-year discounting on a multi-pushback model."""
    from pitopt.core.economics import ORE, WASTE
    from pitopt.core.schedule import schedule_production, schedule_summary

    # Build a 3-pushback model with 2 benches each, mix of ore and waste blocks
    rows = [
        # shell 1, bench 2 (top) -> waste then ore
        {"shell": 1, "bench": 2, "x": 10.0, "y": 10.0, "z": 20.0, "destination": WASTE, "volume": 100.0, "rock_tonnes": 200.0, "ore_tonnes": 200.0, "value": -400.0, "CU_tonnes": 0.0},
        {"shell": 1, "bench": 2, "x": 20.0, "y": 10.0, "z": 20.0, "destination": ORE,   "volume": 100.0, "rock_tonnes": 200.0, "ore_tonnes": 200.0, "value": 1500.0, "CU_tonnes": 3.0},
        # shell 1, bench 1 (bottom)
        {"shell": 1, "bench": 1, "x": 10.0, "y": 10.0, "z": 10.0, "destination": ORE,   "volume": 100.0, "rock_tonnes": 200.0, "ore_tonnes": 200.0, "value": 1800.0, "CU_tonnes": 4.0},
        # shell 2, bench 2
        {"shell": 2, "bench": 2, "x": 30.0, "y": 10.0, "z": 20.0, "destination": WASTE, "volume": 100.0, "rock_tonnes": 200.0, "ore_tonnes": 200.0, "value": -400.0, "CU_tonnes": 0.0},
        {"shell": 2, "bench": 2, "x": 40.0, "y": 10.0, "z": 20.0, "destination": ORE,   "volume": 100.0, "rock_tonnes": 200.0, "ore_tonnes": 200.0, "value": 1200.0, "CU_tonnes": 2.5},
        # shell 3, bench 1
        {"shell": 3, "bench": 1, "x": 50.0, "y": 10.0, "z": 10.0, "destination": ORE,   "volume": 100.0, "rock_tonnes": 200.0, "ore_tonnes": 200.0, "value": 900.0,  "CU_tonnes": 2.0},
    ]
    blocks = pd.DataFrame(rows)
    in_pit = np.ones(len(blocks), dtype=bool)
    discount_rate = 0.10

    sched = schedule_production(
        blocks,
        in_pit,
        ore_capacity=ore_cap,
        total_capacity=total_cap,
        discount_rate=discount_rate,
        by_shell=True,
        capacity_basis=capacity_basis,
    )
    summary = schedule_summary(sched)

    # Manual year-by-year packing and discounting in exact mining order (shell asc, bench desc, x asc, y asc)
    ordered = blocks.sort_values(["shell", "bench", "x", "y"], ascending=[True, False, True, True], kind="stable")
    period = 1
    used_feed = 0.0
    used_moved = 0.0
    manual_periods: dict[int, dict[str, float]] = {}
    for _, row in ordered.iterrows():
        is_ore = row["destination"] == ORE
        if capacity_basis == "tonnes":
            b_feed = row["ore_tonnes"] if is_ore else 0.0
            b_moved = row["rock_tonnes"]
        else:
            b_feed = row["volume"] if is_ore else 0.0
            b_moved = row["volume"]
        if (used_feed + b_feed > ore_cap) or (total_cap is not None and used_moved + b_moved > total_cap):
            period += 1
            used_feed = 0.0
            used_moved = 0.0
        used_feed += b_feed
        used_moved += b_moved
        p = manual_periods.setdefault(period, {"cash_flow": 0.0, "ore_tonnes": 0.0, "waste_tonnes": 0.0})
        p["cash_flow"] += row["value"]
        if is_ore:
            p["ore_tonnes"] += row["ore_tonnes"]
        else:
            p["waste_tonnes"] += row["rock_tonnes"]

    assert len(sched) == len(manual_periods)
    manual_npv = 0.0
    for _, srow in sched.iterrows():
        p_num = int(srow["period"])
        mp = manual_periods[p_num]
        dfac = 1.0 / ((1.0 + discount_rate) ** p_num)
        dcf = mp["cash_flow"] * dfac
        manual_npv += dcf
        assert srow["cash_flow"] == pytest.approx(mp["cash_flow"], rel=1e-6, abs=1e-9)
        assert srow["ore_tonnes"] == pytest.approx(mp["ore_tonnes"], rel=1e-6, abs=1e-9)
        assert srow["waste_tonnes"] == pytest.approx(mp["waste_tonnes"], rel=1e-6, abs=1e-9)
        assert srow["discount_factor"] == pytest.approx(dfac, rel=1e-6, abs=1e-9)
        assert srow["discounted_cash_flow"] == pytest.approx(dcf, rel=1e-6, abs=1e-9)

    assert summary["npv"] == pytest.approx(manual_npv, rel=1e-6, abs=1e-9)
    assert summary["periods"] == len(manual_periods)


# ---------- 8. SciPy Dinic CSR solver equivalence and performance ----------

@pytest.mark.parametrize("shape,angle,seed", [((10, 10, 6), 45, 1), ((12, 9, 8), 30, 2), ((14, 14, 8), 38, 3)])
def test_scipy_dinic_matches_preflow_push_bit_for_bit(shape, angle, seed):
    """CSR-backed scipy_dinic and edmonds_karp must produce 100% bit-for-bit identical
    in_pit partitions to NetworkX preflow_push across grids, edge cases, and extreme scales."""
    df = grid(*shape)
    values = random_values(df, seed)
    arcs = build_precedence(df, slope_angle_deg=angle, max_levels=8)

    pit_preflow = solve_max_closure(values, arcs, method="preflow_push")
    pit_dinic = solve_max_closure(values, arcs, method="scipy_dinic")
    pit_ek = solve_max_closure(values, arcs, method="edmonds_karp")

    assert np.array_equal(pit_dinic, pit_preflow)
    assert np.array_equal(pit_ek, pit_preflow)

    # Edge cases: empty, all-zero, all-positive, all-negative, 2-cycle, extreme scale
    edge_cases = [
        (np.array([], dtype=float), np.empty((0, 2), dtype=np.int64)),
        (np.zeros(4, dtype=float), np.array([[0, 1], [2, 3]], dtype=np.int64)),
        (np.array([3.0, 2.0, 0.0]), np.array([[0, 2]], dtype=np.int64)),
        (np.array([-3.0, -2.0]), np.array([[0, 1]], dtype=np.int64)),
        (np.array([8.0, -2.0]), np.array([[0, 1], [1, 0]], dtype=np.int64)),
        (np.array([1e11, -3e10, 1e-2, -5.0]), np.array([[0, 1], [2, 3]], dtype=np.int64)),
    ]
    for vals, edge_arcs in edge_cases:
        assert np.array_equal(
            solve_max_closure(vals, edge_arcs, method="scipy_dinic"),
            solve_max_closure(vals, edge_arcs, method="preflow_push"),
        )

    with pytest.raises(ValueError, match="method"):
        solve_max_closure(values, arcs, method="unknown_backend")


def test_scipy_dinic_nested_shells_performance_and_equivalence():
    """run_nested_shells on a >20,000-block grid must run fast via scipy_dinic
    with zero nesting violations and exact precedence feasibility."""
    import time

    from pitopt.config import EconomicsConfig, ProductConfig
    from pitopt.core.shells import run_nested_shells

    df = grid(28, 28, 28, dx=10.0, dy=10.0, dz=5.0)
    rng = np.random.default_rng(7)
    cx, cy = df["x"].mean(), df["y"].mean()
    radial = np.hypot(df["x"] - cx, df["y"] - cy) / 80.0
    df["SN_PCT"] = np.clip(0.9 * np.exp(-(radial ** 2)) + rng.normal(0.0, 0.05, len(df)), 0.0, None)
    df["density"] = 2.0

    econ = EconomicsConfig(
        grade_basis="mass_percent",
        mining_recovery=0.95,
        dilution=0.05,
        royalty_rate=0.03,
        mining_cost_per_tonne=2.5,
        processing_cost_per_tonne=9.5,
        products=[ProductConfig(name="SN", grade_col="SN_PCT", price=30_000.0, plant_recovery=0.85, selling_cost_per_tonne=1500.0)],
    )
    arcs = build_precedence(df, slope_angle_deg=45.0, max_levels=8)

    t0 = time.perf_counter()
    solved, report, violations = run_nested_shells(df, arcs, econ, [0.5, 0.7, 0.85, 1.0, 1.15])
    elapsed = time.perf_counter() - t0

    assert len(df) > 20_000
    assert violations == 0
    assert elapsed < 10.0, f"5 nested shells on {len(df)} blocks took too long: {elapsed:.2f}s"
    in_pit = solved["in_pit"].to_numpy()
    assert in_pit.any()
    assert not np.any(in_pit[arcs[:, 0]] & ~in_pit[arcs[:, 1]])
    assert report["blocks"].is_monotonic_increasing
