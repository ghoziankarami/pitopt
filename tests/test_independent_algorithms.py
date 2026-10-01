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
