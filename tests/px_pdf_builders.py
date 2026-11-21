"""Shared hand-built PDF builders for the PX test files (Tray 2.4.0).

Every builder writes a minimal one-page PDF by hand (pypdf objects
only) so the tests pin exactly the bytes.  The six-kind probe rides
one page with the six fixed location words in first-occurrence order
(Tr 3, Tr 7, tiny_font, off_page, off_layer, white_text) plus one
plain painted line for the visible side.  The metadata PDF carries
every clean-relevant Info key.  The incremental PDF carries an old
front-half Info that an appended update section overrides via /Prev.
The white-background PDF (the 2026-11-21 verification) carries one
white text ON a painted rectangle (visible) and one bare white text
(hidden).  The XMP-full PDF carries an Info dict AND an XMP /Metadata
stream at the catalog, page, image-XObject and AcroForm level plus a
page /Thumb, /PieceInfo, one annotation, one embedded file and one
form field value (the widened removal scope and the in_content
survivors).

The marker strings never overlap the fixed words or each other as
substrings (the 2.2.1 request §3.5 rule, carried over).
"""
import pytest

try:
    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, DecodedStreamObject,
                               DictionaryObject, NameObject, NumberObject,
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

# The white-background probe (the 2026-11-21 verification): the white
# text ON the painted rectangle is visible, the bare white text hides.
WHITE_ON_PAINTED_TEXT = "Painted white line pxp."
WHITE_BARE_TEXT = "Bare white line pxb."
WHITE_BG_PLAIN_TEXT = "Plain body line pxv."

# The XMP-full probe: one XMP packet at every level the widened scope
# must reach, plus the in_content survivors (kept, never removed).
XMP_MARKERS = {
    "catalog": "SIEVE-XMP-CATALOG",
    "page": "SIEVE-XMP-PAGE",
    "image": "SIEVE-XMP-IMAGE",
    "form": "SIEVE-XMP-FORM",
}
ANNOT_TEXT = "SIEVE-ANNOT-NOTE"
EMBED_NAME = "SIEVE-EMBED-NAME"
EMBED_BODY = "SIEVE-EMBED-BODY"
FORM_FIELD = "SIEVE-FORM-FIELD"
FORM_VALUE = "SIEVE-FORM-VALUE"
FULL_TEXT = "Full probe line pxf."

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


def build_white_bg_pdf(path) -> None:
    """One page: a painted rectangle (non-white fill), one white text
    fully inside it (visible through the background judgment), one
    bare white text (hidden), one plain line.  The rectangle is wide
    enough for the width-over-estimated text bbox to sit fully inside
    it (Lens paints only fills with a non-near-white decidable color)."""
    _require_writer()
    writer = PdfWriter()
    page = _add_page(writer, b" ".join([
        b"q 0.2 0.4 0.8 rg 40 596 520 36 re f Q",
        b"BT 0 Tr 1 g /F1 12 Tf 60 608 Td "
        b"(%s) Tj ET" % WHITE_ON_PAINTED_TEXT.encode("ascii"),
        b"BT 0 Tr 1 g /F1 12 Tf 50 560 Td "
        b"(%s) Tj ET" % WHITE_BARE_TEXT.encode("ascii"),
        b"BT 0 Tr 0 g /F1 12 Tf 50 540 Td "
        b"(%s) Tj ET" % WHITE_BG_PLAIN_TEXT.encode("ascii"),
    ]))
    with open(path, "wb") as f:
        writer.write(f)


