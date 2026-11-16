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
  PD-T04 - an OCR-layer-only PDF (no painted text, one ``3 Tr``
           line): the visible text is empty, the hidden body is
           reported, and the processing record uses the closed
           vocabulary only (flagged / produced / the css_hidden kind
           - no new word; decided and measured before the feature
           commit, see the §3.2 decision).
  PD-T05 - two PDFs sharing ONLY the invisible marker are never
           reported similar (PDF text never enters the pairwise
           compare - TEXT_EXTS is .txt/.md).
  PD-T06 - the dependency pins: pyproject floor
           sieve-lens[pdf,html-css-full]>=0.22.1, no direct pypdf
           declaration, and the built wheel's METADATA carries the
           same Requires-Dist.
  PD-T08 - gate --self-check carries the PDF probe (expected count
           13 + 1 = 14); the exit-code contract 0/1/2 stays (pinned
           by test_ch_t21_gate_self_check_exit_codes) and the frozen
           GUI entry dispatches to the headless CLI before
           QApplication (pinned by the 2.1.1 tests).
  PD-T09 - the closed vocabularies are unchanged (8 unobserved
           reasons, 6 not-produced reasons); the lifted detail word
           pdf_visible_extraction_disabled is gone from the outputs,
           and a PDF without pypdf keeps the closed
           engine_unavailable reason with no detail.

The expectation values were measured before the red commit
(``scripts/tray221_modes_probe.py`` / ``tray221_ocr_probe.py``
against sieve-lens 0.22.1 / pypdf 6.6.0).
"""
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import sieve_tray
from pd_pdf_builders import (INVISIBLE, MODE_MARKERS, SAME_WORD,
                             build_modes_pdf, build_pdf,
                             build_same_word_pdf, need_pypdf)

REPO_ROOT = Path(__file__).resolve().parent.parent


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


def test_pd_t04_ocr_layer_only_pdf(tmp_path):
    """PD-T04: no painted text, one 3 Tr line - the visible text is
    empty and the record stays in the closed vocabulary."""
    need_pypdf()

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_pdf(inp / "ocr-only.pdf", visible=b"",
              invisible=b"OCR LAYER marker-ocr9")

    receipt = _run_gate(inp, out)

    item = _item_by_name(receipt, "ocr-only.pdf")
    assert item["kind"] == "document"
    assert item["status"] == "flagged"
    assert item["treatment"] == "produced"
    assert item["hidden_segments"]["count"] == 1
    assert item["hidden_segments"]["order_observed"] == 1
    # the visible text is empty: the handoff file exists, 0 bytes
    assert item["output"]["bytes"] == 0
    vf = out / item["output"]["path"]
    assert vf.is_file()
    assert vf.read_bytes() == b""
    # the OCR-layer text stays out of the whole handoff/ tree
    for p in (out / "handoff").rglob("*"):
        if p.is_file():
            blob = p.read_bytes()
            assert b"OCR LAYER marker-ocr9" not in blob
            assert "OCR LAYER marker-ocr9".encode("utf-16-le") not in blob


def test_pd_t05_shared_invisible_marker_is_not_similarity(tmp_path):
    """PD-T05: two PDFs sharing ONLY the invisible marker are never
    reported similar - PDF text never enters the pairwise compare."""
    need_pypdf()

    s1, s2 = tmp_path / "s1", tmp_path / "s2"
    s1.mkdir()
    s2.mkdir()
    build_pdf(s1 / "doc.pdf", visible=b"FIRST SUBMISSION VISIBLE",
              invisible=b"SHARED INVISIBLE marker-pd05")
    build_pdf(s2 / "doc.pdf", visible=b"SECOND SUBMISSION VISIBLE",
              invisible=b"SHARED INVISIBLE marker-pd05")

    result = sieve_tray.run_scan(tmp_path)

    # both PDFs are observed and flagged (the hidden body is reported)
    pdfs = [d for d in result.doc_results
            if str(d["path"]).endswith(".pdf")]
    assert len(pdfs) == 2
    for d in pdfs:
        assert d["status"] == "flagged"
        assert d["mask"] == "1001-000"
    # and nothing is reported similar: the PDF text never rides the
    # pairwise lane, so the shared invisible marker cannot fabricate
    # a pair
    assert result.text_pairs == []


@pytest.fixture(scope="module")
def wheel_path(tmp_path_factory):
    """Build the wheel once for the PD-T06 pins (the CH-T14 way)."""
    dist = tmp_path_factory.mktemp("pd06-dist")
    build = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps",
         "--no-build-isolation", "-w", str(dist), "."],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert build.returncode == 0, build.stdout + build.stderr
    wheels = list(dist.glob("sieve_tray-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_pd_t06_dependency_floor_pins():
    """PD-T06: pyproject pins the published 0.22.1 floor with the pdf
    extra; pypdf is not declared on the tray side."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"sieve-lens[pdf,html-css-full]>=0.22.1"' in pyproject
    assert '"sieve-lens[html-css-full]>=0.22.0"' not in pyproject
    deps_line = pyproject.split("dependencies = ", 1)[1].splitlines()[0]
    assert "pypdf" not in deps_line


