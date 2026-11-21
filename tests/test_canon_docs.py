"""Canon 2.3.0 / stage 9 - the docs (CN-T21, request §3.8-1/§3.8-2):
the three spec documents carry the known examples (KV-C1..C3) and the
tests read them back from the documents themselves; the glossary
exists with the new words; the README carries the three new sections
in both languages with the real docs links; the forbidden screen words
stay out of the new docs and the new module.
"""
import hashlib
import re
import struct
import zlib

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _doc(name: str) -> str:
    return (REPO / "docs" / name).read_text(encoding="utf-8")


def _doc_sha(text: str, label: str) -> str:
    """The 'sha256:...' value that follows the given bold label."""
    m = re.search(re.escape(label) + r"\s*\*?\*?`?(sha256:[0-9a-f]{64})",
                  text)
    assert m is not None, label
    return m.group(1)


# ---------------------------------------------------------------------------
# KV-C1: the clean example (docs/clean-metadata.md §4)

def test_kv_c1_png_example_matches_the_document():
    doc = _doc("clean-metadata.md")
    want = _doc_sha(doc, "出力全体の SHA-256 は")
    import io as _io
    from sieve_canon import run_clean

    def chunk(t, p):
        return (len(p).to_bytes(4, "big") + t + p
                + zlib.crc32(t + p).to_bytes(4, "big"))
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    gama = chunk(b"gAMA", struct.pack(">I", 45455))
    text = chunk(b"tEXt", b"Author\x00Sakura")
    idat = chunk(b"IDAT", b"\x00\x01\x02\x03")
    iend = chunk(b"IEND", b"")
    src = REPO.parent / "_kv_c1_in"
    src.mkdir(exist_ok=True)
    png = src / "kv-c1.png"
    png.write_bytes(sig + ihdr + gama + text + idat + iend)
    # the input hash is stated too
    want_in = _doc_sha(doc, "この入力全体の SHA-256 は")
    assert _sha(png.read_bytes()) == want_in
    out = REPO.parent / "_kv_c1_out"
    receipt = run_clean(png, out)
    got = (out / "handoff" / "kv-c1.png").read_bytes()
    assert _sha(got) == want
    assert receipt["items"][0]["categories_after"]["author"] == 0


# ---------------------------------------------------------------------------
# KV-C2: the normalize example (docs/normalize-format.md §4)

def test_kv_c2_normalize_example_matches_the_document():
    doc = _doc("normalize-format.md")
    m = re.search(r"入力 5 バイト: `([0-9a-f ]+)`", doc)
    assert m is not None
    in_hex = m.group(1).replace(" ", "")
    m = re.search(r"出力 4 バイト: `([0-9a-f ]+)`", doc)
    assert m is not None
    want_out_hex = m.group(1).replace(" ", "")
    want = _doc_sha(doc, "出力全体の SHA-256 は")
    import tempfile
    d = Path(tempfile.mkdtemp())
    src = d / "ex.txt"
    src.write_bytes(bytes.fromhex(in_hex))
    from sieve_canon import run_normalize
    receipt = run_normalize(src, d / "out")
    got = (d / "out" / "handoff" / "ex.txt").read_bytes()
    assert got.hex() == want_out_hex
    assert _sha(got) == want
    assert receipt["items"][0]["observation"]["newlines"]["crlf"] == 1


# ---------------------------------------------------------------------------
# KV-C3: the table-diff example (docs/table-diff.md §4)

def test_kv_c3_table_diff_example_matches_the_document():
    doc = _doc("table-diff.md")
    want_a = _doc_sha(doc, "A の整えた形の SHA-256:")
    want_b = _doc_sha(doc, "B の整えた形の SHA-256:")
    assert "same` 0・`changed` 1" in doc
    import tempfile
    d = Path(tempfile.mkdtemp())
    a = d / "a.csv"
    b = d / "b.csv"
    a.write_text("id,v\n1,x\n2,y\n", encoding="utf-8", newline="")
    b.write_text("id,v\n1,y\n3,z\n", encoding="utf-8", newline="")
    from sieve_canon import run_table_diff
    receipt = run_table_diff(a, b, ("id",), d / "out")
    s = receipt["summary"]
    assert (s["rows_same"], s["rows_changed"], s["rows_removed"],
            s["rows_added"], s["duplicate_keys"]) == (0, 1, 1, 1, 0)
    assert s["a_normalized_sha256"] == want_a
    assert s["b_normalized_sha256"] == want_b


