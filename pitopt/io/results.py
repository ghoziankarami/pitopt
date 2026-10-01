"""
Machine-readable run output for the UI.

Every run writes two files next to the reports:

  <name>_results.json   everything the screens show, as plain numbers —
                        summary, pit by pit, pushbacks, schedule,
                        sensitivity, design, warnings, parameters with
                        their provenance, plan-view rasters, downsampled
                        3D surfaces and a QA section
  <name>_surfaces.npz   the full-resolution topography, design bowl, face
                        position and optimiser shell, so a section drawn
                        in the UI is cut from the real bench geometry
                        rather than from the downsampled display grid

The JSON is deliberately flat and self-describing: a screen never has to
recompute anything the engine already knows, and nothing here is derived
from the display units (Mt, millions) — those are applied by the UI.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import ndimage

from ..config import ProjectConfig
from ..core.economics import marginal_cutoff_grades, product_margin
from ..core.precedence import auto_bench_levels, effective_slope
from ..core.schedule import schedule_summary
from ..core.sensitivity import breakeven_price_factor

CURRENCY = "USD"


def _num(v):
    """JSON-safe number: NaN/inf -> None, numpy scalars -> python."""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return f if math.isfinite(f) else None
    return v


def _rows(frame: pd.DataFrame | None) -> list:
    if frame is None:
        return []
    out = []
    for record in frame.to_dict("records"):
        out.append({k: _num(v) if not isinstance(v, (list, dict, str, bool)) else v for k, v in record.items()})
    return out


def _grid_list(a: np.ndarray, decimals: int = 1) -> list:
    """2-D array -> nested list, non-finite -> None."""
    out = np.round(a.astype(float), decimals).astype(object)
    out[~np.isfinite(a)] = None
    return out.tolist()


def _downsample(a: np.ndarray, step: int) -> np.ndarray:
    return a[::step, ::step]


def _plan_rasters(blocks: pd.DataFrame) -> dict:
    """Per-column rasters at block resolution: what a plan view draws."""
    dx, dy = float(blocks["dx"].iloc[0]), float(blocks["dy"].iloc[0])
    gi0, gj0 = int(blocks["gi"].min()), int(blocks["gj"].min())
    nx, ny = int(blocks["gi"].max()) - gi0 + 1, int(blocks["gj"].max()) - gj0 + 1

    def raster(column: str, minimum: bool = True) -> list:
        sub = blocks[blocks[column] > 0]
        grid = np.zeros((nx, ny), dtype=np.int16)
        if len(sub):
            agg = sub.groupby(["gi", "gj"])[column].min() if minimum else sub.groupby(["gi", "gj"])[column].max()
            grid[agg.index.get_level_values(0) - gi0, agg.index.get_level_values(1) - gj0] = agg.to_numpy()
        return grid.T.ravel().tolist()      # row-major with y as rows, south first

    depth = np.full((nx, ny), np.nan)
    pit = blocks[blocks["in_pit"]]
    if len(pit):
        top = pit.groupby(["gi", "gj"])["z"].max() + float(blocks["dz"].iloc[0]) / 2
        floor = pit.groupby(["gi", "gj"])["z"].min() - float(blocks["dz"].iloc[0]) / 2
        depth[top.index.get_level_values(0) - gi0, top.index.get_level_values(1) - gj0] = (top - floor).to_numpy()
    raster_depth = np.round(np.nan_to_num(depth, nan=0.0), 1).T.ravel().tolist()

    return {
        "x0": float(blocks["x"].min() - dx / 2),
        "y0": float(blocks["y"].min() - dy / 2),
        "dx": dx, "dy": dy, "nx": nx, "ny": ny,
        "pushback": raster("pushback"),
        "period": raster("period") if "period" in blocks.columns else [],
        "depth": raster_depth,
    }


def _contiguity(blocks: pd.DataFrame) -> dict:
    """How many periods are worked as a single connected area."""
    if "period" not in blocks.columns or not (blocks["period"] > 0).any():
        return {"periods": 0, "contiguous": 0, "detail": []}
    gi0, gj0 = int(blocks["gi"].min()), int(blocks["gj"].min())
    shape = (int(blocks["gi"].max()) - gi0 + 1, int(blocks["gj"].max()) - gj0 + 1)
    detail = []
    for period in sorted(int(p) for p in blocks["period"].unique() if p > 0):
        part = blocks[blocks["period"] == period]
        grid = np.zeros(shape, dtype=bool)
        grid[part["gi"].to_numpy() - gi0, part["gj"].to_numpy() - gj0] = True
        labels, count = ndimage.label(grid, structure=np.ones((3, 3)))
        sizes = np.bincount(labels.ravel())[1:] if count else np.array([0])
        share = float(sizes.max() / sizes.sum()) if sizes.sum() else 1.0
        detail.append({"period": period, "areas": int(count), "largest_share": round(share, 4)})
    contiguous = sum(1 for d in detail if d["largest_share"] >= 0.99)
    return {"periods": len(detail), "contiguous": contiguous, "detail": detail}


def _tag_reconciliation(blocks: pd.DataFrame, plan: list[dict]) -> dict:
    """Period cash flow in the plan against the sum of block values tagged with
    that period in the exported block model.

    The scheduler splits each bench run between the periods it spans in
    proportion to tonnes, so a result does not depend on the order of rows in
    the input file. The exported `period` column is a whole-block assignment of
    the same sequence. Totals are identical; a single period can differ, and
    the difference is reported here rather than left to be discovered."""
    if "period" not in blocks.columns or not plan:
        return {"total_difference": 0.0, "max_relative_difference": 0.0, "rows": []}
    tagged = blocks[blocks["period"] > 0].groupby("period")["value"].sum()
    rows, worst = [], 0.0
    scale = max(abs(p["cash_flow"]) for p in plan) or 1.0
    for p in plan:
        by_tag = float(tagged.get(p["period"], 0.0))
        diff = by_tag - p["cash_flow"]
        worst = max(worst, abs(diff) / scale)
        rows.append({"period": p["period"], "plan": p["cash_flow"], "tagged": by_tag, "difference": diff})
    return {"total_difference": float(sum(r["difference"] for r in rows)), "max_relative_difference": worst, "rows": rows}


def _params(cfg: ProjectConfig) -> dict:
    raw = asdict(cfg)
    for key in ("provenance", "source"):
        raw.pop(key, None)
    raw["economics"]["products"] = [asdict(p) for p in cfg.economics.products]
    for section in ("block_model", "surface", "output"):
        for k, v in list(raw[section].items()):
            if isinstance(v, str) and ("/" in v or "\\" in v):
                raw[section][k] = Path(v).name if k == "path" else v
    return raw


def _derived(cfg: ProjectConfig) -> dict:
    """The live panel of the Parameter screen — computed here so the UI can
    show the engine's own numbers rather than its own approximation."""
    econ = cfg.economics
    bm = cfg.block_model
    margins = {p.name: product_margin(econ, p) for p in econ.products}
    cutoffs = marginal_cutoff_grades(econ, 1.0, bm.density)
    levels = cfg.slope.max_bench_levels or auto_bench_levels(cfg.slope.overall_angle_deg, min(bm.dx, bm.dy), bm.dz)
    eff = effective_slope(cfg.slope.overall_angle_deg, min(bm.dx, bm.dy), bm.dz, levels)
    return {"margins": margins, "cutoffs": cutoffs, "template_levels": levels,
            "effective_axis_deg": eff["axis_deg"], "effective_diagonal_deg": eff["diagonal_deg"]}


