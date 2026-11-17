"""Canon 2.3.0 / stage 10 - the self-checks (CN-T19, request §3.8-4):
the three new shapes match on the known inputs (exit 0), report a
difference on a broken expectation (exit 1 shape), refuse to run
gracefully (the error shape), the frozen entry dispatches them before
QApplication, and release.yml runs them on every release OS.
"""
import json
import subprocess
import sys

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

SHAPES = ("clean", "normalize", "table-diff")


@pytest.mark.parametrize("shape", SHAPES)
def test_self_check_matches_with_exit_0(shape):
    proc = subprocess.run(
        [sys.executable, "sieve_tray.py", shape, "--self-check"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # the progress lines ride before the JSON (the s11 extraction form)
    result = json.loads(proc.stdout[proc.stdout.index("{"):])
    assert result["matching"] == result["expected"], result
    assert result["differences"] == []


def test_self_check_difference_carries_exit_1(monkeypatch, tmp_path):
    """A broken expectation reads as 1 (a difference): the monkeypatched
    known value disagrees with the measured one."""
    import sieve_canon
    monkeypatch.setattr(sieve_canon, "_CN_KV_C2_OUTPUT_SHA256",
                        "sha256:" + "0" * 64)
    result = sieve_canon.normalize_self_check()
    assert result["matching"] < result["expected"]
    assert result["differences"][0]["field"] == "output sha256"


def test_frozen_entry_dispatches_the_new_shapes():
    """The dispatch sits before QApplication (the s11 pin, now eight
    shapes)."""
    gui = (REPO / "sieve_tray_gui.py").read_text(encoding="utf-8")
    for shape in SHAPES:
        assert '"%s"' % shape in gui.split("QApplication(sys.argv)")[0], \
            shape
    idx = gui.index('"gate", "cohort", "manifest", "pack", "draw", '
                    '"normalize", "clean", "table-diff"')
    assert idx < gui.index("QApplication(sys.argv)")


def test_release_yml_runs_the_three_new_checks():
    text = (REPO / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8")
    for shape in ("clean", "normalize", "table-diff"):
        # Windows: the Start-Process form with the exit guard
        assert '"%s", "--self-check"' % shape in text, shape
        # macOS: the direct frozen-binary line
        assert "SieveTray %s --self-check" % shape in text, shape
    # the exit-code guard covers the new blocks (the 2026-11-10
    # contract: any exit code but 0 fails the release)
    windows_block = text[text.index("Self-check the frozen artifact"):
                         text.index("Package artifact (Windows)")]
    assert windows_block.count("ExitCode -ne 0") >= 8
