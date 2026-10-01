"""
Reader for self-describing fixed-width ASCII tables (".DAT").

This is the plain-text interchange several packages write (Micromine
exports, ArcGIS/MapInfo attribute dumps): a blank line, "<n> VARIABLES",
then one line per field — name, type (N numeric, C character, an optional
"*" flag), width, decimals — then the data in fixed-width columns:

    12  VARIABLES
    EAST      N 11  3
    DOMAIN    C 20  0
    % ZIRCON  N 22  4

The header carries the column widths, so nothing has to be counted by
hand; a file from a different export reads the same way.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

_HEADER = re.compile(r"^\s*(\d+)\s+VARIABLES\s*$", re.IGNORECASE)


@dataclass
class DatField:
    name: str
    kind: str      # "N" numeric or "C" character
    width: int
    decimals: int


def read_header(path: str) -> tuple[list[DatField], int]:
    """Field list and the number of lines before the data starts."""
    with open(path, errors="replace") as f:
        lines = [f.readline() for _ in range(400)]
    for start, line in enumerate(lines):  # noqa: B007 — `start` is read after the loop
        match = _HEADER.match(line.rstrip("\r\n"))
        if match:
            count = int(match.group(1))
            break
    else:
        raise ValueError(f"{path}: no '<n> VARIABLES' header — not a self-describing .DAT table")

    fields = []
    for line in lines[start + 1: start + 1 + count]:
        line = line.rstrip("\r\n")
        name = line[:10].replace("*", "").strip()
        rest = line[10:].replace("*", " ").split()
        if len(rest) < 2:
            raise ValueError(f"{path}: cannot read field definition {line!r}")
        kind = rest[0].upper()
        width = int(rest[1])
        decimals = int(rest[2]) if len(rest) > 2 else 0
        fields.append(DatField(name, kind, width, decimals))
    return fields, start + 1 + count


def clean_names(raw: list[str]) -> list[str]:
    """'% ZIRCON' -> 'ZIRCON', 'Shape Leng' -> 'Shape_Leng'. Underscores the
    exporter wrote are kept ('_EAST' is Micromine's block-size field, not a
    second EAST); anything still clashing gets a numeric suffix."""
    names, seen = [], set()
    for i, name in enumerate(raw):
        clean = re.sub(r"^[^0-9A-Za-z_]+|[^0-9A-Za-z_]+$", "", name.strip())
        clean = re.sub(r"[^0-9A-Za-z_]+", "_", clean) or f"FIELD{i}"
        base, n = clean, 2
        while clean in seen:
            clean, n = f"{base}_{n}", n + 1
        seen.add(clean)
        names.append(clean)
    return names


def read_dat(path: str, chunksize: int | None = None, usecols: list[str] | None = None):
    """Read the table (or an iterator of chunks). Column names come from the
    header (see clean_names)."""
    fields, skip = read_header(path)
    names = clean_names([f.name for f in fields])
    dtypes = {n: (str if f.kind == "C" else float) for n, f in zip(names, fields)}
    return pd.read_fwf(
        path,
        widths=[f.width for f in fields],
        names=names,
        skiprows=skip,
        dtype=dtypes,
        chunksize=chunksize,
        usecols=usecols,
    )
