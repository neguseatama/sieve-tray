"""Screenshot integrity: README references must match docs/screenshots.

Guards the docs/screenshots directory against stale references: the set
of png references in README.md and README.ja.md must equal the expected
four-screenshot set, and the files present under docs/screenshots must
contain no unreferenced (stale) images.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = "docs/screenshots/"

EXPECTED = {
    SHOTS + "main-window-ja.png",
    SHOTS + "anonymize-tab-ja.png",
    SHOTS + "about-dialog-ja.png",
    SHOTS + "settings-dialog-ja.png",
}


class TestReadmeScreenshots:
    def test_references_match_expected_set(self):
        refs = set()
        for name in ("README.md", "README.ja.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            found = set(re.findall(re.escape(SHOTS) + r"[A-Za-z0-9._-]+\.png", text))
            assert found, name
            refs |= found
        assert refs == EXPECTED, sorted(refs)
        for rel in sorted(refs):
            assert (ROOT / rel).is_file(), rel

    def test_no_unreferenced_screenshots(self):
        present = {SHOTS + p.name for p in (ROOT / SHOTS).glob("*.png")}
        assert present == EXPECTED, sorted(present ^ EXPECTED)
