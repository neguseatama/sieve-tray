"""GT-T15..T22 (Tray 2.0.0 Gate CLI, history, report, i18n, molds,
vendor, README, version).

Red stage: GT-T15 (gate/verify verbs), T16 (gate_runs), T17 (Gate
report), T18 (gate strings), T20 (vendor pins), T21 (README Gate
section) and T22 (2.0.0) fail until the fix commit; GT-T19 is a
regression pin that must already be green in the red stage and stay
green through the fix.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import sieve_tray
from sieve_tray import (UNOBSERVED_REASONS, UNOBSERVED_STAGES,
                        UNOBSERVED_STAGE_BG, render, render_text)
from sieve_tray_storage import CROWD_PAYLOAD_ALLOWLIST
from test_v1_3_engine_updates import (CLEAN_TREE, MOLD_CLEAN_CORE,
                                      MOLD_CLEAN_RENDER,
                                      MOLD_CLEAN_RENDER_TEXT, TREE,
                                      _core_hash, _write_tree_text)
from sieve_tray_i18n import STRINGS

REPO_ROOT = Path(__file__).resolve().parent.parent
TRAY = REPO_ROOT / "sieve_tray.py"

# ---------------------------------------------------------------------------
# Measured pins (Tray v1.4.0 baseline 402be10/f94f1be):
# vendored Redact 0.11.0 (PyPI wheel), vendored sieve-order v1.1.0
# (tag 62c433bd), dependency floors.
# ---------------------------------------------------------------------------

REDACT_0110_SHA = (
    "9203c7476fbac1eb0f25e75c6f31ea48732b4928b43ad2f641c5f5902c94e836")

ORDER_V110_SHA = {
    "sieve_order/__init__.py": (
        "8808be36f88060d18f087aba287d4ee1f5b4525e534602accc2e10485e32ecc5"),
    "sieve_order/__main__.py": (
        "f80d75284f54d068a0e5ecccecf4fe2550ab0431f641ba693e2d0678b8f943ef"),
    "sieve_order/observer.py": (
        "47f0832c7e724d5a7d941880073b86ac776efd0562cb508c6cd132b695c85437"),
    # The upstream package's own test module is NOT vendored: it reads
    # the upstream repo's README/SPEC/pyproject and would fail inside
    # sieve-tray's tree.  (design note for the report.)
}

# The v1.4.0 closed vocabularies (§4-6 measurement) - unchanged here.
V140_UNOBSERVED_STAGES = {
    "remedy": frozenset({
        "refused", "parse_failed", "unreadable", "too_large",
        "symlink_skipped"}),
    "environment": frozenset({"engine_unavailable"}),
    "excluded": frozenset({"not_applicable", "empty_input"}),
}
V140_STAGE_BG = {"remedy": "#fff4d6", "environment": "#f0f0f0",
                 "excluded": "#f8f8f8"}

NOT_PRODUCED_STAGES_FIXED = {
    "needs_settings": "remedy", "not_applicable": "excluded",
    "engine_unavailable": "environment", "engine_refused": "remedy",
    "write_failed": "remedy"}


def _mk_tree(root: Path):
    root.mkdir()
    (root / "a.txt").write_text("alpha\n", encoding="utf-8")
    (root / "b.txt").write_text("beta\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# GT-T15: CLI shapes
# ---------------------------------------------------------------------------

def test_t15_cli_legacy_shape(tmp_path):
    # The legacy shape keeps the v1.4.0 scan semantics: a code group is
    # required, so the mold tree (CLEAN_TREE) is the right corpus.  The
    # report path notation follows the caller's cwd (a v1.4.0 property,
    # unchanged), so the byte comparison runs with the same cwd for both
    # the CLI and the in-process render; the result must equal the
    # v1.4.0 golden pin (GT-T19's hash).
    _write_tree_text(tmp_path, CLEAN_TREE)
    report = tmp_path / "report.html"
    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        proc = subprocess.run(
            [sys.executable, str(TRAY), "in", "-o", str(report)],
            capture_output=True, text=True)
        result = sieve_tray.run_scan(Path("in"))
    finally:
        os.chdir(old)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert report.is_file()
    html = sieve_tray.render(result)
    assert report.read_text(encoding="utf-8") == html
    assert hashlib.sha256(html.encode("utf-8")).hexdigest() == \
        MOLD_CLEAN_RENDER


def test_t15_cli_gate_and_verify(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "gate_out"
    _mk_tree(inp)
    (inp / "g").mkdir()
    (inp / "g" / "keep.py").write_text("x = 1\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(TRAY), "gate", str(inp), "-o", str(out)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    receipt = out / "handoff" / "gate-receipt.json"
    assert receipt.is_file()
    proc = subprocess.run(
        [sys.executable, str(TRAY), "verify", str(receipt),
         "--output", str(out / "handoff")],
        capture_output=True, text=True)
    assert proc.returncode == 0
    assert '"overall": "match"' in proc.stdout
    # `gate`/`verify` as folder names still work in the legacy shape
    inp2, out2 = tmp_path / "gate", tmp_path / "rep2"
    inp2.mkdir()
    (inp2 / "x.py").write_text("y = 2\n", encoding="utf-8")
    report2 = tmp_path / "report2.html"
    proc = subprocess.run(
        [sys.executable, str(TRAY), str(inp2), "-o", str(report2)],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# GT-T16: gate_runs history allowlist
# ---------------------------------------------------------------------------

def _gate_runs_columns(db_path):
    """The gate_runs data columns (the internal autoincrement id is
    not part of the allowlist)."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "PRAGMA table_info(gate_runs)").fetchall()
    finally:
        conn.close()
    return [r[1] for r in rows if r[1] != "id"]


