"""Canon 2.3.0 / stage 1 - the shared parts: the closed vocabularies,
the deterministic-zip rule parity with pack, and the receipt frame
(request §3.1-10/§3.1-11/§3.2-2, §3.1-8, §2-2).

The observation categories are the closed 8 the request names; the
in-content kinds are the closed 3; the mojibake signs are the closed
5.  Nothing here may grow without a design decision - the tests pin
the tuples so a silent extension turns the suite red.
"""
import json

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# the closed vocabularies (request §3.1-10, §3.1-11, §3.2-2)

def test_meta_categories_are_the_closed_eight():
    from sieve_canon import CN_META_CATEGORIES
    assert CN_META_CATEGORIES == (
        "author", "time", "software", "location", "device",
        "title_subject", "thumbnail", "custom")


def test_in_content_kinds_are_the_closed_three():
    from sieve_canon import CN_IN_CONTENT
    assert CN_IN_CONTENT == ("comment", "tracked_change", "hidden_part")


def test_mojibake_signs_are_the_closed_five():
    from sieve_canon import CN_MOJIBAKE_SIGNS
    assert CN_MOJIBAKE_SIGNS == (
        "replacement_char", "c1_controls", "nul_bytes",
        "utf8_invalid", "mixed_newlines")


def test_table_states_are_the_closed_five():
    from sieve_canon import CN_TABLE_STATES
    assert CN_TABLE_STATES == (
        "same", "changed", "removed", "added", "duplicate_key")


def test_candidate_order_is_fixed_and_strict_only():
    """The candidate list is a fixed order and never contains a codec
    that decodes everything (latin-1) - the list only reports codecs
    that can read the bytes strictly (request §3.2-3)."""
    from sieve_canon import CN_CANDIDATE_ORDER
    assert CN_CANDIDATE_ORDER == (
        "utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be",
        "cp932", "euc-jp")
    assert "latin-1" not in CN_CANDIDATE_ORDER
    assert "shift_jis" not in CN_CANDIDATE_ORDER


# ---------------------------------------------------------------------------
# the deterministic-zip rule parity with pack (request §3.1-8)

def test_zip_rules_match_pack():
    """The Office output zip rides the pack rules: the same fixed
    stamp, create_system 3 and the same external attributes."""
    from sieve_canon import _CN_ZIP_STAMP, _CN_ZIP_FILE_ATTR, \
        _CN_ZIP_DIR_ATTR
    import sieve_tray
    assert _CN_ZIP_STAMP == sieve_tray._SEAL_ZIP_STAMP
    assert _CN_ZIP_FILE_ATTR == 0o100644 << 16
    assert _CN_ZIP_DIR_ATTR == (0o040755 << 16) | 0x10


def test_deterministic_zip_writes_the_same_bytes_twice(tmp_path):
    from sieve_canon import _cn_write_deterministic_zip
    members = [("b.txt", b"second\n"), ("a.txt", b"first\n")]
    p1 = tmp_path / "one.zip"
    p2 = tmp_path / "two" / "one.zip"
    _cn_write_deterministic_zip(p1, members)
    _cn_write_deterministic_zip(p2, members)
    assert p1.read_bytes() == p2.read_bytes()
    import zipfile
    with zipfile.ZipFile(p1) as zf:
        assert zf.namelist() == ["a.txt", "b.txt"]
        zi = zf.getinfo("a.txt")
        assert zi.date_time == (1980, 1, 1, 0, 0, 0)
        assert zi.create_system == 3
        assert zi.compress_type == zipfile.ZIP_STORED


# ---------------------------------------------------------------------------
# the receipt frame parity (the same outer frame as the Seal receipts)

def test_normalize_receipt_uses_the_shared_frame(tmp_path):
    """kind sieve-normalize, receipt_version 1, the shared tool frame
    and a digest the shared verifier accepts (request §3.2-7)."""
    src = tmp_path / "in.txt"
    src.write_bytes(b"alpha\n")
    out = tmp_path / "out"
    from sieve_canon import run_normalize
    receipt = run_normalize(src, out)
    assert receipt["receipt_version"] == 1
    assert receipt["kind"] == "sieve-normalize"
    assert receipt["tool"] == {"name": "sieve-tray",
                               "version": _tray_version()}
    from sieve_tray import _gate_digest
    assert receipt["digest"] == _gate_digest(receipt)


def _tray_version():
    from sieve_tray import __version__
    return __version__