def build_xmp_full_pdf(path) -> None:
    """One page with the metadata at EVERY level the widened scope
    reaches: the Info dict, the catalog XMP, the page XMP, an image
    XObject with its own XMP, the AcroForm XMP, a page /Thumb, /PieceInfo
    at the catalog and the page, one annotation, one embedded file and
    one form field with a value.  The XMP streams ride uncompressed so
    the markers are visible in the raw bytes (measured 2026-11-21)."""
    _require_writer()
    writer = PdfWriter()
    page = _add_page(writer, b"BT /F1 12 Tf 72 720 Td (%s) Tj ET"
                     % FULL_TEXT.encode("ascii"))
    writer.add_metadata({
        "/Author": META_MARKERS["author"],
        "/Title": META_MARKERS["title"],
        "/Creator": META_MARKERS["creator"],
        "/Producer": META_MARKERS["producer"],
        "/CreationDate": "D:20260101120000Z",
        "/ModDate": "D:20260102120000Z"})

    def xmp_stream(marker: str) -> DecodedStreamObject:
        s = DecodedStreamObject()
        s.set_data(b"<x:xmpmeta>%s</x:xmpmeta>" % marker.encode("ascii"))
        return s

    # catalog-level XMP + /PieceInfo
    writer._root_object[NameObject("/Metadata")] = writer._add_object(
        xmp_stream(XMP_MARKERS["catalog"]))
    writer._root_object[NameObject("/PieceInfo")] = DictionaryObject({
        NameObject("/App"): DictionaryObject({
            NameObject("/Private"): TextStringObject(
                META_MARKERS["custom"])})})
    # page-level XMP + /Thumb + /PieceInfo
    page[NameObject("/Metadata")] = writer._add_object(
        xmp_stream(XMP_MARKERS["page"]))
    thumb = DecodedStreamObject()
    thumb.set_data(b"q Q")
    page[NameObject("/Thumb")] = writer._add_object(thumb)
    page[NameObject("/PieceInfo")] = DictionaryObject({
        NameObject("/App"): DictionaryObject({
            NameObject("/Private"): TextStringObject(
                META_MARKERS["custom"])})})
    # an image XObject with its own XMP
    img = DecodedStreamObject()
    img.set_data(b"\xff\x00\x00")
    img[NameObject("/Type")] = NameObject("/XObject")
    img[NameObject("/Subtype")] = NameObject("/Image")
    img[NameObject("/Width")] = NumberObject(1)
    img[NameObject("/Height")] = NumberObject(1)
    img[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")
    img[NameObject("/BitsPerComponent")] = NumberObject(8)
    img[NameObject("/Metadata")] = writer._add_object(
        xmp_stream(XMP_MARKERS["image"]))
    img_ref = writer._add_object(img)
    page[NameObject("/Resources")][NameObject("/XObject")] = \
        DictionaryObject({NameObject("/Im1"): img_ref})
    # one annotation (kept by clean - reported under in_content)
    annot = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/FreeText"),
        NameObject("/Rect"): ArrayObject([
            NumberObject(0), NumberObject(0),
            NumberObject(100), NumberObject(20)]),
        NameObject("/Contents"): TextStringObject(ANNOT_TEXT)})
    page[NameObject("/Annots")] = ArrayObject(
        [writer._add_object(annot)])
    # one embedded file (kept - hidden_part)
    ef_stream = DecodedStreamObject()
    ef_stream.set_data(EMBED_BODY.encode("ascii"))
    ef_stream[NameObject("/Type")] = NameObject("/EmbeddedFile")
    ef_ref = writer._add_object(ef_stream)
    ef_file = DictionaryObject({
        NameObject("/Type"): NameObject("/Filespec"),
        NameObject("/F"): TextStringObject(EMBED_NAME),
        NameObject("/EF"): DictionaryObject({
            NameObject("/F"): ef_ref})})
    writer._root_object[NameObject("/Names")] = DictionaryObject({
        NameObject("/EmbeddedFiles"): DictionaryObject({
            NameObject("/Names"): ArrayObject([
                TextStringObject(EMBED_NAME), ef_file])})})
    # one form field with a value (kept - hidden_part) + the form XMP
    field = DictionaryObject({
        NameObject("/T"): TextStringObject(FORM_FIELD),
        NameObject("/V"): TextStringObject(FORM_VALUE),
        NameObject("/FT"): NameObject("/Tx")})
    acro = DictionaryObject({
        NameObject("/Fields"): ArrayObject([writer._add_object(field)])})
    acro[NameObject("/Metadata")] = writer._add_object(
        xmp_stream(XMP_MARKERS["form"]))
    writer._root_object[NameObject("/AcroForm")] = acro
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
