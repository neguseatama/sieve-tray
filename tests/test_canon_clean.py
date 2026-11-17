"""Canon 2.3.0 / stage 6 - the metadata clean (CN-T01..T08, request
§3.1).  The fixtures build real byte structures in the test: PNG
chunks with correct CRCs, a JPEG with a hand-built EXIF TIFF (IFD0
with Artist + Orientation, IFD1 with the thumbnail), an 8BIM IPTC
APP13, and minimal Office packages.  The rule of the stage: the
output keeps the content byte-identical (the content checksum), the
removed values never enter handoff/ (the raw-byte search), and the
original file is never touched.
"""
import hashlib
import json
import struct
import zipfile
import zlib

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# the PNG fixture

def _png_chunk(ctype: bytes, payload: bytes) -> bytes:
    return (len(payload).to_bytes(4, "big") + ctype + payload
            + zlib.crc32(ctype + payload).to_bytes(4, "big"))


def _make_png(with_meta=True):
    ihdr = _png_chunk(b"IHDR",
                      struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    gama = _png_chunk(b"gAMA", struct.pack(">I", 45455))
    idat = _png_chunk(b"IDAT", b"\x00\x01\x02\x03")
    iend = _png_chunk(b"IEND", b"")
    if with_meta:
        text = _png_chunk(b"tEXt", b"Author\0SIEVE-PNG-AUTHOR")
        itime = _png_chunk(b"tIME",
                           struct.pack(">HBBBBB", 2026, 11, 17, 1, 2, 3))
        chunks = [ihdr, gama, text, itime, idat, iend]
    else:
        chunks = [ihdr, gama, idat, iend]
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


# ---------------------------------------------------------------------------
# the JPEG fixture (a hand-built EXIF TIFF)

def _tiff_payload(artist, orientation, thumb):
    """II TIFF: IFD0 (Artist, Orientation) -> IFD1 (thumbnail)."""
    le = "<"
    artist_b = artist.encode("ascii")
    thumb_b = thumb
    ifd0_count = 2
    ifd0_size = 2 + 12 * ifd0_count + 4
    ifd0_off = 8
    artist_off = ifd0_off + ifd0_size
    thumb_off = artist_off + len(artist_b)
    ifd1_off = thumb_off + len(thumb_b)

    def entry(tag, typ, count, value):
        return (struct.pack(le + "HHI", tag, typ, count)
                + value.ljust(4, b"\x00")[:4])

    artist_val = struct.pack(le + "I", artist_off)
    orient_val = struct.pack(le + "H", orientation) + b"\x00\x00"
    ifd0 = (struct.pack(le + "H", ifd0_count)
            + entry(0x013A, 2, len(artist_b), artist_val)
            + entry(0x0112, 3, 1, orient_val)
            + struct.pack(le + "I", ifd1_off))
    ifd1 = (struct.pack(le + "H", 2)
            + entry(0x0201, 4, 1, struct.pack(le + "I", thumb_off))
            + entry(0x0202, 4, 1, struct.pack(le + "I", len(thumb_b)))
            + struct.pack(le + "I", 0))
    tiff = (b"II" + b"\x2a\x00" + struct.pack(le + "I", ifd0_off)
            + ifd0 + artist_b + thumb_b + ifd1)
    return b"Exif\x00\x00" + tiff


def _seg(marker: int, payload: bytes) -> bytes:
    return (bytes([0xFF, marker])
            + (len(payload) + 2).to_bytes(2, "big") + payload)


def _make_jpeg(orientation=1):
    out = [b"\xff\xd8"]
    out.append(_seg(0xE0, b"JFIF\x00" + b"\x01\x02\x00\x00\x01\x00\x01"
                    + b"\x00\x00"))                       # APP0, no thumb
    out.append(_seg(0xE1, _tiff_payload("SIEVE-JPEG-AUTHOR",
                                        orientation,
                                        b"SIEVE-THUMB")))  # APP1 EXIF
    out.append(_seg(0xE2, b"ICC-SAMPLE"))                    # APP2 ICC
    out.append(_seg(0xFE, b"SIEVE-JPEG-COMMENT"))            # COM
    iptc = (b"\x1c\x01\x32" + len("SIEVE-BYLINE").to_bytes(2, "big")
            + b"SIEVE-BYLINE")
    bim = (b"8BIM" + b"\x04\x04" + b"\x00\x00"
           + (len(iptc)).to_bytes(4, "big") + iptc)
    out.append(_seg(0xED, b"Photoshop 3.0\x00" + bim))       # APP13 IPTC
    out.append(_seg(0xDB, b"\x00\x10"))                      # DQT
    out.append(_seg(0xC0, b"\x08" + b"\x00\x01\x00\x01\x01\x01\x11\x00"))
    out.append(_seg(0xC4, b"\x00\x02\x00\x00"))              # DHT
    out.append(_seg(0xDA, b"\x01\x00\x00"))                  # SOS
    out.append(b"\x12\x34\x56")                              # entropy scan
    out.append(b"\xff\xd9")                                  # EOI
    return b"".join(out)


# ---------------------------------------------------------------------------
# the Office fixture

CORE_XML = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats'
            '.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/">'
            '<dc:creator>SIEVE-CREATOR</dc:creator>'
            '<cp:lastModifiedBy>SIEVE-MODIFIER</cp:lastModifiedBy>'
            '<dc:title>SIEVE-DOC-TITLE</dc:title>'
            '<dcterms:created>2026-01-01T00:00:00Z</dcterms:created>'
            '</cp:coreProperties>')

