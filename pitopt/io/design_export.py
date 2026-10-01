"""
Everything the detailed design writes to disk.

    <name>_design_benches.dxf     crest and toe of every bench, one layer per elevation
    <name>_design_ramp.dxf        road centreline and both edges
    <name>_design_sectors.dxf     the sector boundaries, at crest elevation
    <name>_design_detail.json     the session: parameters with provenance, results, validation
    <name>_design_reconciliation.csv / _by_bench.csv / .xlsx

Every file carries the same provenance: the engine, the time, the shell it
came from (a hash of its blocks), where each parameter came from, and the
validation status. In the JSON it is a block a reader cannot miss; in a DXF it
travels as header variables. It is written whether or not anything failed,
and a design with a blocked check says so in every file, because a drawing
gets separated from the report that qualified it.

DXF is AC1024, metres, in the coordinate system of the shell with no
transformation. Layer names follow the export screen: PD_CREST_<RL>,
PD_TOE_<RL>, PD_RAMP_CL, PD_RAMP_EDGE, PD_SECTOR, PD_SHELL_REF.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import ezdxf
import numpy as np
import pandas as pd
from shapely.geometry.base import BaseGeometry

from .. import __version__
from ..config import ProjectConfig
from ..core.design_detail.builder import DesignDetail
from ..core.design_detail.footprint import level_footprint
from ..core.design_detail.ramp import wall_tables

SCHEMA = 1


def _polygons(geometry: BaseGeometry):
    return [] if geometry.is_empty else (list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry])


def _rings(geometry: BaseGeometry):
    """Every boundary of an area — outer edges and islands — as coordinate lists."""
    for polygon in _polygons(geometry):
        yield list(polygon.exterior.coords)[:-1]
        for hole in polygon.interiors:
            yield list(hole.coords)[:-1]


def _layer(prefix: str, rl: float) -> str:
    """PD_CREST_1180, PD_TOE_1167_5. AutoCAD layer names do not take a full stop."""
    return f"{prefix}_{rl:g}".replace(".", "_")


# ── provenance ─────────────────────────────────────────────────────────────────────────────────────────────────
def _leaves(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list) and node and isinstance(node[0], dict):
        for item in node:
            yield from _leaves(item, f"{path}.{item.get('name') or ''}".rstrip("."))
    elif node is not None:
        yield path, node


def parameters(cfg: ProjectConfig) -> list[dict]:
    """Every parameter of the detailed design with its value and where it came from. Anything the project did
    not record a source for is DEFAULT: the design ran on the engine's own value."""
    out = []
    for path, value in _leaves(asdict(cfg.design.detail)):
        if path.startswith("sectors") and path.endswith(".name"):
            continue
        entry = (cfg.provenance or {}).get(f"design.detail.{path}") or (cfg.provenance or {}).get(f"design.{path}") or {}
        source = str(entry.get("source", "default")).upper() if isinstance(entry, dict) else "DEFAULT"
        row = {"id": path, "value": value, "source": source}
        if isinstance(entry, dict) and entry.get("ref"):
            row["ref"] = entry["ref"]
        if isinstance(entry, dict) and entry.get("note"):
            row["note"] = entry["note"]
        out.append(row)
    return out


def provenance(detail: DesignDetail, cfg: ProjectConfig, shell: dict) -> dict:
    validation = detail.validation
    by = validation.by_check() if validation else {}
    return {
        "engine": f"pit-design-engine 0.1 · pitopt {__version__}",
        "generated": datetime.now().astimezone().isoformat(timespec="minutes"),
        "sourceShell": {**shell, "sha256": detail.shell_sha256},
        "optimizationSlopeDeg": cfg.slope.overall_angle_deg,
        "parameters": parameters(cfg),
        "validation": {"shapeFit": by.get("shape_fit"), "ira": by.get("ira"), "osa": by.get("osa"),
                       "reconciliation": by.get("reconciliation"), "ramp": by.get("ramp"),
                       "selfIntersection": by.get("self_intersection"), "minWidth": by.get("min_width")},
        "signedByCP": False,
    }


# ── DXF ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _new_doc(prov: dict, title: str):
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.M
    tags = {"PD_FILE": title, "PD_ENGINE": prov["engine"], "PD_GENERATED": prov["generated"],
            "PD_SHELL_SHA256": prov["sourceShell"]["sha256"], "PD_SLOPE_OPT_DEG": f"{prov['optimizationSlopeDeg']:g}",
            "PD_SIGNED_BY_CP": "false", **{f"PD_VALIDATION_{k.upper()}": str(v) for k, v in prov["validation"].items()},
            "PD_ASSUMPTIONS": str(sum(p["source"] == "ASUMSI" for p in prov["parameters"]))}
    for tag, value in tags.items():
        doc.header.custom_vars.append(tag, value)
    return doc