def _kpis(cfg: ProjectConfig, result, row: pd.Series) -> dict:
    econ = cfg.economics
    plan = schedule_summary(result.schedule) if result.schedule is not None else None
    best = schedule_summary(result.schedule_best)["npv"] if result.schedule_best is not None else None
    worst = schedule_summary(result.schedule_worst)["npv"] if result.schedule_worst is not None else None

    breakeven = leverage = None
    if result.sensitivity is not None:
        breakeven = _num(breakeven_price_factor(result.sensitivity))
        s = result.sensitivity.sort_values("price_factor")
        base = s[np.isclose(s["price_factor"], 1.0)]
        up = s[s["price_factor"] > 1.0].head(1)
        if len(base) and len(up) and base["npv"].iloc[0]:
            dp = float(up["price_factor"].iloc[0]) - 1.0
            dn = float(up["npv"].iloc[0]) / float(base["npv"].iloc[0]) - 1.0
            leverage = _num(dn / dp) if dp else None

    products = {p.name: {"tonnes": _num(row[f"{p.name}_tonnes"]), "price": p.price, "price_unit": p.price_unit,
                         "recovery": p.plant_recovery, "margin": _num(product_margin(econ, p))}
                for p in econ.products}
    return {
        "final_rf": _num(result.final_rf), "final_shell": int(result.final_shell),
        "final_reason": result.final_reason,
        "value_undiscounted": _num(row["value"]),
        "npv_plan": _num(plan["npv"]) if plan else None,
        "npv_best": _num(best), "npv_worst": _num(worst),
        "periods": plan["periods"] if plan else None,
        "rock_t": _num(row["rock_tonnes"]), "ore_t": _num(row["ore_tonnes"]), "waste_t": _num(row["waste_tonnes"]),
        "strip_ratio": _num(row["strip_ratio"]), "volume_m3": _num(row["volume"]),
        "max_depth_m": _num(result.depth["max_depth"]), "crest_rl": _num(result.depth["crest_rl"]),
        "toe_rl": _num(result.depth["toe_rl"]),
        "pushbacks": int(result.blocks["pushback"].max()) if "pushback" in result.blocks else None,
        "pushback_reason": result.pushback_reason, "plan_label": result.plan_label,
        "breakeven": breakeven, "leverage": leverage, "products": products,
        "design_change": {k: _num(result.design.get(k)) for k in ("rock_tonnes_change", "ore_tonnes_change", "value_change")}
        if result.design else None,
        "capacity": cfg.schedule.ore_capacity if cfg.schedule.enabled else None,
        "discount_rate": cfg.schedule.discount_rate if cfg.schedule.enabled else None,
    }


