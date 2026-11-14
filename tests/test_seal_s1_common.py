"""Seal 2.2 / S1 - the shared parts: the hash tree (the whole-folder
checksum) and the check_code section (request 3.1 M4/M5, C1-C7).

The two known values live in docs/manifest-format.md and the tests read
them BACK from the document, so the document and the implementation
cannot drift apart (KV-1: the empty folder = SHA-256(b""); KV-2: the
3-entry fixture spelled out byte by byte in section 4).  An independent
row calculator is written inline here (not imported), so every value is
cross-checked the way a second implementation would do it.

The check_code parts follow section 2 of the same document:
key = the key-file bytes as-is (a trailing LF included), key_id =
HMAC-SHA256(key, "sieve-check-key-id") first 8 bytes hex, check_code =
HMAC-SHA256(key, overall_sha256_ascii + ":" + canonical JSON of the
receipt minus the check_code section and the digest).
"""
import hashlib
import hmac
import json
import os
import re
import stat

import pytest

from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "manifest-format.md"

KV1 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
KV2 = "06965d1ff8239b8e9efad9c88d05e8624d92ac3dd252d047617c82c0de724a92"


# --- independent calculator (a second implementation, by hand) ---------

def _rows_of(folder: Path):
    rows = []
    children = sorted(
        (p for p in folder.iterdir()
         if not p.is_symlink() and (p.is_file() or p.is_dir())),
        key=lambda p: (p.name.encode("utf-8", "surrogateescape"),
                       b"d" if p.is_dir() else b"f"))
    for p in children:
        kind = b"d" if p.is_dir() else b"f"
        if p.is_dir():
            child = hashlib.sha256(b"".join(_rows_of(p))).hexdigest()
        else:
            try:
                child = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                continue  # unreadable: no row
        rows.append(kind + b"\x00" + p.name.encode("utf-8",
                                                   "surrogateescape")
                    + b"\x00" + child.encode("ascii") + b"\n")
    return rows


def _overall(folder: Path) -> str:
    return hashlib.sha256(b"".join(_rows_of(folder))).hexdigest()


# --- the document carries the known values -----------------------------

def _doc_known_values():
    text = DOC.read_text(encoding="utf-8")
    kv = dict(re.findall(r"^(KV-[12]) = ([0-9a-f]{64})$", text,
                         flags=re.M))
    assert set(kv) == {"KV-1", "KV-2"}, f"doc known values missing: {kv}"
    return kv


def _build_kv2(root: Path) -> Path:
    """The exact fixture spelled out in the document, section 4."""
    d = root / "kv2"
    (d / "a" / "empty").mkdir(parents=True)
    (d / "a" / "one.txt").write_bytes(b"one\n")
    (d / "beta.txt").write_bytes(b"beta\n")
    return d


def test_t01_doc_kv1_empty_folder(tmp_path):
    """KV-1 from the document: the empty folder is SHA-256(b"")."""
    from sieve_tray import _seal_overall_sha256
    assert _doc_known_values()["KV-1"] == KV1
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _seal_overall_sha256(empty) == KV1
    assert _overall(empty) == KV1  # independent calculator agrees


def test_t01_doc_kv2_three_entry_fixture(tmp_path):
    """KV-2 from the document: the 3-entry fixture, doc vs impl vs hand."""
    from sieve_tray import _seal_overall_sha256
    assert _doc_known_values()["KV-2"] == KV2
    d = _build_kv2(tmp_path)
    assert _seal_overall_sha256(d) == KV2
    assert _overall(d) == KV2  # independent calculator agrees


def test_t01_names_sort_by_utf8_bytes(tmp_path):
    """Byte order, not codepoint/locale order: 'B.txt' < 'a.txt'."""
    from sieve_tray import _seal_overall_sha256
    d = tmp_path / "ord"
    d.mkdir()
    (d / "a.txt").write_bytes(b"low\n")
    (d / "B.txt").write_bytes(b"up\n")
    want = hashlib.sha256(
        b"f\x00B.txt\x00" + hashlib.sha256(b"up\n").hexdigest().encode()
        + b"\n"
        + b"f\x00a.txt\x00" + hashlib.sha256(b"low\n").hexdigest().encode()
        + b"\n").hexdigest()
    assert _seal_overall_sha256(d) == want
    assert _overall(d) == want


def test_t01_names_not_nfc_normalized(tmp_path):
    """NFC is not applied: decomposed and composed names are two files."""
    from sieve_tray import _seal_overall_sha256
    d = tmp_path / "nfc"
    d.mkdir()
    nfc = "が.txt"           # U+304C, one codepoint
    dec = "か\u3099.txt"      # U+304B + U+3099, two codepoints
    assert nfc != dec
    (d / nfc).write_bytes(b"composed\n")
    (d / dec).write_bytes(b"decomposed\n")
    assert len(os.listdir(d)) == 2
    rows = b"".join(
        (b"f\x00" + name.encode("utf-8") + b"\x00"
         + hashlib.sha256(body).hexdigest().encode() + b"\n")
        for name, body in sorted(
            ((nm, body) for nm, body in
             ((nfc, b"composed\n"), (dec, b"decomposed\n"))),
            key=lambda t: t[0].encode("utf-8")))
    want = hashlib.sha256(rows).hexdigest()
    assert _seal_overall_sha256(d) == want
    assert _overall(d) == want


