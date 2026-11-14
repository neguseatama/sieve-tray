"""Seal 2.2 / S4 - pack and unpack (request 3.1 P1-P12).

pack is a deterministic zip: entries in relative-path byte order
(a directory sorts by its bare path and carries a trailing slash in
the archive; a.txt < a/b because 0x2E < 0x2F), the timestamp pinned to
1980-01-01 00:00:00, create_system 3, external attrs 0o100644 for
files and 0o040755 plus the DOS directory bit for directories, the
UTF-8 flag on non-ASCII names, ZIP_STORED by default and --deflate on
file entries only (directory entries stay STORED under both flags).
The zip lands at -o itself and the receipt lands at the zip's
neighbor handoff/pack-receipt.json, carrying zip_sha256 and the
manifest's whole-folder checksum.

unpack runs the safety checks over EVERY entry before creating
anything: an absolute path, a .. component, a drive letter or a
collision (exact, casefold, or a file entry nested inside another
file entry) refuses with zero extraction and the closed 4 symbols.
A foreign zip (real timestamps, DEFLATED, no directory entries)
passes the same checks.
"""
import hashlib
import json
import os
import zipfile

import pytest

from pathlib import Path


def _run_pack(folder, zip_path, **kw):
    from sieve_tray import run_pack
    return run_pack(folder, zip_path, **kw)


def _run_unpack(zip_path, out, **kw):
    from sieve_tray import run_unpack
    return run_unpack(zip_path, out, **kw)


def _make_src(root: Path) -> Path:
    d = root / "src"
    (d / "sub").mkdir(parents=True)
    (d / "empty").mkdir()
    (d / "a.txt").write_bytes(b"alpha\n")
    (d / "sub" / "deta.txt").write_bytes(b"deta\n")
    (d / "sub" / "data.txt").write_bytes(b"data\n")
    (d / "日本語.txt").write_bytes(b"nihongo\n".decode().encode())
    return d


def _zip_infos(zpath: Path):
    with zipfile.ZipFile(zpath) as z:
        return list(z.infolist())


# ---------------------------------------------------------------------------
# SL-T08: the deterministic pack

def test_t08_pack_is_deterministic(tmp_path):
    """Two packs of the same folder are byte-identical, and every
    entry carries the 1980-01-01 00:00:00 stamp."""
    src = _make_src(tmp_path / "s1")
    src2 = _make_src(tmp_path / "s2")
    z1 = tmp_path / "z1.zip"
    z2 = tmp_path / "z2.zip"
    _run_pack(src, z1)
    _run_pack(src2, z2)
    b1, b2 = z1.read_bytes(), z2.read_bytes()
    assert b1 == b2
    assert hashlib.sha256(b1).hexdigest() == \
        hashlib.sha256(b2).hexdigest()
    for zi in _zip_infos(z1):
        assert zi.date_time == (1980, 1, 1, 0, 0, 0)
        assert zi.create_system == 3


def test_t08_entry_order_is_bare_path_bytes(tmp_path):
    """Directories sort by their bare path and ride with a trailing
    slash; a.txt < a/b (0x2E < 0x2F) < sub/..."""
    src = _make_src(tmp_path)
    z = tmp_path / "z.zip"
    _run_pack(src, z)
    names = [zi.filename for zi in _zip_infos(z)]
    bare = [n[:-1] if n.endswith("/") else n for n in names]
    assert bare == sorted(bare, key=lambda s: s.encode("utf-8"))
    assert "a.txt" in names and "sub/deta.txt" in names
    assert names.index("a.txt") < names.index("sub/")
    assert "sub/" in names and "empty/" in names
    assert all(n.endswith("/") for n in names if n in ("sub/", "empty/"))


