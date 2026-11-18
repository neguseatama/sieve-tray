"""Canon 2.3.0 / stage 3 - the JSON normalization: the pretty style
(CN-T13) and the JCS style against the real RFC 8785 Appendix B
vectors (CN-T14)  (request §3.3).

The Appendix B table was obtained from rfc-editor.org (reported in
§2-5); the vectors here are the exact IEEE 754 hex values of that
table, so the number serializer is pinned to the published samples
including the -0, the 5e-324 and the round-to-even row.
"""
import json
import struct

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# CN-T13: the pretty style (request §3.3-1, §3.3-2, §3.3-4)

def test_pretty_sorts_keys_and_indents_two():
    from sieve_canon import _cn_json_pretty
    out = _cn_json_pretty('{"b": 1, "a": {"d": 2, "c": 3}}')
    assert out == '{\n  "a": {\n    "c": 3,\n    "d": 2\n  },\n  "b": 1\n}\n'


def test_pretty_keeps_array_order_and_non_ascii():
    from sieve_canon import _cn_json_pretty
    out = _cn_json_pretty('{"z": [3, 1, 2], "あ": 1}')
    assert json.loads(out)["z"] == [3, 1, 2]
    assert '"あ"' in out          # ensure_ascii = false
    # the keys are sorted by the codepoint ("z" = U+007A < "あ" = U+3042)
    assert out.index('"z"') < out.index('"あ"')


def test_pretty_preserves_large_integers():
    from sieve_canon import _cn_json_pretty
    big = 123456789012345678901234567890
    out = _cn_json_pretty('{"n": %d}' % big)
    assert json.loads(out)["n"] == big


def test_pretty_refuses_duplicate_keys():
    from sieve_canon import _cn_json_pretty, CNJsonError
    with pytest.raises(CNJsonError) as e:
        _cn_json_pretty('{"a": 1, "a": 2}')
    assert e.value.reason == "json_duplicate_key"


def test_pretty_refuses_nan_and_infinity():
    from sieve_canon import _cn_json_pretty, CNJsonError
    with pytest.raises(CNJsonError) as e:
        _cn_json_pretty('{"a": NaN}')
    assert e.value.reason == "json_invalid_number"
    with pytest.raises(CNJsonError) as e:
        _cn_json_pretty('{"a": Infinity}')
    assert e.value.reason == "json_invalid_number"


def test_pretty_is_idempotent_and_meaning_stable():
    from sieve_canon import _cn_json_pretty
    src = '{"b": [1, {"d": 2, "c": 3}], "a": 4.50}'
    once = _cn_json_pretty(src)
    twice = _cn_json_pretty(once)
    assert once == twice
    assert json.loads(src) == json.loads(once)


def test_pretty_via_normalize_command(tmp_path):
    src = tmp_path / "in.json"
    src.write_bytes(b'{"b": 1, "a": 2}')
    out = tmp_path / "out"
    from sieve_canon import run_normalize
    receipt = run_normalize(src, out)
    assert receipt["items"][0]["status"] == "produced"
    assert (out / "handoff" / "in.json").read_text(encoding="utf-8") == \
        '{\n  "a": 2,\n  "b": 1\n}\n'


# ---------------------------------------------------------------------------
# CN-T14: the JCS style (request §3.3-3, §3.3-5) - the RFC 8785
# Appendix B vectors, the real ones from rfc-editor.org