def _warnings(cfg: ProjectConfig, result, kpis: dict, assumptions: list) -> list:
    """Banner items, three levels: blokir / peringatan / asumsi."""
    out = []
    if not result.closure["closed"]:
        out.append({"level": "peringatan", "tag": "PIT TIDAK TERTUTUP", "link": "plan",
                    "text": f"Pit menyentuh batas model di {result.closure['on_sides'] + result.closure['on_bottom']:,} blok "
                            f"({result.closure['on_sides']:,} lateral, {result.closure['on_bottom']:,} dasar). "
                            "Optimum sebenarnya bisa lebih besar dari yang ditampilkan.",
                    "count": result.closure["on_sides"] + result.closure["on_bottom"]})
    if kpis["breakeven"] is not None and kpis["breakeven"] > 0.85:
        lev = kpis["leverage"]
        out.append({"level": "peringatan", "tag": "RISIKO HARGA", "link": "sensitivitas",
                    "text": f"Break-even pada {kpis['breakeven'] * 100:.1f}% harga rencana."
                            + (f" Leverage ≈{lev:.1f}× — harga turun 10% membuat NPV rencana negatif." if lev and lev * 0.1 >= 1 else ""),
                    "breakeven": kpis["breakeven"], "leverage": lev})
    cand = result.pushback_candidates
    if cand is not None and len(cand) and not cand["practical"].any():
        out.append({"level": "peringatan", "tag": "PUSHBACK TIDAK PRAKTIS", "link": "pushback",
                    "text": f"Tidak ada pembagian shell yang memenuhi lebar kerja dan tonase minimum "
                            f"({len(cand)} kandidat diuji)."})
    if result.nesting_violations:
        out.append({"level": "blokir", "tag": "SHELL TIDAK BERSARANG", "link": "pit-by-pit",
                    "text": f"{result.nesting_violations:,} blok keluar dari shell yang lebih besar — periksa numerik."})
    if assumptions:
        names = ", ".join(a["label"] for a in assumptions)
        out.append({"level": "asumsi", "tag": "ASUMSI", "link": "parameter",
                    "text": f"{len(assumptions)} parameter belum dikonfirmasi pemilik studi — {names}.",
                    "count": len(assumptions)})
    return out


