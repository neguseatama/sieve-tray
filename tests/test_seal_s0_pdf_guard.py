"""Seal 2.2 / S0 - the PDF clause (design-chat ruling (2) of 2026-11-14).

Gate treats a PDF as unobserved with the reason engine_unavailable
*regardless of whether pypdf is installed*: pypdf's visible-text
extraction does not interpret the rendering mode ``3 Tr``, so enabling
it starts a leak (measured in the 2.2 start-up report section 2-2:
the invisible text rode into ``handoff/*.pdf.visible.txt``).  Until the
engine itself understands render modes, the safe side is to not observe
PDFs at all and to record why - closed vocabulary only, with a detail.

SL-T21 (2 tests):
  1. an environment WITH pypdf: a hand-built PDF (one visible line +
     one ``3 Tr`` invisible line) goes through Gate; the invisible
     string appears nowhere in the whole output tree and the reason is
     recorded on the item and in the receipt counters.
  2. an upper-case ``.PDF`` takes the same guard (the suffix is
     normalised before the lane dispatch).
"""
import pytest

INVISIBLE = "INVISIBLE PDF PROMPT secret-marker-7f3a"
VISIBLE = "VISIBLE PDF LINE"


def _minimal_pdf(path):
    """A hand-built minimal PDF: 1 visible line + 1 invisible (3 Tr) line."""
    stream = (
        b"BT /F1 12 Tf 72 720 Td (" + VISIBLE.encode("ascii") + b") Tj ET\n"
        b"BT /F1 12 Tf 72 700 Td 3 Tr ("
        + INVISIBLE.encode("ascii") + b") Tj ET\n"
    )
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
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


def _run_gate(input_dir, output_dir):
    from sieve_tray import run_gate
    return run_gate(input_dir, output_dir)


def _item_by_name(receipt, needle):
    for it in receipt["items"]:
        if needle in str(it.get("path", "")):
            return it
    raise AssertionError(f"no receipt item matches {needle!r}")


def test_t21_invisible_pdf_text_never_reaches_output(tmp_path):
    """SL-T21-1: with pypdf installed, the 3 Tr line stays out of the
    whole output tree and the reason is recorded."""
    pypdf = pytest.importorskip("pypdf")  # the clause is measured WITH pypdf
    assert pypdf.__version__  # and it really is importable

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    _minimal_pdf(inp / "tr3.pdf")
    (inp / "plain.txt").write_text("nothing hidden here\n", encoding="utf-8")

    receipt = _run_gate(inp, out)

    # 1) the invisible string appears nowhere in the whole output tree
    for p in out.rglob("*"):
        if p.is_file():
            blob = p.read_bytes()
            assert INVISIBLE.encode("ascii") not in blob, \
                f"invisible PDF text leaked into {p}"
            assert INVISIBLE.encode("utf-16-le") not in blob, \
                f"invisible PDF text (utf-16) leaked into {p}"

    # 2) the item is unobserved with the closed vocabulary + the detail
    item = _item_by_name(receipt, "tr3.pdf")
    assert item["status"] == "unobserved"
    assert item["unobserved_reason"] == "engine_unavailable"
    assert item["unobserved_detail"] == "pdf_visible_extraction_disabled"
    assert item["lens"]["mask"] == "0000-000"
    assert item["treatment"] == "not_produced"

    # 3) the receipt counters carry the reason
    npbr = receipt["summary"]["not_produced_by_reason"]
    assert npbr.get("engine_unavailable", 0) >= 1


def test_t21_uppercase_pdf_same_guard(tmp_path):
    """SL-T21-2: an upper-case .PDF takes the same short-circuit guard."""
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    _minimal_pdf(inp / "TR3.PDF")

    receipt = _run_gate(inp, out)

    for p in out.rglob("*"):
        if p.is_file():
            assert INVISIBLE.encode("ascii") not in p.read_bytes()

    item = _item_by_name(receipt, "TR3.PDF")
    assert item["kind"] == "document"
    assert item["status"] == "unobserved"
    assert item["unobserved_reason"] == "engine_unavailable"
    assert item["unobserved_detail"] == "pdf_visible_extraction_disabled"
    assert item["treatment"] == "not_produced"
