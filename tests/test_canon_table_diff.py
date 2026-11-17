"""Canon 2.3.0 / stage 5 - the table diff (CN-T16, CN-T17, request
§3.5): the closed 5 states, the complex keys, the column differences
(A only / B only), the duplicate-key rows excluded from the
comparison, the missing key column refused with exit 2, and the
privacy rule: the values, the key values and the column names never
enter handoff/ (the raw-byte search), the local report carries them.
"""
import json
import subprocess
import sys

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

KEY_A = "SIEVE-KEY-A-01"
KEY_B = "SIEVE-KEY-B-02"


def _run_diff(a, b, out, key, **kw):
    from sieve_canon import run_table_diff
    return run_table_diff(Path(a), Path(b), key, Path(out), **kw)


def _write_csv(path, text):
    Path(path).write_text(text, encoding="utf-8", newline="")


# ---------------------------------------------------------------------------
# CN-T16: the 5 states, the columns, the duplicate keys

def test_five_states_and_column_diff(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, "id,score,note,only_a\n"
               + "1,10,kept,extra\n"
               + "2,20,changed,extra\n"
               + "3,30,removed,extra\n")
    _write_csv(b, "id,score,note,only_b\n"
               + "1,10,kept,added\n"
               + "2,21,changed,added\n"
               + "4,40,new,added\n")
    out = tmp_path / "out"
    receipt = _run_diff(a, b, out, ("id",))
    s = receipt["summary"]
    assert s["rows_same"] == 1
    assert s["rows_changed"] == 1
    assert s["rows_removed"] == 1
    assert s["rows_added"] == 1
    assert s["duplicate_keys"] == 0
    assert s["columns_common"] == 3     # id, score, note
    assert s["columns_a_only"] == 1     # only_a
    assert s["columns_b_only"] == 1     # only_b
    # the receipt carries counts and checksums only - no items
    assert receipt["items"] == []


def test_duplicate_keys_are_counted_not_compared(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, "id,v\n1,x\n1,y\n2,z\n")
    _write_csv(b, "id,v\n1,w\n9,q\n")
    out = tmp_path / "out"
    receipt = _run_diff(a, b, out, ("id",))
    s = receipt["summary"]
    # key 1 is duplicated in A -> not compared; key 2 -> removed; 9 -> added
    assert s["duplicate_keys"] == 1
    assert s["rows_removed"] == 1
    assert s["rows_added"] == 1
    assert s["rows_same"] == 0
    assert s["rows_changed"] == 0


def test_complex_key_and_changed_columns(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, "id,region,v\n" + KEY_A + ",jp,old\n")
    _write_csv(b, "id,region,v\n" + KEY_A + ",jp,new\n")
    out = tmp_path / "out"
    receipt = _run_diff(a, b, out, ("id", "region"))
    s = receipt["summary"]
    assert s["rows_changed"] == 1
    # the key columns are stored as the indices, never the names
    assert receipt["settings"]["key_columns"] == [0, 1]


def test_handoff_never_carries_values_keys_or_names(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, "secret_id,score\n" + KEY_A + ",10\n")
    _write_csv(b, "secret_id,score\n" + KEY_A + ",99\n")
    out = tmp_path / "out"
    _run_diff(a, b, out, ("secret_id",))
    raw = b""
    for p in (out / "handoff").rglob("*"):
        if p.is_file():
            raw += p.read_bytes()
    assert KEY_A.encode("utf-8") not in raw       # the key value
    assert b"secret_id" not in raw                # the column name
    assert b"score" not in raw                    # the column name
    # the local report carries the row-level detail instead
    local = (out / "local" / "table-diff-report.html").read_text(
        encoding="utf-8")
    assert KEY_A in local
    assert "secret_id" in local


def test_normalized_checksums_in_the_summary(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, "id,v\r\n1,x\r\n")              # CRLF input
    _write_csv(b, "id,v\n1,x\n")
    out = tmp_path / "out"
    receipt = _run_diff(a, b, out, ("id",))
    s = receipt["summary"]
    # both sides normalize to the same bytes -> same checksum, same row
    import hashlib
    want = "sha256:" + hashlib.sha256(b"id,v\n1,x\n").hexdigest()
    assert s["a_normalized_sha256"] == want
    assert s["b_normalized_sha256"] == want
    assert s["rows_same"] == 1


def test_receipt_uses_the_shared_frame(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, "id,v\n1,x\n")
    _write_csv(b, "id,v\n1,x\n")
    out = tmp_path / "out"
    receipt = _run_diff(a, b, out, ("id",))
    assert receipt["receipt_version"] == 1
    assert receipt["kind"] == "sieve-table-diff"
    from sieve_tray import _gate_digest
    assert receipt["digest"] == _gate_digest(receipt)


# ---------------------------------------------------------------------------
# CN-T17: the refusals and the per-side encodings

def test_missing_key_column_refuses_exit_2(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, "id,v\n1,x\n")
    _write_csv(b, "code,v\n1,x\n")                # no id column
    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "sieve_tray.py", "table-diff", str(a), str(b),
         "--key", "id", "-o", str(out)],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 2
    assert not (out / "handoff").exists()


def test_missing_key_column_in_a_also_refuses(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, "code,v\n1,x\n")
    _write_csv(b, "id,v\n1,x\n")
    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "sieve_tray.py", "table-diff", str(a), str(b),
         "--key", "id", "-o", str(out)],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 2


def test_from_encoding_a_and_b(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_bytes("id,名前\n1,表計算\n".encode("cp932"))
    b.write_bytes("id,名前\n1,表計算\n".encode("utf-8"))
    out = tmp_path / "out"
    receipt = _run_diff(a, b, out, ("id",),
                        from_encoding_a="cp932")
    assert receipt["summary"]["rows_same"] == 1


def test_undecodable_input_refuses_with_closed_words(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, "id,v\n1,x\n")
    b.write_bytes(b"id,v\n1,\xff\n")              # no BOM, invalid UTF-8
    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "sieve_tray.py", "table-diff", str(a), str(b),
         "--key", "id", "-o", str(out)],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 2
    assert "encoding_unknown" in proc.stdout
    assert not (out / "handoff").exists()