LABELS = {
    "economics.rehabilitation_cost_per_volume": "rehabilitasi",
    "slope.overall_angle_deg": "slope",
    "schedule.ore_capacity": "kapasitas",
    "schedule.discount_rate": "discount rate",
    "economics.products.ZIRCON.processing_cost_per_tonne": "penempatan biaya proses",
    "design.bench_height": "tinggi bench",
    "design.bench_face_angle_deg": "sudut muka bench",
}


def _assumptions(cfg: ProjectConfig) -> list:
    out = []
    for path, info in (cfg.provenance or {}).items():
        if isinstance(info, dict) and info.get("source") == "asumsi":
            out.append({"path": path, "label": LABELS.get(path, path.split(".")[-1]), "note": info.get("note", "")})
    return out


def _model_gap(blocks: pd.DataFrame, xs: np.ndarray, topo: np.ndarray, face: np.ndarray) -> dict | None:
    """Ground the design excavates that the block model does not contain.

    The excavation is the volume between the topography and the designed face position, integrated on the design
    grid. The block model only carries material where it has blocks, so where the model's top sits below the
    topography (or its lateral limit falls short) part of that excavation has no blocks: it is neither costed
    nor counted in tonnes. The difference is measured against the block material the design mines."""
    if "design_fraction" not in blocks.columns or len(xs) < 2:
        return None
    cell = float(xs[1] - xs[0])
    geometry = float(np.nansum(np.clip(topo - face, 0.0, None)) * cell * cell)
    material = float((blocks["volume"] * blocks["design_fraction"]).sum())
    if geometry <= 0:
        return None
    gap = geometry - material
    return {"geometry_volume": geometry, "design_material_volume": material, "unmodelled_volume": gap, "share": gap / geometry}


def _qa(cfg: ProjectConfig, result, blocks: pd.DataFrame, surface_faces: int | None, reblock: dict | None,
        gap: dict | None = None) -> dict:
    checks = []

    def add(name, status, detail, group="data", **extra):
        checks.append({"name": name, "status": status, "detail": detail, "group": group, **extra})

    add("Grid reguler", "ok" if blocks[["dx", "dy", "dz"]].nunique().max() == 1 else "peringatan",
        f"Blok {blocks['dx'].iloc[0]:g} × {blocks['dy'].iloc[0]:g} × {blocks['dz'].iloc[0]:g} m, satu ukuran.")
    if reblock:
        diff = reblock["output_volume"] - reblock["source_volume"]
        parent = reblock["parent_size"]
        add("Reblock dari sub-cell", "ok" if abs(diff) < 1 else "peringatan",
            f"Parent {parent['x']:g}×{parent['y']:g}×{parent['z']:g} m → {reblock['blocks']:,} blok "
            f"{'×'.join(f'{v:g}' for v in reblock['target'])} m. Selisih volume {diff:+,.3f} m³.",
            reblock=reblock)
        add("Blok terisi sebagian di tepi", "info",
            f"{reblock['partial_fill_below_half'] * 100:.0f}% blok terisi < 50% — volume sebenarnya dipakai, bukan ukuran nominal.")
    if cfg.surface.path:
        add("Topografi", "ok", f"{Path(cfg.surface.path).name}" + (f" — {surface_faces:,} facet." if surface_faces else "."))
    else:
        add("Topografi", "peringatan", "Tidak ada surface; topografi diturunkan dari puncak block model.")
    if gap:
        flagged = gap["share"] > 0.02
        add("Model menutupi topografi di dalam pit", "peringatan" if flagged else "ok",
            f"{gap['unmodelled_volume']:,.0f} m³ ({gap['share'] * 100:.1f}% volume galian desain) berada di antara topografi dan "
            "puncak model tanpa blok — tidak dihitung biaya maupun tonasenya." if flagged else
            f"Volume galian desain dan volume blok selisih {gap['share'] * 100:.1f}%.", model_topography_gap=gap)
    add("Pit tertutup di dalam model", "ok" if result.closure["closed"] else "peringatan",
        "Pit selesai di dalam model." if result.closure["closed"]
        else f"{result.closure['on_sides'] + result.closure['on_bottom']:,} blok di batas model — perluas model.")
    sums = []
    groups = [c for c in ("domain", "resource_class") if c in blocks.columns]
    if groups:
        for keys, part in blocks.groupby(groups):
            keys = keys if isinstance(keys, tuple) else (keys,)
            rec = dict(zip(groups, keys))
            rec["blocks"] = int(len(part))
            rec["volume"] = float(part["volume"].sum())
            for p in cfg.economics.products:
                w = part["volume"].to_numpy()
                rec[p.grade_col] = float(np.average(part[p.grade_col], weights=w)) if w.sum() else 0.0
            rec["ore_domain"] = bool(part["is_ore_domain"].iloc[0]) if "is_ore_domain" in part else True
            sums.append(rec)
        # A domain that assays like ore but is not allowed as feed: worth saying out loud.
        for rec in sums:
            if not rec["ore_domain"] and rec.get("resource_class") is not None:
                pass
    return {"checks": checks, "domain_class": sums, "reblock": reblock}


