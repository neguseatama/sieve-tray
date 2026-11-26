"""Tray 2.6.0 - the release pack (CK-T12).

The version has one static source (``sieve_tray.__version__``): the
pyproject single-sources it through the dynamic attribute, the two
README titles, the newest CHANGELOG section, and the docs registry all
follow it - the test compares against the running module instead of
carrying its own literal.  The release workflow keeps the tag-trigger
path and checks the extracted release body with the public-text watch
before anything is published.
"""
import re
from pathlib import Path

import sieve_tray

REPO = Path(__file__).resolve().parent.parent


def test_ck_t12_version_consistency_across_the_pack():
    """CK-T12: the version reads from the module and every public
    surface agrees with it - the test carries no version literal."""
    version = sieve_tray.__version__
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = { attr = "sieve_tray.__version__" }' in pyproject
    assert 'dynamic = ["version"]' in pyproject
    for name in ("README.md", "README.ja.md"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert "# Sieve Tray v%s" % version in text, name
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [%s]" % version in changelog
    registry = (REPO / "docs" / "page-registry.md").read_text(
        encoding="utf-8")
    assert "Sieve Tray %s" % version in registry


def test_ck_t12_release_workflow_checks_the_body():
    """CK-T12: the release workflow extracts the body from the newest
    CHANGELOG section and passes it through the public-text watch
    before the release is created; the tag trigger is untouched."""
    workflow = (REPO / ".github" / "workflows" / "release.yml"
                ).read_text(encoding="utf-8")
    assert re.search(r"push:\s*\n\s*tags:\s*\n\s*- \"v\*\"",
                     workflow)
    assert "tools/extract_changelog.py" in workflow
    assert re.search(
        r"extract_changelog\.py \"\$\{GITHUB_REF_NAME#v\}\""
        r".*release_body\.md", workflow, re.S)
    assert "--text release_body.md" in workflow
    # the publish step (the one that carries the body) comes after the
    # watch step
    watch_at = workflow.index("--text release_body.md")
    publish_at = workflow.index("body_path: release_body.md")
    assert watch_at < publish_at
