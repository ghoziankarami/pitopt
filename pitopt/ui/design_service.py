"""
The detailed pit design as the UI sees it.

The design is computed from a finished PitOpt run: its block table gives the
shell, and the parameters come from the scenario's `design.detail` block,
optionally edited in the UI. Editing never overwrites the scenario's YAML —
the edits travel with each Generate and are saved, when the user wants, as a
new scenario, the way every other parameter change in PitOpt is.

Generate is a background job the UI polls, like a run. It reports each bench
as it is finished so the viewer can draw the pit while the rest is computed,
and it can be cancelled; a cancelled Generate leaves the design already on
screen exactly as it was, because the new one replaces it only when complete.

One design is kept per scenario, keyed by the parameters and the run it was
made from. Asking again with nothing changed returns it at once. A changed
parameter rebuilds the whole stack: the wall geometry of one sector reaches
into its neighbours through the blend across their boundary, so reusing the
untouched sectors would be reusing geometry that is no longer right at the
seams, and a full build takes well under a second on a real shell.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import traceback
import uuid
from dataclasses import asdict
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from ..core.cancel import Cancelled, CancelToken
from ..core.design_detail.builder import DesignDetail, build_design
from ..core.design_detail.config import BermConfig
from ..core.design_detail.footprint import level_footprint
from ..core.design_detail.parameters import berm_width, inter_ramp_angle_deg, resolve_sectors
from ..core.design_detail.ramp import size_ramp, wall_tables
from ..io import design_export

DEC = 2                       # coordinates go to the UI at centimetre resolution


def _polygons(geometry: BaseGeometry) -> list[dict]:
    """An area as [{o: outer ring, h: [islands]}] of [x, y] pairs, at centimetre resolution."""
    if geometry.is_empty:
        return []
    parts = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    ring = lambda r: np.round(np.asarray(r.coords)[:-1], DEC).tolist()      # noqa: E731
    return [{"o": ring(p.exterior), "h": [ring(h) for h in p.interiors]} for p in parts if p.geom_type == "Polygon"]


class DesignJob:
    def __init__(self, project: str, scenario: str):
        self.id = uuid.uuid4().hex[:10]
        self.project, self.scenario = project, scenario
        self.status = "running"
        self.events: list[dict] = []
        self.error: str | None = None
        self.fraction = 0.0
        self.started = time.time()
        self.finished: float | None = None
        self.cancel = CancelToken()

    def add(self, event: dict) -> None:
        self.events.append(event)

    def snapshot(self, since: int = 0) -> dict:
        return {"id": self.id, "status": self.status, "events": self.events[since:], "next": len(self.events),
                "fraction": self.fraction, "error": self.error,
                "elapsed": round((self.finished or time.time()) - self.started, 2)}


class Session:
    """One finished design and what it was made from."""

    def __init__(self, detail: DesignDetail, blocks, in_pit: np.ndarray, cfg, key: str, elapsed: float):
        self.detail, self.blocks, self.in_pit, self.cfg, self.key, self.elapsed = detail, blocks, in_pit, cfg, key, elapsed
        self.generated = time.time()


class DesignService:
    def __init__(self, app):
        self.app = app
        self.jobs: dict[str, DesignJob] = {}
        self.sessions: dict[tuple[str, str], Session] = {}
        self.lock = threading.Lock()

    # ── configuration ──
    @staticmethod
    def _overrides(params: dict | None) -> dict:
        """UI edits are {"ramp.width_m": 25, ...} relative to design.detail; the config takes dotted paths."""
        merged = {f"design.detail.{path}": value for path, value in (params or {}).items()}
        merged["design.detail.enabled"] = True            # asking for a design is asking for it, whatever the file says
        return merged

    def config(self, project: str, scenario: str, params: dict | None = None):
        return self.app.config_for(project, scenario, self._overrides(params))

    def _key(self, project: str, scenario: str, cfg) -> str:
        results = self.app.results_path(project, scenario)
        stamp = results.stat().st_mtime_ns if results and results.exists() else 0
        basis = json.dumps({"detail": asdict(cfg.design), "slope": cfg.slope.overall_angle_deg, "run": stamp}, sort_keys=True, default=str)
        return hashlib.sha256(basis.encode()).hexdigest()[:16]

    # ── state for the screens ──
    def state(self, project: str, scenario: str, params: dict | None = None) -> dict:
        results_path = self.app.results_path(project, scenario)
        if not results_path or not results_path.exists():
            return {"has_results": False}
        results = json.loads(results_path.read_text())
        out: dict = {"has_results": True, "meta": results["meta"], "final_pit": results["final_pit"],
                     "verification": results["verification"], "qa": results["qa"]["checks"], "assumptions": results["assumptions"]}
        out["blocks_ready"] = (self.app.output_dir(project, scenario)[0] / f"{results['meta']['name']}_blocks.csv").exists()
        out["files"] = results["outputs"]
        try:
            cfg = self.config(project, scenario, params)
        except ValueError as exc:
            return {**out, "params_error": str(exc)}
        out["params"] = asdict(cfg.design)
        out["slope_deg"] = cfg.slope.overall_angle_deg
        out["provenance"] = {k: v for k, v in (cfg.provenance or {}).items() if k.startswith(("design.", "slope."))}
        out["products"] = [{"name": p.name, "grade_col": p.grade_col} for p in cfg.economics.products]
        out["classes"] = self._classes(cfg)
        ramp = cfg.design.detail.ramp
        if ramp.enabled and (ramp.width_m is not None or ramp.truck_width_m is not None):
            sizing = size_ramp(ramp)
            out["ramp"] = {"width_m": sizing.width_m, "required_width_m": sizing.required_width_m, "source": sizing.source,
                           "width_ok": sizing.width_ok}
        try:
            sectors, notes = resolve_sectors(cfg.design, cfg.slope.overall_angle_deg)
            out["sectors"] = [{**asdict(s), "run_m": s.face_run, "ira_deg": s.ira_deg,
                               "berm_options": self._berm_options(s, cfg)} for s in sectors]
            out["notes"] = notes
        except ValueError as exc:
            out["params_error"] = str(exc)
        session = self.sessions.get((project, scenario))
        out["session"] = None if session is None else {
            "key": session.key, "current": session.key == self._key(project, scenario, cfg),
            "generated": session.generated, "elapsed": round(session.elapsed, 2),
            "status": session.detail.validation.by_check() if session.detail.validation else {}}
        return out

    @staticmethod
    def _berm_options(sector, cfg) -> dict:
        """What each berm criterion would give this sector, so the screen can show them side by side. Ryan has
        no default coefficients, so it is offered only once the project supplies them."""
        overall = cfg.slope.overall_angle_deg
        options = {}
        for method, berm in (("ritchie", BermConfig(method="ritchie")), ("slope", BermConfig(method="slope")),
                             ("ryan", cfg.design.detail.berm if cfg.design.detail.berm.method == "ryan" else None)):
            if berm is None:
                options[method] = None
                continue
            try:
                width, _ = berm_width(berm, sector.bench_height, sector.face_angle_deg, sector.berm_every_n, overall)
            except ValueError:
                options[method] = None
                continue
            options[method] = {"berm_width": width, "ira_deg": inter_ramp_angle_deg(
                sector.bench_height, sector.face_angle_deg, width, sector.berm_every_n)}
        return options

    def block_card(self, project: str, scenario: str) -> dict:
        meta = self.app.block_meta(project, scenario)
        results = json.loads(self.app.results_path(project, scenario).read_text())
        bm = results["params"]["block_model"]
        return {**meta, "file": Path(bm["path"]).name, "extent": self._extent(project, scenario)}

    def _extent(self, project: str, scenario: str) -> dict:
        df = self.app.block_table(project, scenario)
        half = lambda c, d: (float((df[c] - df[d] / 2).min()), float((df[c] + df[d] / 2).max()))     # noqa: E731
        return {"x": half("x", "dx"), "y": half("y", "dy"), "z": half("z", "dz")}

    # ── generate / cancel ──
    def start(self, project: str, scenario: str, params: dict | None) -> DesignJob:
        cfg = self.config(project, scenario, params)                      # a bad parameter fails here, readably, not in the thread
        blocks = self.app.block_table(project, scenario)
        if "in_pit" not in blocks.columns:
            raise ValueError("hasil run tidak memuat kolom in_pit; jalankan ulang optimasi")
        key = self._key(project, scenario, cfg)
        job = DesignJob(project, scenario)
        with self.lock:
            if self.app.demo_mode:
                if any(other.status == "running" for other in self.jobs.values()):
                    raise ValueError("demo design is busy; wait for the current Generate to finish")
                while len(self.jobs) >= 32:
                    del self.jobs[next(iter(self.jobs))]
            for other in self.jobs.values():
                if other.project == project and other.scenario == scenario and other.status == "running":
                    other.cancel.cancel()                                 # one Generate at a time per scenario
            self.jobs[job.id] = job
        threading.Thread(target=self._work, args=(job, cfg, blocks, key), daemon=True).start()
        return job

    def cancel(self, job_id: str) -> DesignJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise FileNotFoundError(f"job desain tidak ditemukan: {job_id}")
        if job.status == "running":
            job.cancel.cancel()
        return job

    def job(self, job_id: str, since: int = 0) -> dict:
        job = self.jobs.get(job_id)
        if job is None:
            raise FileNotFoundError(f"job desain tidak ditemukan: {job_id}")
        return job.snapshot(since)

    def _work(self, job: DesignJob, cfg, blocks, key: str) -> None:
        started = time.time()
        in_pit = blocks["in_pit"].to_numpy().astype(bool)
        existing = self.sessions.get((job.project, job.scenario))
        try:
            if existing is not None and existing.key == key:              # nothing changed: the design on screen is the answer
                job.add({"type": "cached"})
                job.status, job.fraction = "done", 1.0
                return
            weights = {"anchor": 0.05, "benches": 0.05, "ramp": 0.80, "reconcile": 0.88, "validate": 0.96}

            def progress(stage: str, info: dict) -> None:
                if stage == "bench_done":
                    b = info["bench"]
                    job.fraction = 0.05 + 0.75 * info["done"] / max(info["total"], 1)
                    job.add({"type": "bench_done", "index": b.index, "done": info["done"], "total": info["total"],
                             "crest_rl": b.crest_rl, "toe_rl": b.toe_rl, "crest": _polygons(b.crest), "toe": _polygons(b.toe)})
                else:
                    job.fraction = max(job.fraction, weights.get(stage, job.fraction))
                    job.add({"type": "stage", "stage": stage, **{k: v for k, v in info.items() if isinstance(v, (int, float, str))}})

            raster = self._raster_tier(job.project, job.scenario)
            detail = build_design(blocks, in_pit, cfg, raster=raster, progress=progress, cancel=job.cancel)
            job.cancel.check()                                            # replace the design on screen only if not cancelled
            self.sessions[(job.project, job.scenario)] = Session(detail, blocks, in_pit, cfg, key, time.time() - started)
            job.status, job.fraction = "done", 1.0
        except Cancelled:
            job.status = "cancelled"
        except Exception as exc:                                         # noqa: BLE001 — shown to the user verbatim
            job.status, job.error = "error", f"{type(exc).__name__}: {exc}"
            job.add({"type": "error", "text": traceback.format_exc()})
        finally:
            job.finished = time.time()

    def _raster_tier(self, project: str, scenario: str) -> dict | None:
        """The uniform raster design's totals from the run, for the middle tier of the reconciliation."""
        results = json.loads(self.app.results_path(project, scenario).read_text())
        design = results.get("design")
        return design["reconciliation"]["design"] if design else None

    # ── reading the finished design ──
    def session(self, project: str, scenario: str) -> Session:
        session = self.sessions.get((project, scenario))
        if session is None:
            raise FileNotFoundError("belum ada desain untuk skenario ini; tekan Generate")
        return session

    def result(self, project: str, scenario: str) -> dict:
        s = self.session(project, scenario)
        d, cfg = s.detail, s.cfg
        ramp = d.ramp
        (cx, cy), top, _ = wall_tables(d.stack)
        edges = None
        if ramp is not None and len(ramp.x) > 1:
            left, right = design_export.road_edges(ramp, ramp.sizing.width_m / 2.0)
            edges = {"left": np.round(left, DEC).tolist(), "right": np.round(right, DEC).tolist()}
        return {
            "key": s.key, "generated": s.generated, "elapsed": round(s.elapsed, 2),
            "document": design_export.clean(design_export.document(d, cfg, self._shell_meta(project, scenario))),
            "benches": [{"index": b.index, "crest_rl": b.crest_rl, "toe_rl": b.toe_rl,
                         "crest": _polygons(b.crest), "toe": _polygons(b.toe)} for b in d.stack.benches],
            "anchor": _polygons(d.stack.anchor_outline),
            "ramp": None if ramp is None else {
                "x": np.round(ramp.x, DEC).tolist(), "y": np.round(ramp.y, DEC).tolist(), "z": np.round(ramp.z, DEC).tolist(),
                "azimuth": np.round(ramp.azimuth, 3).tolist(), "bench": ramp.bench_of_point.tolist(),
                "edges": edges, "width": ramp.sizing.width_m},
            "shell": [{"rl": float(z), "polys": _polygons(level_footprint(s.blocks, s.in_pit, z).simplify(1.0))}
                      for z in np.unique(np.round(s.blocks.loc[s.in_pit, "z"].to_numpy(), 6))],
            "per_bench": d.reconciliation.per_bench.round(3).to_dict("records"),
            "centre": [cx, cy],
            "sector_lines": [{"name": sec.name, "azimuth": sec.azimuth_from,
                              "to": [cx + float(top.at(sec.azimuth_from)) * np.sin(np.radians(sec.azimuth_from)),
                                     cy + float(top.at(sec.azimuth_from)) * np.cos(np.radians(sec.azimuth_from))]}
                             for sec in d.sectors],
            "classes": self._classes(cfg),
        }

    def _shell_meta(self, project: str, scenario: str) -> dict:
        r = json.loads(self.app.results_path(project, scenario).read_text())["final_pit"]
        return {"final_shell": r["shell"], "final_rf": r["rf"]}

    def _classes(self, cfg) -> dict:
        g = cfg.design.detail.grade_classes
        col = g.grade_col or (cfg.economics.products[0].grade_col if cfg.economics.products else None)
        return {"grade_col": col, "breaks": list(g.breaks), "names": list(g.names), "configured": bool(g.breaks)}

    def plan(self, project: str, scenario: str, rl: float | None = None) -> dict:
        """One bench of the block model as the plan view draws it: every block on that level with its class and
        whether the shell and the design contain it, plus the shell and design outlines at that elevation.
        Works before any design exists (the Source screen shows the shell alone); the design fields are then empty."""
        session = self.sessions.get((project, scenario))
        blocks = session.blocks if session else self.app.block_table(project, scenario)
        in_pit = session.in_pit if session else blocks["in_pit"].to_numpy().astype(bool)
        cfg = session.cfg if session else self.config(project, scenario)
        levels = np.unique(np.round(blocks["z"].to_numpy(), 6))
        shell_levels = np.unique(np.round(blocks.loc[in_pit, "z"].to_numpy(), 6))
        target = float(shell_levels[len(shell_levels) // 2]) if rl is None else rl
        level = float(levels[np.argmin(np.abs(levels - target))])
        at = np.isclose(blocks["z"].to_numpy(), level)
        classes = self._classes(cfg)
        col = classes["grade_col"]
        grade = blocks[col].to_numpy()[at] if col in blocks.columns else np.full(int(at.sum()), np.nan)
        cls = np.searchsorted(classes["breaks"], grade, side="right") if classes["configured"] else np.full(len(grade), -1)
        recon = session.detail.reconciliation if session else None
        return {
            "rl": level, "levels": levels.tolist(), "shell_levels": shell_levels.tolist(),
            "dx": float(blocks["dx"].iloc[0]), "dy": float(blocks["dy"].iloc[0]), "dz": float(blocks["dz"].iloc[0]),
            "x": np.round(blocks["x"].to_numpy()[at], 2).tolist(), "y": np.round(blocks["y"].to_numpy()[at], 2).tolist(),
            "grade": np.round(np.nan_to_num(grade, nan=-1.0), 4).tolist(), "cls": cls.tolist(),
            "value": np.round(blocks["value"].to_numpy()[at], 1).tolist(),
            "ore": (blocks["destination"].to_numpy()[at] == 1).astype(int).tolist(),
            "in_shell": in_pit[at].astype(int).tolist(),
            "in_design": recon.in_design[at].astype(int).tolist() if recon else [0] * int(at.sum()),
            "cause": recon.cause[at].tolist() if recon else [""] * int(at.sum()),
            "shell": _polygons(level_footprint(blocks, in_pit, level)),
            "design": _polygons(session.detail.stack.section_at(level)) if session else [],
            "classes": classes,
        }

    def section(self, project: str, scenario: str, p1: tuple[float, float], p2: tuple[float, float]) -> dict:
        """A vertical slice along a line: where it crosses each bench's crest and toe, the optimiser shell's stair,
        a one-block-thick strip of the block model along it, and where it crosses the road."""
        s = self.session(project, scenario)
        line = LineString([p1, p2])
        length = float(line.length)
        if not np.isfinite([*p1, *p2]).all() or not np.isfinite(length) or length <= 0:
            raise ValueError("section endpoints must be finite and distinct")
        if length / self.app.block_table(project, scenario)["dx"].iloc[0] > 4095:
            raise ValueError("section is too long; use endpoints within 4,095 cells")
        ux, uy = (p2[0] - p1[0]) / length, (p2[1] - p1[1]) / length

        def spans(geometry: BaseGeometry) -> list[list[float]]:
            inside = line.intersection(geometry)
            parts = [] if inside.is_empty else list(getattr(inside, "geoms", [inside]))
            return [[round(line.project(shapely.Point(g.coords[0])), 2), round(line.project(shapely.Point(g.coords[-1])), 2)]
                    for g in parts if g.geom_type == "LineString"]

        rings = [{"index": b.index, "kind": kind, "rl": rl, "spans": spans(g)}
                 for b in s.detail.stack.benches for kind, rl, g in (("crest", b.crest_rl, b.crest), ("toe", b.toe_rl, b.toe))]
        blocks = s.blocks
        dx, dy, dz = float(blocks["dx"].iloc[0]), float(blocks["dy"].iloc[0]), float(blocks["dz"].iloc[0])
        rel_x, rel_y = blocks["x"].to_numpy() - p1[0], blocks["y"].to_numpy() - p1[1]
        along, across = rel_x * ux + rel_y * uy, -rel_x * uy + rel_y * ux
        strip = (np.abs(across) <= min(dx, dy) / 2) & (along >= -dx) & (along <= length + dx)
        classes = self._classes(s.cfg)
        col = classes["grade_col"]
        grade = blocks[col].to_numpy()[strip] if col in blocks.columns else np.full(int(strip.sum()), np.nan)
        cls = np.searchsorted(classes["breaks"], grade, side="right") if classes["configured"] else np.full(len(grade), -1)
        recon = s.detail.reconciliation
        shell_stair = [{"rl": float(z), "spans": spans(level_footprint(blocks, s.in_pit, z))}
                       for z in np.unique(np.round(blocks.loc[s.in_pit, "z"].to_numpy(), 6))]
        crossings = []
        ramp = s.detail.ramp
        if ramp is not None and len(ramp.x) > 1:
            path = LineString(np.column_stack([ramp.x, ramp.y]))
            hit = line.intersection(path)
            for pt in ([] if hit.is_empty else list(getattr(hit, "geoms", [hit]))):
                if pt.geom_type == "Point":
                    i = int(np.argmin(np.hypot(ramp.x - pt.x, ramp.y - pt.y)))
                    crossings.append({"d": round(line.project(pt), 2), "rl": round(float(ramp.z[i]), 2)})
        return {
            "length": length, "rings": rings, "shell": shell_stair, "ramp": crossings, "dz": dz,
            "cell": round(float(dx * abs(ux) + dy * abs(uy)), 3),
            "blocks": {"d": np.round(along[strip], 2).tolist(), "rl": blocks["z"].to_numpy()[strip].tolist(),
                       "cls": cls.tolist(), "grade": np.round(np.nan_to_num(grade, nan=-1.0), 4).tolist(),
                       "mined": recon.in_design[strip].astype(int).tolist(), "in_shell": s.in_pit[strip].astype(int).tolist()},
            "classes": classes,
        }

    # ── export ──
    def export(self, project: str, scenario: str, kinds: list[str] | None) -> list[dict]:
        s = self.session(project, scenario)
        out_dir, name = self.app.output_dir(project, scenario)
        written = design_export.write_all(s.detail, s.cfg, out_dir, name, self._shell_meta(project, scenario),
                                          s.blocks, s.in_pit, kinds=set(kinds) if kinds else None)
        return [{"kind": k, "name": Path(p).name, "bytes": Path(p).stat().st_size} for k, p in written.items()]