def _inputs(blocks: pd.DataFrame) -> list:
    return [
        {"item": "Blok dipakai", "value": f"{len(blocks):,}", "unit": ""},
        {"item": "Easting", "value": f"{blocks['x'].min():,.1f} – {blocks['x'].max():,.1f}", "unit": "m"},
        {"item": "Northing", "value": f"{blocks['y'].min():,.1f} – {blocks['y'].max():,.1f}", "unit": "m"},
        {"item": "RL", "value": f"{blocks['z'].min():,.2f} – {blocks['z'].max():,.2f}", "unit": "m"},
        {"item": "Ukuran blok", "value": f"{blocks['dx'].iloc[0]:g} × {blocks['dy'].iloc[0]:g} × {blocks['dz'].iloc[0]:g}", "unit": "m"},
        {"item": "Volume total", "value": f"{blocks['volume'].sum():,.0f}", "unit": "m³"},
        {"item": "Tonase total", "value": f"{blocks['rock_tonnes'].sum():,.0f}", "unit": "t"},
    ]


def _files(out_dir: Path, name: str) -> list:
    kinds = {".xlsx": "Excel", ".pdf": "PDF", ".html": "HTML 3D", ".dxf": "DXF", ".csv": "CSV", ".png": "Gambar", ".json": "Data"}
    files = []
    for f in sorted(out_dir.glob(f"{name}_*")):
        if f.suffix in kinds and f.suffix != ".npz":
            files.append({"name": f.name, "kind": kinds[f.suffix], "bytes": f.stat().st_size})
    return files