APP_XML = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Properties xmlns="http://schemas.openxmlformats.org/'
           'officeDocument/2006/extended-properties">'
           '<Application>SIEVE-APP</Application>'
           '<Company>SIEVE-COMPANY</Company></Properties>')

CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Types xmlns="http://schemas.openxmlformats.org/'
                 'package/2006/content-types">'
                 '<Default Extension="xml" ContentType='
                 '"application/xml"/></Types>')


def _zip_bytes(parts) -> bytes:
    import io as _io
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in parts:
            zf.writestr(name, data)
    return buf.getvalue()


def _make_docx(comments=False, tracked=False):
    document = (b"<?xml version=\"1.0\"?><w:document>"
                + (b"<w:ins id=\"1\"/><w:del id=\"2\"/>" if tracked
                   else b"")
                + b"</w:document>")
    parts = [("[Content_Types].xml", CONTENT_TYPES.encode("utf-8")),
             ("_rels/.rels", b"<Relationships/>"),
             ("word/document.xml", document),
             ("docProps/core.xml", CORE_XML.encode("utf-8")),
             ("docProps/app.xml", APP_XML.encode("utf-8"))]
    if comments:
        parts.append(("word/comments.xml",
                      b"<?xml version=\"1.0\"?><w:comments>"
                      b"<w:comment w:id=\"1\"/><w:comment w:id=\"2\"/>"
                      b"</w:comments>"))
    return _zip_bytes(parts)


def _make_xlsx(hidden=False):
    sheet = ('<?xml version="1.0"?><workbook>'
             '<sheet name="a" sheetId="1"/>'
             + ('<sheet name="b" sheetId="2" state="hidden"/>'
                if hidden else "")
             + '</workbook>')
    return _zip_bytes([
        ("[Content_Types].xml", CONTENT_TYPES.encode("utf-8")),
        ("xl/workbook.xml", sheet.encode("utf-8")),
        ("docProps/core.xml", CORE_XML.encode("utf-8")),
        ("docProps/app.xml", APP_XML.encode("utf-8"))])


def _run_clean(inp, out, **kw):
    from sieve_canon import run_clean
    return run_clean(Path(inp), Path(out), **kw)


def _one(receipt):
    assert len(receipt["items"]) == 1
    return receipt["items"][0]


def _zeros():
    from sieve_canon import CN_META_CATEGORIES
    return {c: 0 for c in CN_META_CATEGORIES}


# ---------------------------------------------------------------------------
# CN-T01: the PNG round