# ---------------------------------------------------------------------------
# the glossary (request 言葉: the correspondence table gains the new words)

def test_glossary_exists_and_carries_the_new_words():
    text = _doc("glossary.md")
    for word in ("メタデータ", "文字コード", "改行コード", "正規化",
                 "表の比較", "処理記録", "照合コード", "キーファイル"):
        assert word in text, word
    # the Seal correspondences stay (the 表 rows)
    assert "manifest" in text and "handoff/" in text


# ---------------------------------------------------------------------------
# the README sections (§3.8-1: (a) 1-2 sentences, (b) the steps,
# (c) the command block, (d) the docs link - in both languages)

EN_HEADINGS = ("## 🧼 Clean Metadata", "## 🧽 Normalize",
               "## 📊 Compare Tables")
JA_HEADINGS = ("## 🧼 メタデータの除去",
               "## 🧽 テキストと JSON / CSV の整理",
               "## 📊 表の比較")


@pytest.mark.parametrize("name,headings", [
    ("README.md", EN_HEADINGS),
    ("README.ja.md", JA_HEADINGS),
])
def test_readme_carries_the_three_new_sections(name, headings):
    text = (REPO / name).read_text(encoding="utf-8")
    for heading in headings:
        assert heading in text, heading
    for link in ("docs/clean-metadata.md", "docs/normalize-format.md",
                 "docs/table-diff.md"):
        assert link in text, (name, link)
        assert (REPO / link).is_file(), link
    # each new section has a command block (the (c) rule)
    for heading in headings:
        section = text.split(heading, 1)[1]
        section = section.split("\n## ", 1)[0]
        assert section.count("```") >= 2, heading


def test_docs_carry_no_new_forbidden_words():
    from test_seal_s9_readme_docs import FORBIDDEN_SCREEN_WORDS
    for name in ("clean-metadata.md", "normalize-format.md",
                 "table-diff.md", "glossary.md"):
        text = _doc(name)
        for word in FORBIDDEN_SCREEN_WORDS:
            assert word not in text, (name, word)
    src = (REPO / "sieve_canon.py").read_text(encoding="utf-8")
    for word in FORBIDDEN_SCREEN_WORDS:
        assert word not in src, word


def test_selfcheck_constants_match_the_docs():
    """The published known values of the self-checks and the documents
    are the same numbers (the two sides are pinned together)."""
    from sieve_canon import (_CN_KV_C1_CLEAN_SHA256,
                             _CN_KV_C2_OUTPUT_SHA256,
                             _CN_KV_C3_A_SHA256, _CN_KV_C3_B_SHA256)
    assert _CN_KV_C1_CLEAN_SHA256 == _doc_sha(
        _doc("clean-metadata.md"), "出力全体の SHA-256 は")
    assert _CN_KV_C2_OUTPUT_SHA256 == _doc_sha(
        _doc("normalize-format.md"), "出力全体の SHA-256 は")
    assert _CN_KV_C3_A_SHA256 == _doc_sha(
        _doc("table-diff.md"), "A の整えた形の SHA-256:")
    assert _CN_KV_C3_B_SHA256 == _doc_sha(
        _doc("table-diff.md"), "B の整えた形の SHA-256:")


def test_clean_doc_states_the_pdf_inclusion():
    # 2.4.0 (the PDF request): the doc no longer excludes the PDF - the
    # PDF section (1.4) states the scope, the removed/kept split and
    # the determinism contract
    doc = _doc("clean-metadata.md")
    assert "### 1.4 PDF（2.4.0 から）" in doc
    assert "取り除く" in doc and "残す" in doc
    assert "同じ pypdf の版で、同じ結果" in doc
