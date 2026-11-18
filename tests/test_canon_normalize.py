"""Canon 2.3.0 / stage 2 - the text normalization: the observation
(CN-T09), the UTF-8 LF output rules (CN-T10), the explicit-encoding
refusals (CN-T11) and --check (CN-T12)  (request §3.2).

The rule of the stage: no auto-detection conversion.  A file is read
as-is only with a BOM or valid UTF-8; everything else is refused with
encoding_unknown and the strictly-readable candidates in the fixed
order, or converted only when the user names the codec.  The receipt
never carries text content - counts and checksums only.
"""
import hashlib
import json
import subprocess
import sys

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _run_normalize(inp, out, **kw):
    from sieve_canon import run_normalize
    return run_normalize(Path(inp), Path(out), **kw)


def _one_item(receipt):
    assert len(receipt["items"]) == 1
    return receipt["items"][0]


# ---------------------------------------------------------------------------
# CN-T09: the observation (request §3.2-1, §3.2-2)

def test_observe_lf_only(tmp_path):
    from sieve_canon import _cn_observe_text
    obs = _cn_observe_text(b"alpha\nbeta\n")
    assert obs["bom"] is None
    assert obs["newlines"] == {"lf": 2, "crlf": 0, "cr": 0}
    assert obs["nul_bytes"] == 0
    assert obs["utf8_valid"] is True
    assert obs["signs"] == {"replacement_char": 0, "c1_controls": 0,
                            "nul_bytes": 0, "utf8_invalid": 0,
                            "mixed_newlines": 0}


def test_observe_crlf_cr_and_mixed(tmp_path):
    from sieve_canon import _cn_observe_text
    obs = _cn_observe_text(b"a\r\nb\r\n")
    assert obs["newlines"] == {"lf": 0, "crlf": 2, "cr": 0}
    obs = _cn_observe_text(b"a\rb\rc\n")
    assert obs["newlines"] == {"lf": 1, "crlf": 0, "cr": 2}
    obs = _cn_observe_text(b"a\r\nb\nc\rd\n")
    assert obs["newlines"] == {"lf": 2, "crlf": 1, "cr": 1}
    assert obs["signs"]["mixed_newlines"] == 1


def test_observe_nul_and_invalid_utf8(tmp_path):
    from sieve_canon import _cn_observe_text
    obs = _cn_observe_text(b"a\x00b\n")
    assert obs["nul_bytes"] == 1
    assert obs["signs"]["nul_bytes"] == 1
    obs = _cn_observe_text(b"abc\xff\n")
    assert obs["utf8_valid"] is False
    assert obs["signs"]["utf8_invalid"] == 1


def test_observe_bom_kinds(tmp_path):
    from sieve_canon import _cn_observe_text
    assert _cn_observe_text(b"\xef\xbb\xbfa\n")["bom"] == "utf-8"
    assert _cn_observe_text(
        b"\xff\xfe" + "a\n".encode("utf-16-le"))["bom"] == "utf-16-le"
    assert _cn_observe_text(
        b"\xfe\xff" + "a\n".encode("utf-16-be"))["bom"] == "utf-16-be"
    assert _cn_observe_text(
        b"\xff\xfe\x00\x00" + "a\n".encode("utf-32-le"))["bom"] == \
        "utf-32-le"
    assert _cn_observe_text(
        b"\x00\x00\xfe\xff" + "a\n".encode("utf-32-be"))["bom"] == \
        "utf-32-be"


def test_observe_replacement_char_and_c1(tmp_path):
    from sieve_canon import _cn_observe_text
    obs = _cn_observe_text("a\ufffdb\n".encode("utf-8"))
    assert obs["signs"]["replacement_char"] == 1
    obs = _cn_observe_text("a\x85b\n".encode("utf-8"))
    assert obs["signs"]["c1_controls"] == 1


def test_observe_utf8_validity_is_reported_null_for_utf16(tmp_path):
    """A UTF-16 BOM names the encoding; the raw bytes are not UTF-8
    bytes, so the UTF-8 validity question does not apply (None) and
    the utf8_invalid sign stays 0 (the context is UTF-16, not broken
    UTF-8)."""
    from sieve_canon import _cn_observe_text
    obs = _cn_observe_text(b"\xff\xfe" + "a\n".encode("utf-16-le"))
    assert obs["utf8_valid"] is None
    assert obs["signs"]["utf8_invalid"] == 0


# ---------------------------------------------------------------------------
# CN-T10: the output rules (request §3.2-5)

