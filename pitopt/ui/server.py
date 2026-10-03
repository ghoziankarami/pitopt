"""
Local web server for the PitOpt UI.

Standard library only. It serves the static front end, lists projects and
their scenarios, hands the front end each run's results.json, cuts sections
from the saved surfaces, packages outputs, and runs the optimiser in a
background thread while streaming its log.

One run at a time: an optimisation uses a core flat out and a second would
only slow both, so a second request is refused with 409 instead of queued.

The server binds to 127.0.0.1 and reads and writes only under the project
root it was given. Every path that arrives from the browser is resolved and
checked to sit inside that root before it is touched.
"""
from __future__ import annotations

import copy
import io
import json
import math
import mimetypes
import os
import re
import threading
import time
import traceback
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import yaml
from scipy.ndimage import map_coordinates

from ..core.cancel import Cancelled, CancelToken
from .design_service import DesignService
from .staging import discard, promote, staging_dir

STATIC = Path(__file__).resolve().parent / "static"

# Progress lines emitted by the pipeline, in order, and the stage each one
# belongs to — what the Jalankan stepper shows.
STAGES = [
    ("Baca data", ("Loaded",)),
    ("Clip topografi", ("Clipped",)),
    ("Precedence lereng", ("Precedence graph",)),
    ("Shell RAF", ("Shell ", "Solved")),
    ("Pit by pit", ("Pit by pit", "Final pit:")),
    ("Pushback", ("Pushback count", "Pushbacks:", "Plant rate")),
    ("Jadwal", ("Schedule",)),
    ("Sensitivitas", ("Price sensitivity",)),
    ("Desain bench", ("Pit design", "Pit face position", "Stage surfaces")),
    ("Laporan", ("Interactive 3D", "Excel workbook", "PDF report")),
    ("Verifikasi", ("Verification",)),
    ("Selesai", ("Results for the UI",)),
]


MAX_UPLOAD = 4 * 2**30
MAX_JSON_BODY = 256 * 1024

DEMO_REPO_URL = "https://github.com/ghoziankarami/pitopt"

# In demo mode, every POST is refused except these — the bench-design screens stay interactive (they
# read an already-solved shell and rebuild in well under a second, all in memory, nothing written to
# disk) while anything that runs the solver, uploads data, or touches project files is blocked.
DEMO_ALLOWED_POSTS = {"/api/design/state", "/api/design/run", "/api/design/cancel"}


class Job:
    def __init__(self, project: str, scenario: str):
        self.cancel = CancelToken()
        self.id = uuid.uuid4().hex[:10]
        self.project, self.scenario = project, scenario
        self.status = "running"
        self.log: list[str] = []
        self.stage = 0
        self.fraction = 0.0
        self.error: str | None = None
        self.started = time.time()
        self.finished: float | None = None

    def add(self, line: str) -> None:
        self.log.append(line)
        for index, (_name, prefixes) in enumerate(STAGES):
            if line.startswith(prefixes):
                self.stage = max(self.stage, index)
        m = re.match(r"(Shell|Pit by pit) (\d+)/(\d+)", line)
        base = self.stage / len(STAGES)
        if m:
            base += (int(m.group(2)) / int(m.group(3))) / len(STAGES)
        self.fraction = min(0.99, base) if self.status == "running" else 1.0

    def snapshot(self, since: int = 0) -> dict:
        return {
            "id": self.id, "status": self.status, "stage": self.stage, "stages": [s for s, _ in STAGES],
            "fraction": self.fraction, "log": self.log[since:], "next": len(self.log),
            "error": self.error, "elapsed": round((self.finished or time.time()) - self.started, 1),
        }


