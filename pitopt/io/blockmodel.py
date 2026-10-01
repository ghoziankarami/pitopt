"""
Block model CSV I/O.

Column names are supplied by config rather than assumed, so exports from
Surpac, Datamine, Vulcan, GEMS, Leapfrog or a hand-built CSV all load
without renaming anything first. Coordinates must be block centroids —
the usual export convention; shift by half a block if yours are corners.

Two filters live here because they are resource-model decisions, not
optimisation ones:

- `include_classes` lists the confidence categories that may be
  *processed*. Reporting codes (JORC, KCMI, NI 43-101) do not let
  Inferred material carry a reserve, so it earns no revenue. It is not
  deleted, though: the ground is still there, and where it lies inside the
  pit or its slope it has to be dug and paid for like any other waste.
  Deleting it would let the pit strip it for free and cut walls straight
  through it.
- `ore_domains` marks which geological domains may be routed to the plant.
  Overburden and bedrock are not feed whatever they assay.
"""
from __future__ import annotations

import pandas as pd

from ..config import BlockModelConfig, EconomicsConfig


def load_block_model(cfg: BlockModelConfig, econ: EconomicsConfig | None = None) -> pd.DataFrame:
    raw = pd.read_csv(cfg.path)

    grade_columns = [p.grade_col for p in econ.products] if econ else []
    if cfg.grade_col and cfg.grade_col not in grade_columns:
        grade_columns.append(cfg.grade_col)

    required = {"x": cfg.x_col, "y": cfg.y_col, "z": cfg.z_col}
    missing = [src for src in list(required.values()) + grade_columns if src not in raw.columns]
    if missing:
        raise ValueError(
            f"Column(s) {missing} not found in {cfg.path}. Available columns: {list(raw.columns)}"
        )

    df = pd.DataFrame({name: raw[src].astype(float) for name, src in required.items()})
    for column in grade_columns:
        df[column] = raw[column].astype(float).fillna(0.0)

    for name, col, default in (
        ("dx", cfg.dx_col, cfg.dx),
        ("dy", cfg.dy_col, cfg.dy),
        ("dz", cfg.dz_col, cfg.dz),
        ("density", cfg.density_col, cfg.density),
    ):
        df[name] = raw[col].astype(float) if col and col in raw.columns else default

    if cfg.volume_col and cfg.volume_col in raw.columns:
        df["volume"] = raw[cfg.volume_col].astype(float)
        nominal = (df["dx"] * df["dy"] * df["dz"]).to_numpy()
        if (df["volume"].to_numpy() > nominal * 1.001).any():
            raise ValueError(
                f"{cfg.volume_col} exceeds the nominal block volume for some blocks — "
                "a block cannot hold more material than its own cell."
            )

    if cfg.domain_col and cfg.domain_col in raw.columns:
        df["domain"] = raw[cfg.domain_col].astype(str)
    if cfg.class_col and cfg.class_col in raw.columns:
        df["resource_class"] = raw[cfg.class_col].astype(str)

    processable = pd.Series(True, index=df.index)
    if cfg.include_classes:
        if "resource_class" not in df.columns:
            raise ValueError("block_model.include_classes is set but no class_col was supplied or found.")
        in_class = df["resource_class"].isin(cfg.include_classes)
        if not in_class.any():
            raise ValueError(
                f"No blocks in classes {cfg.include_classes}. "
                f"Available: {sorted(df['resource_class'].unique())}"
            )
        processable &= in_class
        df.attrs["classes_as_waste"] = int((~in_class).sum())

    if cfg.ore_domains and "domain" in df.columns:
        processable &= df["domain"].isin(cfg.ore_domains)
    df["is_ore_domain"] = processable.to_numpy()

    invalid = df[["dx", "dy", "dz", "density"]].le(0).any(axis=1)
    if invalid.any():
        raise ValueError(f"{int(invalid.sum())} blocks have non-positive block size or density.")

    return df.reset_index(drop=True)


def write_block_model(df: pd.DataFrame, path: str) -> None:
    """Write the solved model back out as CSV, keeping the reporting
    columns a planner needs downstream (shell index, destination, value)."""
    leading = [
        "x", "y", "z", "dx", "dy", "dz", "density", "domain", "resource_class",
        "bench", "volume", "rock_tonnes", "ore_tonnes", "destination",
        "revenue", "value_ore", "value_waste", "value", "shell", "pushback", "period", "in_pit",
    ]
    present = [c for c in leading if c in df.columns]
    extra = [c for c in df.columns if c not in present and c not in ("gi", "gj", "is_ore_domain")]
    df[present + extra].to_csv(path, index=False)
