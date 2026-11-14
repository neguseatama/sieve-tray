"""Seal 2.2 / S2 - the manifest command: the file list, the duplicates,
the diff against a second folder, and the CLI (request 3.1 M1-M11).

The receipt keeps the 2.1.1 frame (receipt_version 1 stays) and is
written LAST into handoff/; there is no local/ tree for a manifest.
The diff mode pairs a removed path with an added path only when the
SHA-256 group is identical, only the first pair in path-ascending
order per group, and the leftover candidates keep their original
state while every multi-candidate group adds one ambiguous_move.
"""
import hashlib
import json
import os

import pytest

from pathlib import Path


def _run_manifest(input_dir, output_dir, **kw):
    from sieve_tray import run_manifest
    return run_manifest(input_dir, output_dir, **kw)


def _make_fixture(root: Path) -> Path:
    """A small tree with subfolders, a symlink, and two equal files."""
    d = root / "in"
    (d / "sub").mkdir(parents=True)
    (d / "a.txt").write_bytes(b"alpha\n")
    (d / "sub" / "one.txt").write_bytes(b"one\n")
    (d / "sub" / "copy_of_one.txt").write_bytes(b"one\n")
    (d / "B.txt").write_bytes(b"upper\n")
    os.symlink("a.txt", d / "link.txt")
    return d


def _digest_ok(receipt) -> bool:
    from sieve_tray import _gate_digest
    return receipt["digest"] == _gate_digest(receipt)


# ---------------------------------------------------------------------------
# SL-T02: the single-mode manifest

def test_t02_scan_order_and_items(tmp_path):
    """Regular files only, relative POSIX paths, UTF-8 byte ascending,
    NFC never applied; symlinks go to skipped with the closed word."""
    from sieve_tray import UNOBSERVED_REASONS
    d = _make_fixture(tmp_path)
    receipt = _run_manifest(d, tmp_path / "out")
    paths = [it["path"] for it in receipt["items"]]
    # B (0x42) sorts before a (0x61): byte order, not locale order;
    # inside sub/ 'copy_of_one.txt' < 'one.txt' ('c' < 'o')
    assert paths == ["B.txt", "a.txt", "sub/copy_of_one.txt",
                     "sub/one.txt"]
    it = receipt["items"][0]
    assert it == {"path": "B.txt", "bytes": 6,
                  "sha256": hashlib.sha256(b"upper\n").hexdigest()}
    skipped = {s["path"]: s["reason"] for s in receipt["skipped"]}
    assert skipped == {"link.txt": "symlink_skipped"}
    assert set(skipped.values()) <= UNOBSERVED_REASONS


def test_t02_receipt_frame_and_last_write(tmp_path):
    """The 2.1.1 frame, digest recomputes, no local/, receipt last."""
    d = _make_fixture(tmp_path)
    out = tmp_path / "out"
    receipt = _run_manifest(d, out)
    assert receipt["receipt_version"] == 1
    assert receipt["kind"] == "sieve-manifest"
    assert receipt["tool"] == {"name": "sieve-tray",
                               "version": "2.1.1"}
    assert receipt["settings"]["against"] is None
    assert _digest_ok(receipt)
    handoff = out / "handoff"
    assert (handoff / "manifest-receipt.json").is_file()
    assert not (out / "local").exists()  # a manifest has no local tree
    raw = (handoff / "manifest-receipt.json").read_bytes()
    assert raw.endswith(b"\n")         # the canonical form, one LF
    rc_mtime = (handoff / "manifest-receipt.json").stat().st_mtime_ns
    for p in handoff.rglob("*"):
        if p.is_file() and p.name != "manifest-receipt.json":
            assert p.stat().st_mtime_ns <= rc_mtime


