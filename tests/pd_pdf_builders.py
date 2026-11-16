"""Shared hand-built PDF builders for the PD test files (Tray 2.2.1).

Every builder writes a minimal one-page PDF by hand (no generator
dependency) so the tests pin exactly the content-stream bytes: one
``Tj`` show-text operator per line, with the text render mode set per
line via ``Tr``.  The visible and the invisible strings are chosen so
they never overlap each other as substrings (the 2.2.1 request §3.5).
"""
import pytest

INVISIBLE = "INVISIBLE PDF PROMPT secret-marker-7f3a"
VISIBLE = "VISIBLE PDF LINE"

# PD-T02: the same page carries one marker per render mode.
MODE_MARKERS = ["M0fill", "M1stroke", "M2fillstroke", "M3invisible",
                "M4fillclip", "M5strokeclip", "M6fillstrokeclip",
                "M7clipline"]

# PD-T03: the same word rides both the visible and the invisible line.
SAME_WORD = "apple"


def _write_pdf(path, stream: bytes) -> None:
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b">>\nstream\n"
        + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    path.write_bytes(bytes(out))


def build_pdf(path, visible: bytes = VISIBLE.encode("ascii"),
              invisible: bytes = INVISIBLE.encode("ascii")) -> None:
    """1 visible line (mode 0) + 1 invisible line (mode 3).  An empty
    ``visible`` makes the OCR-layer-only shape (PD-T04)."""
    parts = []
    if visible:
        parts.append(b"BT /F1 12 Tf 72 720 Td (" + visible + b") Tj ET\n")
    parts.append(b"BT /F1 12 Tf 72 700 Td 3 Tr (" + invisible + b") Tj ET\n")
    _write_pdf(path, b"".join(parts))


def build_modes_pdf(path) -> None:
    """PD-T02: one marker per text render mode 0..7 on one page."""
    lines = []
    y = 720
    for mode, mark in enumerate(MODE_MARKERS):
        lines.append(
            b"BT /F1 12 Tf " + str(y).encode() + b" 0 Td " +
            str(mode).encode() + b" Tr (" + mark.encode("ascii")
            + b") Tj ET\n")
        y -= 20
    _write_pdf(path, b"".join(lines))


def build_same_word_pdf(path) -> None:
    """PD-T03: the word ``apple`` appears once visibly and once inside
    the invisible line (never as a substring of each other)."""
    _write_pdf(
        path,
        b"BT /F1 12 Tf 72 720 Td (" + SAME_WORD.encode("ascii")
        + b" pie recipe) Tj ET\n"
        b"BT /F1 12 Tf 72 700 Td 3 Tr (" + SAME_WORD.encode("ascii")
        + b" secret plan) Tj ET\n")


def need_pypdf():
    """The PD clause is measured WITH pypdf - skip when it is absent."""
    pypdf = pytest.importorskip("pypdf")
    assert pypdf.__version__
    return pypdf
