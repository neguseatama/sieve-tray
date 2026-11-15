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
import shutil

import pytest

from pathlib import Path

from seal_platform import can_create_names


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

def test_t07_symbols_measured_on_disk_when_the_disk_holds_them(tmp_path):
    """The disk-measured half of the audit symbols: every lane asks the
    disk first (seal_platform.can_create_names) and skips when this
    volume cannot hold the name - a Linux CI volume holds all of them,
    a Windows/macOS default holds the subset it can.  The symbols
    themselves stay covered on all three OSes by the pure classifier
    test (CI #90, 2026-11-15)."""
    d = tmp_path / "tree"
    (d / "sub dir").mkdir(parents=True)          # a directory is audited
    nfd = "cafe\u0301.txt"                       # decomposed
    nfc = "caf\u00e9.txt"                         # composed
    wanted = set()
    if can_create_names(tmp_path, ["CON.txt"]):
        (d / "CON.txt").write_bytes(b"r\n")
        wanted.add("reserved_name_win")
    if can_create_names(tmp_path, ["a<b.txt"]):
        (d / "a<b.txt").write_bytes(b"f\n")
        wanted.add("forbidden_char_win")
    if can_create_names(tmp_path, ["dot."]):
        (d / "dot.").write_bytes(b"t\n")
        wanted.add("trailing_dot_or_space")
    if can_create_names(tmp_path, ["space "]):
        (d / "space ").write_bytes(b"t\n")
        wanted.add("trailing_dot_or_space")
    if can_create_names(tmp_path, ["A.txt", "a.txt"]):
        (d / "A.txt").write_bytes(b"c\n")
        (d / "a.txt").write_bytes(b"c\n")
        wanted.add("case_collision")
    if can_create_names(tmp_path, [nfd, nfc]):
        (d / nfd).write_bytes(b"n\n")
        (d / nfc).write_bytes(b"n\n")
        wanted.add("normalization_collision")
    # too_long_path: a >240-byte relative path; probed OUTSIDE the
    # audited tree first, because a Windows volume refuses the mkdir
    chain = "/".join(f"level-{i:02d}-padding-padding-padding"
                     for i in range(8))
    deep_rel = "sub dir/" + chain + "/deep.txt"
    probe = tmp_path / "_seal_deep_probe"
    deep_ok = True
    try:
        (probe / deep_rel).parent.mkdir(parents=True)
        (probe / deep_rel).write_bytes(b"d\n")
    except (OSError, ValueError):
        deep_ok = False
    finally:
        shutil.rmtree(probe, ignore_errors=True)
    if deep_ok:
        deep = d / "sub dir"
        for i in range(8):
            deep = deep / f"level-{i:02d}-padding-padding-padding"
        deep.mkdir(parents=True, exist_ok=True)
        (deep / "deep.txt").write_bytes(b"d\n")
        wanted.add("too_long_path")
    receipt = _run_audit_names(d)
    got = set()
    for e in receipt["items"]:
        got.update(e["symbols"])
    assert wanted <= got
    # the report is path + symbol only - no fixes, no advice
    for e in receipt["items"]:
        assert set(e) <= {"path", "path_hex", "symbols"}
    assert receipt["kind"] == "sieve-audit-names"