def test_t02_overall_matches_the_document_known_value(tmp_path):
    """summary.overall_sha256 is the hash tree of section 1 of the doc."""
    from sieve_tray import _seal_overall_sha256
    d = tmp_path / "kv2"
    (d / "a" / "empty").mkdir(parents=True)
    (d / "a" / "one.txt").write_bytes(b"one\n")
    (d / "beta.txt").write_bytes(b"beta\n")
    receipt = _run_manifest(d, tmp_path / "out")
    assert receipt["summary"]["overall_sha256"] == \
        "06965d1ff8239b8e9efad9c88d05e8624d92ac3dd252d047617c82c0de724a92"
    assert receipt["summary"]["overall_sha256"] == \
        _seal_overall_sha256(d)


def test_t02_cli_end_to_end(tmp_path, capsys):
    """sieve-tray manifest <folder> -o <out> runs and prints the digest."""
    from sieve_tray import _gate_main
    d = _make_fixture(tmp_path)
    out = tmp_path / "out"
    rc = _gate_main(["manifest", str(d), "-o", str(out)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "manifest" in err or out.joinpath(
        "handoff", "manifest-receipt.json").is_file()
    assert out.joinpath("handoff", "manifest-receipt.json").is_file()
    receipt = json.loads(
        out.joinpath("handoff", "manifest-receipt.json")
        .read_text(encoding="utf-8"))
    assert receipt["kind"] == "sieve-manifest"
    assert _digest_ok(receipt)


def test_t02_check_code_section_is_optional(tmp_path):
    """--key-file adds one check_code section; without it there is
    none; receipt_version stays 1 either way."""
    d = _make_fixture(tmp_path)
    kf = tmp_path / "key.txt"
    kf.write_bytes(b"pass\n")
    r_plain = _run_manifest(d, tmp_path / "out1")
    assert "check_code" not in r_plain
    r_key = _run_manifest(d, tmp_path / "out2",
                          key_file=kf)
    assert r_key["receipt_version"] == 1
    cc = r_key["check_code"]
    assert set(cc) == {"key_id", "value"}
    assert cc["value"].startswith("hmac-sha256:")
    assert len(cc["value"]) == len("hmac-sha256:") + 64
    # the same key reproduces the same code over the same receipt body
    from sieve_tray import _seal_check_code
    assert cc["value"] == _seal_check_code(
        b"pass\n", r_key["summary"]["overall_sha256"], r_key)
    assert _digest_ok(r_key)


# ---------------------------------------------------------------------------
# SL-T03: the duplicates (byte comparison confirms)

def test_t03_duplicate_groups_byte_confirmed(tmp_path):
    """Two byte-equal files group; the group carries the ascending
    paths and the summary counts groups, files and bytes."""
    d = tmp_path / "in"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "x.bin").write_bytes(b"same bytes here\n")
    (d / "a-dup.bin").write_bytes(b"same bytes here\n")
    (d / "unique.txt").write_bytes(b"unique\n")
    receipt = _run_manifest(d, tmp_path / "out")
    groups = receipt["duplicates"]
    assert len(groups) == 1
    g = groups[0]
    assert g["sha256"] == hashlib.sha256(b"same bytes here\n").hexdigest()
    assert g["paths"] == ["a-dup.bin", "sub/x.bin"]
    s = receipt["summary"]
    assert s["duplicate_groups"] == 1
    assert s["duplicate_files"] == 2
    assert s["duplicate_bytes"] == 2 * len(b"same bytes here\n")


def test_t03_no_group_without_duplicates(tmp_path):
    """All-unique trees report zero groups and no entries."""
    d = tmp_path / "in"
    d.mkdir()
    (d / "a").write_bytes(b"a\n")
    (d / "b").write_bytes(b"b\n")
    receipt = _run_manifest(d, tmp_path / "out")
    assert receipt["duplicates"] == []
    assert receipt["summary"]["duplicate_groups"] == 0


def test_t03_byte_comparison_is_the_confirmation():
    """The group confirmation compares bytes, not only hashes: the
    helper answers false for differing bytes of the same length."""
    from sieve_tray import _seal_bytes_equal
    a = tmp_a = Path("/nonexistent-a")  # placeholder, real files below
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        f1 = t / "f1"; f1.write_bytes(b"content-1\n")
        f2 = t / "f2"; f2.write_bytes(b"content-1\n")
        f3 = t / "f3"; f3.write_bytes(b"content-2\n")
        assert _seal_bytes_equal(f1, f2) is True
        assert _seal_bytes_equal(f1, f3) is False


# ---------------------------------------------------------------------------
# SL-T04: the diff (--against) with the 5 closed states

def _make_a(root: Path) -> Path:
    a = root / "a"
    a.mkdir(parents=True)
    (a / "keep.txt").write_bytes(b"keep\n")
    (a / "changed.txt").write_bytes(b"old\n")
    (a / "gone.txt").write_bytes(b"gone-content\n")
    (a / "moved-name.txt").write_bytes(b"same-moved-bytes\n")
    (a / "dup1.txt").write_bytes(b"dup-bytes\n")
    (a / "dup2.txt").write_bytes(b"dup-bytes\n")
    return a


def _make_b(root: Path) -> Path:
    b = root / "b"
    b.mkdir(parents=True)
    (b / "keep.txt").write_bytes(b"keep\n")
    (b / "changed.txt").write_bytes(b"new\n")
    (b / "fresh.txt").write_bytes(b"fresh\n")
    (b / "renamed.txt").write_bytes(b"same-moved-bytes\n")
    (b / "dup3.txt").write_bytes(b"dup-bytes\n")
    (b / "dup4.txt").write_bytes(b"dup-bytes\n")
    return b


def _diff_map(receipt):
    out = {}
    for e in receipt["differences"]:
        key = e.get("path_b") if e["state"] in ("moved",) else e["path"]
        out[(e["state"], key)] = e
    return out


def test_t04_four_states_and_moved_pairing(tmp_path):
    """same / changed / removed / added / moved - and a moved pair is
    bound by the sha group, first pair in path order only."""
    a, b = _make_a(tmp_path), _make_b(tmp_path)
    receipt = _run_manifest(a, tmp_path / "out", against=b)
    dm = _diff_map(receipt)
    assert dm[("same", "keep.txt")]["sha256"] == \
        hashlib.sha256(b"keep\n").hexdigest()
    assert dm[("changed", "changed.txt")]["sha256_a"] != \
        dm[("changed", "changed.txt")]["sha256_b"]
    assert dm[("removed", "gone.txt")]
    assert dm[("added", "fresh.txt")]
    mv = dm[("moved", "renamed.txt")]
    assert mv["path"] == "moved-name.txt"
    assert mv["path_b"] == "renamed.txt"
    # dup1/dup2 (removed) vs dup3/dup4 (added): one group, several
    # candidates -> only ONE pair moves (the first in path order),
    # the rest keep their state, and the group adds ambiguous_move 1
    assert dm[("moved", "dup3.txt")]["path"] == "dup1.txt"
    assert dm[("removed", "dup2.txt")]
    assert dm[("added", "dup4.txt")]
    s = receipt["summary"]
    assert (s["same"], s["changed"], s["removed"], s["added"],
            s["moved"]) == (1, 1, 2, 2, 2)
    assert s["ambiguous_move"] == 1


def test_t04_diff_receipt_shape_and_states_closed(tmp_path):
    """The diff receipt empties items/skipped/duplicates, carries the
    B overall in settings, and uses only the closed 5 states."""
    from sieve_tray import _seal_overall_sha256
    a, b = _make_a(tmp_path), _make_b(tmp_path)
    receipt = _run_manifest(a, tmp_path / "out", against=b)
    assert receipt["items"] == []
    assert receipt["skipped"] == []
    assert receipt["duplicates"] == []
    assert receipt["settings"]["overall_b"] == _seal_overall_sha256(b)
    assert {e["state"] for e in receipt["differences"]} <= {
        "same", "changed", "removed", "added", "moved"}
    assert receipt["summary"]["overall_sha256"] != \
        receipt["settings"]["overall_b"]
    assert _digest_ok(receipt)


def test_t04_diff_cli_exit_codes(tmp_path, capsys):
    """The CLI: differences give 1, an identical pair gives 0."""
    from sieve_tray import _gate_main
    a, b = _make_a(tmp_path), _make_b(tmp_path)
    out = tmp_path / "out"
    rc = _gate_main(["manifest", str(a), "--against", str(b),
                     "-o", str(out)])
    assert rc == 1  # there are differences
    # a clean pair exits 0
    a2 = tmp_path / "a2"; a2.mkdir()
    (a2 / "x.txt").write_bytes(b"x\n")
    b2 = tmp_path / "b2"; b2.mkdir()
    (b2 / "x.txt").write_bytes(b"x\n")
    rc = _gate_main(["manifest", str(a2), "--against", str(b2),
                     "-o", str(tmp_path / "out2")])
    assert rc == 0


def test_t02_skipped_special_and_unreadable_dir(tmp_path):
    """One walk records every refusal with the closed vocabulary: a
    FIFO is not_applicable, an unlistable directory is unreadable, and
    a file under an unreadable directory never becomes an item."""
    from sieve_tray import UNOBSERVED_REASONS
    d = tmp_path / "in"
    (d / "ok").mkdir(parents=True)
    (d / "ok" / "f.txt").write_bytes(b"f\n")
    os.mkfifo(d / "pipe")                      # special file
    locked = d / "locked"
    locked.mkdir()
    (locked / "hidden.txt").write_bytes(b"hidden\n")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("an unreadable dir is listable for root")
    locked.chmod(0o000)
    try:
        receipt = _run_manifest(d, tmp_path / "out")
    finally:
        locked.chmod(0o755)
    paths = [it["path"] for it in receipt["items"]]
    assert paths == ["ok/f.txt"]
    skipped = {(s["path"], s["reason"]) for s in receipt["skipped"]}
    assert ("pipe", "not_applicable") in skipped
    assert ("locked", "unreadable") in skipped
    # the walk cannot see inside an unlistable directory, so the dir
    # itself carries the reason for its whole subtree
    assert all(not p.startswith("locked/") for p, _r in skipped)
    assert {r for _p, r in skipped} <= UNOBSERVED_REASONS
    # the whole-folder checksum sees only what the walk could read:
    # a mirror folder with just ok/f.txt hashes the same
    from sieve_tray import _seal_overall_sha256
    mirror = tmp_path / "mirror"
    (mirror / "ok").mkdir(parents=True)
    (mirror / "ok" / "f.txt").write_bytes(b"f\n")
    assert receipt["summary"]["overall_sha256"] == \
        _seal_overall_sha256(mirror)


def test_t04_diff_order_is_deterministic(tmp_path):
    """The differences list: A-side entries by their A path bytes,
    added entries by their B path bytes after them - byte order, not
    locale order, and stable across runs."""
    a, b = _make_a(tmp_path), _make_b(tmp_path)
    r1 = _run_manifest(a, tmp_path / "out1", against=b)
    r2 = _run_manifest(a, tmp_path / "out2", against=b)
    keys1 = [(e["state"], e["path"]) for e in r1["differences"]]
    keys2 = [(e["state"], e["path"]) for e in r2["differences"]]
    assert keys1 == keys2
    a_keys = [(e["state"], e["path"]) for e in r1["differences"]
              if e["state"] != "added"]
    assert a_keys == sorted(a_keys, key=lambda t: t[1].encode("utf-8"))
    added = [(e["state"], e["path"]) for e in r1["differences"]
             if e["state"] == "added"]
    assert added == sorted(added, key=lambda t: t[1].encode("utf-8"))
    # no path is reported twice (a moved path is not also removed)
    paths = [e["path"] for e in r1["differences"]]
    assert len(paths) == len(set(paths))