def test_t08_metadata_fixed_and_utf8_flag(tmp_path):
    """create_system 3; file 0o100644; dir 0o040755 with the DOS
    directory bit; the Japanese name carries the UTF-8 flag while the
    ASCII names do not."""
    src = _make_src(tmp_path)
    z = tmp_path / "z.zip"
    _run_pack(src, z)
    infos = {zi.filename: zi for zi in _zip_infos(z)}
    fi = infos["a.txt"]
    assert fi.external_attr >> 16 == 0o100644
    di = infos["sub/"]
    assert di.external_attr >> 16 == 0o040755
    assert di.external_attr & 0x10 == 0x10     # DOS directory bit
    assert di.compress_type == zipfile.ZIP_STORED
    jp = infos["日本語.txt"]
    assert jp.flag_bits & 0x800 == 0x800       # UTF-8 flag
    assert infos["a.txt"].flag_bits & 0x800 == 0


def test_t08_deflate_files_only_and_the_note(tmp_path):
    """--deflate compresses file entries only; directory entries stay
    STORED under both flags; the receipt records the zlib note
    verbatim; the default is STORED."""
    from sieve_tray import _seal_manifest_scan  # noqa: F401 (context)
    src = _make_src(tmp_path)
    z_plain = tmp_path / "plain.zip"
    r_plain = _run_pack(src, z_plain)
    assert all(zi.compress_type == zipfile.ZIP_STORED
               for zi in _zip_infos(z_plain))
    assert "note" not in r_plain["settings"]
    z_def = tmp_path / "def.zip"
    r_def = _run_pack(src, z_def, deflate=True)
    infos = {zi.filename: zi for zi in _zip_infos(z_def)}
    assert infos["a.txt"].compress_type == zipfile.ZIP_DEFLATED
    assert infos["sub/"].compress_type == zipfile.ZIP_STORED
    assert infos["empty/"].compress_type == zipfile.ZIP_STORED
    assert r_def["settings"]["note"] == \
        "バイト列の一致は、同じ zlib でのみ保証されます"


def test_t08_zip_and_overall_hashes_match_manifest(tmp_path):
    """summary.zip_sha256 is the hash of the written zip and
    summary.overall_sha256 equals the manifest's whole-folder
    checksum for the same folder."""
    from sieve_tray import run_manifest
    src = _make_src(tmp_path)
    z = tmp_path / "z.zip"
    receipt = _run_pack(src, z)
    assert receipt["summary"]["zip_sha256"] == \
        "sha256:" + hashlib.sha256(z.read_bytes()).hexdigest()
    mreceipt = run_manifest(src, tmp_path / "mout")
    assert receipt["summary"]["overall_sha256"] == \
        mreceipt["summary"]["overall_sha256"]


def test_t08_cli_end_to_end_and_placement(tmp_path, capsys):
    """P11: pack <folder> -o <zip> - the zip lands at -o itself and
    the receipt lands at the zip's neighbor handoff/; the zip's parent
    must already exist (the pre-check)."""
    from sieve_tray import _gate_main
    src = _make_src(tmp_path)
    out = tmp_path / "out"
    out.mkdir()                      # the parent of the zip must exist
    z = out / "bundle.zip"
    rc = _gate_main(["pack", str(src), "-o", str(z)])
    assert rc == 0
    assert z.is_file()
    receipt = json.loads(
        (out / "handoff" / "pack-receipt.json").read_text(encoding="utf-8"))
    assert receipt["kind"] == "sieve-pack"
    assert receipt["summary"]["zip_sha256"] == \
        "sha256:" + hashlib.sha256(z.read_bytes()).hexdigest()


def test_t08_pack_safety_rules(tmp_path):
    """The zip must be new, its parent must exist, and it must not sit
    inside the input folder (the input's neighbor is the normal
    shape); an unreadable file goes to skipped, not into the zip."""
    from sieve_tray import run_pack
    src = _make_src(tmp_path)
    with pytest.raises(ValueError):
        run_pack(src, src / "inside.zip")          # inside the input
    with pytest.raises(ValueError):
        run_pack(src, tmp_path / "no" / "such" / "x.zip")  # no parent
    z = tmp_path / "z.zip"
    z.write_bytes(b"occupied")
    with pytest.raises(ValueError):
        run_pack(src, z)                            # not new
    z.unlink()
    secret = src / "secret.bin"
    secret.write_bytes(b"do not pack\n")
    secret.chmod(0o000)
    try:
        if os.geteuid() == 0 if hasattr(os, "geteuid") else False:
            pytest.skip("an unreadable file is readable for root")
        receipt = _run_pack(src, z)
    finally:
        secret.chmod(0o644)
    assert [s["path"] for s in receipt["skipped"]] == ["secret.bin"]
    with zipfile.ZipFile(z) as zf:
        assert "secret.bin" not in zf.namelist()


