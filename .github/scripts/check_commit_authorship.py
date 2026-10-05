#!/usr/bin/env python3
"""Check authorship metadata on commits introduced by a pull request."""
import argparse
import re
import subprocess

TOOL_NAME = re.compile(r"^(?:Claude(?: .*)?|ChatGPT|Codex|GitHub Copilot|Gemini)$", re.I)
TOOL_EMAILS = {"noreply@anthropic.com", "noreply@openai.com"}

def has_tool_credit(name, email, message):
    if TOOL_NAME.fullmatch(name.strip()) or email.lower().strip() in TOOL_EMAILS:
        return True
    for line in message.splitlines():
        if re.match(r"^\s*(?:co-authored-by|signed-off-by):", line, re.I):
            credit = line.split(":", 1)[1].strip()
            credit_name = credit.split("<", 1)[0].strip()
            if TOOL_NAME.fullmatch(credit_name) or any(e in credit.lower() for e in TOOL_EMAILS):
                return True
    return False

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("head")
    args = parser.parse_args()
    for value in (args.base, args.head):
        if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
            parser.error("base and head must be full commit SHAs")
    commits = subprocess.check_output(
        ["git", "rev-list", f"{args.base}..{args.head}"], text=True
    ).splitlines()
    rejected = []
    for sha in commits:
        name, email, message = subprocess.check_output(
            ["git", "show", "-s", "--format=%an%n%ae%n%B", sha], text=True
        ).split("\n", 2)
        if has_tool_credit(name, email, message):
            rejected.append(sha)
    if rejected:
        raise SystemExit("Use accountable human authorship; remove assistant signatures: " + ", ".join(rejected))
    print(f"Authorship metadata checked on {len(commits)} commits.")

if __name__ == "__main__":
    main()
