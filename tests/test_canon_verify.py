"""Canon 2.3.0 / stage 7 - the verify extension (CN-T18 and the CN-T06
verify parts, request §3.6): the three new receipts are verified with
the EXISTING vocabulary only - output_changed / output_missing /
input_changed / input_missing for the differs side,
settings_unavailable for a missing input position - and the exit
codes stay 0 / 1 / 2.  The raw-byte rule of CN-T06: a cleaned output
with metadata added back reports differs.
"""
import json
import subprocess
import sys
import zlib

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO / "tests"))
from test_canon_clean import (  # noqa: E402 - the shared fixtures
    _make_jpeg, _make_png, _png_chunk)


def _run_clean(inp, out, **kw):
    from sieve_canon import run_clean
    return run_clean(Path(inp), Path(out), **kw)


def _run_normalize(inp, out, **kw):
    from sieve_canon import run_normalize
    return run_normalize(Path(inp), Path(out), **kw)


def _run_diff(a, b, out, key, **kw):
    from sieve_canon import run_table_diff
    return run_table_diff(Path(a), Path(b), key, Path(out), **kw)


def _verify(receipt_path, *extra, cwd=REPO):
    cmd = [sys.executable, "sieve_tray.py", "verify", str(receipt_path)]
    cmd += [str(e) for e in extra]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8")


def _closed_words():
    from sieve_tray import VERIFY_REASONS, VERIFY_NOT_VERIFIABLE_REASONS
    return VERIFY_REASONS | VERIFY_NOT_VERIFIABLE_REASONS


# ---------------------------------------------------------------------------
# the clean receipt (CN-T06 + CN-T18)

def test_clean_verify_match_exit_0(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "pic.png").write_bytes(_make_png())
    out = tmp_path / "out"
    receipt = _run_clean(src, out)
    proc = _verify(out / "handoff" / "clean-receipt.json",
                   "--root", out / "handoff")
    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    assert result["overall"] == "match"
    assert result["scope"] == "outputs_only"


def test_clean_verify_tampered_output_reports_output_changed(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "pic.png").write_bytes(_make_png())
    out = tmp_path / "out"
    _run_clean(src, out)
    copy = out / "handoff" / "pic.png"
    copy.write_bytes(copy.read_bytes() + b"\x00")      # any byte change
    proc = _verify(out / "handoff" / "clean-receipt.json",
                   "--root", out / "handoff")
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["overall"] == "differs"
    assert result["items"][0]["reason"] == "output_changed"


def test_clean_verify_metadata_added_back_reports_differs(tmp_path):
    """CN-T06: the re-observation catches a metadata chunk added back
    to the cleaned output - in the existing output_changed word."""
    src = tmp_path / "in"
    src.mkdir()
    (src / "pic.png").write_bytes(_make_png())
    out = tmp_path / "out"
    _run_clean(src, out)
    copy = out / "handoff" / "pic.png"
    clean_bytes = copy.read_bytes()
    # rebuild with a fresh tEXt before IEND
    from sieve_canon import _cn_png_chunks, _cn_png_chunk_bytes
    chunks = _cn_png_chunks(clean_bytes)
    parts = [clean_bytes[:8]]
    for ctype, payload in chunks:
        if ctype == "IEND":
            parts.append(_png_chunk(b"tEXt", b"Author\0SIEVE-BACK"))
        parts.append(_png_chunk(ctype.encode("latin-1"), payload))
    copy.write_bytes(b"".join(parts))
    proc = _verify(out / "handoff" / "clean-receipt.json",
                   "--root", out / "handoff")
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["overall"] == "differs"
    assert result["items"][0]["reason"] == "output_changed"


def test_clean_verify_without_root_is_not_verifiable(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "pic.png").write_bytes(_make_png())
    out = tmp_path / "out"
    _run_clean(src, out)
    proc = _verify(out / "handoff" / "clean-receipt.json")
    assert proc.returncode == 2
    result = json.loads(proc.stdout)
    assert result["overall"] == "not_verifiable"
    assert result["not_verifiable_reason"] == "settings_unavailable"


