"""Shared hand-built PDF builders for the PX test files (Tray 2.4.0).

Every builder writes a minimal one-page PDF by hand (pypdf objects
only) so the tests pin exactly the bytes.  The six-kind probe rides
one page with the six fixed location words in first-occurrence order
(Tr 3, Tr 7, tiny_font, off_page, off_layer, white_text) plus one
plain painted line for the visible side.  The metadata PDF carries
every clean-relevant Info key.  The incremental PDF carries an old
front-half Info that an appended update section overrides via /Prev.

The marker strings never overlap the fixed words or each other as
substrings (the 2.2.1 request §3.5 rule, carried over).
"""
import pytest

try:
    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, DecodedStreamObject,
                               DictionaryObject, NameObject,
                               TextStringObject)
except ImportError:          # the module stays importable without pypdf
    PdfWriter = None         # (the tests skip through need_pypdf first)


# PX-T03: the author-controlled layer name that must never leave the
# observation (the record strips it, handoff/ never sees it).
LAYER_NAME = "SIEVE-LAYER-Z9"

# The six fixed words of the 2026-11-21 ruling, in match order.
LOCATION_WORDS = ("Tr 3", "Tr 7", "tiny_font", "off_page",
                  "off_layer", "white_text")

# The six-kind probe: one hidden body per fixed word + one plain line.
SIX_KIND_TEXTS = {
    "Tr 3": "Invisible prompt line px3.",
    "Tr 7": "Clip memo line px7.",
    "tiny_font": "Small print line pxt.",
    "off_page": "Off page line pxo.",
    "off_layer": "Layer line pxl.",
    "white_text": "White line pxw.",
}
VISIBLE_LINE = "Plain body line pxv."

# The exact 0.23.x locations of the six-kind probe, first-occurrence
# order (measured with sieve-lens 0.23.0 / pypdf 6.6.0 before the red
# commit - scripts/tray240_px_probe.py).
SIX_KIND_LOCATIONS = [
    "page 1 (invisible text, Tr 3)",
    "page 1 (invisible text, Tr 7)",
    "page 1 (tiny_font)",
    "page 1 (off_page)",
    "page 1 (off_layer '%s')" % LAYER_NAME,
    "page 1 (white_text)",
]

# The metadata PDF markers, one per clean-relevant Info key.
META_MARKERS = {
    "author": "SIEVE-PDF-AUTHOR",
    "title": "SIEVE-PDF-TITLE",
    "subject": "SIEVE-PDF-SUBJECT",
    "keywords": "SIEVE-PDF-KEYS",
    "creator": "SIEVE-PDF-CREATOR",
    "producer": "SIEVE-PDF-PRODUCER",
    "custom": "SIEVE-PDF-CUSTOM",
}
META_TEXT = "Meta probe line."

# The incremental PDF: the front half carries the old author, the
# appended update section overrides /Info with the new one (/Prev).
OLD_AUTHOR = "SIEVE-PDF-OLD-AUTHOR"
OLD_CREATOR = "SIEVE-PDF-OLD-CREATOR"
NEW_AUTHOR = "SIEVE-PDF-NEW-AUTHOR"
NEW_CREATOR = "SIEVE-PDF-NEW-CREATOR"
INCREMENTAL_TEXT = "Incremental probe line."


def need_pypdf():
    """The PX clause is measured WITH pypdf - skip when it is absent."""
    pypdf = pytest.importorskip("pypdf")
    assert pypdf.__version__
    return pypdf


def _require_writer():
    if PdfWriter is None:
        raise RuntimeError("pypdf is required to build the PX probe PDFs")


def _font_obj(writer):
    return DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica")})


def _add_page(writer, stream: bytes):
    page = writer.add_blank_page(width=612, height=792)
    font_ref = writer._add_object(_font_obj(writer))
    s = DecodedStreamObject()
    s.set_data(stream)
    page[NameObject("/Contents")] = writer._add_object(s)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject(
            {NameObject("/F1"): font_ref})})
    return page