def write_benches_dxf(detail: DesignDetail, path: Path, prov: dict, shell_reference=None) -> Path:
    """Crest and toe of every bench as closed 3D polylines, each elevation on its own layer so it can be
    switched off, and an island as its own polyline."""
    doc = _new_doc(prov, path.name)
    msp = doc.modelspace()
    for bench in detail.stack.benches:
        for geometry, prefix, rl in ((bench.crest, "PD_CREST", bench.crest_rl), (bench.toe, "PD_TOE", bench.toe_rl)):
            layer = _layer(prefix, rl)
            if layer not in doc.layers:
                doc.layers.add(layer)
            for ring in _rings(geometry):
                msp.add_polyline3d([(x, y, rl) for x, y in ring], close=True, dxfattribs={"layer": layer})
    if shell_reference is not None:
        doc.layers.add("PD_SHELL_REF")
        for rl, outline in shell_reference:
            for ring in _rings(outline):
                msp.add_polyline3d([(x, y, rl) for x, y in ring], close=True, dxfattribs={"layer": "PD_SHELL_REF"})
    doc.saveas(path)
    return path


def road_edges(ramp, half: float) -> tuple[np.ndarray, np.ndarray]:
    """Left and right edge of the road, half a width either side of the centreline in plan, at the road's own
    elevation. The direction of travel at each point is the chord of its neighbours."""
    xy = np.column_stack([ramp.x, ramp.y])
    tangent = np.gradient(xy, axis=0)
    tangent /= np.maximum(np.hypot(*tangent.T), 1e-12)[:, None]
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    return xy + half * normal, xy - half * normal


def write_ramp_dxf(detail: DesignDetail, path: Path, prov: dict) -> Path:
    """The road: a centreline whose elevation is the road's real one, and its two edges."""
    ramp = detail.ramp
    doc = _new_doc(prov, path.name)
    msp = doc.modelspace()
    doc.layers.add("PD_RAMP_CL")
    doc.layers.add("PD_RAMP_EDGE")
    if len(ramp.x) > 1:
        msp.add_polyline3d(list(zip(ramp.x, ramp.y, ramp.z)), dxfattribs={"layer": "PD_RAMP_CL"})
        left, right = road_edges(ramp, ramp.sizing.width_m / 2.0)
        for edge in (left, right):
            msp.add_polyline3d([(x, y, z) for (x, y), z in zip(edge, ramp.z)], dxfattribs={"layer": "PD_RAMP_EDGE"})
    doc.saveas(path)
    return path


def write_sectors_dxf(detail: DesignDetail, path: Path, prov: dict) -> Path:
    """One line per sector boundary, from the floor's centre to the crest at crest elevation, with the sector's
    name at its middle."""
    doc = _new_doc(prov, path.name)
    msp = doc.modelspace()
    doc.layers.add("PD_SECTOR")
    (cx, cy), top, _ = wall_tables(detail.stack)
    rl = detail.stack.benches[0].crest_rl
    for sector in detail.sectors:
        if len(detail.sectors) > 1:
            r = float(top.at(sector.azimuth_from))
            a = math.radians(sector.azimuth_from)
            msp.add_line((cx, cy, rl), (cx + r * math.sin(a), cy + r * math.cos(a), rl), dxfattribs={"layer": "PD_SECTOR"})
        length = (sector.azimuth_to - sector.azimuth_from) % 360.0 or 360.0
        mid = math.radians(sector.azimuth_from + length / 2.0)
        r = float(top.at(sector.azimuth_from + length / 2.0)) * 0.7
        msp.add_text(sector.name, height=max(top.radius[np.isfinite(top.radius)].max() * 0.03, 1.0),
                     dxfattribs={"layer": "PD_SECTOR", "insert": (cx + r * math.sin(mid), cy + r * math.cos(mid), rl)})
    doc.saveas(path)
    return path


# ── JSON ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _tally(t) -> dict:
    return asdict(t)


