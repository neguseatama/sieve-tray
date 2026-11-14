"""Seal 2.2 / S7 - draw (request 3.6, SL-T14).

A verifiable draw over a roster: key(x) = SHA-256(seed || NUL || x),
items sorted by key bytes then item bytes, dealt round-robin into k
groups (k = --groups, or ceil(items / --size)).  The grouping with
names lands in local/draw-result.json (written BEFORE the receipt);
the handoff/draw-receipt.json carries the roster hash, the seed, the
parameters and the result hash only - never the names.  The claim
stays limited and the procedure lives in docs/draw-procedure.md with
the two known values KV-D1 / KV-D2, which these tests read back from
the document (doc vs implementation vs an independent hand
calculation cannot drift apart).  The document carries the seed
warning sentence and never claims 公平 or 無作為.
"""
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parent.parent / "docs" / "draw-procedure.md"


def _run_draw(roster, seed, out, **kw):
    from sieve_tray import run_draw
    return run_draw(roster, seed, out, **kw)


def _hand(rows):
    """An independent calculator: the documented procedure, by hand."""
    seed, lines = rows["seed"], rows["lines"]
    if rows["groups"] is not None:
        k = rows["groups"]
    else:
        k = -(-len(lines) // rows["size"])
    keys = {x: hashlib.sha256(seed.encode("utf-8") + b"\x00"
                              + x.encode("utf-8")).hexdigest()
            for x in lines}
    order = sorted(lines, key=lambda x: (bytes.fromhex(keys[x]),
                                         x.encode("utf-8")))
    groups = [[] for _ in range(k)]
    for pos, x in enumerate(order):
        groups[pos % k].append(x)
    rb = b"\n".join(x.encode("utf-8") for x in lines) + b"\n"
    local = (json.dumps({"groups": groups, "ordered": order},
                        ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")) + "\n").encode("utf-8")
    return {"keys": keys, "ordered": order, "groups": groups,
            "roster_sha256": hashlib.sha256(rb).hexdigest(),
            "result_sha256": hashlib.sha256(local).hexdigest(),
            "local_bytes": local}


def _doc_blocks():
    text = DOC.read_text(encoding="utf-8")
    blocks = {}
    for kv in ("KV-D1", "KV-D2"):
        m = re.search(r"### " + kv + r":[\s\S]*?(?=^### |\Z)", text, re.M)
        assert m, "the document lost the %s block" % kv
        blocks[kv] = m.group(0)
    return blocks


def _doc_rows(block):
    """The fixture spelled out in the document block."""

    def one(pattern, cast=str):
        m = re.search(pattern, block, re.M)
        assert m, pattern
        return cast(m.group(1))

    roster = one(r'^roster = "(.*)"$').replace("\\n", "\n")
    seed = one(r'^seed = "(.*)"$')
    if re.search(r"^groups = \d+$", block, re.M):
        k = one(r"^groups = (\d+)$", int)
        size = None
    else:
        size = one(r"^size = (\d+)$", int)
        k = None
    keys = dict(re.findall(r"^key\((\w+)\)\s+= ([0-9a-f]{64})$",
                           block, re.M))
    ordered = json.loads(one(r"^ordered = (\[.*\])$"))
    groups = json.loads(one(r"^groups = (\[\[.*\]\])$"))
    rhash = one(r"^KV-D\d-roster = ([0-9a-f]{64})$")
    lhash = one(r"^KV-D\d-result = ([0-9a-f]{64})$")
    return {"lines": roster.split("\n")[:-1], "seed": seed,
            "groups": k, "size": size, "doc_keys": keys,
            "doc_ordered": ordered, "doc_groups": groups,
            "doc_roster_sha256": rhash, "doc_result_sha256": lhash,
            "roster_text": roster}


def _assert_block(kv):
    rows = _doc_rows(_doc_blocks()[kv])
    hand = _hand(rows)
    # doc vs an independent hand calculation
    assert rows["doc_keys"] == hand["keys"]
    assert rows["doc_ordered"] == hand["ordered"]
    assert rows["doc_groups"] == hand["groups"]
    assert rows["doc_roster_sha256"] == hand["roster_sha256"]
    assert rows["doc_result_sha256"] == hand["result_sha256"]
    # doc vs the implementation's key part
    from sieve_tray import _seal_draw_keys
    assert _seal_draw_keys(rows["seed"],
                           [x.encode("utf-8")
                            for x in rows["lines"]]) == \
        [bytes.fromhex(hand["keys"][x]) for x in rows["lines"]]
    return rows, hand


# ---------------------------------------------------------------------------
# SL-T14: the two known values read back from the document

def test_t14_doc_kv_d1(tmp_path):
    rows, hand = _assert_block("KV-D1")
    roster = tmp_path / "roster.txt"
    roster.write_text(rows["roster_text"], encoding="utf-8", newline="")
    out = tmp_path / "out"
    receipt = _run_draw(roster, rows["seed"], out, groups=rows["groups"])
    result = json.loads((out / "local" / "draw-result.json")
                        .read_text(encoding="utf-8"))
    assert result["ordered"] == hand["ordered"]
    assert result["groups"] == hand["groups"]
    assert receipt["summary"]["roster_sha256"] == \
        "sha256:" + hand["roster_sha256"]
    assert receipt["summary"]["result_sha256"] == \
        "sha256:" + hand["result_sha256"]


def test_t14_doc_kv_d2(tmp_path):
    rows, hand = _assert_block("KV-D2")
    roster = tmp_path / "roster.txt"
    roster.write_text(rows["roster_text"], encoding="utf-8", newline="")
    out = tmp_path / "out"
    receipt = _run_draw(roster, rows["seed"], out, size=rows["size"])
    result = json.loads((out / "local" / "draw-result.json")
                        .read_text(encoding="utf-8"))
    # k = ceil(5 / 2) = 3; the last group is short
    assert result["groups"] == hand["groups"]
    assert [len(g) for g in result["groups"]] == [2, 2, 1]
    assert receipt["summary"]["roster_sha256"] == \
        "sha256:" + hand["roster_sha256"]
    assert receipt["summary"]["result_sha256"] == \
        "sha256:" + hand["result_sha256"]


def test_t14_tie_breaks_by_item_bytes():
    """Same key -> the item bytes decide (a direct comparator test)."""
    from sieve_tray import _seal_draw_order
    items = [b"x", b"A", b"m"]
    same = b"\x01" * 32
    order = _seal_draw_order(items, [same, same, same])
    assert [items[i] for i in order] == [b"A", b"m", b"x"]
    # and the documented hand rule agrees
    assert [items[i] for i in order] == \
        sorted(items, key=lambda b: (same, b))


def test_t14_duplicate_lines_stay_deterministic(tmp_path):
    roster = tmp_path / "roster.txt"
    roster.write_text("bob\nalice\nbob\n", encoding="utf-8", newline="")
    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    r1 = _run_draw(roster, "seed-x", out1, groups=2)
    r2 = _run_draw(roster, "seed-x", out2, groups=2)
    a = (out1 / "local" / "draw-result.json").read_bytes()
    b = (out2 / "local" / "draw-result.json").read_bytes()
    assert a == b  # two runs, byte-identical
    res = json.loads(a)
    assert res["ordered"].count("bob") == 2  # nothing lost
    assert len(res["ordered"]) == 3
    assert r1["summary"]["items"] == 3


# ---------------------------------------------------------------------------
# the receipt: hashes and parameters ride, the names never do

def test_t14_the_roster_never_rides_the_receipt(tmp_path):
    roster = tmp_path / "roster.txt"
    names = ["yamada-taro", "suzuki-hanako", "tanaka-jiro"]
    roster.write_text("\n".join(names) + "\n", encoding="utf-8",
                      newline="")
    out = tmp_path / "out"
    receipt = _run_draw(roster, "public-seed-1", out, groups=2)
    blob = json.dumps(receipt, ensure_ascii=False)
    for name in names:
        assert name not in blob, name
    # the seed is public and rides; the result hash rides
    assert receipt["settings"]["seed"] == "public-seed-1"
    assert receipt["summary"]["result_sha256"].startswith("sha256:")
    assert receipt["summary"]["roster_sha256"].startswith("sha256:")
    # the result itself is local/, not handoff/
    assert not (out / "handoff" / "draw-result.json").exists()
    handoff_files = sorted(p.name for p in (out / "handoff").iterdir())
    assert handoff_files == ["draw-receipt.json"]


def test_t14_receipt_frame_and_digest(tmp_path):
    roster = tmp_path / "roster.txt"
    roster.write_text("a1\nb2\nc3\n", encoding="utf-8", newline="")
    out = tmp_path / "out"
    receipt = _run_draw(roster, "s", out, size=2)
    assert receipt["receipt_version"] == 1
    assert receipt["kind"] == "sieve-draw"
    assert receipt["settings"]["groups"] == 2  # ceil(3 / 2)
    assert receipt["settings"]["size"] == 2
    assert receipt["items"] == [] and receipt["skipped"] == []
    body = {k: v for k, v in receipt.items() if k != "digest"}
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    assert receipt["digest"] == "sha256:" + hashlib.sha256(blob).hexdigest()
    # result_sha256 = the written local file's bytes, directly checkable
    local_bytes = (out / "local" / "draw-result.json").read_bytes()
    assert receipt["summary"]["result_sha256"] == \
        "sha256:" + hashlib.sha256(local_bytes).hexdigest()


def test_t14_the_result_is_written_before_the_receipt(tmp_path,
                                                      monkeypatch):
    import sieve_tray
    roster = tmp_path / "roster.txt"
    roster.write_text("a1\nb2\n", encoding="utf-8", newline="")
    out = tmp_path / "out"
    real = sieve_tray._gate_write_atomic

    def failing(path, data):
        if path.name.endswith("draw-receipt.json"):
            raise OSError("the receipt write fails (order probe)")
        return real(path, data)

    monkeypatch.setattr(sieve_tray, "_gate_write_atomic", failing)
    with pytest.raises(OSError):
        _run_draw(roster, "s", out, groups=1)
    assert (out / "local" / "draw-result.json").exists()


# ---------------------------------------------------------------------------
# closed refusals (exit 2)

def test_t14_refusals(tmp_path):
    from sieve_tray import run_draw
    good = tmp_path / "roster.txt"
    good.write_text("a1\nb2\n", encoding="utf-8", newline="")
    out = tmp_path / "out"
    for kw, exc in (
        ({}, ValueError),  # neither flag
        ({"groups": 2, "size": 1}, ValueError),  # both flags
        ({"groups": 0}, ValueError),  # a useless number of groups
        ({"size": 0}, ValueError),  # a useless size
    ):
        with pytest.raises(ValueError):
            run_draw(good, "s", out, **kw)
    with pytest.raises(ValueError):
        run_draw(tmp_path / "missing.txt", "s", out, groups=1)
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    with pytest.raises(ValueError):
        run_draw(empty, "s", out, groups=1)
    blank = tmp_path / "blank.txt"
    blank.write_bytes(b"a1\n\nb2\n")
    with pytest.raises(ValueError):
        run_draw(blank, "s", out, groups=1)
    notutf8 = tmp_path / "raw.txt"
    notutf8.write_bytes(b"a1\n\xff\xfeb2\n")
    with pytest.raises(ValueError):
        run_draw(notutf8, "s", out, groups=1)


def test_t14_cli_neither_or_both_flags_exit_2(tmp_path):
    from sieve_tray import _gate_main
    roster = tmp_path / "roster.txt"
    roster.write_text("a1\nb2\n", encoding="utf-8", newline="")
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as e1:
        _gate_main(["draw", str(roster), "--seed", "s",
                    "-o", str(out)])
    assert e1.value.code == 2
    with pytest.raises(SystemExit) as e2:
        _gate_main(["draw", str(roster), "--seed", "s",
                    "--groups", "2", "--size", "1", "-o", str(out)])
    assert e2.value.code == 2


# ---------------------------------------------------------------------------
# the document carries the warning and never overclaims

def test_t14_document_wording():
    text = DOC.read_text(encoding="utf-8")
    assert "seed は、結果を見る前に公開してください" in text
    assert "公平" not in text
    assert "無作為" not in text
    assert "処理記録" in text  # the glossary wording, not 受領書