def build_six_kinds_pdf(path) -> None:
    """One page, one hidden body per fixed word in first-occurrence
    order + one plain painted line for the visible side.

    Every non-3/7 block resets the text render mode (Tr persists
    across BT/ET) and the plain line resets the fill color (the white
    line's 1 g would otherwise paint it white too)."""
    _require_writer()
    writer = PdfWriter()
    page = _add_page(writer, b" ".join([
        b"BT /F1 12 Tf 50 700 Td 3 Tr "
        b"(Invisible prompt line px3.) Tj ET",
        b"BT /F1 12 Tf 0 Tr 50 680 Td 7 Tr "
        b"(Clip memo line px7.) Tj ET",
        b"BT /F1 1.9 Tf 0 Tr 50 660 Td "
        b"(Small print line pxt.) Tj ET",
        b"BT /F1 12 Tf 0 Tr 700 700 Td "
        b"(Off page line pxo.) Tj ET",
        b"/MC0 /Pr0 BDC BT /F1 12 Tf 0 Tr 50 640 Td "
        b"(Layer line pxl.) Tj ET EMC",
        b"BT 0 Tr 1 g /F1 12 Tf 50 620 Td "
        b"(White line pxw.) Tj ET",
        b"BT 0 Tr 0 g /F1 12 Tf 50 600 Td "
        b"(Plain body line pxv.) Tj ET",
    ]))
    ocg = DictionaryObject({
        NameObject("/Type"): NameObject("/OCG"),
        NameObject("/Name"): TextStringObject(LAYER_NAME)})
    ocg_ref = writer._add_object(ocg)
    page[NameObject("/Resources")][NameObject("/Properties")] = \
        DictionaryObject({NameObject("/Pr0"): ocg_ref})
    writer._root_object[NameObject("/OCProperties")] = DictionaryObject({
        NameObject("/D"): DictionaryObject({
            NameObject("/OFF"): ArrayObject([ocg_ref])})})
    with open(path, "wb") as f:
        writer.write(f)


def build_meta_pdf(path, *, author="SIEVE-PDF-AUTHOR") -> None:
    """One page + an Info dict with every clean-relevant key (the
    standard six, the dates, and one non-standard custom key)."""
    _require_writer()
    writer = PdfWriter()
    _add_page(writer, b"BT /F1 12 Tf 72 720 Td (Meta probe line.) Tj ET")
    writer.add_metadata({
        "/Author": author,
        "/Title": META_MARKERS["title"],
        "/Subject": META_MARKERS["subject"],
        "/Keywords": META_MARKERS["keywords"],
        "/Creator": META_MARKERS["creator"],
        "/Producer": META_MARKERS["producer"],
        "/CustomKey": META_MARKERS["custom"],
        "/CreationDate": "D:20260101120000Z",
        "/ModDate": "D:20260102120000Z"})
    with open(path, "wb") as f:
        writer.write(f)


def build_incremental_pdf(path) -> None:
    """Two-section PDF: the front half carries /Author (old) and the
    appended update section overrides /Info via /Prev; a reader must
    resolve the newest /Info (measured: it does)."""
    base_objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length 58 >>\nstream\n"
        b"BT /F1 12 Tf 72 720 Td (Incremental probe line.) Tj ET\n"
        b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Author (SIEVE-PDF-OLD-AUTHOR) "
        b"/Creator (SIEVE-PDF-OLD-CREATOR) >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(base_objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref1 = len(out)
    out += f"xref\n0 {len(base_objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(base_objs) + 1} /Root 1 0 R "
            f"/Info 6 0 R >>\nstartxref\n{xref1}\n%%EOF\n").encode()
    upd_at = len(out)
    out += (b"7 0 obj\n<< /Author (SIEVE-PDF-NEW-AUTHOR) "
            b"/Creator (SIEVE-PDF-NEW-CREATOR) >>\nendobj\n")
    xref2 = len(out)
    out += b"xref\n7 1\n" + f"{upd_at:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size 8 /Root 1 0 R /Info 7 0 R "
            f"/Prev {xref1} >>\nstartxref\n{xref2}\n%%EOF\n").encode()
    path.write_bytes(bytes(out))
