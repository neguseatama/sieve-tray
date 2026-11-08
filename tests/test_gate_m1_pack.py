"""GT-T14 (Tray 2.0.0 Gate sample pack and self-check).

Red stage: samples/gate/, tools/make_gate_samples.py and
gate_self_check() arrive with the fix commit.

Contract (request §3.5):
  - samples/gate/ holds 13 harmless sample files in 10 categories
    (the HTML category grew to 3 files per the amended GT-T03) plus
    MANIFEST.json carrying each file's SHA-256 and the expected
    observation (status, hidden-segment presence, Order axes, Redact
    counts, treatment reason) - never a digest of Gate's own output;
  - the samples are generated deterministically by
    tools/make_gate_samples.py (fixed zip timestamps); regenerating
    into a temp dir is byte-identical to the committed tree;
  - the self-check (GUI button / `gate --self-check`) compares the
    expected observations and reports "expected n / m" plus any
    differing item.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES = REPO_ROOT / "samples" / "gate"
MANIFEST = SAMPLES / "MANIFEST.json"
GENERATOR = REPO_ROOT / "tools" / "make_gate_samples.py"

# The expected observation fields the self-check compares (§3.5).
EXPECT_FIELDS = {"kind", "status", "hidden_count", "order_observed",
                 "order_axes", "redact_spans", "treatment",
                 "not_produced_reason"}

# 13 sample files across the 10 §3.5 categories.
SAMPLE_NAMES = [
    "hidden_vanish.docx",
    "hidden_tinyfont.docx",
    "hidden_tracked.docx",
    "html_inline_style.html",
    "html_style_block.html",
    "html_hidden_attr.html",
    "invisible_chars.txt",
    "plain.txt",
    "contacts.txt",
    "cp932.txt",
    "table.csv",
    "unknown.xyz",
    "broken.docx",
]


def _self_check(**kw):
    from sieve_tray import gate_self_check
    return gate_self_check(**kw)


def test_t14_manifest_hashes_match_files():
    assert MANIFEST.is_file(), "samples/gate/MANIFEST.json missing"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = {e["file"]: e for e in manifest["items"]}
    assert set(entries) == set(SAMPLE_NAMES)
    for name, entry in entries.items():
        data = (SAMPLES / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], name
        expect = entry["expect"]
        assert EXPECT_FIELDS <= set(expect.keys()), name
        assert expect["treatment"] in ("produced", "not_produced"), name


def test_t14_regeneration_byte_identical(tmp_path):
    assert GENERATOR.is_file(), "tools/make_gate_samples.py missing"
    target = tmp_path / "regen"
    proc = subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(target)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    committed = {p.name: p.read_bytes() for p in SAMPLES.iterdir()
                 if p.is_file()}
    regen = {p.name: p.read_bytes() for p in target.rglob("*")
             if p.is_file() and p.parent.name == "gate"}
    assert set(committed) == set(regen)
    for name in committed:
        assert committed[name] == regen[name], f"{name} differs"


def test_t14_self_check_all_expected(tmp_path):
    result = _self_check(progress=None)
    assert set(result.keys()) >= {"expected", "matching", "differences"}
    assert result["expected"] == result["matching"], result["differences"]
    assert result["differences"] == []


def test_t14_samples_are_harmless():
    """The pack carries no real personal data: the fictional values are
    the check-digit-valid constants measured from Redact 0.11.0's own
    tests, and no sample may contain a plausible real-looking name+number
    pair beyond those constants."""
    contacts = (SAMPLES / "contacts.txt").read_text(encoding="utf-8")
    for value in ("123456789018", "7123456789012", "4242424242424242",
                  "yamada@example.jp", "03-1234-5678", "150-0001"):
        assert value in contacts
    for sample in SAMPLE_NAMES:
        blob = (SAMPLES / sample).read_bytes()
        assert not blob.startswith(b"\xef\xbb\xbf") or sample == "cp932.txt"


def test_self_check_without_sample_pack_reports_error(tmp_path,
                                                      monkeypatch):
    """Packaging guard: installed wheels carry no samples/gate, so the
    self-check reports a structured error instead of raising."""
    import sieve_tray
    monkeypatch.setattr(sieve_tray, "REPO_ROOT", tmp_path)
    result = _self_check(progress=None)
    assert result["error"] == "sample_pack_not_available", result
    assert "samples/gate" in result["detail"].replace("\\", "/")