def test_t08_check_code_section(tmp_path):
    """--key-file adds the check_code section; receipt_version stays 1."""
    src = _make_src(tmp_path)
    kf = tmp_path / "key.txt"
    kf.write_bytes(b"pack-key\n")
    receipt = _run_pack(src, tmp_path / "z.zip", key_file=kf)
    assert receipt["receipt_version"] == 1
    assert receipt["check_code"]["key_id"]
    assert receipt["check_code"]["value"].startswith("hmac-sha256:")


# ---------------------------------------------------------------------------
# SL-T09: the safe unpack

def _pack_foreign(tmp_path):
    """A zip that Tray did not make: real timestamps, DEFLATED, no
    directory entries at all (so no empty directory can ride)."""
    src = tmp_path / "f-src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_bytes(b"alpha\n")
    (src / "sub" / "deta.txt").write_bytes(b"deta\n")
    (src / "sub" / "data.txt").write_bytes(b"data\n")
    z = tmp_path / "foreign.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(src))
    return z, src


def test_t09_roundtrip_is_byte_identical(tmp_path):
    """pack -> unpack reproduces the tree byte for byte and the
    whole-folder checksums agree; the empty directory comes back."""
    src = _make_src(tmp_path)
    z = tmp_path / "z.zip"
    _run_pack(src, z)
    out = tmp_path / "out"
    receipt = _run_unpack(z, out)
    assert receipt["settings"]["extracted"] == 4  # the file entries
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        q = out / rel
        assert q.exists(), f"missing {rel}"
        if p.is_file():
            assert q.read_bytes() == p.read_bytes()
    from sieve_tray import _seal_overall_sha256
    assert receipt["summary"]["overall_sha256"] == \
        _seal_overall_sha256(src)


def test_t09_six_refusal_forms_extract_nothing(tmp_path):
    """absolute / parent_ref / drive_letter / exact collision /
    casefold collision / file-inside-file: all refuse with zero
    extraction, the closed symbols, and the receipt still written."""
    from sieve_tray import _seal_manifest_scan  # noqa: F401
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("ok.txt", b"fine\n")
        zf.writestr("/abs.txt", b"abs\n")                    # absolute
        zf.writestr("a/../../esc.txt", b"esc\n")             # parent_ref
        zf.writestr("C:/drive.txt", b"drv\n")                # drive
        zf.writestr("dup.txt", b"one\n")
        zf.writestr("dup.txt", b"two\n")                     # exact dup
        zf.writestr("Case.txt", b"c\n")
        zf.writestr("case.txt", b"c\n")                      # casefold
        zf.writestr("nested/file.txt", b"n\n")
        zf.writestr("nested/file.txt/inner.txt", b"i\n")     # in-file
    out = tmp_path / "out"
    receipt = _run_unpack(z, out)
    refused = {(e["path"], e["symbol"]) for e in receipt["refused"]}
    assert ("/abs.txt", "absolute_path") in refused
    assert ("a/../../esc.txt", "parent_ref") in refused
    assert ("C:/drive.txt", "drive_letter") in refused
    assert ("dup.txt", "collision") in refused
    assert ("case.txt", "collision") in refused
    assert ("nested/file.txt/inner.txt", "collision") in refused
    # nothing from the archive reached the disk (only the receipt)
    assert not (out / "ok.txt").exists()
    assert not (out / "nested").exists()
    assert (out / "handoff" / "unpack-receipt.json").is_file()
    assert receipt["settings"]["extracted"] == 0
    s = receipt["summary"]
    assert s["absolute_path"] == 1 and s["parent_ref"] == 1
    assert s["drive_letter"] == 1 and s["collision"] == 3