def test_clean_verify_no_paths_uses_the_index_names(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "pic.png").write_bytes(_make_png())
    out = tmp_path / "out"
    receipt = _run_clean(src, out, no_paths=True)
    proc = _verify(out / "handoff" / "clean-receipt.json",
                   "--root", out / "handoff")
    assert proc.returncode == 0
    assert receipt["items"][0]["path"] is None
    assert receipt["items"][0]["output_name"] == "0001.png"


# ---------------------------------------------------------------------------
# the normalize receipt

def test_normalize_verify_match_and_tamper(tmp_path):
    src = tmp_path / "in.txt"
    src.write_bytes(b"a\r\n")
    out = tmp_path / "out"
    _run_normalize(src, out)
    proc = _verify(out / "handoff" / "normalize-receipt.json",
                   "--root", out)
    assert proc.returncode == 0
    copy = out / "handoff" / "in.txt"
    copy.write_bytes(b"zzz\n")
    proc = _verify(out / "handoff" / "normalize-receipt.json",
                   "--root", out)
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["items"][0]["reason"] == "output_changed"


def test_normalize_verify_changed_input(tmp_path):
    src = tmp_path / "in.txt"
    src.write_bytes(b"a\r\n")
    out = tmp_path / "out"
    _run_normalize(src, out)
    src.write_bytes(b"b\r\n")                    # the original moved on
    proc = _verify(out / "handoff" / "normalize-receipt.json",
                   "--root", out)
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["items"][0]["reason"] == "input_changed"


def test_normalize_verify_missing_output(tmp_path):
    src = tmp_path / "in.txt"
    src.write_bytes(b"a\r\n")
    out = tmp_path / "out"
    _run_normalize(src, out)
    (out / "handoff" / "in.txt").unlink()
    proc = _verify(out / "handoff" / "normalize-receipt.json",
                   "--root", out)
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["items"][0]["reason"] == "output_missing"


# ---------------------------------------------------------------------------
# the table-diff receipt

def test_table_diff_verify_match_then_changed_input(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,v\n1,x\n", encoding="utf-8", newline="")
    b.write_text("id,v\n1,x\n", encoding="utf-8", newline="")
    out = tmp_path / "out"
    _run_diff(a, b, out, ("id",))
    proc = _verify(out / "handoff" / "table-diff-receipt.json")
    assert proc.returncode == 0
    a.write_text("id,v\n1,y\n", encoding="utf-8", newline="")
    proc = _verify(out / "handoff" / "table-diff-receipt.json")
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["items"][0]["reason"] == "input_changed"


def test_table_diff_verify_missing_input_is_not_verifiable(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,v\n1,x\n", encoding="utf-8", newline="")
    b.write_text("id,v\n1,x\n", encoding="utf-8", newline="")
    out = tmp_path / "out"
    _run_diff(a, b, out, ("id",))
    a.unlink()
    proc = _verify(out / "handoff" / "table-diff-receipt.json")
    assert proc.returncode == 2
    result = json.loads(proc.stdout)
    assert result["overall"] == "not_verifiable"
    assert result["not_verifiable_reason"] == "settings_unavailable"


# ---------------------------------------------------------------------------
# CN-T18: the vocabulary stays closed across the three receipts

def test_verify_reasons_stay_in_the_closed_sets(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "pic.png").write_bytes(_make_png())
    (src / "pic.jpg").write_bytes(_make_jpeg(orientation=6))
    out = tmp_path / "out"
    _run_clean(src, out)
    proc = _verify(out / "handoff" / "clean-receipt.json",
                   "--root", out / "handoff")
    result = json.loads(proc.stdout)
    closed = _closed_words()
    for it in result["items"]:
        assert it["reason"] in closed
    assert result["overall"] in ("match", "differs", "not_verifiable")
    # every new receipt kind rides the same two closed sets
    from sieve_canon import CN_MOJIBAKE_SIGNS
    assert "output_changed" in closed
