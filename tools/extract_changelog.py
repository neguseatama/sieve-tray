#!/usr/bin/env python3
"""Extract one version's section from CHANGELOG.md as the release body.

release.yml (release-extras) runs this with the tag's version (the v
prefix stripped) and hands the output to the release attach as
body_path.  The section starts at `## [<version>]` and runs to the next
`## [` heading (or EOF); the heading line itself is not part of the body
because the release title already carries the tag.  A version with no
section exits 1 - a tag without its CHANGELOG section fails the release
structurally, not by publishing an empty body (the 2026-11-13 ruling:
the release body is built from the CHANGELOG).
"""
import re
import sys
from pathlib import Path


def extract(text: str, version: str) -> str:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.fullmatch(rf"## \[{re.escape(version)}\]( - .*)?", line):
            start = i + 1
            break
    if start is None:
        return ""
    out = []
    for line in lines[start:]:
        if line.startswith("## ["):
            break
        out.append(line)
    return "\n".join(out).strip() + "\n"


def main(argv: list) -> int:
    if len(argv) != 2:
        print("usage: extract_changelog.py <version>", file=sys.stderr)
        return 2
    changelog = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    body = extract(changelog.read_text(encoding="utf-8"), argv[1])
    if not body:
        print(f"no '## [{argv[1]}]' section in CHANGELOG.md - cut the tag "
              "only after the section exists", file=sys.stderr)
        return 1
    sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