def test_t16_gate_runs_allowlist(tmp_path):
    from sieve_tray_storage import Storage
    db = tmp_path / "empty.sqlite"
    Storage(str(db))  # creates the tables, incl. gate_runs
    columns = _gate_runs_columns(db)
    assert columns == [
        "run_id", "created_at", "items_total", "produced",
        "np_needs_settings", "np_unobserved", "np_not_applicable",
        "np_engine_unavailable", "np_engine_refused", "np_write_failed",
        "status_flagged", "status_clean", "status_unobserved",
        "receipt_digest", "engines_version"]
    # a recorded run only carries the allowlisted counts
    from sieve_tray_storage import Storage
    db = tmp_path / "history.sqlite"
    storage = Storage(str(db))
    storage.record_gate_run(
        run_id="r-1", created_at=0, items_total=5, produced=3,
        np_needs_settings=1, np_unobserved=1, np_not_applicable=0,
        np_engine_unavailable=0, np_engine_refused=0, np_write_failed=0,
        status_flagged=2, status_clean=1, status_unobserved=2,
        receipt_digest="sha256:" + "0" * 64,
        engines_version="sieve-lens 0.22.0; sieve-redact 0.11.0")
    assert _gate_runs_columns(db) == columns


def test_t16_no_paths_in_history(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    (inp / "weird_name_XY7q.txt").write_text("secret body AB3z\n",
                                             encoding="utf-8")
    from sieve_tray import run_gate
    from sieve_tray_storage import Storage
    db = tmp_path / "h.sqlite"
    run_gate(inp, out, storage_path=str(db))
    blob = db.read_bytes()
    assert b"weird_name_XY7q" not in blob
    assert b"secret body AB3z" not in blob
    assert str(inp).encode("utf-8") not in blob
    assert str(out).encode("utf-8") not in blob


def test_t16_existing_tables_intact(tmp_path):
    """An existing v1.4.0 DB gains gate_runs without touching the rest."""
    from sieve_tray_storage import Storage
    db = tmp_path / "old.sqlite"
    storage = Storage(str(db))
    storage.save_crowd_run({
        "input_path": "old.csv", "output_path": "out.csv",
        "records_in": 3, "records_out": 2, "suppressed": 1,
        "k_achieved": 2, "max_risk": 0.5, "avg_risk": 0.25,
        "status": "ok", "reason": None, "report_text": "report"})
    del storage
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        crowd_cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(crowd_runs)").fetchall() if r[1] != "id"]
        crowd_rows = conn.execute(
            "SELECT COUNT(*) FROM crowd_runs").fetchone()[0]
    finally:
        conn.close()
    assert crowd_cols == [
        "timestamp", "status", "reason", "records_in", "records_out",
        "suppressed", "k_requested", "k_achieved", "max_risk",
        "avg_risk", "before_alone", "after_alone", "payload_json"]
    assert crowd_rows == 1
    assert _gate_runs_columns(db)  # gate_runs created alongside


# ---------------------------------------------------------------------------
# GT-T17: the Gate report
# ---------------------------------------------------------------------------

def _report_after_run(tmp_path, **kw):
    from sieve_tray import run_gate
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    (inp / "hidden.html").write_text(
        '<html><head><style>.s{display:none}</style></head><body>'
        '<p class="s">HIDDEN PIECE &lt;img src=x onerror=alert(1)&gt;'
        '</p><p>VISIBLE HTML</p></body></html>', encoding="utf-8")
    (inp / "table.csv").write_bytes(b"a,b\n1,2\n")
    (inp / "unknown.xyz").write_bytes(b"\x00\x01mystery\n")
    run_gate(inp, out, **kw)
    return (out / "local" / "gate-report.html").read_text(encoding="utf-8")


def test_t17_report_no_external_requests(tmp_path):
    report = _report_after_run(tmp_path)
    assert "http://" not in report and "https://" not in report
    assert "<script" not in report.lower()
    assert "<link" not in report.lower()
    assert "<img" not in report.lower()


def test_t17_report_escapes_fragments(tmp_path):
    report = _report_after_run(tmp_path)
    # the hidden fragment (with its embedded tag) is escaped, not raw
    assert "<img src=x onerror=alert(1)>" not in report
    assert "&lt;img src=x onerror=alert(1)&gt;" in report
    assert "HIDDEN PIECE" in report  # visible only in the local report


def test_t17_report_stage_colors(tmp_path):
    report = _report_after_run(tmp_path)
    # §3.2 mapping, using the existing three-stage colors only:
    # needs_settings + engine_refused -> remedy (#fff4d6),
    # not_applicable -> excluded (#f8f8f8)
    assert report.count("#fff4d6") >= 1
    assert report.count("#f8f8f8") >= 1


def test_t17_report_environment_stage(tmp_path, monkeypatch):
    """engine_unavailable rows get the environment gray (#f0f0f0)."""
    from sieve_tray import run_gate
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    (inp / "style.html").write_text(
        '<html><head><style>.s{display:none}</style></head><body>'
        '<p class="s">H</p><p>V</p></body></html>', encoding="utf-8")
    monkeypatch.setitem(__import__("sys").modules,
                        "sieve_lens_ext.html_css_selectors", None)
    run_gate(inp, out)
    report = (out / "local" / "gate-report.html").read_text(
        encoding="utf-8")
    assert report.count("#f0f0f0") >= 1


def test_t17_browser_opens_file_uri(tmp_path, monkeypatch):
    from sieve_tray import run_gate
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    run_gate(inp, out)
    seen = []
    monkeypatch.setattr(sieve_tray.webbrowser, "open",
                        lambda uri: seen.append(uri))
    from sieve_tray_storage import Storage  # noqa: F401  (import sanity)
    # the report opener reuses the existing open_in_browser helper
    from sieve_tray import open_report_gate
    open_report_gate(out / "local" / "gate-report.html")
    assert len(seen) == 1
    assert seen[0].startswith("file://")


# ---------------------------------------------------------------------------
# GT-T18: i18n symmetry
# ---------------------------------------------------------------------------

def test_t18_gate_strings_en_ja_symmetry():
    en = {k: v for k, v in STRINGS["en"].items() if k.startswith("gate")}
    ja = {k: v for k, v in STRINGS["ja"].items() if k.startswith("gate")}
    assert en and ja, "gate strings missing"
    assert set(en) == set(ja)
    import re as _re
    def placeholders(value):
        return sorted(_re.findall(r"\{[^{}]+\}", value))
    for key in en:
        assert placeholders(en[key]) == placeholders(ja[key]), key


# ---------------------------------------------------------------------------
# GT-T19: v1.4.0 molds (regression pin - green in the red stage too)
# ---------------------------------------------------------------------------

def test_t19_golden_render_clean_byte_identical(tmp_path):
    _write_tree_text(tmp_path, CLEAN_TREE)
    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = sieve_tray.run_scan(Path("in"))
    finally:
        os.chdir(old)
    assert _core_hash(result) == MOLD_CLEAN_CORE
    assert hashlib.sha256(
        render(result).encode("utf-8")).hexdigest() == MOLD_CLEAN_RENDER
    assert hashlib.sha256(
        render_text(result).encode("utf-8")).hexdigest() == \
        MOLD_CLEAN_RENDER_TEXT


def test_t19_closed_vocabularies_unchanged():
    assert UNOBSERVED_REASONS == frozenset({
        "refused", "parse_failed", "unreadable", "too_large",
        "symlink_skipped", "engine_unavailable", "not_applicable",
        "empty_input"})
    assert UNOBSERVED_STAGES == V140_UNOBSERVED_STAGES
    assert UNOBSERVED_STAGE_BG == V140_STAGE_BG
    assert len(CROWD_PAYLOAD_ALLOWLIST) == 11


# ---------------------------------------------------------------------------
# GT-T20: vendor and floors
# ---------------------------------------------------------------------------

def test_t20_redact_vendor_byte_identical():
    vendored = REPO_ROOT / "sieve_redact.py"
    assert hashlib.sha256(vendored.read_bytes()).hexdigest() == \
        REDACT_0110_SHA


def test_t20_order_vendor_byte_identical():
    for rel, expected in ORDER_V110_SHA.items():
        p = REPO_ROOT / rel
        assert p.is_file(), f"{rel} not vendored"
        assert hashlib.sha256(p.read_bytes()).hexdigest() == expected, rel


def test_t20_dependency_floors():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # v2.1.0 (M2, request §3.13): the scope/referee floors ride with the
    # cohort lane once the engines are published - refreshed from the
    # M1-era >=1.3.0 observation to the published 1.5.0 / 1.6.0.
    assert "sieve-lens>=0.22.0" in pyproject
    assert "sieve-scope>=1.5.0" in pyproject
    assert "sieve-referee>=1.6.0" in pyproject


# ---------------------------------------------------------------------------
# GT-T21: README (en/ja) Gate section
# ---------------------------------------------------------------------------

def _h2_heads(path: Path):
    return [line.strip() for line in path.read_text(encoding="utf-8")
            .splitlines() if line.startswith("## ")]


def test_t21_readme_gate_section():
    for name in ("README.md", "README.ja.md"):
        heads = _h2_heads(REPO_ROOT / name)
        gate = [h for h in heads if "Gate" in h]
        assert gate, f"{name} has no Gate section"
        # Gate sits near the top (§3.6: right after the intro block)
        assert heads.index(gate[0]) <= 3, f"{name}: Gate not near top"


def test_t21_readme_headline_alignment():
    en = _h2_heads(REPO_ROOT / "README.md")
    ja = _h2_heads(REPO_ROOT / "README.ja.md")
    assert len(en) == len(ja), "en/ja section counts diverge"


def test_t21_readme_no_limits_section_added():
    # §3.6: Gate must not ADD a limitations section.  v1.4.0 already
    # carries exactly one ("Known Limitations" / the ja counterpart);
    # the Gate work leaves that count unchanged.
    for name in ("README.md", "README.ja.md"):
        heads = _h2_heads(REPO_ROOT / name)
        limits = [h for h in heads
                  if "imitation" in h.lower()
                  or "既知の制限" in h or "限界" in h]
        assert len(limits) == 1, f"{name}: {limits!r}"


# ---------------------------------------------------------------------------
# GT-T22: version bump
# ---------------------------------------------------------------------------

def test_t22_version_consistency():
    assert sieve_tray.__version__ == "2.1.1"
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject or \
        'version = "2.1.1"' in pyproject
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.lstrip("# \n").startswith("[2.1.1]") or \
        "## [2.1.1]" in changelog
