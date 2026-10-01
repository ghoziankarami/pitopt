"""
Bringing your own data into the UI: inspect an uploaded file, guess the column
mapping, and write a project.yaml the engine can run.

Nothing here invents a value. Column guesses are only suggestions the user
confirms; block size comes from the coordinates or from size columns; every
parameter the user did not touch is recorded in `provenance` as an assumption.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ALLOWED = {".csv", ".dxf"}

# Column names as the common packages export them (normalised: lower case, punctuation dropped, a leading
# underscore kept). Datamine XC/XINC, Surpac x_centre/dim_x, Vulcan centroid_x, Leapfrog X/size_x, Deswik
# XC/XSIZE, GEMS XCENTER, Micromine EAST/_EAST — where the leading underscore is what marks the block *size*
# field, so it must survive normalisation or "_EAST" would be taken for the easting.
_GUESS = {
    "x": ("x", "east", "easting", "xc", "xcentre", "xcentroid", "centroidx", "xm", "xcenter", "centrex", "centerx", "midx"),
    "y": ("y", "north", "northing", "yc", "ycentre", "ycentroid", "centroidy", "ym", "ycenter", "centrey", "centery", "midy"),
    "z": ("z", "rl", "elev", "elevation", "level", "zc", "zcentre", "zcentroid", "centroidz", "zm", "zcenter", "centrez",
          "centerz", "midz"),
    "dx": ("dx", "xinc", "xsize", "sizex", "sx", "dimx", "xdim", "_east", "_x", "xblocksize", "blocksizex", "xlength"),
    "dy": ("dy", "yinc", "ysize", "sizey", "sy", "dimy", "ydim", "_north", "_y", "yblocksize", "blocksizey", "ylength"),
    "dz": ("dz", "zinc", "zsize", "sizez", "sz", "dimz", "zdim", "_rl", "_z", "zblocksize", "blocksizez", "zlength"),
    "density": ("density", "dens", "sg", "bd", "bulkdensity", "specificgravity", "drydensity", "insitudensity"),
    "domain": ("domain", "zone", "geozone", "lith", "litho", "lithology", "rocktype", "rock", "geology", "geocode", "unit",
               "estdomain", "weathering"),
    "class": ("class", "category", "resclass", "resourceclass", "rescat", "resource", "classification", "jorc", "confidence",
              "rescategory"),
}


def safe_name(name: str) -> str:
    base = re.sub(r"[^0-9A-Za-z._-]+", "_", Path(name).name).strip("._")
    if not base or Path(base).suffix.lower() not in ALLOWED:
        raise ValueError(f"jenis berkas tidak diterima (pakai {', '.join(sorted(ALLOWED))}): {name}")
    return base


def slugify(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_-]+", "_", text.strip()).strip("_").lower()
    if not slug:
        raise ValueError("nama proyek kosong")
    return slug


def _normal(column: str) -> str:
    """Lower case, punctuation dropped — but a leading underscore kept (see _GUESS)."""
    name = column.strip()
    return ("_" if name.startswith("_") else "") + re.sub(r"[^a-z0-9]", "", name.lower())


def _match(columns: list[str], names: tuple) -> str | None:
    """The first column whose normalised name is in `names`, trying the names in order of preference. Only a
    suggestion: the wizard shows it and the user confirms or picks another, so any column name works."""
    norm: dict[str, str] = {}
    for column in columns:
        norm.setdefault(_normal(column), column)           # the first of two columns that normalise alike wins
    for name in names:
        if name in norm:
            return norm[name]
    return None


def _spacing(values: np.ndarray) -> tuple[float | None, bool]:
    """Smallest coordinate step and whether the centres sit on one regular lattice."""
    u = np.unique(np.round(values, 6))
    if len(u) < 2:
        return None, True
    step = float(np.min(np.diff(u)))
    if step <= 0:
        return None, True
    frac = np.abs(((u - u[0]) / step) - np.round((u - u[0]) / step))
    return step, bool((frac < 0.02).mean() > 0.98)


def inspect_csv(path: Path) -> dict:
    head = pd.read_csv(path, nrows=8)
    columns = list(head.columns)
    numeric = [c for c in columns if pd.api.types.is_numeric_dtype(head[c])]
    guess = {k: _match(columns, v) for k, v in _GUESS.items()}
    coords = [guess[k] for k in ("x", "y", "z")]
    info: dict = {"kind": "block_model", "columns": columns, "numeric": numeric, "guess": guess,
                  "preview": head.head(5).astype(object).where(head.head(5).notna(), None).values.tolist(), "warnings": []}
    if not all(coords):
        info["warnings"].append("Kolom koordinat X/Y/Z tidak terdeteksi otomatis — pilih manual.")
        info["rows"] = int(sum(1 for _ in open(path, "rb")) - 1)
        return info

    xyz = pd.read_csv(path, usecols=coords)
    info["rows"] = int(len(xyz))
    info["extent"] = {k: [float(xyz[c].min()), float(xyz[c].max())] for k, c in zip("xyz", coords)}
    size, regular = {}, True
    for k, c in zip("xyz", coords):
        s, ok = _spacing(xyz[c].to_numpy())
        size[k], regular = s, regular and ok
    info["spacing"] = size
    info["regular"] = regular
    if not regular:
        info["warnings"].append("Pusat blok tidak berada pada satu kisi reguler (sub-cell atau ukuran campuran). "
                                "Jalankan reblock lebih dulu supaya precedence lereng benar.")
    size_cols = [guess[k] for k in ("dx", "dy", "dz") if guess[k]]
    if size_cols:
        sizes = pd.read_csv(path, usecols=size_cols)
        if any(sizes[c].nunique() > 1 for c in size_cols):
            info["regular"] = False
            info["variable_size"] = True
            info["warnings"].append("Ukuran blok tidak seragam (model sub-cell): jalankan reblock ke satu ukuran penambangan sebelum optimasi.")
    if xyz.duplicated().any():
        info["warnings"].append("Ada koordinat blok ganda.")
    others = [c for c in numeric if c not in coords and c not in [guess[k] for k in ("dx", "dy", "dz")]]
    if others:
        table = pd.read_csv(path, usecols=others)
        info["stats"] = {c: [float(table[c].min()), float(table[c].max())] for c in others}
    return info


def inspect_surface(path: Path) -> dict:
    if path.suffix.lower() == ".dxf":
        from ..io.dxf import read_surface_points

        pts = read_surface_points(str(path))
        if not len(pts):
            raise ValueError("DXF tidak berisi 3DFACE/MESH/POLYLINE/POINT dengan koordinat XYZ.")
        warnings = []
        if np.all(pts[:, 2] == 0.0):
            warnings.append("Semua elevasi di DXF bernilai 0 — kontur 2D yang kehilangan elevasinya? Periksa sebelum "
                            "dipakai; permukaan datar di RL 0 akan memotong model di elevasi itu.")
        return {"kind": "surface", "format": "dxf", "points": int(len(pts)), "warnings": warnings,
                "extent": {k: [float(pts[:, i].min()), float(pts[:, i].max())] for i, k in enumerate("xyz")}}
    df = pd.read_csv(path, nrows=5)
    cols = list(df.columns)
    guess = {k: _match(cols, _GUESS[k]) for k in "xyz"}
    return {"kind": "surface", "format": "csv", "columns": cols, "guess": guess}


def inspect_file(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".dxf":
        return inspect_surface(path)
    info = inspect_csv(path)
    # a small three-column CSV is a topography, not a block model
    if len(info["columns"]) <= 4 and info.get("guess", {}).get("x") and info["guess"].get("z") and info["rows"] > 0 and not info["numeric"][3:]:
        return {**info, "kind": "surface_csv"}
    return info


def reblock_file(folder: Path, spec: dict) -> dict:
    """Regularise an uploaded sub-celled / non-uniform CSV onto mining blocks (see core.reblock for the rules).

    Writes `<name>_reblocked_blocks.csv` next to the source and returns the reconciliation the user must
    check (volume in vs out, blocks, weighting) plus the inspection of the new file."""
    from ..core.reblock import ReblockSpec, reblock, write_outputs

    source = folder / safe_name(spec["file"])
    if source.suffix.lower() != ".csv":
        raise ValueError("reblock hanya untuk model blok CSV")
    header = list(pd.read_csv(source, nrows=0).columns)

    def column(key: str, required: bool = True) -> str | None:
        name = spec.get(key) or None
        if name is None and required:
            raise ValueError(f"kolom {key} wajib dipilih")
        if name is not None and name not in header:
            raise ValueError(f"kolom tidak ada di berkas: {name}")
        return name

    size_cols = [column(k, required=False) for k in ("size_x", "size_y", "size_z")]
    parent = spec.get("parent")
    if not all(size_cols):
        size_cols = [None, None, None]
        if not parent or len(parent) != 3 or not all(float(v) > 0 for v in parent):
            raise ValueError("isi ukuran parent block (dx, dy, dz) atau pilih kolom ukuran blok")
    target = tuple(float(v) for v in spec.get("target") or ())
    if len(target) != 3 or not all(v > 0 for v in target):
        raise ValueError("ukuran blok target (dx, dy, dz) harus > 0")
    grades = [g for g in (spec.get("grades") or []) if g in header]
    categories = [c for c in (spec.get("categories") or []) if c in header]
    density = column("density", required=False)
    x, y, z = column("x"), column("y"), column("z")
    normalise = {c: r"\d+$" for c in categories if c in (spec.get("strip_digits") or [])}
    rspec = ReblockSpec(
        source=str(source), x=x, y=y, z=z,
        size_x=size_cols[0], size_y=size_cols[1], size_z=size_cols[2],
        parent=tuple(float(v) for v in parent) if parent and not all(size_cols) else None,
        grades=grades, categories=categories, density=density, target=target, normalise=normalise,
    )
    blocks, summary = reblock(rspec)
    name = f"{source.stem}_reblocked"
    written = write_outputs(blocks, rspec, str(folder), name, surface=False)
    table = summary["source_volume_by_category"]
    result_file = Path(written["blocks"])
    return {
        "file": result_file.name,
        "blocks": int(summary["blocks"]),
        "source_volume": float(summary["source_volume"]),
        "output_volume": float(summary["output_volume"]),
        "volume_difference": float(summary["output_volume"] - summary["source_volume"]),
        "parent_size": summary["parent_size"],
        "origin": summary["origin"],
        "grade_weighting": summary["grade_weighting"],
        "partial_fill_below_half": float((blocks["FILL"] < 0.5).mean()),
        "by_category": (table.reset_index().rename(columns={"volume": "volume_m3"}).to_dict("records") if table is not None else []),
        "columns": {"x": x, "y": y, "z": z, "density": density, "grades": grades, "categories": categories, "volume": "volume"},
        "inspect": inspect_file(result_file),
    }


DEFAULT_RFS = [round(0.4 + 0.05 * i, 2) for i in range(17)]          # 0.40 … 1.20


def build_project(spec: dict) -> tuple[str, dict]:
    """Project slug and the YAML dictionary for a wizard spec. Raises ValueError with a readable message."""
    title = (spec.get("title") or "").strip()
    slug = slugify(spec.get("slug") or title)
    bm, eco = spec.get("block_model") or {}, spec.get("economics") or {}
    touched = set(spec.get("touched") or [])
    for key in ("file", "x_col", "y_col", "z_col"):
        if not bm.get(key):
            raise ValueError(f"block_model.{key} wajib diisi")
    products = eco.get("products") or []
    if not products:
        raise ValueError("Minimal satu produk (kolom kadar + harga) wajib diisi")

    block: dict = {"path": f"data/{bm['file']}", "x_col": bm["x_col"], "y_col": bm["y_col"], "z_col": bm["z_col"]}
    for k in ("dx", "dy", "dz"):
        if bm.get(f"{k}_col"):
            block[f"{k}_col"] = bm[f"{k}_col"]
        else:
            if not bm.get(k):
                raise ValueError(f"Ukuran blok {k} wajib diisi (tidak ada kolom {k})")
            block[k] = float(bm[k])
    if bm.get("density_col"):
        block["density_col"] = bm["density_col"]
    else:
        block["density"] = float(bm.get("density") or 0) or _fail("Densitas (t/m³) wajib diisi bila tidak ada kolom densitas")
    for k in ("domain_col", "class_col"):
        if bm.get(k):
            block[k] = bm[k]
    if bm.get("volume_col"):
        block["volume_col"] = bm["volume_col"]              # reblocked models carry partly filled edge cells
    for k in ("include_classes", "ore_domains"):
        if bm.get(k):
            block[k] = list(bm[k])

    prods = []
    for p in products:
        if not p.get("name") or not p.get("grade_col") or not float(p.get("price") or 0) > 0:
            raise ValueError("Tiap produk butuh nama, kolom kadar, dan harga > 0")
        prods.append({"name": str(p["name"]).strip(), "grade_col": p["grade_col"], "price": float(p["price"]),
                      "price_unit": p.get("price_unit", "t"), "plant_recovery": float(p.get("plant_recovery", 1.0)),
                      "processing_cost_per_tonne": float(p.get("processing_cost_per_tonne", 0.0)),
                      "selling_cost_per_tonne": float(p.get("selling_cost_per_tonne", 0.0))})
        if p.get("density"):
            prods[-1]["density"] = float(p["density"])

    economics = {"grade_basis": eco.get("grade_basis", "mass_percent")}
    for k in ("mining_recovery", "dilution", "royalty_rate", "mining_cost_per_tonne", "mining_cost_per_volume",
              "processing_cost_per_tonne", "rehabilitation_cost_per_tonne"):
        if eco.get(k) not in (None, ""):
            economics[k] = float(eco[k])
    economics["products"] = prods

    if not spec.get("capacity") and not spec.get("periods"):
        raise ValueError("Isi kapasitas umpan (t/periode) atau umur tambang (jumlah periode) — salah satu wajib untuk jadwal")
    schedule: dict = {"enabled": True, "discount_rate": float(spec.get("discount_rate", 0.10))}
    if spec.get("capacity"):
        schedule["ore_capacity"] = float(spec["capacity"])
    else:
        schedule["periods"] = int(spec["periods"])

    cfg: dict = {
        "project": {"name": slug, "title": title or slug, "scenario": "Dasar", "order": 50},
        "block_model": block,
        "economics": economics,
        "slope": {"overall_angle_deg": float(spec.get("slope_angle", 45))},
        "shells": {"revenue_factors": DEFAULT_RFS},
        "final_pit": {"criterion": "average", "tolerance": 0.01},
        "pushbacks": {"method": spec.get("pushback_method", "shells")},
        "schedule": schedule,
        "sensitivity": {"enabled": True},
        "output": {"directory": f"../../outputs/{slug}"},
    }
    if (spec.get("surface") or {}).get("file"):
        s = spec["surface"]
        cfg["surface"] = {"path": f"data/{s['file']}", "format": s.get("format", "dxf")}
        if s.get("format") == "csv":
            cfg["surface"].update({"x_col": s["x_col"], "y_col": s["y_col"], "z_col": s["z_col"]})
    bench = float(spec.get("bench_height") or (block.get("dz") or 0) or 0)
    if bench > 0:
        cfg["design"] = {"bench_height": bench, "bench_face_angle_deg": float(spec.get("bench_face_angle", 65))}

    labels = {"slope_angle": "slope.overall_angle_deg", "capacity": "schedule.ore_capacity", "periods": "schedule.periods", "discount_rate": "schedule.discount_rate",
              "bench_height": "design.bench_height", "bench_face_angle": "design.bench_face_angle_deg",
              "mining_recovery": "economics.mining_recovery", "dilution": "economics.dilution",
              "density": "block_model.density", "mining_cost_per_tonne": "economics.mining_cost_per_tonne",
              "processing_cost_per_tonne": "economics.processing_cost_per_tonne"}
    prov = {}
    for key, path in labels.items():
        if key in touched:
            prov[path] = {"source": "input", "ref": "Wizard proyek baru", "note": "Diisi pengguna saat membuat proyek."}
        elif key == "capacity" and not spec.get("capacity") or key == "periods" and not spec.get("periods"):
            continue
        elif not (key in ("bench_height",) and not bench):
            prov[path] = {"source": "asumsi", "ref": "Wizard proyek baru",
                          "note": "Nilai bawaan wizard, belum dikonfirmasi pengguna. Ganti dengan angka studi."}
    for p in prods:
        base = f"economics.products.{p['name']}"
        prov[f"{base}.price"] = {"source": "input", "ref": "Wizard proyek baru", "note": "Harga diisi pengguna."}
    cfg["provenance"] = prov
    return slug, cfg


def _fail(msg: str):
    raise ValueError(msg)


def write_project(projects_dir: Path, slug: str, cfg: dict) -> Path:
    folder = projects_dir / slug
    (folder / "data").mkdir(parents=True, exist_ok=True)
    target = folder / "project.yaml"
    if target.exists():
        raise ValueError(f"Proyek '{slug}' sudah ada — pakai nama lain.")
    target.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    return target
