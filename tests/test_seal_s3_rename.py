"""Seal 2.2 / S3 - rename and audit-names (request 3.1 R1-R8).

rename never touches the source: the default is a plan only, and
--apply builds a new-name tree at the -o copy destination (the source
stays byte-identical).  Collisions are detected at the plan stage and
the run refuses instead of auto-renaming.  The rule fields are closed
({seq} / {seq:width} / {stem} / {ext} / {hash8} / {parent}); the
handoff receipt carries the rule, the counts, the collisions and the
mapping HASH only - names never leave in the handoff; the mapping
table is local/rename-plan.json and --no-paths turns it into seq
numbers.

audit-names reports path + symbol only (no fixes), for files AND
directories, with the closed 8 symbols; a name that is not valid
UTF-8 rides as path: null + path_hex.
"""
import hashlib
import json
import os

import pytest

from pathlib import Path


def _run_rename(folder, out, **kw):
    from sieve_tray import run_rename
    return run_rename(folder, out, **kw)


def _run_audit_names(folder, **kw):
    from sieve_tray import run_audit_names
    return run_audit_names(folder, **kw)


def _make_src(root: Path) -> Path:
    d = root / "src"
    (d / "sub").mkdir(parents=True)
    (d / "report.txt").write_bytes(b"report body\n")
    (d / "sub" / "data.csv").write_bytes(b"a,b\n1,2\n")
    (d / "plain.md").write_bytes(b"# plain\n")
    return d


# ---------------------------------------------------------------------------
# SL-T05: the rename plan and the apply

def test_t05_plan_only_changes_nothing(tmp_path):
    """R1: the default is a plan; the source keeps every byte and no
    new tree appears anywhere."""
    src = _make_src(tmp_path)
    before = {p: p.read_bytes() for p in src.rglob("*") if p.is_file()}
    out = tmp_path / "out"
    receipt = _run_rename(src, out, pattern="{seq:3}-{stem}{ext}")
    assert receipt["kind"] == "sieve-rename"
    assert receipt["settings"]["apply"] is False
    after = {p: p.read_bytes() for p in src.rglob("*") if p.is_file()}
    assert before == after          # source untouched
    assert set(p for p in src.rglob("*") if p.is_file()) == set(before)
    assert (out / "local" / "rename-plan.json").is_file()


def test_t05_apply_builds_the_copy_at_destination(tmp_path):
    """R1: --apply builds the renamed tree at -o; the source stays
    byte-identical and the relative directories are unchanged."""
    src = _make_src(tmp_path)
    out = tmp_path / "out"
    receipt = _run_rename(src, out, pattern="{stem}-v2{ext}",
                          apply=True)
    assert receipt["settings"]["apply"] is True
    # the source is untouched
    assert (src / "report.txt").read_bytes() == b"report body\n"
    assert (src / "sub" / "data.csv").is_file()
    # the destination carries the new names under the same dirs
    dst = out / "renamed"
    assert (dst / "report-v2.txt").read_bytes() == b"report body\n"
    assert (dst / "sub" / "data-v2.csv").read_bytes() == b"a,b\n1,2\n"
    assert (dst / "plain-v2.md").read_bytes() == b"# plain\n"
    assert not (dst / "report.txt").exists()


def test_t05_rule_fields_and_unknown_refusal(tmp_path):
    """R2: the five fields expand; an unknown field is refused."""
    src = _make_src(tmp_path)
    out = tmp_path / "out"
    receipt = _run_rename(src, out,
                          pattern="{seq:3}|{parent}|{hash8}|{stem}{ext}")
    plan = json.loads(
        (out / "local" / "rename-plan.json").read_text(encoding="utf-8"))
    mapping = {e["from"]: e["to"] for e in plan["mapping"]}
    h_plain = hashlib.sha256(b"# plain\n").hexdigest()[:8]
    h_report = hashlib.sha256(b"report body\n").hexdigest()[:8]
    h_data = hashlib.sha256(b"a,b\n1,2\n").hexdigest()[:8]
    # seq follows the byte-ascending order of the relative paths; a
    # root-level file has no parent inside the tree ({parent} = "")
    assert mapping["plain.md"] == f"001||{h_plain}|plain.md"
    assert mapping["report.txt"] == f"002||{h_report}|report.txt"
    # the rule shapes the BASENAME; the relative directory is unchanged
    assert mapping["sub/data.csv"] == f"sub/003|sub|{h_data}|data.csv"
    with pytest.raises(ValueError):
        _run_rename(src, tmp_path / "out2",
                    pattern="{seq}-{date}.txt")   # unknown field
    with pytest.raises(ValueError):
        _run_rename(src, tmp_path / "out3", pattern="{stem{ext}")