class App:
    def __init__(self, root: Path, extra_hosts: frozenset[str] = frozenset(), demo_mode: bool = False):
        self.root = root.resolve()
        self.projects_dir = self.root / "projects"
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.running: Job | None = None
        self._blocks: dict = {}
        self.design = DesignService(self)
        # hostnames a trusted reverse proxy may present in Host/Origin, in addition to loopback —
        # see Handler._guard. Never trust this for anything but that header check.
        self.extra_hosts = extra_hosts
        self.demo_mode = demo_mode
        self.demo_projects = frozenset({"example_tin", "porphyry_synthetic"})

    # ── discovery ──
    def scenario_files(self, project: str) -> list[Path]:
        folder = self._inside(self.projects_dir / project)
        return sorted(p for p in folder.glob("*.yaml") if p.is_file())

    def list_projects(self) -> list[dict]:
        out = []
        for folder in sorted(p for p in self.projects_dir.iterdir() if p.is_dir()):
            if self.demo_mode and folder.name not in self.demo_projects:
                continue
            scenarios = []
            title = folder.name
            order = 100
            for yml in sorted(folder.glob("*.yaml")):
                try:
                    raw = yaml.safe_load(yml.read_text()) or {}
                except yaml.YAMLError:
                    continue
                if "block_model" not in raw:
                    continue
                info = raw.get("project", {}) or {}
                title = info.get("title", title)
                order = info.get("order", order)
                results = self.results_path(folder.name, yml.stem, raw, yml)
                scenarios.append({
                    "id": yml.stem, "name": info.get("name", yml.stem),
                    "label": info.get("scenario", yml.stem),
                    "has_results": bool(results and results.exists()),
                    "run_at": self._run_at(results),
                })
            if scenarios:
                out.append({"id": folder.name, "title": title, "scenarios": scenarios,
                            "_key": (bool((folder / "raw").exists()), order, folder.name)})
        # `project.order` (lower first) picks the default; projects holding raw client data (raw/) go last
        out.sort(key=lambda p: p["_key"])
        for p in out:
            del p["_key"]
        return out

    @staticmethod
    def _run_at(results: Path | None) -> float | None:
        return results.stat().st_mtime if results and results.exists() else None

    def load_raw(self, project: str, scenario: str) -> tuple[dict, Path]:
        yml = self._inside(self.projects_dir / project / f"{scenario}.yaml")
        if not yml.exists():
            raise FileNotFoundError(f"{project}/{scenario}")
        return yaml.safe_load(yml.read_text()) or {}, yml

    def results_path(self, project: str, scenario: str, raw: dict | None = None, yml: Path | None = None) -> Path | None:
        if raw is None:
            raw, yml = self.load_raw(project, scenario)
        out = self._inside(yml.parent / raw.get("output", {}).get("directory", "outputs"))
        name = (raw.get("project", {}) or {}).get("name", "pit")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", str(name)):
            raise ValueError("project.name must be a simple filename")
        return self._inside(out / f"{name}_results.json")

    def output_dir(self, project: str, scenario: str) -> tuple[Path, str]:
        raw, yml = self.load_raw(project, scenario)
        out = (yml.parent / raw.get("output", {}).get("directory", "outputs")).resolve()
        return self._inside(out), (raw.get("project", {}) or {}).get("name", "pit")

    def _inside(self, path: Path) -> Path:
        path = path.resolve()
        if self.root not in path.parents and path != self.root:
            raise PermissionError(f"path di luar folder proyek: {path}")
        return path

    # ── configuration ──
    def resolved(self, project: str, scenario: str, overrides: dict | None = None) -> dict:
        """The scenario as the engine will see it: every default filled in,
        plus provenance and the numbers derived from the parameters. With
        overrides, the same for the edited (unsaved) configuration."""
        from ..io.results import _derived, _params

        cfg = self.config_for(project, scenario, overrides)
        return {"resolved": _params(cfg), "provenance": cfg.provenance, "derived": _derived(cfg)}

    def config_for(self, project: str, scenario: str, overrides: dict | None = None):
        """The scenario's configuration, validated, with dotted-path overrides applied to a copy. Nothing is
        written to the scenario's own file."""
        from ..config import ProjectConfig

        raw, yml = self.load_raw(project, scenario)
        if overrides:
            raw = self._apply(raw, overrides)
        tmp_parent = yml.parent
        if self.demo_mode:
            # Keep the read-only showcase from creating temporary config files in its project root.
            for section, key in (("block_model", "path"), ("surface", "path"), ("output", "directory")):
                value = (raw.get(section) or {}).get(key)
                if value:
                    resolved = self._inside(yml.parent / value)
                    raw[section][key] = str(resolved)
            tmp_parent = Path(os.environ.get("TMPDIR", "/tmp"))
        tmp = tmp_parent / f".pitopt-resolve-{uuid.uuid4().hex}.yaml"
        try:
            tmp.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
            return ProjectConfig.from_yaml(str(tmp))
        finally:
            tmp.unlink(missing_ok=True)

    def save_scenario(self, project: str, scenario: str, overrides: dict, save_as: str) -> str:
        raw, _yml = self.load_raw(project, scenario)
        slug = re.sub(r"[^0-9A-Za-z_-]+", "_", save_as).strip("_")
        if not slug:
            raise ValueError("nama skenario kosong")
        raw = self._apply(raw, overrides) if overrides else copy.deepcopy(raw)
        info = raw.setdefault("project", {})
        base = str(info.get("name", "pit")).split("__")[0]
        info["name"] = f"{base}__{slug}"
        info["scenario"] = save_as
        out = raw.setdefault("output", {})
        out["directory"] = str(Path(out.get("directory", "outputs")).parent / slug)
        target = self._inside(self.projects_dir / project / f"{slug}.yaml")
        target.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
        return slug

    # ── running ──
    @staticmethod
    def _apply(raw: dict, overrides: dict) -> dict:
        """Dotted-path overrides onto the raw YAML dict. Products are
        addressed by name: economics.products.ZIRCON.price."""
        raw = copy.deepcopy(raw)
        for path, value in overrides.items():
            parts = path.split(".")
            node = raw
            for key in parts[:-1]:
                if isinstance(node, list):
                    node = next((p for p in node if p.get("name") == key), None)
                    if node is None:
                        raise ValueError(f"tidak ada produk bernama {key} di {path}")
                    continue
                nxt = node.setdefault(key, {}) if isinstance(node, dict) else None
                node = nxt
            leaf = parts[-1]
            if isinstance(node, list):
                raise ValueError(f"tidak bisa mengatur {path}")
            node[leaf] = value
        return raw

    def start_run(self, project: str, scenario: str, overrides: dict, save_as: str | None) -> Job:
        from ..config import ProjectConfig

        raw, yml = self.load_raw(project, scenario)
        target_id = scenario
        if save_as:
            target_id = self.save_scenario(project, scenario, overrides, save_as)
            yml = self._inside(self.projects_dir / project / f"{target_id}.yaml")
        elif overrides:
            raise ValueError("parameter yang diubah butuh nama skenario (save_as) agar hasil asli tetap ada")

        cfg = ProjectConfig.from_yaml(str(yml))       # validates; raises ValueError with a readable message
        with self.lock:
            if self.running and self.running.status == "running":
                raise RuntimeError("an optimisation is already running")
            job = Job(project, target_id)
            self.jobs[job.id] = job
            self.running = job

        out_dir, name = self.output_dir(project, target_id)
        staging = staging_dir(out_dir, job.id)
        real_directory = cfg.output.directory

        def work() -> None:
            from ..pipeline import run

            try:
                cfg.output.directory = str(staging)              # the run writes here; the previous result is untouched
                run(cfg, verbose=False, log_fn=job.add, context={"project": project, "scenario": target_id}, cancel=job.cancel)
                promote(staging, out_dir, name, real_directory)
                job.status = "done"
            except Cancelled:
                job.status = "cancelled"
                job.log.append("Run dibatalkan — hasil sebelumnya tidak diubah.")
            except Exception as exc:                  # noqa: BLE001 — surfaced to the UI verbatim
                job.status = "error"
                job.error = f"{type(exc).__name__}: {exc}"
                job.log.append(traceback.format_exc())
            finally:
                discard(staging)
                job.finished = time.time()
                job.fraction = 1.0 if job.status == "done" else job.fraction
                try:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    suffix = "run" if job.status == "done" else f"run_{job.status}"
                    (out_dir / f"{name}_{suffix}.log").write_text("\n".join(job.log))
                except Exception:                     # noqa: BLE001
                    pass

        threading.Thread(target=work, daemon=True).start()
        return job

    # ── project management ──
    def _scenario_outputs(self, project: str) -> dict[str, Path]:
        """scenario id -> its output directory, for every scenario of a project."""
        out = {}
        for yml in self.scenario_files(project):
            raw = yaml.safe_load(yml.read_text()) or {}
            if "block_model" in raw:
                out[yml.stem] = self._inside((yml.parent / (raw.get("output", {}) or {}).get("directory", "outputs")).resolve())
        return out

    def cancel_job(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise FileNotFoundError(f"job tidak ditemukan: {job_id}")
        if job.status == "running":
            job.cancel.cancel()
        return job

    def _guard_idle(self, project: str, scenario: str | None = None) -> None:
        job = self.running
        if job and job.project == project and (scenario is None or job.scenario == scenario):
            raise ValueError("optimasi sedang berjalan untuk proyek ini — tunggu selesai dulu")

    def rename(self, project: str, scenario: str | None, name: str) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("nama tidak boleh kosong")
        self._guard_idle(project, scenario)
        targets = [self._inside(self.projects_dir / project / f"{scenario}.yaml")] if scenario else self.scenario_files(project)
        for yml in targets:
            raw = yaml.safe_load(yml.read_text()) or {}
            if "block_model" not in raw:
                continue
            info = raw.setdefault("project", {})
            info["scenario" if scenario else "title"] = name
            yml.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
        return {"ok": True}

    def delete_preview(self, project: str, scenario: str | None = None) -> dict:
        """What a delete would remove, so the dialog can say so before anyone confirms."""
        folder = self._inside(self.projects_dir / project)
        outs = self._scenario_outputs(project)
        if scenario:
            outs = {scenario: outs[scenario]} if scenario in outs else {}
        files = [self._inside(folder / f"{scenario}.yaml")] if scenario else [folder]
        size = lambda path: sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() else (path.stat().st_size if path.exists() else 0)  # noqa: E731
        # an output folder that any surviving scenario (in this or another project) still uses stays
        keep = set()
        for other in sorted(p.name for p in self.projects_dir.iterdir() if p.is_dir()):
            for sid, d in self._scenario_outputs(other).items():
                if other != project or (scenario and sid != scenario):
                    keep.add(d)
        shared = {d for d in outs.values() if d in keep}
        rows = [{"path": str(f.relative_to(self.root)), "bytes": size(f)} for f in files]
        rows += [{"path": str(d.relative_to(self.root)), "bytes": size(d)} for d in outs.values() if d.exists() and d not in shared]
        raw_dir = folder / "raw"
        return {"items": rows, "has_raw_data": raw_dir.exists(), "bytes": sum(r["bytes"] for r in rows)}

    def delete(self, project: str, scenario: str | None, confirm: str) -> dict:
        import shutil

        expected = scenario or project
        if confirm != expected:
            raise ValueError(f"ketik '{expected}' untuk mengonfirmasi")
        self._guard_idle(project, scenario)
        preview = self.delete_preview(project, scenario)
        for item in preview["items"]:
            path = self._inside(self.root / item["path"])
            if not any(base in path.parents for base in (self.projects_dir, self.root / "outputs")):
                raise PermissionError(f"menolak menghapus {path}")
            shutil.rmtree(path) if path.is_dir() else path.unlink(missing_ok=True)
        with self.lock:
            self._blocks.clear()
        return {"deleted": [i["path"] for i in preview["items"]]}

    # ── block model slices ──
    def block_table(self, project: str, scenario: str):
        import pandas as pd

        out_dir, name = self.output_dir(project, scenario)
        csv = out_dir / f"{name}_blocks.csv"
        if not csv.exists():
            raise FileNotFoundError("belum ada hasil run untuk skenario ini")
        key = (str(csv), csv.stat().st_mtime)
        with self.lock:
            if self._blocks.get("k") == key:
                return self._blocks["t"]
        df = pd.read_csv(csv)
        for c, cd in (("x", "dx"), ("y", "dy"), ("z", "dz")):
            step = float(df[cd].iloc[0])
            df[f"i{c}"] = np.round((df[c] - df[c].min()) / step).astype(int)
        df["iz"] = df["iz"].max() - df["iz"]                      # 0 = top bench
        with self.lock:
            self._blocks = {"k": key, "t": df}
        return df

    def block_meta(self, project: str, scenario: str) -> dict:
        df = self.block_table(project, scenario)
        results = json.loads(self.results_path(project, scenario).read_text())
        grade_cols = [c for c in [p["grade_col"] for p in results["params"]["economics"]["products"]] if c in df.columns]
        attrs = []
        for c, label in [(g, f"Kadar {g}") for g in grade_cols] + [("value", "Nilai blok (USD)"), ("rock_tonnes", "Tonase batuan (t)"), ("ore_tonnes", "Tonase umpan (t)")]:
            if c in df.columns:
                attrs.append({"key": c, "label": label, "type": "numeric", "min": float(df[c].min()), "max": float(df[c].max())})
        for c, label in (("domain", "Domain"), ("resource_class", "Kelas sumberdaya")):
            if c in df.columns:
                vals = sorted(df[c].astype(str).unique())[:40]
                attrs.append({"key": c, "label": label, "type": "category", "values": vals})
        attrs.append({"key": "destination", "label": "Tujuan (umpan / waste)", "type": "category", "values": ["Waste", "Umpan"]})
        attrs.append({"key": "in_pit", "label": "Di dalam pit final", "type": "category", "values": ["Di luar", "Di dalam"]})
        for c, label in (("shell", "Shell RAF"), ("pushback", "Pushback"), ("period", "Periode")):
            if c in df.columns and df[c].max() > 0:
                attrs.append({"key": c, "label": label, "type": "ordinal", "max": int(df[c].max())})
        return {"blocks": int(len(df)), "nx": int(df["ix"].max() + 1), "ny": int(df["iy"].max() + 1), "nz": int(df["iz"].max() + 1),
                "x0": float(df["x"].min()), "y0": float(df["y"].min()), "ztop": float(df["z"].max()),
                "dx": float(df["dx"].iloc[0]), "dy": float(df["dy"].iloc[0]), "dz": float(df["dz"].iloc[0]), "attrs": attrs}

    def block_slice(self, project: str, scenario: str, axis: str, index: int, attr: str) -> dict:
        import pandas as pd

        df = self.block_table(project, scenario)
        if attr not in df.columns:
            raise ValueError(f"atribut tidak ada: {attr}")
        col = {"z": "iz", "x": "ix", "y": "iy"}[axis]
        part = df[df[col] == index]
        nx, ny, nz = int(df["ix"].max() + 1), int(df["iy"].max() + 1), int(df["iz"].max() + 1)
        cols_idx, rows_idx, w, h = {"z": ("ix", "iy", nx, ny), "y": ("ix", "iz", nx, nz), "x": ("iy", "iz", ny, nz)}[axis]
        values = part[attr]
        if values.dtype == bool:
            values = values.astype(int)
        elif not pd.api.types.is_numeric_dtype(values):
            codes = {v: n for n, v in enumerate(sorted(df[attr].astype(str).unique()))}
            values = part[attr].astype(str).map(codes)
        grid = np.full((h, w), np.nan)
        r = part[rows_idx].to_numpy()
        if axis == "z":
            r = h - 1 - r                                             # north at the top
        grid[r, part[cols_idx].to_numpy()] = values.to_numpy(dtype=float)
        z = float(df.loc[df["iz"] == index, "z"].iloc[0]) if axis == "z" and len(part) else None
        coord = z if axis == "z" else float(df[df[col] == index][{"x": "x", "y": "y"}[axis]].iloc[0]) if len(part) else None
        return {"axis": axis, "index": index, "coord": coord, "w": w, "h": h,
                "cells": [None if np.isnan(v) else round(float(v), 4) for v in grid.ravel()],
                "count": int(len(part))}

    # ── bring your own data ──
    def create_project(self, spec: dict) -> dict:
        from ..config import ProjectConfig
        from . import onboard

        slug, cfg = onboard.build_project(spec)
        target = onboard.write_project(self.projects_dir, slug, cfg)
        try:
            ProjectConfig.from_yaml(str(target))
            for label, rel in (("block model", cfg["block_model"]["path"]), ("surface", (cfg.get("surface") or {}).get("path"))):
                if rel and not (target.parent / rel).exists():
                    raise ValueError(f"{label} belum diunggah: {rel}")
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return {"project": slug, "scenario": "project"}

    # ── sections ──
    def section(self, project: str, scenario: str, p1: tuple[float, float], p2: tuple[float, float], layers: list[str]) -> dict:
        out_dir, name = self.output_dir(project, scenario)
        data = np.load(out_dir / f"{name}_surfaces.npz")
        xs, ys = data["xs"].astype(float), data["ys"].astype(float)
        cell = float(xs[1] - xs[0])
        coords = (*p1, *p2)
        if not np.isfinite(coords).all():
            raise ValueError("section coordinates must be finite")
        length = float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
        if not np.isfinite(length) or length / cell > 4095:
            raise ValueError("section is too long; use endpoints within 4,095 cells")
        n = max(2, int(length / cell) + 1)
        px = np.linspace(p1[0], p2[0], n)
        py = np.linspace(p1[1], p2[1], n)
        ix = (px - xs[0]) / cell
        iy = (py - ys[0]) / cell

        def sample(a: np.ndarray) -> list:
            a = a.astype(float)
            valid = np.isfinite(a)
            filled = np.where(valid, a, 0.0)
            v = map_coordinates(filled, [ix, iy], order=1, mode="nearest")
            w = map_coordinates(valid.astype(float), [ix, iy], order=1, mode="nearest")
            out = np.where(w > 0.99, v, np.nan)
            return [None if not np.isfinite(t) else round(float(t), 2) for t in out]

        series = {"topo": sample(data["topo"]), "optimiser": sample(data["optimiser"])}
        for layer in layers:
            if layer in data.files:
                series[layer] = sample(data[layer])
        return {"distance": [round(float(d), 2) for d in np.linspace(0, length, n)], "length": length,
                "cell": cell, "series": series, "available": [f for f in data.files if f not in ("xs", "ys")]}

    # ── package ──
    def package(self, project: str, scenario: str, only: list[str] | None = None) -> bytes:
        out_dir, name = self.output_dir(project, scenario)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(out_dir.glob(f"{name}_*")):
                if f.suffix in (".npz",) or (only and f.name not in only):
                    continue
                zf.write(f, f.name)
        return buffer.getvalue()


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PitOptUI/0.4"

        def log_message(self, fmt, *args):            # quiet
            pass

        # ── helpers ──
        def _guard(self) -> bool:
            """Refuse requests a browser page on another site could send to this local server.

            The server has no login, so anything that can reach it can rename or delete projects. Two checks stop
            other websites from doing that: the Host header must be this machine (blocks DNS rebinding), and a
            state-changing request must carry a header only our own pages add (a cross-site page cannot send it
            without a CORS preflight, and the server never answers one), with a matching Origin when the browser
            sends one. Behind a reverse proxy, app.extra_hosts adds the public hostname(s) the proxy forwards as
            Host — the process still only binds to 127.0.0.1, so it's reachable solely through that proxy."""
            port = self.server.server_address[1]
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"} | app.extra_hosts
            if (self.headers.get("Host") or "") not in allowed:
                self._json({"error": "dilarang: host tidak dikenal"}, 403)
                return False
            if self.command == "POST":
                origin = self.headers.get("Origin")
                if origin and origin.split("://", 1)[-1] not in allowed:
                    self._json({"error": "dilarang: asal permintaan tidak dikenal"}, 403)
                    return False
                if self.headers.get("X-PitOpt") != "1" or self.headers.get("Sec-Fetch-Site") == "cross-site":
                    self._json({"error": "dilarang: permintaan tidak berasal dari aplikasi"}, 403)
                    return False
            return True

        def _json(self, payload, status: int = 200) -> None:
            body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path, download: str | None = None) -> None:
            if not path.is_file():
                self._json({"error": "tidak ditemukan"}, 404)
                return
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix == ".woff2":
                ctype = "font/woff2"
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{download}"')
            elif path.suffix in (".css", ".js", ".html"):
                self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            with open(path, "rb") as f:
                while chunk := f.read(1 << 16):
                    self.wfile.write(chunk)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= MAX_JSON_BODY:
                raise ValueError("JSON body must be at most 256 KiB")
            def invalid_constant(value):
                raise ValueError(f"non-finite JSON value: {value}")
            body = json.loads(self.rfile.read(length) or b"{}", parse_constant=invalid_constant)
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            return body

        def _upload(self, q: dict) -> dict:
            """Stream the request body to projects/<slug>/data/<file> (CSV block model or DXF/CSV topography)."""
            from . import onboard

            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_UPLOAD:
                raise ValueError(f"ukuran berkas harus 1 B – {MAX_UPLOAD // 2**30} GB")
            name = onboard.safe_name(q["name"])
            folder = app._inside(app.projects_dir / onboard.slugify(q["project"]) / "data")
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / name
            left = length
            with open(target, "wb") as f:
                while left:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        raise ValueError("unggahan terputus")
                    f.write(chunk)
                    left -= len(chunk)
            return {"file": target.name, "bytes": target.stat().st_size, "inspect": onboard.inspect_file(target)}

        def _design_get(self, route: str, q: dict):
            d, project, scenario = app.design, q.get("project", ""), q.get("scenario", "")
            if route == "blocks":
                return d.block_card(project, scenario)
            if route == "job":
                return d.job(q.get("id", ""), int(q.get("since", 0)))
            if route == "result":
                return d.result(project, scenario)
            if route == "plan":
                return d.plan(project, scenario, float(q["rl"]) if "rl" in q else None)
            if route == "section":
                return d.section(project, scenario, (float(q["x1"]), float(q["y1"])), (float(q["x2"]), float(q["y2"])))
            raise KeyError(f"rute desain tidak dikenal: {route}")

        def _design_post(self, route: str, body: dict):
            d, project, scenario = app.design, body.get("project", ""), body.get("scenario", "")
            if app.demo_mode and route in ("state", "run"):
                params = body.get("params") or {}
                if not isinstance(params, dict) or len(params) > 64:
                    raise ValueError("demo parameters must be an object with at most 64 fields")
                def bounded(value, key=""):
                    if isinstance(value, dict):
                        for k, v in value.items():
                            bounded(v, str(k))
                    elif isinstance(value, list):
                        if len(value) > 16:
                            raise ValueError("demo lists are limited to 16 items")
                        for item in value:
                            bounded(item, key)
                    elif isinstance(value, (int, float)) and not isinstance(value, bool):
                        if not math.isfinite(value) or abs(value) > 100000:
                            raise ValueError("demo numeric parameters are out of range")
                        if "angle" in key or key.endswith(("ira_max_deg", "osa_max_deg")):
                            if not 5 <= value <= 85:
                                raise ValueError("demo angles must be between 5 and 85 degrees")
                    elif isinstance(value, str) and len(value) > 256:
                        raise ValueError("demo text parameters are too long")
                for k, v in params.items():
                    bounded(v, k)
            if route == "state":
                return d.state(project, scenario, body.get("params"))
            if route == "run":
                job = d.start(project, scenario, body.get("params"))
                return {"job": job.id}
            if route == "cancel":
                job = d.cancel(body["id"])
                return {"id": job.id, "status": job.status}
            if route == "export":
                return {"files": d.export(project, scenario, body.get("kinds"))}
            raise KeyError(f"rute desain tidak dikenal: {route}")

        # ── routes ──
        def do_GET(self):                            # noqa: N802
            if not self._guard():
                return
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path == "/api/meta":
                    return self._json({"demo": app.demo_mode, "repo_url": DEMO_REPO_URL,
                                       "default_project": os.environ.get("PITOPT_DEFAULT_PROJECT") if app.demo_mode else None})
                if app.demo_mode and q.get("project") and q["project"] not in app.demo_projects:
                    return self._json({"error": "proyek tidak tersedia di demo publik"}, 404)
                if app.demo_mode and url.path in {"/api/package", "/api/delete-preview", "/api/inspect", "/api/uniques"}:
                    return self._json({"error": "endpoint dinonaktifkan di demo publik"}, 403)
                if url.path == "/api/projects":
                    return self._json(app.list_projects())
                if url.path == "/api/results":
                    path = app.results_path(q["project"], q["scenario"])
                    if not path or not path.exists():
                        return self._json({"error": "belum ada hasil untuk skenario ini"}, 404)
                    return self._file(path)
                if url.path == "/api/config":
                    raw, _ = app.load_raw(q["project"], q["scenario"])
                    return self._json({"raw": raw, **app.resolved(q["project"], q["scenario"])})
                if url.path == "/api/job":
                    job = app.jobs.get(q.get("id", ""))
                    if not job:
                        return self._json({"error": "job tidak ditemukan"}, 404)
                    return self._json(job.snapshot(int(q.get("since", 0))))
                if url.path == "/api/current-job":
                    job = app.running
                    return self._json(job.snapshot(int(q.get("since", 0))) if job else None)
                if url.path == "/api/inspect":
                    from . import onboard

                    path = app._inside(app.projects_dir / onboard.slugify(q["project"]) / "data" / onboard.safe_name(q["file"]))
                    return self._json(onboard.inspect_file(path))
                if url.path.startswith("/api/design/"):
                    return self._json(self._design_get(url.path[len("/api/design/"):], q))
                if url.path == "/api/blockmeta":
                    return self._json(app.block_meta(q["project"], q["scenario"]))
                if url.path == "/api/blockslice":
                    return self._json(app.block_slice(q["project"], q["scenario"], q["axis"], int(q["index"]), q["attr"]))
                if url.path == "/api/delete-preview":
                    return self._json(app.delete_preview(q["project"], q.get("scenario") or None))
                if url.path == "/api/uniques":
                    import pandas as pd

                    from . import onboard

                    path = app._inside(app.projects_dir / onboard.slugify(q["project"]) / "data" / onboard.safe_name(q["file"]))
                    col = pd.read_csv(path, usecols=[q["col"]])[q["col"]].astype(str)
                    counts = col.value_counts()
                    return self._json({"values": [{"value": k, "count": int(v)} for k, v in counts.head(60).items()], "total": int(len(counts))})
                if url.path == "/api/section":
                    layers = [s for s in q.get("layers", "").split(",") if s]
                    return self._json(app.section(
                        q["project"], q["scenario"], (float(q["x1"]), float(q["y1"])), (float(q["x2"]), float(q["y2"])), layers))
                if url.path == "/api/runlog":
                    out_dir, name = app.output_dir(q["project"], q["scenario"])
                    log = out_dir / f"{name}_run.log"
                    return self._json({"log": log.read_text().splitlines() if log.exists() else []})
                if url.path == "/api/download":
                    out_dir, name = app.output_dir(q["project"], q["scenario"])
                    target = app._inside(out_dir / Path(q["file"]).name)
                    return self._file(target, download=target.name)
                if url.path == "/api/package":
                    only = [f for f in q.get("files", "").split(",") if f] or None
                    data = app.package(q["project"], q["scenario"], only)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Content-Disposition", f'attachment; filename="{q["scenario"]}_paket.zip"')
                    self.end_headers()
                    return self.wfile.write(data)
                if url.path == "/static/vendor/plotly.min.js":
                    import plotly

                    return self._file(Path(plotly.__file__).parent / "package_data" / "plotly.min.js")
                if url.path in ("/", "/index.html"):
                    return self._file(STATIC / "index.html")
                if url.path.startswith("/static/"):
                    target = (STATIC / url.path[len("/static/"):]).resolve()
                    if STATIC.resolve() not in target.parents:
                        return self._json({"error": "dilarang"}, 403)
                    return self._file(target)
                return self._json({"error": "tidak ditemukan"}, 404)
            except (KeyError, ValueError) as exc:
                return self._json({"error": f"permintaan tidak valid: {exc}"}, 400)
            except FileNotFoundError as exc:
                return self._json({"error": f"tidak ditemukan: {exc}"}, 404)
            except PermissionError as exc:
                return self._json({"error": str(exc)}, 403)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:                  # noqa: BLE001 — never leave the browser with an empty reply
                traceback.print_exc()
                return self._json({"error": f"kesalahan server: {type(exc).__name__}: {exc}"}, 500)

        def do_POST(self):                           # noqa: N802
            if not self._guard():
                return
            url = urlparse(self.path)
            if app.demo_mode and url.path not in DEMO_ALLOWED_POSTS:
                return self._json({"error": f"demo publik ini hanya baca untuk fitur ini — clone dan jalankan sendiri: {DEMO_REPO_URL}"}, 403)
            try:
                if url.path == "/api/upload":               # raw body, must not be parsed as JSON
                    return self._json(self._upload({k: v[0] for k, v in parse_qs(url.query).items()}))
                body = self._body()
                if app.demo_mode and url.path in {"/api/design/state", "/api/design/run", "/api/design/cancel"}:
                    if url.path != "/api/design/cancel" and body.get("project") not in app.demo_projects:
                        return self._json({"error": "proyek tidak tersedia di demo publik"}, 404)
                    if url.path == "/api/design/cancel":
                        job = app.design.jobs.get(body.get("id", ""))
                        if job is None or job.project not in app.demo_projects:
                            return self._json({"error": "job tidak ditemukan"}, 404)
                if url.path == "/api/run":
                    job = app.start_run(body["project"], body["scenario"], body.get("overrides") or {}, body.get("save_as") or None)
                    return self._json({"job": job.id, "scenario": job.scenario})
                if url.path.startswith("/api/design/"):
                    return self._json(self._design_post(url.path[len("/api/design/"):], body))
                if url.path == "/api/cancel":
                    job = app.cancel_job(body["id"])
                    return self._json({"id": job.id, "status": job.status})
                if url.path == "/api/rename":
                    return self._json(app.rename(body["project"], body.get("scenario") or None, body["name"]))
                if url.path == "/api/delete":
                    return self._json(app.delete(body["project"], body.get("scenario") or None, body.get("confirm", "")))
                if url.path == "/api/reblock":
                    from . import onboard

                    folder = app._inside(app.projects_dir / onboard.slugify(body["project"]) / "data")
                    return self._json(onboard.reblock_file(folder, body))
                if url.path == "/api/create-project":
                    return self._json(app.create_project(body))
                if url.path == "/api/derive":
                    return self._json(app.resolved(body["project"], body["scenario"], body.get("overrides") or {}))
                if url.path == "/api/save":
                    slug = app.save_scenario(body["project"], body["scenario"], body.get("overrides") or {}, body["save_as"])
                    return self._json({"scenario": slug})
                if url.path == "/api/validate":
                    from ..config import ProjectConfig

                    raw, yml = app.load_raw(body["project"], body["scenario"])
                    raw = app._apply(raw, body.get("overrides") or {})
                    tmp = yml.parent / f".validate_{uuid.uuid4().hex[:6]}.yaml"
                    try:
                        tmp.write_text(yaml.safe_dump(raw, sort_keys=False))
                        ProjectConfig.from_yaml(str(tmp))
                    finally:
                        tmp.unlink(missing_ok=True)
                    return self._json({"ok": True})
                return self._json({"error": "tidak ditemukan"}, 404)
            except RuntimeError as exc:
                return self._json({"error": str(exc)}, 409)
            except (KeyError, ValueError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)
            except FileNotFoundError as exc:
                return self._json({"error": f"tidak ditemukan: {exc}"}, 404)
            except PermissionError as exc:
                return self._json({"error": str(exc)}, 403)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:                  # noqa: BLE001 — never leave the browser with an empty reply
                traceback.print_exc()
                return self._json({"error": f"kesalahan server: {type(exc).__name__}: {exc}"}, 500)

    return Handler


