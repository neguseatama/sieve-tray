"""Seal 2.2 / S0 - the PDF clause, updated to the PD-T01 form (2.2.1).

2.2.0 short-circuited the Gate PDF lane (reason ``engine_unavailable``,
detail ``pdf_visible_extraction_disabled``) because the then-current
Lens visible-text extraction did not interpret the rendering mode
``3 Tr``: the invisible text rode into ``handoff/*.pdf.visible.txt``
(measured in the 2.2 start-up report section 2-2).

Lens 0.22.1 removes the leak at the source: the visible text is built
from the same classification that reports the hidden text, so the
hidden bodies can never re-enter the visible side.  Tray 2.2.1
(reopen request §3.2) therefore lifts the short-circuit: a PDF rides
the normal document lane again.

SL-T21 stays as the regression, updated to the PD-T01 form (the
reopen request §4):
  1. a hand-built PDF (one visible line + one ``3 Tr`` invisible
     line) is OBSERVED; the invisible string appears nowhere in the
     whole ``handoff/`` tree (raw bytes, ascii and utf-16), the
     observation reports the hidden body (count 1, Order observed),
     and the visible line reaches ``handoff/*.pdf.visible.txt``.
  2. an upper-case ``.PDF`` takes the same lane (the suffix is
     normalised before the lane dispatch).
"""
from pathlib import Path

from pd_pdf_builders import (INVISIBLE, VISIBLE, build_pdf, need_pypdf)


def _run_gate(input_dir, output_dir):
    from sieve_tray import run_gate
    return run_gate(input_dir, output_dir)


def _item_by_name(receipt, needle):
    for it in receipt["items"]:
        if needle in str(it.get("path", "")):
            return it
    raise AssertionError(f"no receipt item matches {needle!r}")


def _handoff_files(out: Path):
    handoff = out / "handoff"
    assert handoff.is_dir(), "run_gate produced no handoff/ folder"
    return [p for p in handoff.rglob("*") if p.is_file()]


def test_t21_invisible_pdf_text_never_reaches_handoff(tmp_path):
    """SL-T21-1 / PD-T01: the 3 Tr line stays out of the whole
    handoff/ tree, is reported as hidden, and the item is observed."""
    need_pypdf()

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_pdf(inp / "tr3.pdf")
    (inp / "plain.txt").write_text("nothing hidden here\n",
                                   encoding="utf-8")

    receipt = _run_gate(inp, out)

    # 1) the invisible string appears nowhere in the whole handoff tree
    for p in _handoff_files(out):
        blob = p.read_bytes()
        assert INVISIBLE.encode("ascii") not in blob, \
            f"invisible PDF text leaked into {p}"
        assert INVISIBLE.encode("utf-16-le") not in blob, \
            f"invisible PDF text (utf-16) leaked into {p}"

    # 2) the item is observed (flagged), the hidden body is reported
    item = _item_by_name(receipt, "tr3.pdf")
    assert item["kind"] == "document"
    assert item["status"] == "flagged"
    assert item["treatment"] == "produced"
    assert item["hidden_segments"]["count"] == 1
    assert item["hidden_segments"]["order_observed"] == 1
    assert item["output"]["path"].endswith("tr3.pdf.visible.txt")

    # 3) the visible line reaches the handoff file, the invisible one
    #    does not
    visible_file = out / item["output"]["path"]
    text = visible_file.read_text(encoding="utf-8")
    assert VISIBLE in text
    assert INVISIBLE not in text


def test_t21_uppercase_pdf_same_lane(tmp_path):
    """SL-T21-2 / PD-T01: an upper-case .PDF takes the same observed
    lane as the lower-case one."""
    need_pypdf()

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_pdf(inp / "TR3.PDF")

    receipt = _run_gate(inp, out)

    for p in _handoff_files(out):
        blob = p.read_bytes()
        assert INVISIBLE.encode("ascii") not in blob
        assert INVISIBLE.encode("utf-16-le") not in blob

    item = _item_by_name(receipt, "TR3.PDF")
    assert item["kind"] == "document"
    assert item["status"] == "flagged"
    assert item["treatment"] == "produced"
    assert item["hidden_segments"]["count"] == 1