def document(detail: DesignDetail, cfg: ProjectConfig, shell: dict) -> dict:
    """The design as one JSON-able document: provenance first, then the parameters per sector, the benches,
    the road, the reconciliation and every validation finding."""
    stack, ramp, recon, validation = detail.stack, detail.ramp, detail.reconciliation, detail.validation
    osa = {o.name: o for o in detail.osa}
    return {
        "schema": SCHEMA,
        "provenance": provenance(detail, cfg, shell),
        "anchor": stack.anchor,
        "floor_rl": detail.floor_rl,
        "crest_rl": detail.crest_rl,
        "floor_width_m": detail.floor_width_m,
        "floor_widened": detail.floor_widened,
        "smoothing": asdict(detail.smoothing) | {"area_change_m2": detail.smoothing.area_change_m2},
        "sectors": [{
            **{k: v for k, v in asdict(s).items()},
            "run_m": s.face_run, "ira_deg": s.ira_deg,
            "ira_status": next(a.status for a in detail.angles if a.name == s.name),
            **({"osa_deg": osa[s.name].osa_deg, "osa_no_ramp_deg": osa[s.name].osa_no_ramp_deg,
                "osa_analytic_no_ramp_deg": osa[s.name].analytic_no_ramp_deg, "osa_status": osa[s.name].status,
                "worst_azimuth_deg": osa[s.name].worst_azimuth_deg, "ramp_crossings_max": osa[s.name].crossings_max}
               if s.name in osa else {}),
        } for s in detail.sectors],
        "benches": [{
            "index": b.index, "crest_rl": b.crest_rl, "toe_rl": b.toe_rl, "crest_area_m2": b.crest.area,
            "toe_area_m2": b.toe.area, "crest_offsets_m": b.crest_offsets, "toe_offsets_m": b.toe_offsets,
            "crest_parts": len(_polygons(b.crest)),
        } for b in stack.benches],
        "ramp": None if ramp is None else {
            "pattern": ramp.pattern, "direction": ramp.direction, "width_m": ramp.sizing.width_m,
            "width_source": ramp.sizing.source, "required_width_m": ramp.sizing.required_width_m,
            "grade_pct": ramp.sizing.grade_pct, "complete": ramp.complete,
            "broken": None if ramp.broken is None else asdict(ramp.broken),
            "horizontal_length_m": ramp.horizontal_length_m, "turns": ramp.turns,
            "entry_azimuth_deg": ramp.entry_azimuth_deg, "entry_defaulted": ramp.entry_defaulted,
            "reversals_at_bench": ramp.reversals,
            "measured_grade_pct": {str(k): v for k, v in ramp.grade_by_bench().items()},
        },
        "reconciliation": None if recon is None else {
            "shell": _tally(recon.shell), "raster_design": recon.raster, "practical_design": _tally(recon.design),
            "gained": {k: _tally(v) for k, v in recon.gained.items()}, "left_behind": _tally(recon.left_behind),
            "change_pct": {m: recon.change_pct(m) for m in ("rock_tonnes", "ore_tonnes", "value")},
            "status": {m: recon.status(m) for m in ("rock_tonnes", "ore_tonnes", "value")},
            "residual": recon.residual(),
            "thresholds_pct": {"warn": recon.warn_pct, "block": recon.block_pct},
        },
        "findings": [asdict(f) for f in validation.findings] if validation else [],
        "warnings": detail.warnings,
    }


