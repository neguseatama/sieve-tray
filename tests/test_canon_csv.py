"""Canon 2.3.0 / stage 4 - the CSV normalization (CN-T15, request
§3.4): quoting only when needed, the doubled quotes, the untouched
cell values, the observed (never fixed) ragged rows, the explicit
--sort-by byte order, and the idempotence.
"""
import json

from pathlib import Path

import pytest


def _norm(text, **kw):
    from sieve_canon import _cn_csv_normalize_text
    return _cn_csv_normalize_text(text, **kw)


def _normtext(text, **kw):
    return _norm(text, **kw)[0]


def test_csv_quotes_only_when_needed():
    out = _normtext('a,b,c\n1,2,3\n"x,y",z\n')
    assert out == 'a,b,c\n1,2,3\n"x,y",z\n'
    # a plain value is never quoted
    assert out.splitlines()[1] == "1,2,3"


def test_csv_quotes_delimiter_quote_and_newline_only():
    out = _normtext('a,b\nplain,"has,comma"\n')
    lines = out.splitlines()
    assert lines[1] == 'plain,"has,comma"'
    out = _normtext('a,b\nplain,"say ""hi"""\n')
    assert out.splitlines()[1] == 'plain,"say ""hi"""'
    out = _normtext('a,b\nplain,"two\nlines"\n')
    assert 'plain,"two\nlines"' in out


def test_csv_values_are_untouched():
    """No whitespace stripping, no number rewriting - the cells ride
    as-is (§3.4-2)."""
    out = _normtext('a,b\n 1.50 ,007\n')
    assert out == 'a,b\n 1.50 ,007\n'
    rows = list(__import__("csv").reader(out.splitlines()))
    assert rows[1] == [" 1.50 ", "007"]


def test_csv_header_stays_first_and_rows_keep_lf():
    out = _normtext('z,a\r\n9,1\n8,2\n')
    assert out == 'z,a\n9,1\n8,2\n'
    assert out.splitlines()[0] == "z,a"


def test_csv_newline_crlf():
    out = _normtext('a,b\n1,2\n', newline="crlf")
    assert out == 'a,b\r\n1,2\r\n'


def test_csv_ragged_rows_observed_not_fixed():
    """A short row stays short; the count lands in the receipt item
    (§3.4-3)."""
    src_text = 'a,b,c\n1,2\n3,4,5\n'
    out, info = _norm(src_text)
    assert out.splitlines()[1] == "1,2"          # not fixed
    assert info["ragged_rows"] == 1
    assert info["columns"] == 3


def test_csv_sort_by_byte_order_stable():
    """--sort-by sorts the rows by the UTF-8 bytes of the named
    column (A < a < b in byte order); equal keys keep the original
    order (the stable sort, §3.4-4)."""
    out, _info = _norm('name,n\nb,1\nA,2\na,3\nb,4\n',
                       sort_by=("name",))
    assert out.splitlines() == ["name,n", "A,2", "a,3", "b,1", "b,4"]


def test_csv_sort_by_two_columns():
    out, _info = _norm('g,n\nx,2\ny,1\nx,1\ny,2\n',
                       sort_by=("g", "n"))
    assert out.splitlines() == ["g,n", "x,1", "x,2", "y,1", "y,2"]


def test_csv_no_sort_by_default():
    out, _info = _norm('n\nz\na\n')
    assert out == 'n\nz\na\n'


def test_csv_delimiter_option():
    out, info = _norm('a;b\n"x;y";2\n', delimiter=";")
    assert out == 'a;b\n"x;y";2\n'
    assert info["columns"] == 2


def test_csv_idempotent_and_roundtrip_equal():
    import csv as _csv
    import io as _io
    src = 'a,b\n1,"x,y"\n"multi\nline",2\n'
    once, _ = _norm(src)
    twice, _ = _norm(once)
    assert once == twice

    def table(t):
        return list(_csv.reader(_io.StringIO(t, newline="")))
    assert table(src) == table(twice)      # the values survive


def test_csv_malformed_quotes_are_refused():
    from sieve_canon import _cn_csv_normalize_text, CNCSVError
    with pytest.raises(CNCSVError) as e:
        _cn_csv_normalize_text('a,b\n"x"y,2\n')
    assert e.value.reason == "parse_failed"    # the existing closed word


def test_csv_via_normalize_command(tmp_path):
    src = tmp_path / "in.csv"
    src.write_bytes(b'a,b\r\n1,"x,y"\n2,3\n')
    out = tmp_path / "out"
    from sieve_canon import run_normalize
    receipt = run_normalize(src, out)
    item = receipt["items"][0]
    assert item["status"] == "produced"
    assert (out / "handoff" / "in.csv").read_text(encoding="utf-8") == \
        'a,b\n1,"x,y"\n2,3\n'
    assert item["csv"]["ragged_rows"] == 0
    assert item["csv"]["columns"] == 2


def test_csv_receipt_does_not_carry_the_values(tmp_path):
    marker = "SIEVE-CSV-PRIVATE"
    src = tmp_path / "in.csv"
    src.write_bytes(('a,b\n1,' + marker + '\n').encode("utf-8"))
    out = tmp_path / "out"
    from sieve_canon import run_normalize
    receipt = run_normalize(src, out)
    assert marker not in json.dumps(receipt, ensure_ascii=False)
