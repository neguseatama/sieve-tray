"""Tray 2.6.0 - the repository-inspection integration (CK-T09).

The check command joins the repository tooling: a pre-commit hook and
a GitHub Action both call ``sieve-tray check``, and the CI proves both
paths (``pre-commit try-repo`` over the checked-out tree and the local
``uses: ./`` action) on ubuntu.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_ck_t09_pre_commit_hook_declares_the_check():
    """CK-T09: the hook file names the sieve-check hook, calls the
    check command, and rides the observable extensions."""
    hook = REPO / ".pre-commit-hooks.yaml"
    assert hook.is_file()
    text = hook.read_text(encoding="utf-8")
    assert "- id: sieve-check" in text
    assert "entry: sieve-tray check" in text
    assert "language: python" in text
    assert "pass_filenames: true" in text
    files_line = [line for line in text.splitlines()
                  if line.strip().startswith("files:")][0]
    for ext in ("docx", "html?", "md", "txt", "pdf", "csv", "xlsx",
                "png", "jpe?g", "gif", "bmp", "tif", "webp"):
        assert ext in files_line, ext


def test_ck_t09_action_declares_inputs_and_github_output():
    """CK-T09: the composite action takes the paths, the excludes, the
    only-hidden / strict switches and the tray version, and runs the
    check with the github output format."""
    action = REPO / "action.yml"
    assert action.is_file()
    text = action.read_text(encoding="utf-8")
    assert "using: composite" in text
    for name in ("paths", "exclude", "only-hidden", "strict",
                 "tray-version"):
        assert "%s:" % name in text, name
    assert "sieve-tray check" in text
    assert "--format github" in text


def test_ck_t09_ci_runs_both_integration_paths():
    """CK-T09: the CI carries the two integration jobs - the hook via
    pre-commit try-repo and the action via uses: ./ - on ubuntu."""
    workflow = (REPO / ".github" / "workflows" / "test.yml"
                ).read_text(encoding="utf-8")
    assert "pre-commit try-repo" in workflow
    assert "uses: ./" in workflow
    assert workflow.count("runs-on: ubuntu-latest") >= 1