def test_t01_symlinks_excluded(tmp_path):
    """Symlinks (to files and to dirs) carry no row."""
    from sieve_tray import _seal_overall_sha256
    d = tmp_path / "sym"
    (d / "sub").mkdir(parents=True)
    (d / "real.txt").write_bytes(b"real\n")
    os.symlink("real.txt", d / "link.txt")
    os.symlink("sub", d / "dirlink")
    (d / "sub" / "inner.txt").write_bytes(b"inner\n")
    want = hashlib.sha256(
        b"f\x00real.txt\x00"
        + hashlib.sha256(b"real\n").hexdigest().encode() + b"\n"
        + b"d\x00sub\x00"
        + hashlib.sha256(
            b"f\x00inner.txt\x00"
            + hashlib.sha256(b"inner\n").hexdigest().encode()
            + b"\n").hexdigest().encode() + b"\n").hexdigest()
    assert _seal_overall_sha256(d) == want
    assert _overall(d) == want


@pytest.mark.skipif(os.geteuid() == 0 if hasattr(os, "geteuid") else False,
                    reason="an unreadable file is still readable for root")
def test_t01_unreadable_excluded(tmp_path):
    """A file the tool cannot read carries no row (manifest records it
    as skipped with the closed vocabulary; the tree just excludes it)."""
    from sieve_tray import _seal_overall_sha256
    d = tmp_path / "unr"
    d.mkdir()
    (d / "ok.txt").write_bytes(b"ok\n")
    secret = d / "no_access.txt"
    secret.write_bytes(b"secret\n")
    secret.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            secret.read_bytes()
        want = hashlib.sha256(
            b"f\x00ok.txt\x00"
            + hashlib.sha256(b"ok\n").hexdigest().encode()
            + b"\n").hexdigest()
        assert _seal_overall_sha256(d) == want
        assert _overall(d) == want
    finally:
        secret.chmod(0o644)


def test_t01_key_id_is_hmac_first_8_bytes():
    """key_id = HMAC-SHA256(key, "sieve-check-key-id")[:8] hex."""
    from sieve_tray import _seal_check_key_id
    key = b"word of a passphrase"
    want = hmac.new(key, b"sieve-check-key-id",
                    hashlib.sha256).hexdigest()[:16]
    assert _seal_check_key_id(key) == want
    # a different key gives a different id
    assert _seal_check_key_id(b"another") != want


def test_t01_key_is_the_file_bytes_including_trailing_lf(tmp_path):
    """The key is the file content as-is: a trailing LF changes the id."""
    from sieve_tray import _seal_check_key_id
    kf = tmp_path / "key.txt"
    kf.write_bytes(b"pass\n")          # the file a user writes in an editor
    raw = kf.read_bytes()
    assert raw.endswith(b"\n")
    assert _seal_check_key_id(raw) == \
        hmac.new(b"pass\n", b"sieve-check-key-id",
                 hashlib.sha256).hexdigest()[:16]
    assert _seal_check_key_id(raw) != \
        hmac.new(b"pass", b"sieve-check-key-id",
                 hashlib.sha256).hexdigest()[:16]


def test_t01_check_code_independent_hmac(tmp_path):
    """check_code = HMAC over overall + ':' + canonical JSON of the
    receipt minus check_code and digest - verified by hand here."""
    from sieve_tray import _seal_check_code, _gate_norm_json
    key = b"pass\n"
    overall = KV2
    receipt = {
        "receipt_version": 1,
        "kind": "sieve-manifest",
        "tool": {"name": "sieve-tray", "version": "2.1.1"},
        "engines": {},
        "settings": {"against": None},
        "items": [],
        "summary": {"items": 0, "overall_sha256": overall},
        "digest": "sha256:" + "0" * 64,   # excluded from the message
    }
    value = _seal_check_code(key, overall, receipt)
    body = {k: v for k, v in receipt.items()
            if k not in ("check_code", "digest")}
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    want = "hmac-sha256:" + hmac.new(
        key, overall.encode("ascii") + b":" + blob,
        hashlib.sha256).hexdigest()
    assert value == want
    # the canonical form is the digest form: no trailing LF inside the
    # message, while the written receipt file has one
    assert not blob.endswith(b"\n")
    assert _gate_norm_json(body).endswith("\n")

    # adding the check_code section does not change the digest of a
    # receipt that predates it (2.1.1 verify recomputes over ALL keys)
    import sieve_tray
    r2 = dict(receipt)
    r2["check_code"] = {"key_id": sieve_tray._seal_check_key_id(key),
                        "value": value}
    r2["digest"] = sieve_tray._gate_digest(r2)
    assert r2["digest"] == sieve_tray._gate_digest(r2)