# ---------------------------------------------------------------------------
# SL-T06: collisions and the no-names rule

def _make_collision(root: Path) -> Path:
    d = root / "src"
    d.mkdir(parents=True)
    (d / "one.txt").write_bytes(b"1\n")
    (d / "two.txt").write_bytes(b"2\n")
    (d / "three.txt").write_bytes(b"3\n")
    return d


def test_t06_collision_detected_before_any_creation(tmp_path):
    """R3: a pattern that maps two files onto one name is a collision
    at the plan stage; --apply refuses and leaves nothing behind."""
    src = _make_collision(tmp_path)
    out = tmp_path / "out"
    receipt = _run_rename(src, out, pattern="same{ext}")
    assert receipt["summary"]["collisions"] >= 1
    assert receipt["summary"]["collision"] == ["rename_collision"]
    assert not (out / "renamed").exists()          # plan wrote no tree
    rc_apply = _run_rename(src, out, pattern="same{ext}",
                           apply=True)
    assert rc_apply["summary"]["collision"] == ["rename_collision"]
    assert not (out / "renamed").exists()          # refused, no tree
    # the source is still intact
    assert (src / "one.txt").read_bytes() == b"1\n"


def test_t06_names_never_reach_the_handoff(tmp_path):
    """R7: the handoff carries the mapping HASH only; the mapping table
    lives in local/rename-plan.json; --no-paths turns it into seq
    numbers."""
    src = _make_src(tmp_path)
    out = tmp_path / "out"
    receipt = _run_rename(src, out, pattern="{seq:2}-{stem}{ext}")
    handoff_raw = (out / "handoff" / "rename-receipt.json").read_bytes()
    for name in (b"report", b"data", b"plain", b"sub"):
        assert name not in handoff_raw, \
            f"the name {name!r} leaked into the handoff"
    assert "mapping_sha256" in receipt["summary"]
    plan = json.loads(
        (out / "local" / "rename-plan.json").read_text(encoding="utf-8"))
    blob = json.dumps(plan["mapping"], ensure_ascii=False,
                      sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    assert receipt["summary"]["mapping_sha256"] == \
        "sha256:" + hashlib.sha256(blob).hexdigest()
    # --no-paths: the plan's from-side speaks in seq numbers only
    # (the to-side carries the new names the rule actually makes)
    out2 = tmp_path / "out2"
    _run_rename(src, out2, pattern="{seq:2}-{stem}{ext}", no_paths=True)
    plan2 = json.loads(
        (out2 / "local" / "rename-plan.json").read_text(encoding="utf-8"))
    assert all(e["from"].startswith("#") for e in plan2["mapping"])
    assert not any("report" in e["from"] or "data" in e["from"]
                   for e in plan2["mapping"])


# ---------------------------------------------------------------------------
# SL-T07: audit-names, the closed 8 symbols

def test_t07_seven_symbols_measured_on_disk(tmp_path):
    """The symbols a Linux disk can hold are all measured: reserved,
    forbidden char, trailing dot/space, too-long path, case collision,
    normalization collision - files and directories alike."""
    d = tmp_path / "tree"
    (d / "sub dir").mkdir(parents=True)          # a directory is audited
    (d / "CON.txt").write_bytes(b"r\n")            # reserved_name_win
    (d / "a<b.txt").write_bytes(b"f\n")            # forbidden_char_win
    (d / "dot.").write_bytes(b"t\n")               # trailing_dot_or_space
    (d / "space ").write_bytes(b"t\n")             # trailing_dot_or_space
    (d / "A.txt").write_bytes(b"c\n")              # case_collision
    (d / "a.txt").write_bytes(b"c\n")              # case_collision
    nfc = "cafe\u0301.txt"                         # NFD
    nfd = "caf\u00e9.txt"                          # NFC
    (d / nfc).write_bytes(b"n\n")
    (d / nfd).write_bytes(b"n\n")
    deep = d / "sub dir"
    for i in range(8):
        deep = deep / f"level-{i:02d}-padding-padding-padding"
    deep.mkdir(parents=True, exist_ok=True)
    (deep / "deep.txt").write_bytes(b"d\n")        # too_long_path
    receipt = _run_audit_names(d)
    got = {}
    for e in receipt["items"]:
        for sym in e["symbols"]:
            got.setdefault(sym, []).append(e.get("path"))
    assert set(got) >= {
        "reserved_name_win", "forbidden_char_win",
        "trailing_dot_or_space", "too_long_path", "case_collision",
        "normalization_collision"}
    # the report is path + symbol only - no fixes, no advice
    for e in receipt["items"]:
        assert set(e) <= {"path", "path_hex", "symbols"}
    assert receipt["kind"] == "sieve-audit-names"


def test_t07_too_long_name_in_the_pure_classifier():
    """A >255-byte basename cannot exist on a Linux disk, so the
    classifier is a pure function and is tested directly."""
    from sieve_tray import _seal_name_symbols
    # "a"*252 + ".txt" = 256 bytes -> over the limit
    assert "too_long_name" in _seal_name_symbols("a" * 252 + ".txt",
                                                 "a" * 252 + ".txt",
                                                 [])
    # "a"*251 + ".txt" = 255 bytes -> exactly at the limit, not over
    assert "too_long_name" not in _seal_name_symbols(
        "a" * 251 + ".txt", "a" * 251 + ".txt", [])
    assert "too_long_name" not in _seal_name_symbols(
        "ok.txt", "ok.txt", [])


def test_t07_not_utf8_name_rides_as_path_hex(tmp_path):
    """A name that is not valid UTF-8 cannot ride in JSON: path null +
    path_hex, and the not_utf8_name symbol."""
    d = tmp_path / "tree"
    d.mkdir()
    raw_name = b"bad\xff name.txt"
    (d / raw_name.decode("utf-8", "surrogateescape")).write_bytes(b"x\n")
    (d / "ok.txt").write_bytes(b"o\n")
    receipt = _run_audit_names(d)
    bad = [e for e in receipt["items"] if e.get("path") is None]
    assert len(bad) == 1
    assert bad[0]["path_hex"] == raw_name.hex()
    assert "not_utf8_name" in bad[0]["symbols"]
    ok = [e for e in receipt["items"] if e.get("path") == "ok.txt"]
    assert len(ok) == 1 and ok[0]["symbols"] == []


def test_t07_audit_cli_and_exit(tmp_path, capsys):
    """The audit-names subcommand runs from the CLI and prints the
    digest; the receipt file lands in handoff/."""
    from sieve_tray import _gate_main
    d = tmp_path / "tree"
    d.mkdir()
    (d / "CON.txt").write_bytes(b"r\n")
    out = tmp_path / "out"
    rc = _gate_main(["audit-names", str(d), "-o", str(out)])
    assert rc == 0
    receipt = json.loads(
        (out / "handoff" / "audit-names-receipt.json")
        .read_text(encoding="utf-8"))
    assert receipt["kind"] == "sieve-audit-names"
    syms = [e["symbols"] for e in receipt["items"]
            if e.get("path") == "CON.txt"]
    assert syms == [["reserved_name_win"]]


def test_t06_casefold_collision_refused(tmp_path):
    """A destination pair that differs only by case would collide on
    Windows and macOS defaults: the plan reports rename_collision and
    the apply refuses (no auto-renaming exists)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "X.txt").write_bytes(b"up\n")
    (src / "x.txt").write_bytes(b"low\n")
    out = tmp_path / "out"
    receipt = _run_rename(src, out, pattern="{stem}{ext}", apply=True)
    assert receipt["summary"]["collision"] == ["rename_collision"]
    assert receipt["summary"]["collisions"] >= 1
    assert not (out / "renamed").exists()
    # a rule that folds the case resolves it: the apply then builds
    receipt2 = _run_rename(src, out, pattern="{seq}-{stem}{ext}",
                           apply=True)
    assert receipt2["summary"]["collision"] == []
    assert (out / "renamed" / "1-X.txt").read_bytes() == b"up\n"
    assert (out / "renamed" / "2-x.txt").read_bytes() == b"low\n"


def test_t07_audit_no_paths_and_symbol_counts(tmp_path):
    """--no-paths reports seq numbers in audit order; the summary
    carries the symbol counts."""
    d = tmp_path / "tree"
    d.mkdir()
    (d / "CON.txt").write_bytes(b"r\n")
    (d / "a<b.txt").write_bytes(b"f\n")
    (d / "clean.txt").write_bytes(b"c\n")
    receipt = _run_audit_names(d, no_paths=True)
    assert [e["seq"] for e in receipt["items"]] == [1, 2, 3]
    assert all("path" not in e and "path_hex" not in e
               for e in receipt["items"])
    s = receipt["summary"]["symbols"]
    assert s.get("reserved_name_win") == 1
    assert s.get("forbidden_char_win") == 1
    assert sum(s.values()) == 2  # clean.txt carries no symbol