def test_normalize_utf8_lf_input_is_byte_identical(tmp_path):
    src = tmp_path / "in.txt"
    src.write_bytes(b"alpha\nbeta\n")
    out = tmp_path / "out"
    receipt = _run_normalize(src, out)
    item = _one_item(receipt)
    assert item["status"] == "produced"
    copy = out / "handoff" / "in.txt"
    assert copy.read_bytes() == b"alpha\nbeta\n"
    assert item["input_sha256"] == _sha(b"alpha\nbeta\n")
    assert item["output_sha256"] == _sha(b"alpha\nbeta\n")


def test_normalize_strips_bom_and_adds_one_trailing_newline(tmp_path):
    src = tmp_path / "bom.txt"
    src.write_bytes(b"\xef\xbb\xbfa\r\nb")   # BOM + CRLF + no final NL
    out = tmp_path / "out"
    _run_normalize(src, out)
    assert (out / "handoff" / "bom.txt").read_bytes() == b"a\nb\n"


def test_normalize_utf16_bom_becomes_utf8_no_bom(tmp_path):
    src = tmp_path / "u16.txt"
    src.write_bytes(b"\xff\xfe" + "表計算\n".encode("utf-16-le"))
    out = tmp_path / "out"
    receipt = _run_normalize(src, out)
    assert _one_item(receipt)["status"] == "produced"
    assert (out / "handoff" / "u16.txt").read_bytes() == \
        "表計算\n".encode("utf-8")


def test_normalize_crlf_option(tmp_path):
    src = tmp_path / "in.txt"
    src.write_bytes(b"a\r\nb\nc\n")
    out = tmp_path / "out"
    _run_normalize(src, out, newline="crlf")
    assert (out / "handoff" / "in.txt").read_bytes() == b"a\r\nb\r\nc\r\n"


def test_normalize_nfc_option(tmp_path):
    src = tmp_path / "nfd.txt"
    src.write_bytes("が\n".encode("utf-8"))  # already NFC
    nfd = tmp_path / "in.txt"
    nfd.write_bytes("か\u3099\n".encode("utf-8"))  # NFD for が
    out = tmp_path / "out"
    _run_normalize(nfd, out)
    plain = (out / "handoff" / "in.txt").read_bytes()
    assert plain == "か\u3099\n".encode("utf-8")   # default: no NFC
    _run_normalize(nfd, out, nfc=True)
    composed = (out / "handoff" / "in.txt").read_bytes()
    assert composed == "が\n".encode("utf-8")
    assert composed != plain


def test_normalize_is_idempotent(tmp_path):
    src = tmp_path / "in.txt"
    src.write_bytes(b"\xef\xbb\xbfa\r\nb")
    out1 = tmp_path / "o1"
    out2 = tmp_path / "o2"
    first = _run_normalize(src, out1)
    again = _run_normalize(out1 / "handoff" / "in.txt", out2)
    assert (out2 / "handoff" / "in.txt").read_bytes() == \
        (out1 / "handoff" / "in.txt").read_bytes()
    assert again["items"][0]["output_sha256"] == \
        first["items"][0]["output_sha256"]


def test_normalize_empty_file_stays_empty(tmp_path):
    src = tmp_path / "empty.txt"
    src.write_bytes(b"")
    out = tmp_path / "out"
    receipt = _run_normalize(src, out)
    assert _one_item(receipt)["status"] == "produced"
    assert (out / "handoff" / "empty.txt").read_bytes() == b""


def test_normalize_folder_keeps_relative_names(tmp_path):
    root = tmp_path / "in"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_bytes(b"a\r\n")
    (root / "sub" / "b.md").write_bytes(b"b\n")
    (root / "skip.pdf").write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    receipt = _run_normalize(root, out)
    assert (out / "handoff" / "a.txt").read_bytes() == b"a\n"
    assert (out / "handoff" / "sub" / "b.md").read_bytes() == b"b\n"
    statuses = {it["path"]: it["status"] for it in receipt["items"]}
    assert statuses["a.txt"] == "produced"
    assert statuses["skip.pdf"] == "not_applicable"
    assert not (out / "handoff" / "skip.pdf").exists()


# ---------------------------------------------------------------------------
# CN-T11: the explicit-encoding refusals (request §3.2-3, §3.2-4)

def test_unknown_encoding_refuses_with_candidates(tmp_path):
    """cp932 bytes that are not valid UTF-8: no BOM, invalid UTF-8 and
    no --from-encoding -> refused with encoding_unknown and the
    strictly-readable candidates in the fixed order (here: cp932)."""
    src = tmp_path / "cp932.txt"
    src.write_bytes("表計算\n".encode("cp932"))
    out = tmp_path / "out"
    receipt = _run_normalize(src, out)
    item = _one_item(receipt)
    assert item["status"] == "refused"
    assert item["reason"] == "encoding_unknown"
    assert item["candidates"] == ["cp932"]
    assert not (out / "handoff" / "cp932.txt").exists()