# (IEEE 754 hex, the expected ECMAScript serialization) - the exact
# rows of RFC 8785 Appendix B "Number Serialization Samples"
RFC8785_APPENDIX_B = [
    ("0000000000000000", "0"),
    ("8000000000000000", "0"),                    # minus zero
    ("0000000000000001", "5e-324"),
    ("8000000000000001", "-5e-324"),
    ("7fefffffffffffff", "1.7976931348623157e+308"),
    ("ffefffffffffffff", "-1.7976931348623157e+308"),
    ("4340000000000000", "9007199254740992"),
    ("c340000000000000", "-9007199254740992"),
    ("4430000000000000", "295147905179352830000"),
    ("44b52d02c7e14af5", "9.999999999999997e+22"),
    ("44b52d02c7e14af6", "1e+23"),
    ("44b52d02c7e14af7", "1.0000000000000001e+23"),
    ("444b1ae4d6e2ef4e", "999999999999999700000"),
    ("444b1ae4d6e2ef4f", "999999999999999900000"),
    ("444b1ae4d6e2ef50", "1e+21"),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7"),
    ("3eb0c6f7a0b5ed8d", "0.000001"),
    ("41b3de4355555553", "333333333.3333332"),
    ("41b3de4355555554", "333333333.33333325"),
    ("41b3de4355555555", "333333333.3333333"),
    ("41b3de4355555556", "333333333.3333334"),
    ("41b3de4355555557", "333333333.33333343"),
    ("becbf647612f3696", "-0.0000033333333333333333"),
    ("43143ff3c1cb0959", "1424953923781206.2"),   # round to even
]


@pytest.mark.parametrize("hex754,expected", RFC8785_APPENDIX_B)
def test_jcs_number_matches_rfc8785_appendix_b(hex754, expected):
    from sieve_canon import _cn_es_number
    value = struct.unpack(">d", bytes.fromhex(hex754))[0]
    assert _cn_es_number(value) == expected


def test_jcs_number_refuses_nan_and_infinity():
    from sieve_canon import _cn_es_number, CNJsonError
    with pytest.raises(CNJsonError) as e:
        _cn_es_number(float("nan"))
    assert e.value.reason == "json_invalid_number"
    with pytest.raises(CNJsonError) as e:
        _cn_es_number(float("inf"))
    assert e.value.reason == "json_invalid_number"


def test_jcs_sorts_keys_by_utf16_code_units():
    """The §3.2.3 sorting vector of RFC 8785: the 7 property names and
    the expected order after the UTF-16 code-unit sort.  Only the
    ASCII control range uses the \\uhhhh form; U+0080 and above stay
    as-is (§3.2.2.2), so the locator builds the raw quoted forms."""
    from sieve_canon import _cn_json_jcs, _cn_jcs_str
    names = ["\u20ac", "\r", "\ufb33", "1", "\U0001f600",
             "\u0080", "\u00f6"]
    obj = {n: i for i, n in enumerate(reversed(names))}
    out = _cn_json_jcs(json.dumps(obj))
    expected_order = ["\r", "1", "\u0080", "\u00f6", "\u20ac",
                      "\U0001f600", "\ufb33"]
    pos = [out.index(_cn_jcs_str(k)) for k in expected_order]
    assert pos == sorted(pos)


def test_jcs_string_escaping_matches_rfc8785():
    """The §3.2.2 string vector, checked against the canonical form
    extracted from the §3.2.4 byte vector (the RFC's own expected
    bytes - no hand-built literal here)."""
    from sieve_canon import _cn_json_jcs, _cn_jcs_str
    src = ('{"string": "\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022'
           '\\u005c\\\\\\"\\/"}')
    value = json.loads(src)["string"]
    expected_hex = (
        "7b 22 6c 69 74 65 72 61 6c 73 22 3a 5b 6e 75 6c 6c 2c 74 72 "
        "75 65 2c 66 61 6c 73 65 5d 2c 22 6e 75 6d 62 65 72 73 22 3a "
        "5b 33 33 33 33 33 33 33 33 33 2e 33 33 33 33 33 33 33 2c 31 "
        "65 2b 33 30 2c 34 2e 35 2c 30 2e 30 30 32 2c 31 65 2d 32 37 "
        "5d 2c 22 73 74 72 69 6e 67 22 3a 22 e2 82 ac 24 5c 75 30 30 "
        "30 66 5c 6e 41 27 42 5c 22 5c 5c 5c 5c 5c 22 2f 22 7d")
    doc = bytes.fromhex(expected_hex.replace(" ", "")).decode("utf-8")
    fragment = doc.split('"string":"', 1)[1].rsplit('"', 1)[0]
    assert _cn_jcs_str(value) == '"' + fragment + '"' 