def clean(node):
    """JSON has no NaN or infinity; a missing number is null."""
    if isinstance(node, dict):
        return {k: clean(v) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [clean(v) for v in node]
    if isinstance(node, (np.floating, float)):
        return None if not math.isfinite(node) else float(node)
    if isinstance(node, np.integer):
        return int(node)
    return node


# ── tables ─────────────────────────────────────────────────────────────────────────────────────────────────────
def reconciliation_table(detail: DesignDetail) -> pd.DataFrame:
    """Shell -> raster design -> practical design, and where the difference came from. Every line is a total of
    blocks; the last line is what is left over, which must be zero."""
    r = detail.reconciliation
    cols = ["blocks", "ore_blocks", "waste_blocks", "rock_tonnes", "ore_tonnes", "value"]
    rows = [("shell", r.shell.__dict__)]
    if r.raster:
        rows.append(("raster_design", {c: r.raster.get(c) for c in cols}))
    rows.append(("practical_design", r.design.__dict__))
    diff = {c: getattr(r.design, c) - getattr(r.shell, c) for c in cols}
    rows.append(("difference", diff))
    rows += [(f"+ dilution: {k}", v.__dict__) for k, v in r.gained.items()]
    rows.append(("- left behind (only in the shell)", {c: -getattr(r.left_behind, c) for c in cols}))
    rows.append(("residual (must be 0)", r.residual()))
    table = pd.DataFrame([{"line": name, **{c: values.get(c) for c in cols}} for name, values in rows])
    table["rock_change_pct"] = [None] * len(table)
    table.loc[table["line"] == "difference", "rock_change_pct"] = r.change_pct("rock_tonnes")
    return table


def validation_table(detail: DesignDetail) -> pd.DataFrame:
    return pd.DataFrame([asdict(f) for f in detail.validation.findings])


def sector_table(detail: DesignDetail) -> pd.DataFrame:
    osa = {o.name: o for o in detail.osa}
    rows = []
    for s in detail.sectors:
        a = next(x for x in detail.angles if x.name == s.name)
        o = osa.get(s.name)
        rows.append({
            "sector": s.name, "azimuth_from": s.azimuth_from, "azimuth_to": s.azimuth_to, "bench_height_m": s.bench_height,
            "face_angle_deg": s.face_angle_deg, "berm_width_m": s.berm_width, "berm_method": s.berm_method,
            "ira_deg": a.ira_deg, "ira_max_deg": a.ira_max_deg, "ira_status": a.status,
            "osa_no_ramp_deg": o.osa_no_ramp_deg if o else None, "osa_deg": o.osa_deg if o else None,
            "osa_max_deg": s.osa_max_deg, "osa_status": o.status if o else None,
        })
    return pd.DataFrame(rows)


# ── the writer ─────────────────────────────────────────────────────────────────────────────────────────────────
KINDS = ("benches", "ramp", "sectors", "json", "tables")


def write_all(detail: DesignDetail, cfg: ProjectConfig, out_dir: Path, name: str, shell: dict,
              blocks: pd.DataFrame | None = None, in_pit: np.ndarray | None = None,
              kinds: set[str] | None = None) -> dict[str, str]:
    """Write the outputs of the detailed design, all of them or the `kinds` asked for; returns kind -> path.
    The JSON carries the provenance and the validation, so it is worth writing whatever else is chosen."""
    wanted = set(KINDS) if kinds is None else set(kinds) | {"json"}
    out_dir.mkdir(parents=True, exist_ok=True)
    prov = provenance(detail, cfg, shell)
    written: dict[str, str] = {}

    reference = None
    if "benches" in wanted and cfg.output.design_shell_reference and blocks is not None:
        reference = [(float(z), level_footprint(blocks, in_pit, z)) for z in sorted(blocks.loc[in_pit, "z"].unique())]
    if "benches" in wanted:
        written["design_benches_dxf"] = str(write_benches_dxf(detail, out_dir / f"{name}_design_benches.dxf", prov, reference))
    if "ramp" in wanted and detail.ramp is not None:
        written["design_ramp_dxf"] = str(write_ramp_dxf(detail, out_dir / f"{name}_design_ramp.dxf", prov))
    if "sectors" in wanted:
        written["design_sectors_dxf"] = str(write_sectors_dxf(detail, out_dir / f"{name}_design_sectors.dxf", prov))

    json_path = out_dir / f"{name}_design_detail.json"
    json_path.write_text(json.dumps(clean(document(detail, cfg, shell)), indent=1, allow_nan=False))
    written["design_detail_json"] = str(json_path)

    if "tables" in wanted and detail.reconciliation is not None:
        recon = reconciliation_table(detail)
        by_bench = detail.reconciliation.per_bench
        recon.to_csv(out_dir / f"{name}_design_reconciliation.csv", index=False)
        by_bench.to_csv(out_dir / f"{name}_design_by_bench.csv", index=False)
        written["design_reconciliation_csv"] = str(out_dir / f"{name}_design_reconciliation.csv")
        written["design_by_bench_csv"] = str(out_dir / f"{name}_design_by_bench.csv")
        xlsx = out_dir / f"{name}_design_reconciliation.xlsx"
        with pd.ExcelWriter(xlsx, engine="xlsxwriter") as book:
            recon.to_excel(book, sheet_name="Reconciliation", index=False)
            by_bench.to_excel(book, sheet_name="By bench", index=False)
            validation_table(detail).to_excel(book, sheet_name="Validation", index=False)
            sector_table(detail).to_excel(book, sheet_name="Sectors", index=False)
            pd.DataFrame(prov["parameters"]).to_excel(book, sheet_name="Parameters", index=False)
        written["design_reconciliation_xlsx"] = str(xlsx)
    return written
