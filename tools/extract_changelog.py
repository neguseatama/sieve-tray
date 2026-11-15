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

The body rides to stdout as UTF-8 BYTES (the CI #90 fix round,
2026-11-15): the [2.2.0] section carries ja words, and a runner whose
stdout defaults to a legacy codepage (Windows cp1252 under a captured
pipe) raised UnicodeEncodeError before a single byte left the process.
With the bytes form the body is byte-exact on every runner; the
release-extras step that redirects it into release_body.md runs on
ubuntu-latest (measured 2026-11-15), and no longer depends on that.
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
    # UTF-8 bytes, not str: sys.stdout's encoding follows the runner's
    # locale (cp1252 on a captured Windows pipe) and the section body
    # is not encodable there - the bytes form is byte-exact everywhere
    sys.stdout.buffer.write(body.encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