def test_t07_the_pure_classifier_reads_every_symbol():
    """The closed 8 symbols through the pure classifier, name list in,
    symbol list out - no disk involved, so the names a Windows/macOS
    volume refuses to hold (the reserved device name, the forbidden
    char, the trailing dot/space, the case-fold pair, the NFC/NFD
    pair, a name that is not valid UTF-8) are covered on every OS
    (CI #90, 2026-11-15)."""
    from sieve_tray import _seal_name_symbols
    assert _seal_name_symbols("CON.txt", "CON.txt", []) == \
        ["reserved_name_win"]
    assert _seal_name_symbols("a<b.txt", "a<b.txt", []) == \
        ["forbidden_char_win"]
    assert _seal_name_symbols("dot.", "dot.", []) == \
        ["trailing_dot_or_space"]
    assert _seal_name_symbols("space ", "space ", []) == \
        ["trailing_dot_or_space"]
    # a >255-byte basename cannot exist on any disk, so its rel path
    # is over the path limit too and the two symbols fire together
    assert "too_long_name" in _seal_name_symbols(
        "a" * 252 + ".txt", "a" * 252 + ".txt", [])
    assert _seal_name_symbols("x.txt", "sub dir/" + "x" * 241, []) == \
        ["too_long_path"]
    bad = b"bad\xff name.txt".decode("utf-8", "surrogateescape")
    assert _seal_name_symbols(bad, bad, []) == ["not_utf8_name"]
    assert _seal_name_symbols("a.txt", "a.txt", ["A.txt"]) == \
        ["case_collision"]
    nfc = "が.txt"                    # U+304C, one codepoint
    dec = "か\u3099.txt"              # U+304B + U+3099, two codepoints
    assert _seal_name_symbols(dec, dec, [nfc]) == \
        ["normalization_collision"]
    # a clean name stays clean
    assert _seal_name_symbols("ok.txt", "ok.txt", []) == []


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
    path_hex, and the not_utf8_name symbol.  The disk half runs only
    where the volume holds such a name; the symbol itself stays
    covered on every OS by the pure classifier (CI #90, 2026-11-15)."""
    d = tmp_path / "tree"
    d.mkdir()
    raw_name = b"bad\xff name.txt"
    suri = raw_name.decode("utf-8", "surrogateescape")
    if not can_create_names(tmp_path, [suri]):
        pytest.skip("this disk refuses a name that is not valid UTF-8")
    (d / suri).write_bytes(b"x\n")
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
    digest; the receipt file lands in handoff/.  The flagged-name
    lane rides a creatable name: where the volume refuses CON.txt the
    run stays shape-only (CI #90, 2026-11-15)."""
    from sieve_tray import _gate_main
    d = tmp_path / "tree"
    d.mkdir()
    flagged = can_create_names(tmp_path, ["CON.txt"])
    if flagged:
        (d / "CON.txt").write_bytes(b"r\n")
    out = tmp_path / "out"
    rc = _gate_main(["audit-names", str(d), "-o", str(out)])
    assert rc == 0
    receipt = json.loads(
        (out / "handoff" / "audit-names-receipt.json")
        .read_text(encoding="utf-8"))
    assert receipt["kind"] == "sieve-audit-names"
    if flagged:
        syms = [e["symbols"] for e in receipt["items"]
                if e.get("path") == "CON.txt"]
        assert syms == [["reserved_name_win"]]
    else:
        assert all(not e["symbols"] for e in receipt["items"])


def test_t06_the_plan_collision_counter_is_pure():
    """The plan-stage collision count over the DESTINATION name list -
    a pure function, so the pairs a case-folding or normalizing volume
    cannot hold are covered on every OS (CI #90, 2026-11-15)."""
    from sieve_tray import _seal_plan_collisions
    assert _seal_plan_collisions(["one.txt", "two.txt"]) == 0
    assert _seal_plan_collisions(["same.txt", "same.txt"]) == 1   # exact
    assert _seal_plan_collisions(["X.txt", "x.txt"]) == 1        # casefold
    assert _seal_plan_collisions(["が.txt", "か\u3099.txt"]) == 1  # NFC
    assert _seal_plan_collisions([None]) == 1      # non-UTF-8 source name
    assert _seal_plan_collisions(["a"], dir_rels={"a"}) == 1     # onto a dir
    assert _seal_plan_collisions(
        ["X.txt", "x.txt", "same.txt", "same.txt"]) == 2


def test_t06_casefold_collision_refused(tmp_path):
    """A destination pair that differs only by case would collide on
    Windows and macOS defaults: the plan reports rename_collision and
    the apply refuses (no auto-renaming exists).  The disk half needs
    a volume that holds the X/x pair; where the volume folds case the
    lane skips and the pure counter test above carries the refusal on
    every OS (CI #90, 2026-11-15)."""
    if not can_create_names(tmp_path, ["X.txt", "x.txt"]):
        pytest.skip("this volume folds case - the pure counter test "
                    "covers the refusal")
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
    carries the symbol counts.  The flagged lanes ride creatable
    names, so the seq/count shape is measured on every OS (CI #90,
    2026-11-15; a Linux CI volume holds both and keeps the full
    1/2/3 + 1/1/2 measurement)."""
    d = tmp_path / "tree"
    d.mkdir()
    (d / "clean.txt").write_bytes(b"c\n")
    wanted = []
    if can_create_names(tmp_path, ["CON.txt"]):
        (d / "CON.txt").write_bytes(b"r\n")
        wanted.append("reserved_name_win")
    if can_create_names(tmp_path, ["a<b.txt"]):
        (d / "a<b.txt").write_bytes(b"f\n")
        wanted.append("forbidden_char_win")
    receipt = _run_audit_names(d, no_paths=True)
    assert [e["seq"] for e in receipt["items"]] == \
        list(range(1, 1 + len(wanted) + 1))
    assert all("path" not in e and "path_hex" not in e
               for e in receipt["items"])
    s = receipt["summary"]["symbols"]
    for sym in wanted:
        assert s.get(sym) == 1
    assert sum(s.values()) == len(wanted)  # clean.txt carries no symbol
