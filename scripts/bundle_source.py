"""
Concatenate the whole system — package, scripts, configs, docs — into one
Markdown file, so the complete source can be handed to a fresh session or
a reviewer as a single attachment.

Data files are listed but not inlined: the block models run to hundreds of
megabytes, and client data (projects/*/raw/) should not travel with a code
bundle.

Usage:
    python scripts/bundle_source.py            # -> dist/pitopt_source_bundle.md
"""
from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "dist" / "pitopt_source_bundle.md"

INCLUDE = [
    "README.md",
    "docs/PRD.md",
    "pyproject.toml",
    "Makefile",
    ".gitignore",
]
INCLUDE_GLOBS = ["pitopt/**/*.py", "scripts/*.py", "scripts/*.sh", "tests/*.py", "pitopt/ui/static/**/*.js", "pitopt/ui/static/css/*.css", "pitopt/ui/static/index.html", "projects/**/*.yaml", "projects/**/README.md", "benchmarks/**/README.md"]
LANGUAGE = {".py": "python", ".yaml": "yaml", ".toml": "toml", ".md": "markdown", ".txt": "text", "": "makefile", ".js": "javascript", ".css": "css", ".html": "html", ".sh": "bash"}


def main() -> None:
    files = [ROOT / f for f in INCLUDE if (ROOT / f).exists()]
    for pattern in INCLUDE_GLOBS:
        files += sorted(p for p in ROOT.glob(pattern) if "__pycache__" not in p.parts)
    seen, ordered = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            ordered.append(f)

    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ""

    lines = [
        "# pitopt — full source bundle",
        "",
        f"Generated {date.today().isoformat()}" + (f" from commit {commit}" if commit else "") + ".",
        "",
        "## Files",
        "",
    ]
    lines += [f"- `{f.relative_to(ROOT)}` ({f.stat().st_size:,} bytes)" for f in ordered]
    lines += ["", "## Data (not inlined)", ""]
    for folder in ("projects", "benchmarks"):
        for f in sorted((ROOT / folder).rglob("*")):
            if f.is_file() and "Zone.Identifier" not in f.name and "raw" not in f.parts and "data" not in f.parts:
                lines.append(f"- `{f.relative_to(ROOT)}` ({f.stat().st_size:,} bytes)")

    for f in ordered:
        fence = "````" if f.suffix == ".md" else "```"
        lines += ["", f"## `{f.relative_to(ROOT)}`", "", f"{fence}{LANGUAGE.get(f.suffix, '')}", f.read_text().rstrip(), fence]

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text("\n".join(lines) + "\n")
    print(f"Bundled {len(ordered)} files -> {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
