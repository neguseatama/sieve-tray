"""Tray 2.2.1 - the Gate PDF lane reopens (reopen request §3.2, §4).

The 2.2.0 short-circuit is gone: Lens 0.22.1 builds the visible text
and the hidden report from one shared classification (the text a PDF
does not paint can never appear on the visible side), so Gate can
observe PDFs again.  The PD tests pin the reopened lane:

  PD-T02 - one marker per text render mode 0..7 on one page: the
           painted modes (0, 1, 2, 4, 5, 6) reach the handoff visible
           text, mode 3 stays out (and is reported as a hidden body),
           mode 7 (clip only, paints nothing) stays out entirely
           (measured 2026-11-16 with Lens 0.22.1).
  PD-T03 - the same word on both the visible and the invisible line:
           exactly one occurrence in the handoff visible text.

The expectation values were measured before the red commit
(``scripts/tray221_modes_probe.py`` against sieve-lens 0.22.1 /
pypdf 6.6.0).
"""
from pathlib import Path

from pd_pdf_builders import (MODE_MARKERS, SAME_WORD, build_modes_pdf,
                             build_pdf, build_same_word_pdf, need_pypdf)


def _run_gate(input_dir, output_dir):
    from sieve_tray import run_gate
    return run_gate(input_dir, output_dir)


def _item_by_name(receipt, needle):
    for it in receipt["items"]:
        if needle in str(it.get("path", "")):
            return it
    raise AssertionError(f"no receipt item matches {needle!r}")


def _visible_text_of(out: Path, item: dict) -> bytes:
    return (out / item["output"]["path"]).read_bytes()


def test_pd_t02_render_modes_painted_vs_not(tmp_path):
    """PD-T02: painted modes reach the handoff text; modes 3 and 7
    stay out of the whole handoff/ tree."""
    need_pypdf()

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_modes_pdf(inp / "modes.pdf")

    receipt = _run_gate(inp, out)

    item = _item_by_name(receipt, "modes.pdf")
    assert item["kind"] == "document"
    assert item["status"] == "flagged"
    assert item["treatment"] == "produced"
    # one hidden body: the mode-3 marker
    assert item["hidden_segments"]["count"] == 1

    text = _visible_text_of(out, item)
    for mode in (0, 1, 2, 4, 5, 6):
        assert MODE_MARKERS[mode].encode("ascii") in text, \
            f"painted mode {mode} ({MODE_MARKERS[mode]}) missing"

    # modes 3 and 7: nowhere in the whole handoff/ tree (raw bytes)
    for p in (out / "handoff").rglob("*"):
        if not p.is_file():
            continue
        blob = p.read_bytes()
        for bad in (3, 7):
            assert MODE_MARKERS[bad].encode("ascii") not in blob, \
                f"mode-{bad} text leaked into {p}"
            assert MODE_MARKERS[bad].encode("utf-16-le") not in blob, \
                f"mode-{bad} text (utf-16) leaked into {p}"


def test_pd_t03_same_word_visible_and_invisible(tmp_path):
    """PD-T03: the shared word survives exactly once in the visible
    text - the invisible occurrence never doubles it."""
    need_pypdf()

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_same_word_pdf(inp / "same.pdf")

    receipt = _run_gate(inp, out)

    item = _item_by_name(receipt, "same.pdf")
    assert item["treatment"] == "produced"
    assert item["hidden_segments"]["count"] == 1

    text = _visible_text_of(out, item)
    assert text.count(SAME_WORD.encode("ascii")) == 1
    assert b"secret" not in text
