"""The release version is one string everywhere it is written.

The 2026-11-13 ruling (README と Releases の版表記の統一): pyproject,
__version__, the CHANGELOG and the README titles must carry the same
version, pinned by this one test.  The README keeps exactly one version
literal - its title - because downloads ride releases/latest and the
release asset names are decided from the tag: no release requires
touching README prose, so the title cannot silently drift the way the
stale "# Sieve Tray v1.4.0" heading did against 2.1.0.
"""

import re
import subprocess
import sys
from pathlib import Path

import sieve_tray

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_release_version_is_single_sourced():
    version = sieve_tray.__version__
    # pyproject: the dynamic attr wiring is the only version statement -
    # no hardcoded version literal anywhere in the file
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = { attr = "sieve_tray.__version__" }' in pyproject
    assert not re.search(r'^version = "[0-9]', pyproject, re.M)
    # CHANGELOG: the first section is the release version
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\]", changelog, re.M)
    assert first is not None, "CHANGELOG has no '## [x.y.z]' section"
    assert first.group(1) == version
    # README titles (en/ja): the title line carries the release version,
    # and it is the file's ONLY version literal
    for name in ("README.md", "README.ja.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        title = re.search(r"^# Sieve Tray v([0-9]+\.[0-9]+\.[0-9]+)\s*$",
                          text, re.M)
        assert title is not None, f"{name}: no '# Sieve Tray v...' title"
        assert title.group(1) == version, (
            f"{name}: title is v{title.group(1)}, release is {version}")
        assert text.count(version) == 1, (
            f"{name}: the release version appears "
            f"{text.count(version)}x, expected exactly 1 (the title)")
        # downloads ride releases/latest and the asset names are not
        # hardcoded - a new release must not require a README edit
        assert "releases/latest" in text, f"{name}: no releases/latest link"
        assert "SieveTray-v" not in text, (
            f"{name}: hardcodes a versioned asset name")


def test_changelog_extractor_serves_the_release_body():
    """tools/extract_changelog.py prints the [version] section body and
    fails the release structurally (exit 1) for a version with no
    section - a tag is cut only after the section exists."""
    script = REPO_ROOT / "tools" / "extract_changelog.py"
    run = subprocess.run(
        [sys.executable, str(script), sieve_tray.__version__],
        capture_output=True, text=True)
    assert run.returncode == 0, f"exit {run.returncode}: {run.stderr}"
    body = run.stdout
    assert body.strip(), "the release body came back empty"
    assert "## [" not in body, "the body leaks a section heading"
    # a version with no section must fail, not produce an empty body
    missing = subprocess.run(
        [sys.executable, str(script), "9.9.9"],
        capture_output=True, text=True)
    assert missing.returncode == 1, (
        f"exit {missing.returncode} for a version with no section")
    assert missing.stdout.strip() == ""