def write_results(cfg: ProjectConfig, result, ctx: dict) -> tuple[str, dict]:
    """Build the results document, write it and the surfaces file.
    ctx supplies what the result object does not carry: design grids and
    surfaces, timing and the verification numbers."""
    blocks: pd.DataFrame = result.blocks
    report = result.report
    row = report.iloc[result.final_shell - 1]
    products = [p.name for p in cfg.economics.products]
    out_dir = Path(cfg.output.directory)

    # ── pit by pit ──
    table = []
    for _, r in report.iterrows():
        entry = {
            "rf": _num(r["revenue_factor"]), "shell": int(r["shell"]), "blocks": int(r["blocks"]),
            "rock_t": _num(r["rock_tonnes"]), "ore_t": _num(r["ore_tonnes"]), "waste_t": _num(r["waste_tonnes"]),
            "sr": _num(r["strip_ratio"]), "value": _num(r["value"]),
            "npv_best": _num(r.get("npv_best")), "npv_worst": _num(r.get("npv_worst")), "npv_avg": _num(r.get("npv_average")),
            "periods": _num(r.get("periods")), "empty": int(r["blocks"]) == 0,
            "final": bool(r.get("final_pit", False)),
            "products": {n: _num(r[f"{n}_tonnes"]) for n in products},
        }
        table.append(entry)
    filled = [t for t in table if not t["empty"] and t["npv_avg"] is not None]
    peak_avg = max(filled, key=lambda t: t["npv_avg"]) if filled else None
    peak_undisc = max((t for t in table if not t["empty"]), key=lambda t: t["value"]) if filled else None
    first_filled = next((t["shell"] for t in table if not t["empty"]), None)
    for t in table:
        t["note"] = ("Pit kosong — tidak ekonomis" if t["empty"]
                     else "Shell pertama yang terisi" if t["shell"] == first_filled
                     else "Puncak NPV rata-rata" if peak_avg and t["shell"] == peak_avg["shell"]
                     else "Puncak tak terdiskonto" if peak_undisc and t["shell"] == peak_undisc["shell"] else "")

    # ── pushbacks ──
    pushbacks = _rows(result.pushbacks)
    if result.schedule is not None and "pushbacks" in result.schedule.columns and pushbacks:
        active: dict = {}
        for _, s in result.schedule.iterrows():
            for token in str(s["pushbacks"]).replace(" ", "").split(","):
                if token.startswith("PB"):
                    active.setdefault(int(token[2:]), []).append(int(s["period"]))
        for pb in pushbacks:
            periods = active.get(int(pb["pushback"]), [])
            pb["periods"] = [min(periods), max(periods)] if periods else None
    strips = None
    if "strip" in blocks.columns:
        strip_col = blocks[(blocks["pushback"] > 0)]
        strips = {int(pb): [int(g["strip"].min()), int(g["strip"].max())] for pb, g in strip_col.groupby("pushback")}
        for pb in pushbacks:
            pb["strips"] = strips.get(int(pb["pushback"]))
    cand = result.pushback_candidates
    candidates = _rows(cand.head(15)) if cand is not None else []

    # ── schedule ──
    def schedule_rows(frame: pd.DataFrame | None) -> list:
        if frame is None:
            return []
        keep = ["period", "years", "pushbacks", "blocks", "volume", "rock_tonnes", "ore_tonnes", "waste_tonnes",
                "strip_ratio", "cash_flow", "discount_factor", "discounted_cash_flow", "cumulative_cash_flow", "npv"]
        keep += [f"{n}_tonnes" for n in products]
        cols = [c for c in keep if c in frame.columns]
        return _rows(frame[cols])

    # ── sensitivity ──
    sens = None
    if result.sensitivity is not None:
        sens = {
            "all": _rows(result.sensitivity[["price_factor", "value", "npv", "ore_tonnes", "waste_tonnes", "periods"]]),
            "per_product": {},
            "breakeven": _num(breakeven_price_factor(result.sensitivity)),
            "breakeven_value": _num(breakeven_price_factor(result.sensitivity, "value")),
        }
        if result.sensitivity_by_product is not None:
            for name, part in result.sensitivity_by_product.groupby("product"):
                sens["per_product"][name] = _rows(part[["price_factor", "value", "npv"]])

    # ── design ──
    design = None
    g = result.design_geometry
    if g is not None and result.design is not None:
        design = {
            "bench_height": g.bench_height, "face_angle_deg": g.face_angle_deg, "berm_width": _num(g.berm_width),
            "overall_angle_deg": _num(g.overall_angle_deg),
            "reconciliation": {k: _num(v) if not isinstance(v, dict) else {kk: _num(vv) for kk, vv in v.items()}
                               for k, v in result.design.items()},
        }

    kpis = _kpis(cfg, result, row)
    assumptions = _assumptions(cfg)
    warnings = _warnings(cfg, result, kpis, assumptions)

    reblock = None
    stem = re.sub(r"_blocks$", "", Path(cfg.block_model.path).stem)
    candidate = Path(cfg.block_model.path).with_name(f"{stem}_reblock.json")
    if candidate.exists():
        reblock = json.loads(candidate.read_text())

    # ── surfaces: display grids (downsampled) + full-resolution npz ──
    xs, ys, topo = ctx["xs"], ctx["ys"], ctx["topo"]
    step = max(1, int(math.ceil(max(len(xs), len(ys)) / 160)))
    layers = {}
    if ctx.get("bowl") is not None:
        layers["bowl"] = ctx["bowl"]
    layers["face"] = ctx["face"]
    for (kind, n), surface in ctx["stage_faces"].items():
        layers[f"{kind}_{n}"] = surface
    grids3d = {
        "x": np.round(xs[::step], 1).tolist(), "y": np.round(ys[::step], 1).tolist(),
        "topo": _grid_list(_downsample(topo, step)),
        "layers": {k: _grid_list(_downsample(v, step)) for k, v in layers.items()},
        "step_m": float(step * (xs[1] - xs[0])),
    }
    npz_path = out_dir / f"{cfg.name}_surfaces.npz"
    saved = {"xs": xs.astype("float64"), "ys": ys.astype("float64"), "topo": topo.astype("float32"),
             "optimiser": ctx["optimiser"].astype("float32")}
    for k, v in layers.items():
        saved[k] = np.where(np.isfinite(v), v, np.nan).astype("float32")
    np.savez_compressed(npz_path, **saved)

    verification = ctx.get("verification") or {}
    doc = {
        "meta": {
            "schema_version": 1,
            "project": ctx.get("project", cfg.name), "scenario": ctx.get("scenario", cfg.name), "name": cfg.name,
            "engine_version": ctx.get("engine_version"), "run_at": ctx.get("run_at"), "duration_s": ctx.get("duration_s"),
            "currency": CURRENCY, "shells": len(report), "blocks": int(len(blocks)),
            "config_path": cfg.source, "surfaces": npz_path.name,
        },
        "verification": {
            "walls": verification.get("violations", (None, None, None))[0],
            "cone": verification.get("violations", (None, None, None))[1],
            "schedule": verification.get("violations", (None, None, None))[2],
            "detail": verification,
        },
        "kpis": kpis,
        "warnings": warnings,
        "assumptions": assumptions,
        "pit_by_pit": table,
        "final_pit": {
            "shell": int(result.final_shell), "rf": _num(result.final_rf), "reason": result.final_reason,
            "row": next(t for t in table if t["shell"] == result.final_shell),
            "peak_avg": peak_avg, "peak_undiscounted": peak_undisc,
            "criterion": cfg.final_pit.criterion, "tolerance": cfg.final_pit.tolerance,
        },
        "pushbacks": {"method": cfg.pushbacks.method, "count_reason": result.pushback_reason, "rows": pushbacks,
                      "candidates": candidates, "candidates_total": int(len(cand)) if cand is not None else 0,
                      "candidates_practical": int(cand["practical"].sum()) if cand is not None else 0,
                      "strip_width": cfg.pushbacks.strip_width, "min_width": cfg.pushbacks.min_width,
                      "plan_label": result.plan_label},
        "schedule": {"tag_reconciliation": _tag_reconciliation(blocks, schedule_rows(result.schedule)),
                     "plan": schedule_rows(result.schedule), "best": schedule_rows(result.schedule_best),
                     "worst": schedule_rows(result.schedule_worst), "contiguity": _contiguity(blocks),
                     "products": products},
        "sensitivity": sens,
        "design": design,
        "params": _params(cfg),
        "derived": _derived(cfg),
        "provenance": cfg.provenance or {},
        "plan_view": _plan_rasters(blocks),
        "grids3d": grids3d,
        "inputs": _inputs(blocks),
        "qa": _qa(cfg, result, blocks, ctx.get("surface_faces"), reblock, _model_gap(blocks, xs, topo, ctx["face"])),
        "outputs": _files(out_dir, cfg.name),
    }
    if getattr(result, "design_detail", None) is not None:      # F-DES-6; absent, not null, when the detailed design is off
        from .design_export import clean, document

        doc["design_detail"] = clean(document(result.design_detail, cfg, {"final_shell": result.final_shell,
                                                                         "final_rf": result.final_rf}))
    path = out_dir / f"{cfg.name}_results.json"
    # write to a temp file and rename: the UI polls this file and must never read half of it
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False))
    tmp.replace(path)
    return str(path), doc