def test_pd_t06_wheel_metadata_requires_dist(wheel_path):
    """PD-T06: the built wheel's METADATA carries the same floor."""
    with zipfile.ZipFile(wheel_path) as z:
        meta_name = next(n for n in z.namelist()
                         if n.endswith(".dist-info/METADATA"))
        meta = z.read(meta_name).decode("utf-8")
    reqs = [line for line in meta.splitlines()
            if line.startswith("Requires-Dist:")]
    # setuptools alphabetizes the extras, so match the floor in an
    # order-independent way
    lens_reqs = [r for r in reqs
                 if r.startswith("Requires-Dist: sieve-lens[")]
    assert len(lens_reqs) == 1, reqs
    lens_req = lens_reqs[0][len("Requires-Dist: sieve-lens["):]
    extras, _, floor = lens_req.partition("]")
    assert set(extras.split(",")) == {"pdf", "html-css-full"}
    assert floor == ">=0.22.1"
    assert not any(r.startswith("Requires-Dist: pypdf") for r in reqs)


def test_pd_t08_self_check_carries_pdf_probe():
    """PD-T08: gate --self-check runs the PDF probe (13 + 1 = 14) and
    matches everything on a healthy environment."""
    result = sieve_tray.gate_self_check(progress=None)
    assert result["expected"] == 14, result["differences"]
    assert result["matching"] == result["expected"]
    assert result["differences"] == []


def test_pd_t09_vocabulary_unchanged():
    """PD-T09: the closed vocabularies keep exactly their old words."""
    assert sieve_tray.UNOBSERVED_REASONS == frozenset({
        "refused", "parse_failed", "unreadable", "too_large",
        "symlink_skipped", "engine_unavailable", "not_applicable",
        "empty_input"})
    assert sieve_tray.NOT_PRODUCED_REASONS == frozenset({
        "needs_settings", "unobserved", "not_applicable",
        "engine_unavailable", "engine_refused", "write_failed"})
    assert "pdf_visible_extraction_disabled" \
        not in sieve_tray.UNOBSERVED_REASONS


def test_pd_t09_pdf_without_pypdf_keeps_closed_vocabulary(
        tmp_path, monkeypatch):
    """PD-T09: without pypdf the PDF degrades to the closed
    engine_unavailable reason with NO detail (the lifted detail word
    never reappears)."""
    import importlib as _importlib

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_pdf(inp / "doc.pdf")
    real = _importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name in ("sieve_lens_ext.pdf", "sieve_lens_ext.pdf_images"):
            raise ImportError("simulated: %s" % name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(_importlib, "import_module", fake_import)

    receipt = _run_gate(inp, out)

    item = _item_by_name(receipt, "doc.pdf")
    assert item["status"] == "unobserved"
    assert item["unobserved_reason"] == "engine_unavailable"
    assert item["unobserved_detail"] is None
    assert item["treatment"] == "not_produced"