def test_jcs_full_document_matches_rfc8785_bytes():
    """The §3.2.2 -> §3.2.3 -> §3.2.4 chain: the parsed sample
    canonicalizes to the published UTF-8 byte sequence."""
    from sieve_canon import _cn_json_jcs
    src = ('{"numbers": [333333333.33333329, 1E30, 4.50, 2e-3, '
           '0.000000000000000000000000001], '
           '"string": "\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022'
           '\\u005c\\\\\\"\\/", "literals": [null, true, false]}')
    out = _cn_json_jcs(src)
    expected_hex = (
        "7b 22 6c 69 74 65 72 61 6c 73 22 3a 5b 6e 75 6c 6c 2c 74 72 "
        "75 65 2c 66 61 6c 73 65 5d 2c 22 6e 75 6d 62 65 72 73 22 3a "
        "5b 33 33 33 33 33 33 33 33 33 2e 33 33 33 33 33 33 33 2c 31 "
        "65 2b 33 30 2c 34 2e 35 2c 30 2e 30 30 32 2c 31 65 2d 32 37 "
        "5d 2c 22 73 74 72 69 6e 67 22 3a 22 e2 82 ac 24 5c 75 30 30 "
        "30 66 5c 6e 41 27 42 5c 22 5c 5c 5c 5c 5c 22 2f 22 7d")
    expected = bytes.fromhex(expected_hex.replace(" ", ""))
    assert out.encode("utf-8") == expected


def test_jcs_refuses_unsafe_integers():
    from sieve_canon import _cn_json_jcs, CNJsonError
    with pytest.raises(CNJsonError) as e:
        _cn_json_jcs('{"n": 9007199254740993}')   # 2^53 + 1
    assert e.value.reason == "json_number_unsafe"
    # 2^53 itself is the max safe integer (Appendix B row 4340...)
    assert _cn_json_jcs('{"n": 9007199254740992}') == '{"n":9007199254740992}'
    # the pretty style keeps the big integer (§3.3-2: no rounding)
    from sieve_canon import _cn_json_pretty
    big = 123456789012345678901234567890
    assert json.loads(_cn_json_pretty('{"n": %d}' % big))["n"] == big


def test_jcs_refuses_lone_surrogates():
    from sieve_canon import _cn_json_jcs, CNJsonError
    with pytest.raises(CNJsonError) as e:
        _cn_json_jcs('{"s": "\\ud800"}')
    assert e.value.reason == "parse_failed"    # the existing closed word


def test_jcs_is_idempotent_and_meaning_stable():
    from sieve_canon import _cn_json_jcs
    src = '{"b": [1, {"d": 2, "c": [true, null]}], "a": 4.5}'
    once = _cn_json_jcs(src)
    twice = _cn_json_jcs(once)
    assert once == twice
    assert json.loads(src) == json.loads(once)
    assert " " not in once and "\n" not in once   # no whitespace


def test_jcs_via_normalize_has_no_trailing_newline(tmp_path):
    """--style jcs writes the exact canonical bytes: the RFC form has
    no trailing newline, so the text-level trailing-newline rule
    (§3.2-5) does not ride the jcs style (recorded in the stage log)."""
    src = tmp_path / "in.json"
    src.write_bytes(b'{"b": 1, "a": 2}')
    out = tmp_path / "out"
    from sieve_canon import run_normalize
    receipt = run_normalize(src, out, style="jcs")
    assert receipt["items"][0]["status"] == "produced"
    data = (out / "handoff" / "in.json").read_bytes()
    assert data == b'{"a":2,"b":1}'