def test_unknown_encoding_candidates_stay_strict(tmp_path):
    """The candidate list reports only codecs that read the bytes
    strictly, in the fixed order.  Python's cp932 maps 0xFF to a
    private-use code point, so cp932 reads b'abc\\xff\\n' strictly and
    is reported; latin-1 would read any bytes and is never reported
    (request §3.2-3: no codec that decodes everything)."""
    src = tmp_path / "broken.txt"
    src.write_bytes(b"abc\xff\n")
    out = tmp_path / "out"
    receipt = _run_normalize(src, out)
    item = _one_item(receipt)
    assert item["status"] == "refused"
    assert item["reason"] == "encoding_unknown"
    assert item["candidates"] == ["cp932"]
    assert "latin-1" not in item["candidates"]


def test_from_encoding_converts(tmp_path):
    src = tmp_path / "cp932.txt"
    src.write_bytes("表計算\n".encode("cp932"))
    out = tmp_path / "out"
    receipt = _run_normalize(src, out, from_encoding="cp932")
    item = _one_item(receipt)
    assert item["status"] == "produced"
    assert (out / "handoff" / "cp932.txt").read_bytes() == \
        "表計算\n".encode("utf-8")


def test_from_encoding_refuses_undecodable_without_replacement(tmp_path):
    """A byte sequence the named codec cannot read is refused - no
    U+FFFD replacement, no output copy (request §3.2-4).  utf-8 is a
    valid explicit choice and these bytes are not valid UTF-8."""
    src = tmp_path / "bad.txt"
    src.write_bytes(b"abc\xff\n")
    out = tmp_path / "out"
    receipt = _run_normalize(src, out, from_encoding="utf-8")
    item = _one_item(receipt)
    assert item["status"] == "refused"
    assert item["reason"] == "parse_failed"   # the existing closed word
    # no U+FFFD replacement happened anywhere in the receipt (the word
    # replacement_char in the observation vocabulary is a count, not a
    # substitution)
    assert "\ufffd" not in json.dumps(receipt)
    assert not (out / "handoff" / "bad.txt").exists()


def test_cli_exit_is_1_when_a_file_is_refused(tmp_path):
    src = tmp_path / "cp932.txt"
    src.write_bytes("表計算\n".encode("cp932"))
    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "sieve_tray.py", "normalize", str(src),
         "-o", str(out)],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 1
    assert "encoding_unknown" in proc.stdout


def test_cli_exit_is_0_when_every_file_is_produced(tmp_path):
    src = tmp_path / "in.txt"
    src.write_bytes(b"a\r\n")
    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "sieve_tray.py", "normalize", str(src),
         "-o", str(out)],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0
    assert (out / "handoff" / "normalize-receipt.json").is_file()


# ---------------------------------------------------------------------------
# CN-T12: --check (request §3.2-6)

def test_check_writes_receipt_only(tmp_path):
    src = tmp_path / "in.txt"
    src.write_bytes(b"a\r\nb\x00\n")
    out = tmp_path / "out"
    receipt = _run_normalize(src, out, check=True)
    item = _one_item(receipt)
    assert item["status"] == "observed"
    assert item["output_sha256"] is None
    assert item["input_sha256"] == _sha(b"a\r\nb\x00\n")
    assert item["observation"]["signs"]["nul_bytes"] == 1
    assert not (out / "handoff" / "in.txt").exists()
    assert (out / "handoff" / "normalize-receipt.json").is_file()
    assert receipt["settings"]["check"] is True


def test_cli_check_exit_is_0(tmp_path):
    src = tmp_path / "in.txt"
    src.write_bytes(b"a\n")
    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "sieve_tray.py", "normalize", str(src),
         "-o", str(out), "--check"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0
    assert (out / "handoff" / "normalize-receipt.json").is_file()
    assert not (out / "handoff" / "in.txt").exists()


# ---------------------------------------------------------------------------
# the receipt privacy: no text content in the receipt (request §3.2-7)

def test_receipt_never_carries_text_content(tmp_path):
    marker = "SIEVE-PRIVATE-MARKER"
    src = tmp_path / "in.txt"
    src.write_bytes(("x " + marker + " y\r\n").encode("utf-8"))
    out = tmp_path / "out"
    receipt = _run_normalize(src, out)
    raw = json.dumps(receipt, ensure_ascii=False)
    assert marker not in raw