def test_png_removes_text_and_time_keeps_display_chunks(tmp_path):
    src = tmp_path / "pic.png"
    src.write_bytes(_make_png())
    out = tmp_path / "out"
    receipt = _run_clean(src, out)
    item = _one(receipt)
    assert item["status"] == "cleaned"
    copy = (out / "handoff" / "pic.png").read_bytes()
    # the display-related and mandatory chunks survive
    from sieve_canon import _cn_png_chunks
    types = [t for t, _p in _cn_png_chunks(copy)]
    assert types == ["IHDR", "gAMA", "IDAT", "IEND"]   # CRCs re-checked
    assert b"SIEVE-PNG-AUTHOR" not in copy
    assert item["content_checksum_match"] is True
    assert item["categories_after"] == _zeros()
    assert item["categories_before"]["author"] == 1
    assert item["categories_before"]["time"] == 1


def test_png_clean_of_a_clean_file_is_byte_identical(tmp_path):
    src = tmp_path / "clean.png"
    src.write_bytes(_make_png(with_meta=False))
    out = tmp_path / "out"
    receipt = _run_clean(src, out)
    item = _one(receipt)
    assert item["status"] == "cleaned"
    assert (out / "handoff" / "clean.png").read_bytes() == \
        src.read_bytes()


# ---------------------------------------------------------------------------
# CN-T02: the JPEG round

def test_jpeg_removes_exif_iptc_com_thumbnail_keeps_icc(tmp_path):
    src = tmp_path / "pic.jpg"
    src.write_bytes(_make_jpeg(orientation=1))
    out = tmp_path / "out"
    receipt = _run_clean(src, out)
    item = _one(receipt)
    assert item["status"] == "cleaned"
    assert item["orientation_kept"] is False
    copy = (out / "handoff" / "pic.jpg").read_bytes()
    for marker in (b"SIEVE-JPEG-AUTHOR", b"SIEVE-THUMB",
                   b"SIEVE-JPEG-COMMENT", b"SIEVE-BYLINE"):
        assert marker not in copy
    assert b"ICC-SAMPLE" in copy                      # APP2 stays
    from sieve_canon import _cn_jpeg_segments
    names = [s[0] for s in _cn_jpeg_segments(copy)]
    assert "APP1" not in names and "APP13" not in names
    assert "COM" not in names
    assert names.count("SOS") == 1 and "SCAN" in names
    assert b"\x12\x34\x56" in copy                    # the entropy data
    assert item["content_checksum_match"] is True
    assert item["categories_after"] == _zeros()
    before = item["categories_before"]
    assert before["author"] == 2      # the EXIF Artist + the IPTC By-line
    assert before["thumbnail"] == 1   # the IFD1 thumbnail
    assert before["custom"] >= 1      # the COM comment


def test_jpeg_orientation_is_kept_as_minimal_exif(tmp_path):
    src = tmp_path / "rot.jpg"
    src.write_bytes(_make_jpeg(orientation=6))
    out = tmp_path / "out"
    receipt = _run_clean(src, out)
    item = _one(receipt)
    assert item["orientation_kept"] is True
    copy = (out / "handoff" / "pic.jpg" if False else
            (out / "handoff" / "rot.jpg")).read_bytes()
    assert b"SIEVE-JPEG-AUTHOR" not in copy           # the rest still goes
    # the minimal EXIF carries the orientation 6
    from sieve_canon import _cn_jpeg_segments, _cn_exif_orientation
    for name, payload, _raw in _cn_jpeg_segments(copy):
        if name == "APP1":
            assert _cn_exif_orientation(payload) == 6
            break
    else:
        pytest.fail("the minimal EXIF is missing")
    assert item["categories_after"] == _zeros()


# ---------------------------------------------------------------------------
# CN-T03: the Office round