def serve(root: str = ".", port: int = 8765, open_browser: bool = True, public_host: str | None = None,
          demo: bool | None = None) -> None:
    """public_host: comma-separated hostname(s) (no scheme/port) a reverse proxy in front of this
    process forwards as Host — e.g. "pitopt.orebit.id". Falls back to the PITOPT_PUBLIC_HOST env
    var. The process still binds only to 127.0.0.1; this just tells _guard which Host/Origin headers
    the proxy is expected to present.

    demo: read-only public showcase — every POST is refused except the bench-design screens (see
    DEMO_ALLOWED_POSTS), and the front end shows a synthetic-demo disclosure banner. Falls back to
    the PITOPT_DEMO env var (any non-empty value means true)."""
    public_host = public_host or os.environ.get("PITOPT_PUBLIC_HOST", "")
    extra_hosts = frozenset(h.strip() for h in public_host.split(",") if h.strip())
    demo_mode = bool(os.environ.get("PITOPT_DEMO")) if demo is None else demo
    app = App(Path(root), extra_hosts=extra_hosts, demo_mode=demo_mode)
    if not app.projects_dir.is_dir():
        raise SystemExit(f"no projects/ folder under {app.root}")
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    url = f"http://127.0.0.1:{port}/"
    print(f"PitOpt UI  {url}   (root {app.root})   Ctrl+C to stop" + ("   [DEMO — read-only]" if demo_mode else ""))
    if open_browser:
        import webbrowser

        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