def test_t09_backslash_parent_form_caught(tmp_path):
    """The checks read backslashes as separators too: a\\..\\..\\evil
    is a parent_ref."""
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a\\..\\..\\evil.txt", b"e\n")
    out = tmp_path / "out"
    receipt = _run_unpack(z, out)
    assert receipt["refused"] == [
        {"path": "a\\..\\..\\evil.txt", "symbol": "parent_ref"}]
    assert not (out / "evil.txt").exists()


def test_t09_foreign_zip_passes_the_same_checks(tmp_path):
    """P10: a foreign zip (real timestamps, DEFLATED, no dir entries)
    unpacks like our own."""
    z, src = _pack_foreign(tmp_path)
    out = tmp_path / "out"
    receipt = _run_unpack(z, out)
    assert receipt["refused"] == []
    assert (out / "a.txt").read_bytes() == b"alpha\n"
    assert (out / "sub" / "data.txt").read_bytes() == b"data\n"
    from sieve_tray import _seal_overall_sha256
    assert receipt["summary"]["overall_sha256"] == \
        _seal_overall_sha256(src)


def test_t09_receipt_shape_and_archive_handoff_merge(tmp_path):
    """settings carries extracted / zip_sha256 / zip_name; an archive
    that ships its own handoff/ merges, and our receipt stays the
    last word in it."""
    z = tmp_path / "z.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("data.txt", b"d\n")
        zf.writestr("handoff/note.txt", b"from the sender\n")
    out = tmp_path / "out"
    receipt = _run_unpack(z, out)
    s = receipt["settings"]
    assert s["zip_name"] == "z.zip"
    assert s["zip_sha256"] == \
        "sha256:" + hashlib.sha256(z.read_bytes()).hexdigest()
    assert s["extracted"] == 2  # data.txt + the archive's handoff note
    assert (out / "handoff" / "note.txt").read_bytes() == \
        b"from the sender\n"
    # our receipt is the last word in the merged handoff
    rc_mtime = (out / "handoff" / "unpack-receipt.json")
    assert rc_mtime.is_file()
    assert rc_mtime.stat().st_mtime_ns >= \
        (out / "handoff" / "note.txt").stat().st_mtime_ns


def test_t09_cli_exit_codes(tmp_path, capsys):
    """The CLI: a refused unpack exits 1 with the receipt written; a
    clean unpack exits 0."""
    from sieve_tray import _gate_main
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../esc.txt", b"e\n")
    out = tmp_path / "out1"
    rc = _gate_main(["unpack", str(evil), "-o", str(out)])
    assert rc == 1
    assert (out / "handoff" / "unpack-receipt.json").is_file()
    assert not (out / "esc.txt").exists()
    good, _src = _pack_foreign(tmp_path / "g")
    out2 = tmp_path / "out2"
    rc = _gate_main(["unpack", str(good), "-o", str(out2)])
    assert rc == 0
    assert (out2 / "a.txt").is_file()


def test_t09_empty_folder_roundtrip(tmp_path):
    """An empty folder packs into an entry-less zip (the overall is
    KV-1) and unpacks into an empty tree (the overall is KV-1)."""
    from sieve_tray import _seal_overall_sha256
    KV1 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    src = tmp_path / "nothing"
    src.mkdir()
    z = tmp_path / "empty.zip"
    receipt = _run_pack(src, z)
    assert _zip_infos(z) == []           # zero entries
    assert receipt["summary"]["overall_sha256"] == KV1
    assert receipt["summary"]["files"] == 0
    out = tmp_path / "out"
    r2 = _run_unpack(z, out)
    assert r2["refused"] == []
    assert r2["settings"]["extracted"] == 0
    # the receipt's overall was computed BEFORE its own handoff/ was
    # written, so the empty tree is KV-1 on the receipt; the disk then
    # carries exactly the receipt's handoff (the last word)
    assert r2["summary"]["overall_sha256"] == KV1
    assert sorted(p.name for p in out.iterdir()) == ["handoff"]
    assert [p.name for p in (out / "handoff").iterdir()] == \
        ["unpack-receipt.json"]
