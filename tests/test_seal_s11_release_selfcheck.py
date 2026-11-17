"""SL-T20 (Seal 2.2, S11): the frozen app runs the three Seal
self-checks.

The 2.1.0 ruling (§3.10) made the frozen GUI entry dispatch
gate|cohort --self-check to the headless CLI before QApplication;
SL-T20 extends the release.yml post-processing to the three Seal
commands: the frozen app must pass the `manifest` / `pack` / `draw`
`--self-check` equivalents - each runs a small known input and
compares the expected values - under the same 0/1/2 exit contract
(0 = the expected values matched, 1 = a difference, 2 = the
self-check could not run; the 2026-11-10 ruling).

The expectations ride the PUBLISHED known values - docs/manifest-
format.md §4 KV-2 and docs/draw-procedure.md §4 KV-D1/KV-D2 - and
the deterministic pack receipt; never a receipt digest (the digest
covers tool.version, so it moves with a release).  The known-value
strings are read back from the two docs, so the docs, the
implementation and this test cross-check one another (the SL-T01 /
SL-T14 pattern).

The macOS/Windows legs of the frozen runs are measured by the
release.yml workflow_dispatch trial run on the runners (the ch_t20
note); this file pins the static shape of the workflow and the GUI
dispatch, and runs the three self-checks unfrozen - the dispatch,
the engines and the expectations are the same code the frozen app
carries.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import sieve_tray

REPO_ROOT = Path(__file__).resolve().parent.parent
TRAY = REPO_ROOT / "sieve_tray.py"
GUI = REPO_ROOT / "sieve_tray_gui.py"
RELEASE = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _docs_known_values():
    """The published known values, read back from the two docs."""
    mf = (REPO_ROOT / "docs" / "manifest-format.md").read_text(
        encoding="utf-8")
    dp = (REPO_ROOT / "docs" / "draw-procedure.md").read_text(
        encoding="utf-8")
    kv = {"KV-2": re.search(r"^KV-2 = ([0-9a-f]{64})$", mf,
                            re.M).group(1)}
    for name in ("KV-D1-roster", "KV-D1-result",
                 "KV-D2-roster", "KV-D2-result"):
        kv[name] = re.search(r"^%s = ([0-9a-f]{64})$" % name, dp,
                             re.M).group(1)
    return kv


def _run_cli_self_check(cmd):
    proc = subprocess.run(
        [sys.executable, str(TRAY), cmd, "--self-check"],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    obj = json.loads(proc.stdout[proc.stdout.index("{"):])
    return proc, obj


# ---------------------------------------------------------------------------
# the static shape: release.yml post-processing + the GUI dispatch
# ---------------------------------------------------------------------------

def test_t20_release_workflow_runs_the_three_self_checks():
    text = RELEASE.read_text(encoding="utf-8")
    # both frozen-artifact self-check steps stay in place (ch_t20 keeps
    # its own pins; here the three Seal shapes join each OS step)
    w0 = text.index("Self-check the frozen artifact (Windows)")
    w1 = text.index("Package artifact (Windows)")
    m0 = text.index("Self-check the frozen artifact (macOS)")
    m1 = text.index("Package artifact (macOS)")
    for cmd in ("manifest", "pack", "draw"):
        # Windows: the Start-Process argument list on the frozen exe
        assert ('"%s", "--self-check"' % cmd) in text[w0:w1], cmd
        # macOS: the app binary line
        assert ("MacOS/SieveTray %s --self-check" % cmd) in text[m0:m1], cmd
    # any exit code but 0 fails the release (the 2026-11-10 contract);
    # the new blocks reuse the same guard
    assert "ExitCode -ne 0" in text[w0:w1]


def test_t20_gui_dispatches_the_five_self_checks():
    gui = GUI.read_text(encoding="utf-8")
    tuple_form = ('"gate", "cohort", "manifest", "pack", "draw", '
                  '"normalize", "clean", "table-diff"')
    assert tuple_form in gui
    # a self-check run never opens a window: the dispatch sits before
    # QApplication (the ch_t20 pin, now covering the five shapes)
    assert gui.index(tuple_form) < gui.index("QApplication(sys.argv)")
    assert '"--self-check" in sys.argv[2:]' in gui


# ---------------------------------------------------------------------------
# the expectations are the published known values (SL-T01/SL-T14 pattern)
# ---------------------------------------------------------------------------

def test_t20_expectations_are_the_published_known_values():
    kv = _docs_known_values()
    assert sieve_tray._SEAL_KV2_OVERALL == kv["KV-2"]
    assert sieve_tray._SEAL_KVD1_ROSTER_SHA256 == kv["KV-D1-roster"]
    assert sieve_tray._SEAL_KVD1_RESULT_SHA256 == kv["KV-D1-result"]
    assert sieve_tray._SEAL_KVD2_ROSTER_SHA256 == kv["KV-D2-roster"]
    assert sieve_tray._SEAL_KVD2_RESULT_SHA256 == kv["KV-D2-result"]


# ---------------------------------------------------------------------------
# the three self-checks through the CLI (unfrozen; rc 0 = matched)
# ---------------------------------------------------------------------------

def test_t20_manifest_self_check_cli():
    proc, obj = _run_cli_self_check("manifest")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert obj["matching"] == obj["expected"] == 5
    assert obj["differences"] == []


def test_t20_pack_self_check_cli():
    proc, obj = _run_cli_self_check("pack")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert obj["matching"] == obj["expected"] == 5
    assert obj["differences"] == []


def test_t20_draw_self_check_cli():
    proc, obj = _run_cli_self_check("draw")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert obj["matching"] == obj["expected"] == 7
    assert obj["differences"] == []


# ---------------------------------------------------------------------------
# rc 1 semantics: a wrong expectation is reported as a difference
# ---------------------------------------------------------------------------

def test_t20_manifest_self_check_reports_a_difference(monkeypatch):
    monkeypatch.setattr(sieve_tray, "_SEAL_KV2_OVERALL", "0" * 64)
    result = sieve_tray.manifest_self_check()
    assert result["matching"] < result["expected"]
    assert result["differences"][0]["field"] == "summary.overall_sha256"


def test_t20_pack_self_check_reports_a_difference(monkeypatch):
    monkeypatch.setattr(sieve_tray, "_SEAL_KV2_OVERALL", "0" * 64)
    result = sieve_tray.pack_self_check()
    assert result["matching"] < result["expected"]
    fields = [d["field"] for d in result["differences"]]
    assert "summary.overall_sha256" in fields
    assert "roundtrip overall_sha256" in fields


def test_t20_draw_self_check_reports_a_difference(monkeypatch):
    monkeypatch.setattr(sieve_tray, "_SEAL_KVD1_RESULT_SHA256", "0" * 64)
    result = sieve_tray.draw_self_check()
    assert result["matching"] < result["expected"]
    assert result["differences"][0]["field"] == "KV-D1 result_sha256"


# ---------------------------------------------------------------------------
# rc 2 semantics: the self-check could not run (no temp input possible)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["manifest_self_check", "pack_self_check",
                                  "draw_self_check"])
def test_t20_self_check_input_unavailable(name, monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("no temp space")
    monkeypatch.setattr(sieve_tray.tempfile, "TemporaryDirectory", _boom)
    result = getattr(sieve_tray, name)()
    assert result["error"] == "self_check_input_unavailable"
