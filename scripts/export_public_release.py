#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Orebit (Ghozian Islam Karami)
"""Export a clean public snapshot of PitOpt's tracked source to a target folder.

Only git-tracked files are copied. Internal agent-orchestration files, handover
notes and private audit records are excluded, and the export is verified before
the script reports success.

Usage:
    python3 scripts/export_public_release.py /path/to/empty/target
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Paths (files or directory prefixes, repo-relative, POSIX) kept out of the public snapshot.
EXCLUDED_EXACT = {
    "AGENTS.md",
    "CLAUDE.md",
    "STANDARDS.md",
    "docs/PLAN-pitopt.md",
    "docs/README.md",
    "docs/SPEC.md",
    "docs/FOUNDATION_AUDIT_2026-10-13.md",
    "docs/HANDOVER_CREDIBILITY_USABILITY.md",
    "docs/PR_CREDIBILITY_USABILITY.md",
    "docs/RELEASE_HANDOFF_P1_P6.md",
    "docs/LOCAL_DEPLOYMENT.md",
}
EXCLUDED_PREFIXES = (
    "ops/",
    "docs/archive/",
    "docs/handover/",
    ".tmp-tier-receipts/",
    "public-release/",
    "Asset Social Media/",
    "outputs/",
    "build/",
    "dist/",
)
# Any path segment matching these is excluded wherever it appears.
EXCLUDED_SEGMENTS = {".venv", "__pycache__", ".pytest_cache", ".pytest_runs"}


def is_excluded(rel: str) -> bool:
    if rel in EXCLUDED_EXACT or rel.startswith(EXCLUDED_PREFIXES):
        return True
    return bool(set(Path(rel).parts) & EXCLUDED_SEGMENTS)


def tracked_files(root: Path) -> list[str]:
    raw = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout
    return [p for p in raw.decode("utf-8", errors="surrogateescape").split("\0") if p]


def export(root: Path, target: Path) -> list[str]:
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"FAIL: target is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for rel in tracked_files(root):
        if is_excluded(rel):
            continue
        source = root / rel
        if source.is_symlink() or not source.is_file():
            continue  # symlinks and submodules are never published
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        copied.append(rel)
    return copied


def verify(target: Path) -> list[str]:
    problems = []
    for path in target.rglob("*"):
        rel = path.relative_to(target).as_posix()
        if path.is_file() and is_excluded(rel):
            problems.append(f"internal file leaked: {rel}")
    for required in ("README.md", "LICENSE", "pyproject.toml"):
        if not (target / required).is_file():
            problems.append(f"missing required file: {required}")
    readme = (target / "README.md").read_text(encoding="utf-8", errors="replace")
    for phrase in ("private development workspace", "research prototype"):
        if phrase in readme.lower():
            problems.append(f"README contains internal wording: {phrase!r}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", type=Path, help="empty directory to receive the public snapshot")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    target = args.target.resolve()
    if target == root or root in target.parents:
        raise SystemExit("FAIL: target must be outside the working repository")

    copied = export(root, target)
    problems = verify(target)
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"Exported {len(copied)} files to {target}")
    print("Public snapshot verified: no internal agent files, README is product copy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