def test_docx_docprops_emptied_other_parts_byte_identical(tmp_path):
    src = tmp_path / "doc.docx"
    src.write_bytes(_make_docx())
    out = tmp_path / "out"
    receipt = _run_clean(src, out)
    item = _one(receipt)
    assert item["status"] == "cleaned"
    copy = (out / "handoff" / "doc.docx").read_bytes()
    with zipfile.ZipFile(io_bytes(copy)) as zf:
        names = zf.namelist()
        # the deterministic zip sorts the members by the name bytes
        assert names == ["[Content_Types].xml", "_rels/.rels",
                         "docProps/app.xml", "docProps/core.xml",
                         "word/document.xml"]      # nothing dropped
        assert zf.read("word/document.xml") == \
            _make_docx_parts()["word/document.xml"]
        core = zf.read("docProps/core.xml").decode("utf-8")
        assert "SIEVE-CREATOR" not in core
        assert "coreProperties" in core           # still a valid shape
    for marker in ("SIEVE-CREATOR", "SIEVE-MODIFIER", "SIEVE-DOC-TITLE",
                   "SIEVE-APP", "SIEVE-COMPANY"):
        assert marker.encode("utf-8") not in copy
    assert item["content_checksum_match"] is True
    assert item["categories_after"] == _zeros()
    before = item["categories_before"]
    assert before["author"] == 3   # creator + lastModifiedBy + Company
    assert before["software"] == 1
    assert before["time"] == 1
    assert before["title_subject"] == 1


def test_docx_zip_is_deterministic_and_readable(tmp_path):
    src = tmp_path / "doc.docx"
    src.write_bytes(_make_docx())
    out1 = tmp_path / "o1"
    out2 = tmp_path / "o2"
    r1 = _run_clean(src, out1)
    r2 = _run_clean(src, out2)
    b1 = (out1 / "handoff" / "doc.docx").read_bytes()
    b2 = (out2 / "handoff" / "doc.docx").read_bytes()
    assert b1 == b2
    with zipfile.ZipFile(io_bytes(b1)) as zf:
        assert zf.testzip() is None
        assert zf.read("word/document.xml") == \
            _make_docx_parts()["word/document.xml"]
    assert r1["items"][0]["output_sha256"] == \
        r2["items"][0]["output_sha256"]


def test_office_in_content_is_counted_not_removed(tmp_path):
    src = tmp_path / "doc.docx"
    src.write_bytes(_make_docx(comments=True, tracked=True))
    out = tmp_path / "out"
    receipt = _run_clean(src, out)
    item = _one(receipt)
    assert item["in_content"] == {"comment": 2, "tracked_change": 2,
                                  "hidden_part": 0}
    copy = (out / "handoff" / "doc.docx").read_bytes()
    # the content itself rides unchanged (the parts stay byte-identical)
    with zipfile.ZipFile(io_bytes(copy)) as zf:
        assert zf.read("word/document.xml") == \
            _make_docx_parts(tracked=True)["word/document.xml"]
        assert zf.read("word/comments.xml") == \
            _make_docx_parts(comments=True)["word/comments.xml"]


def test_xlsx_hidden_sheet_counted(tmp_path):
    src = tmp_path / "book.xlsx"
    src.write_bytes(_make_xlsx(hidden=True))
    out = tmp_path / "out"
    receipt = _run_clean(src, out)
    item = _one(receipt)
    assert item["in_content"]["hidden_part"] == 1


def _make_docx_parts(comments=False, tracked=False):
    """The raw member bytes of the fixture, for the byte-equality
    checks."""
    document = (b"<?xml version=\"1.0\"?><w:document>"
                + (b"<w:ins id=\"1\"/><w:del id=\"2\"/>" if tracked
                   else b"")
                + b"</w:document>")
    parts = {"[Content_Types].xml": CONTENT_TYPES.encode("utf-8"),
             "_rels/.rels": b"<Relationships/>",
             "word/document.xml": document,
             "docProps/core.xml": CORE_XML.encode("utf-8"),
             "docProps/app.xml": APP_XML.encode("utf-8")}
    if comments:
        parts["word/comments.xml"] = (
            b"<?xml version=\"1.0\"?><w:comments>"
            b"<w:comment w:id=\"1\"/><w:comment w:id=\"2\"/>"
            b"</w:comments>")
    return parts


