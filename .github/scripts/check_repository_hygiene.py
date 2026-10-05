#!/usr/bin/env python3
"""Check tracked source boundaries without printing credential values."""
import argparse
import re
import subprocess
from pathlib import Path

PRIVATE_KEY = re.compile(
    rb"(?m)^-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----\s*$"
)
LOCAL_DIRS = {"node_modules", ".venv", "__pycache__"}
OUTPUT_ROOTS = {"dist", ".next", "coverage", "test-results", "playwright-report"}
CREDENTIAL_FILES = {".netrc", ".npmrc", "id_rsa", "id_ed25519", "credentials.json"}


def check(root):
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout.split(b"\0")
    problems = []
    for raw in tracked:
        if not raw:
            continue
        name = raw.decode("utf-8", errors="surrogateescape")
        path = Path(name)
        parts = set(path.parts)
        reason = None
        if parts & LOCAL_DIRS or path.parts[0] in OUTPUT_ROOTS:
            reason = "local dependencies or generated output"
        elif path.name in CREDENTIAL_FILES:
            reason = "local credential/config file"
        elif path.name == ".env" or path.name.startswith(".env."):
            if not path.name.endswith((".example", ".sample", ".template")):
                reason = "runtime environment file; commit only reviewed examples"
        if reason:
            problems.append((name, reason))
        full = root / path
        if full.is_symlink():
            continue
        if full.is_file() and PRIVATE_KEY.search(full.read_bytes()):
            problems.append((name, "private key material"))
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    problems = check(args.root.resolve())
    for path, reason in problems:
        print(f"FAIL: {path}: {reason}")
    if problems:
        return 1
    print("Tracked source boundary checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