def io_bytes(data: bytes):
    import io
    return io.BytesIO(data)


# ---------------------------------------------------------------------------
# CN-T05: the out-of-scope and the broken inputs

def test_out_of_scope_and_broken_files(tmp_path):
    root = tmp_path / "in"
    root.mkdir()
    (root / "plain.txt").write_bytes(b"text\n")
    (root / "doc.pdf").write_bytes(b"%PDF-1.4\n")
    (root / "weird.xyz").write_bytes(b"data\n")
    (root / "broken.jpg").write_bytes(b"\xff\xd8\xff\x00\x00")
    (root / "broken.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0a" + b"tEXtXXXXX" +
        b"\x00\x00\x00\x00")
    (root / "broken.docx").write_bytes(b"not a zip")
    out = tmp_path / "out"
    receipt = _run_clean(root, out)
    by_path = {it["path"]: it for it in receipt["items"]}
    assert by_path["plain.txt"]["status"] == "not_applicable"
    assert by_path["doc.pdf"]["status"] == "not_applicable"
    assert by_path["doc.pdf"]["format"] == "pdf"
    assert by_path["weird.xyz"]["status"] == "not_applicable"
    for name in ("broken.jpg", "broken.png", "broken.docx"):
        assert by_path[name]["status"] == "refused"
        assert by_path[name]["reason"] == "parse_failed"
    handoff = out / "handoff"
    for name in ("plain.txt", "doc.pdf", "weird.xyz", "broken.jpg",
                 "broken.png", "broken.docx"):
        assert not (handoff / name).exists()
    assert (handoff / "clean-receipt.json").is_file()


# ---------------------------------------------------------------------------
# CN-T07: the privacy and the untouched original

def test_removed_values_never_enter_handoff_original_untouched(tmp_path):
    root = tmp_path / "in"
    root.mkdir()
    (root / "pic.jpg").write_bytes(_make_jpeg(orientation=1))
    (root / "pic.png").write_bytes(_make_png())
    (root / "doc.docx").write_bytes(_make_docx(comments=True))
    before = {p.name: _sha(p.read_bytes())
              for p in root.iterdir()}
    out = tmp_path / "out"
    receipt = _run_clean(root, out)
    raw = b""
    for p in (out / "handoff").rglob("*"):
        if p.is_file():
            raw += p.read_bytes()
    for marker in (b"SIEVE-JPEG-AUTHOR", b"SIEVE-THUMB", b"SIEVE-BYLINE",
                   b"SIEVE-PNG-AUTHOR", b"SIEVE-CREATOR",
                   b"SIEVE-MODIFIER", b"SIEVE-DOC-TITLE", b"SIEVE-APP",
                   b"SIEVE-COMPANY", b"SIEVE-JPEG-COMMENT"):
        assert marker not in raw
    # the local report carries the detail instead
    local = (out / "local" / "clean-report.html").read_text("utf-8")
    assert "SIEVE-JPEG-AUTHOR" in local
    assert "SIEVE-CREATOR" in local
    # the originals ride unchanged
    for p in root.iterdir():
        assert _sha(p.read_bytes()) == before[p.name]


# ---------------------------------------------------------------------------
# CN-T08: the determinism

def test_clean_is_deterministic_across_runs_and_dirs(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "pic.png").write_bytes(_make_png())
    (src / "pic.jpg").write_bytes(_make_jpeg(orientation=6))
    o1 = tmp_path / "o1"
    o2 = tmp_path / "o2"
    r1 = _run_clean(src, o1)
    r2 = _run_clean(src, o2)
    assert (o1 / "handoff" / "clean-receipt.json").read_bytes() == \
        (o2 / "handoff" / "clean-receipt.json").read_bytes()
    for name in ("pic.png", "pic.jpg"):
        assert (o1 / "handoff" / name).read_bytes() == \
            (o2 / "handoff" / name).read_bytes()
    assert r1["items"][0]["output_sha256"] == \
        r2["items"][0]["output_sha256"]
