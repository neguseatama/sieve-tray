"""Tray 2.4.0 - the PDF exchange lane (request §4, PX-T01..T15).

Red-first (2026-11-21): the five red tests PX-T01 / T03 / T07 / T09 /
T10 enter the suite BEFORE the implementation and fail on the 2.3.1
tree, plus pins that guard what must not move (PX-T05's handoff shape
- green at birth - and the Lens 0.23.x location grammar the record
extraction reads).  The 2026-11-21 verification added the missing
rows and fixed the numbering to the request's own: the white-text
background judgment is PX-T02 (green at birth under the 0.23.x
observation, red under the 0.22.1 floor), Cohort is PX-T04, the
in_content observation is PX-T11, the unobserved reasons are PX-T12,
and the widened XMP scope rides PX-T07.  The former T02/T04/T05
functions were renamed mechanically (T02 -> T05, docs -> T15, the
frozen-app self-check -> T13).

  PX-T01 - the dependency floor moves to the PUBLISHED 0.23.0, and
           the six fixed hidden kinds (Tr 3, Tr 7, tiny_font,
           off_page, off_layer, white_text) reach Gate's
           hidden_segments count and the Order observation.
  PX-T02 - the white-text background judgment: white text ON a
           painted rectangle is visible (it reaches the handoff
           output), bare white text hides; the Lens diagnostic keys
           never enter the receipt.
  PX-T03 - the raw-byte inspection: the layer name and the fixed
           words never enter handoff/, the local record carries only
           the fixed words + page positions (the name part is thrown
           away, unknown location shapes record the position alone),
           and the digest and verify are untouched by the record.
  PX-T04 - Cohort: the PDF's five-kind observation reaches the
           report (hidden count + fragments), the PDF text joins no
           comparison pool, and cohort writes no kind record.
  PX-T05 - (pin) the handoff processing record keeps its existing
           shape: the closed hidden_segments keys, no location, no
           kind word anywhere in the receipt; a run without PDFs
           writes no kind record at all.
  PX-T07 - a PDF joins clean: the Info metadata is removed, the
           content is kept, the removed values ride the local report
           only, and the original file is untouched; the XMP
           /Metadata is removed at the catalog, page, image-XObject
           and AcroForm level together with /Thumb and /PieceInfo.
  PX-T09 - the determinism contract: SAME pypdf version, two runs,
           byte-identical output (no fixed sha256 lives in this
           test), and the /ID is decided by the content - two inputs
           differing only in their metadata clean to identical bytes.
  PX-T10 - an incremental-update PDF (old front-half Info behind
           /Prev) is rewritten so the old values survive nowhere in
           the output bytes while the page and its text survive.
  PX-T11 - the in_content observation: annotations, embedded files
           and form field values are observed, reported with the
           EXISTING closed words, and never removed.
  PX-T12 - the unobserved reasons: encrypted = refused, a broken PDF
           = parse_failed, no pypdf = engine_unavailable (the size
           and symlink rules stay as they are).

The expectations were measured before the red commit
(scripts/tray240_px_probe.py against sieve-lens 0.23.0 / pypdf 6.6.0,
tree fcd5a484; probe2/probe3 on pypdf 7.1.0 for the verification
rows).  The PX-T05 pin and the T03 handoff-absence half are green at
birth; the record-dependent and clean-dependent halves go red here
and turn green with the feature commit.
"""
import io
import json
import sys
from pathlib import Path

import pytest

import sieve_tray
from px_pdf_builders import (ANNOT_TEXT, EMBED_NAME, FORM_FIELD,
                             FORM_VALUE, FULL_TEXT, INCREMENTAL_TEXT,
                             LAYER_NAME, LOCATION_WORDS, META_MARKERS,
                             META_TEXT, NEW_AUTHOR, NEW_CREATOR,
                             OLD_AUTHOR, OLD_CREATOR, SIX_KIND_LOCATIONS,
                             SIX_KIND_TEXTS, VISIBLE_LINE,
                             WHITE_BARE_TEXT, WHITE_BG_PLAIN_TEXT,
                             WHITE_ON_PAINTED_TEXT, XMP_MARKERS,
                             build_incremental_pdf, build_meta_pdf,
                             build_six_kinds_pdf, build_white_bg_pdf,
                             build_xmp_full_pdf, need_pypdf)

REPO_ROOT = Path(__file__).resolve().parent.parent

# the fixed words, in the order the six-kind probe emits them
RECORD_WORDS = ["Tr 3", "Tr 7", "tiny_font", "off_page",
                "off_layer", "white_text"]


def _run_gate(input_dir, output_dir):
    from sieve_tray import run_gate
    return run_gate(input_dir, output_dir)


def _run_clean(input_dir, output_dir):
    from sieve_canon import run_clean
    return run_clean(Path(input_dir), Path(output_dir))


def _run_cohort(input_dir, output_dir):
    from sieve_tray import run_cohort
    return run_cohort(Path(input_dir), Path(output_dir))


def _item_by_name(receipt, needle):
    for it in receipt["items"]:
        if needle in str(it.get("path", "")):
            return it
    raise AssertionError(f"no receipt item matches {needle!r}")


def _zeros():
    from sieve_canon import CN_META_CATEGORIES
    return {c: 0 for c in CN_META_CATEGORIES}


# ---------------------------------------------------------------------------
# PX-T01: the floor and the six kinds

def test_px_t01_dependency_floor_and_hidden_kinds(tmp_path):
    """PX-T01: the floor names the published 0.23.0 and Gate counts
    all six fixed kinds (red on 2.3.1: the floor still says 0.22.1
    and the floor lens reports only Tr 3)."""
    need_pypdf()

    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"sieve-lens[pdf,html-css-full]>=0.23.0"' in pyproject
    assert '"sieve-lens[pdf,html-css-full]>=0.22.1"' not in pyproject
    deps_line = pyproject.split("dependencies = ", 1)[1].splitlines()[0]
    assert "pypdf" not in deps_line

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_six_kinds_pdf(inp / "six.pdf")

    receipt = _run_gate(inp, out)
    item = _item_by_name(receipt, "six.pdf")
    assert item["kind"] == "document"
    assert item["status"] == "flagged"
    assert item["treatment"] == "produced"
    # one hidden body per fixed word + nothing else
    assert item["hidden_segments"]["count"] == 6
    assert item["hidden_segments"]["order_observed"] == 6
    assert item["hidden_segments"]["truncated"] == 0
    assert item["hidden_segments"]["skipped"] == 0

    # the visible side keeps only the plain line
    vis = (out / item["output"]["path"]).read_bytes()
    assert VISIBLE_LINE.encode("ascii") in vis
    for text in SIX_KIND_TEXTS.values():
        assert text.encode("ascii") not in vis


# ---------------------------------------------------------------------------
# PX-T02: the white-text background judgment (the 2026-11-21 verification)

def test_px_t02_white_text_background_judgment(tmp_path):
    """PX-T02: white text ON a painted rectangle is visible - it
    reaches the handoff output; bare white text hides (count 1).
    The Lens diagnostic keys (white_on_painted, color_unresolved)
    fire on this input yet never enter the receipt bytes."""
    need_pypdf()
    from sieve_lens import SieveLensEngine
    from sieve_lens_ext.pdf import install as _pdf_install

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_white_bg_pdf(inp / "whitebg.pdf")

    # the observation sanity: the judgment fired (painted white kept,
    # bare white hidden) - under the 0.22.1 floor both whites ride the
    # visible side and this test goes red (the floor guard)
    engine = SieveLensEngine()
    _pdf_install(engine)
    obs = engine.observe(inp / "whitebg.pdf")
    assert dict(obs.diagnostics).get("white_on_painted") == 1
    hidden = [s for s in obs.segments if not s.visible]
    assert [s.text for s in hidden] == [WHITE_BARE_TEXT]

    receipt = _run_gate(inp, out)
    item = _item_by_name(receipt, "whitebg.pdf")
    assert item["status"] == "flagged"
    assert item["hidden_segments"]["count"] == 1
    assert item["treatment"] == "produced"

    # the painted white and the plain line reach the handoff output;
    # the bare white does not
    vis = (out / item["output"]["path"]).read_text("utf-8")
    assert WHITE_ON_PAINTED_TEXT in vis
    assert WHITE_BG_PLAIN_TEXT in vis
    assert WHITE_BARE_TEXT not in vis

    # the diagnostic keys never enter the receipt
    receipt_bytes = json.dumps(receipt, sort_keys=True).encode("utf-8")
    assert b"white_on_painted" not in receipt_bytes
    assert b"color_unresolved" not in receipt_bytes


# ---------------------------------------------------------------------------
# PX-T04: Cohort - observed, but never text-compared

def test_px_t04_cohort_pdf_observed_not_compared(tmp_path):
    """PX-T04: the cohort document lane observes the PDFs (the hidden
    count carries the five kinds, the fragments reach the local
    report), the PDF text joins NO comparison pair, and cohort writes
    no kind record.  Red before the feature commit: the PDFs join the
    referee pool."""
    need_pypdf()

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_six_kinds_pdf(inp / "a.pdf")
    build_meta_pdf(inp / "b.pdf")
    (inp / "note.txt").write_bytes(b"shared sentence one.\n")

    receipt = _run_cohort(inp, out)
    by_path = {it.get("path"): it for it in receipt["items"]}
    a = by_path["a.pdf"]
    b = by_path["b.pdf"]
    # observed: the five kinds ride the hidden count, the mask is real
    assert a["kind"] == "document"
    assert a["hidden_segments"]["count"] == 6
    assert a["hidden_segments"]["order_observed"] == 6
    assert a["lens"]["mask"] == "1001-000"
    assert b["hidden_segments"]["count"] == 0
    # the PDF text never joins the comparison pool (the closed words:
    # not_compared + not_applicable)
    assert a["status"] == "not_compared"
    assert a["unobserved_reason"] == "not_applicable"
    assert b["status"] == "not_compared"
    assert b["unobserved_reason"] == "not_applicable"
    # the non-PDF document still compares
    assert by_path["note.txt"]["status"] == "compared"
    # no pair carries a PDF side
    for p in receipt.get("pairs", []):
        assert not str(p.get("a", "")).endswith(".pdf"), p
        assert not str(p.get("b", "")).endswith(".pdf"), p
    # the observation reaches the local report (the fragments)
    report = (out / "local" / "cohort-report.html").read_text("utf-8")
    assert SIX_KIND_TEXTS["Tr 3"] in report
    # cohort writes no kind record (the record is the Gate lane only)
    assert not (out / "local" / "gate-hidden-kinds.json").exists()


# ---------------------------------------------------------------------------
# PX-T05: the handoff shape pin (green at birth; was T02 before the
# 2026-11-21 verification renamed the numbers to the request's own)

def test_px_t05_handoff_shape_unchanged(tmp_path):
    """PX-T05: the receipt item keeps the exact 2.3.1 key set, the
    closed hidden_segments keys, and no location / kind word anywhere
    in the receipt bytes."""
    need_pypdf()

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_six_kinds_pdf(inp / "six.pdf")

    receipt = _run_gate(inp, out)
    item = _item_by_name(receipt, "six.pdf")
    assert set(item.keys()) == {
        "engine_detail", "hidden_segments", "input", "kind", "lens",
        "not_produced_reason", "output", "path", "redact",
        "removed_invisible", "status", "treatment",
        "unobserved_detail", "unobserved_reason"}
    assert set(item["hidden_segments"].keys()) == {
        "count", "order_observed", "order_axes", "truncated", "skipped"}

    receipt_bytes = json.dumps(receipt, sort_keys=True).encode("utf-8")
    for word in LOCATION_WORDS:
        assert word.encode("ascii") not in receipt_bytes, word
    assert LAYER_NAME.encode("ascii") not in receipt_bytes
    assert b"page 1 (" not in receipt_bytes


def test_px_t05_run_without_pdf_writes_no_kind_record(tmp_path):
    """PX-T05: a run without any PDF keeps the local tree exactly as
    2.3.1 wrote it - no kind record file appears (the stopping
    condition stays untriggered for non-PDF inputs)."""
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    (inp / "plain.txt").write_bytes(b"plain body line\n", )
    (inp / "note.md").write_bytes(b"# note\n\nplain body\n")

    _run_gate(inp, out)
    assert not (out / "local" / "gate-hidden-kinds.json").exists()


# ---------------------------------------------------------------------------
# PX-T03: the raw-byte inspection and the local kind record

def test_px_t03_raw_bytes_and_local_kind_record(tmp_path):
    """PX-T03: the layer name and the six fixed words never enter
    handoff/; the record under local/ carries only the fixed words and
    the page positions (no name); the digest and verify are untouched."""
    need_pypdf()

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_six_kinds_pdf(inp / "six.pdf")

    receipt = _run_gate(inp, out)

    # handoff/ raw bytes: no name, no fixed word, no location fragment
    handoff_raw = b""
    for p in (out / "handoff").rglob("*"):
        if p.is_file():
            handoff_raw += p.read_bytes()
    assert LAYER_NAME.encode("ascii") not in handoff_raw
    assert LAYER_NAME.encode("utf-16-le") not in handoff_raw
    for word in LOCATION_WORDS:
        assert word.encode("ascii") not in handoff_raw, word
    assert b"page 1 (" not in handoff_raw

    # the record lives under local/ only, one entry per hidden body,
    # word + page position and nothing else
    record_path = out / "local" / "gate-hidden-kinds.json"
    assert record_path.is_file()
    record_bytes = record_path.read_bytes()
    record = json.loads(record_bytes.decode("utf-8"))
    assert record["record_version"] == 1
    assert record["kind"] == "sieve-gate-hidden-kinds"
    assert record["items"] == [{"item": 1, "entries": [
        {"page": "page 1", "word": "Tr 3"},
        {"page": "page 1", "word": "Tr 7"},
        {"page": "page 1", "word": "tiny_font"},
        {"page": "page 1", "word": "off_page"},
        {"page": "page 1", "word": "off_layer"},
        {"page": "page 1", "word": "white_text"},
    ]}]
    # the name part is thrown away - and so is every free-form string
    assert LAYER_NAME.encode("ascii") not in record_bytes

    # the record is not part of the processing record: the digest
    # and the verify verdict stay exactly as without it
    from sieve_tray import verify_gate
    verdict = verify_gate(out / "handoff" / "gate-receipt.json",
                          output_dir=out)
    assert verdict["overall"] == "match", verdict


def test_px_t03_record_words_are_the_fixed_list_only():
    """PX-T03: the words come out of the fixed list only.  A location
    outside the list records the page position alone (no new word); a
    location without a page position records nothing; the quoted name
    part is discarded BEFORE the match (a name containing a fixed
    word cannot fabricate a second word)."""
    entries = sieve_tray._gate_hidden_kinds_entries
    # the six 0.23.x shapes -> exactly their fixed word
    assert entries("page 1 (invisible text, Tr 3)") == \
        [{"page": "page 1", "word": "Tr 3"}]
    assert entries("page 1 (invisible text, Tr 7)") == \
        [{"page": "page 1", "word": "Tr 7"}]
    assert entries("page 1 (tiny_font)") == \
        [{"page": "page 1", "word": "tiny_font"}]
    assert entries("page 1 (off_page)") == \
        [{"page": "page 1", "word": "off_page"}]
    assert entries("page 1 (off_layer '%s')" % LAYER_NAME) == \
        [{"page": "page 1", "word": "off_layer"}]
    assert entries("page 1 (white_text)") == \
        [{"page": "page 1", "word": "white_text"}]
    # the form shape: the form name and the layer name are thrown away
    assert entries("page 1 (form '/Fm0', off_layer '/L1')") == \
        [{"page": "page 1", "word": "off_layer"}]
    # a location outside the list: position only, no new word
    assert entries("page 1 (future_label)") == [{"page": "page 1"}]
    # a name containing a fixed word cannot fabricate that word
    assert entries("page 1 (off_layer 'tiny_font')") == \
        [{"page": "page 1", "word": "off_layer"}]
    # no page position: nothing is recorded
    assert entries("selector:body > p") == []


# ---------------------------------------------------------------------------
# PX-T07: the PDF joins clean

def test_px_t07_clean_pdf_joins_metadata_removal(tmp_path):
    """PX-T07: doc.pdf stops being not_applicable - the Info metadata
    is removed, the page and its text are kept, the removed values
    ride the local report only, and the original file is untouched."""
    need_pypdf()
    from pypdf import PdfReader

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_meta_pdf(inp / "doc.pdf")
    before = (inp / "doc.pdf").read_bytes()

    receipt = _run_clean(inp, out)
    assert len(receipt["items"]) == 1
    item = receipt["items"][0]
    assert item["status"] == "cleaned"
    assert item["format"] == "pdf"
    assert item["reason"] is None

    # the closed categories: what the PDF carries before, zero after
    before_cats = item["categories_before"]
    assert before_cats["author"] >= 1
    assert before_cats["time"] >= 2
    assert before_cats["software"] >= 2
    assert before_cats["title_subject"] >= 3
    assert before_cats["custom"] >= 1
    assert before_cats["location"] == 0
    assert before_cats["device"] == 0
    assert item["categories_after"] == _zeros()
    assert item["in_content"] == {"comment": 0, "tracked_change": 0,
                                  "hidden_part": 0}
    assert item["content_checksum_match"] is True
    assert item["output_bytes"] > 0

    # the cleaned copy opens, keeps its one page and its text
    out_bytes = (out / "handoff" / "doc.pdf").read_bytes()
    assert out_bytes.startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(out_bytes))
    assert len(reader.pages) == 1
    assert META_TEXT in reader.pages[0].extract_text()

    # the removed values never enter handoff/
    handoff_raw = b""
    for p in (out / "handoff").rglob("*"):
        if p.is_file():
            handoff_raw += p.read_bytes()
    for marker in META_MARKERS.values():
        assert marker.encode("ascii") not in handoff_raw
    # the local report carries the detail instead
    local = (out / "local" / "clean-report.html").read_text("utf-8")
    assert META_MARKERS["author"] in local
    assert META_MARKERS["creator"] in local

    # the original file rides unchanged
    assert (inp / "doc.pdf").read_bytes() == before


def test_px_t07_xmp_removed_at_every_level(tmp_path):
    """PX-T07 (the 2026-11-21 verification row): the XMP /Metadata
    leaves at EVERY level - the catalog, the page, the image XObject
    and the AcroForm - together with the page /Thumb and /PieceInfo at
    the catalog and the page.  The marker streams ride uncompressed in
    the input (measured), so the raw-byte absence in the output is a
    real assertion, and the after-observation counts zero everywhere."""
    need_pypdf()
    from pypdf import PdfReader

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_xmp_full_pdf(inp / "full.pdf")

    # the measured premise: the markers ARE in the input raw bytes
    raw_in = (inp / "full.pdf").read_bytes()
    for marker in XMP_MARKERS.values():
        assert marker.encode("ascii") in raw_in, marker
    assert b"/Thumb" in raw_in

    receipt = _run_clean(inp, out)
    item = receipt["items"][0]
    assert item["status"] == "cleaned"
    assert item["categories_after"] == _zeros()
    assert item["content_checksum_match"] is True

    out_bytes = (out / "handoff" / "full.pdf").read_bytes()
    for marker in XMP_MARKERS.values():
        assert marker.encode("ascii") not in out_bytes, marker
    assert b"/Thumb" not in out_bytes

    # the logical view agrees: no /Metadata anywhere, no /Thumb,
    # no /PieceInfo; the content still reads
    reader = PdfReader(io.BytesIO(out_bytes))
    root = reader.trailer["/Root"]
    assert root.get("/Metadata") is None
    assert root.get("/PieceInfo") is None
    # /Names carries the embedded file - CONTENT, kept (PX-T11)
    assert root.get("/Names") is not None
    page = reader.pages[0]
    assert page.get("/Metadata") is None
    assert page.get("/Thumb") is None
    assert page.get("/PieceInfo") is None
    acro = root.get("/AcroForm")
    assert acro is not None and acro.get("/Metadata") is None
    img = (page["/Resources"].get("/XObject") or {})["/Im1"].get_object()
    assert img.get("/Metadata") is None
    assert FULL_TEXT in page.extract_text()
    # the reader-side metadata is gone entirely
    assert dict(reader.metadata or {}).get("/Author") is None


# ---------------------------------------------------------------------------
# PX-T09: the determinism contract (same version, two runs)

def test_px_t09_same_version_determinism(tmp_path):
    """PX-T09: the contract is the SAME pypdf version, two runs,
    byte-identical output.  No fixed sha256 lives in this test (the
    2026-11-21 ruling)."""
    need_pypdf()

    inp = tmp_path / "in"
    inp.mkdir()
    build_meta_pdf(inp / "doc.pdf")
    o1, o2 = tmp_path / "o1", tmp_path / "o2"

    r1 = _run_clean(inp, o1)
    r2 = _run_clean(inp, o2)

    assert (o1 / "handoff" / "doc.pdf").read_bytes() == \
        (o2 / "handoff" / "doc.pdf").read_bytes()
    assert (o1 / "handoff" / "clean-receipt.json").read_bytes() == \
        (o2 / "handoff" / "clean-receipt.json").read_bytes()
    assert r1["items"][0]["output_sha256"] == \
        r2["items"][0]["output_sha256"]


def test_px_t09_id_is_content_derived(tmp_path):
    """PX-T09: the /ID is decided by the content - two inputs that
    differ only in their metadata clean to IDENTICAL bytes (the same
    content-derived /ID included)."""
    need_pypdf()

    inp = tmp_path / "in"
    inp.mkdir()
    build_meta_pdf(inp / "a.pdf", author="SIEVE-PDF-AUTHOR-1")
    build_meta_pdf(inp / "b.pdf", author="SIEVE-PDF-AUTHOR-2")
    o1, o2 = tmp_path / "o1", tmp_path / "o2"

    _run_clean(inp, o1)
    _run_clean(inp, o2)

    a = (o1 / "handoff" / "a.pdf").read_bytes()
    b = (o2 / "handoff" / "b.pdf").read_bytes()
    assert a == b
    from pypdf import PdfReader
    id_a = PdfReader(io.BytesIO(a)).trailer.get("/ID")
    id_b = PdfReader(io.BytesIO(b)).trailer.get("/ID")
    assert id_a is not None
    assert list(id_a) == list(id_b)


# ---------------------------------------------------------------------------
# PX-T10: the incremental update

def test_px_t10_incremental_old_info_dropped(tmp_path):
    """PX-T10: an incremental-update PDF is rewritten so the front
    half's old Info survives nowhere in the output bytes, the newest
    Info is removed with the rest, and the page and its text survive."""
    need_pypdf()
    from pypdf import PdfReader

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_incremental_pdf(inp / "incr.pdf")

    # sanity: a reader resolves the newest /Info through /Prev
    reader = PdfReader(str(inp / "incr.pdf"))
    assert reader.metadata.get("/Author") == NEW_AUTHOR

    receipt = _run_clean(inp, out)
    item = _item_by_name(receipt, "incr.pdf")
    assert item["status"] == "cleaned"
    assert item["format"] == "pdf"
    assert item["content_checksum_match"] is True

    out_bytes = (out / "handoff" / "incr.pdf").read_bytes()
    # the old front half is gone, and the newest metadata is gone too
    for marker in (OLD_AUTHOR, OLD_CREATOR, NEW_AUTHOR, NEW_CREATOR):
        assert marker.encode("ascii") not in out_bytes
    # the logical content survives
    out_reader = PdfReader(io.BytesIO(out_bytes))
    assert len(out_reader.pages) == 1
    assert INCREMENTAL_TEXT in out_reader.pages[0].extract_text()

    handoff_raw = b""
    for p in (out / "handoff").rglob("*"):
        if p.is_file():
            handoff_raw += p.read_bytes()
    assert OLD_AUTHOR.encode("ascii") not in handoff_raw
    assert NEW_AUTHOR.encode("ascii") not in handoff_raw


# ---------------------------------------------------------------------------
# PX-T11: the in_content observation (kept, never removed)

def test_px_t11_in_content_observed_not_removed(tmp_path):
    """PX-T11: the annotations, the embedded files and the form field
    values are OBSERVED with the existing closed in_content words and
    reported in the receipt, and the output keeps every one of them.
    Red before the feature commit: the PDF is not_applicable."""
    need_pypdf()
    from pypdf import PdfReader

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_xmp_full_pdf(inp / "full.pdf")

    receipt = _run_clean(inp, out)
    item = receipt["items"][0]
    assert item["status"] == "cleaned"
    # the closed words only: the annotation counts as a comment, the
    # embedded file and the form value count as hidden parts; a PDF
    # carries no tracked change
    assert item["in_content"] == {"comment": 1, "tracked_change": 0,
                                  "hidden_part": 2}

    out_bytes = (out / "handoff" / "full.pdf").read_bytes()
    reader = PdfReader(io.BytesIO(out_bytes))
    root = reader.trailer["/Root"]
    # the annotation survives
    assert len(reader.pages[0].get("/Annots") or []) == 1
    # the embedded file survives
    assert (root.get("/Names") or {}).get("/EmbeddedFiles") is not None
    # the form field with its value survives
    acro = root.get("/AcroForm")
    assert acro is not None
    field = acro["/Fields"][0].get_object()
    assert str(field.get("/T")) == FORM_FIELD
    assert str(field.get("/V")) == FORM_VALUE
    assert FULL_TEXT in reader.pages[0].extract_text()

    # the receipt carries the counts, not the values
    receipt_blob = json.dumps(receipt, sort_keys=True).encode("utf-8")
    for value in (ANNOT_TEXT, EMBED_NAME, FORM_VALUE):
        assert value.encode("ascii") not in receipt_blob, value


# ---------------------------------------------------------------------------
# PX-T12: the unobserved reasons

def test_px_t12_unobserved_reasons(tmp_path, monkeypatch):
    """PX-T12: an encrypted PDF is refused, a broken PDF is
    parse_failed, and without pypdf the reason is engine_unavailable -
    all three with the existing closed words.  The symlink rule stays
    untouched (the scan skips links; no new size rule appears)."""
    need_pypdf()
    import os as _os
    from pypdf import PdfWriter

    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()

    # the encrypted probe (RC4, user password set)
    enc_writer = PdfWriter()
    enc_writer.add_blank_page(width=612, height=792)
    enc_writer.encrypt("secret")
    with open(inp / "enc.pdf", "wb") as f:
        enc_writer.write(f)
    # the broken probe (not a PDF at all)
    (inp / "broken.pdf").write_bytes(b"%PDF-1.4\nnot really a pdf\x00\x01")

    receipt = _run_clean(inp, out)
    by_path = {it.get("path"): it for it in receipt["items"]}
    enc = by_path["enc.pdf"]
    assert enc["status"] == "refused"
    assert enc["reason"] == "refused"
    assert enc["output_sha256"] is None
    broken = by_path["broken.pdf"]
    assert broken["status"] == "refused"
    assert broken["reason"] == "parse_failed"
    # no copy of either reaches handoff/
    assert not (out / "handoff" / "enc.pdf").exists()
    assert not (out / "handoff" / "broken.pdf").exists()

    # the engine_unavailable probe: no pypdf importable
    out2 = tmp_path / "out2"
    inp2 = tmp_path / "in2"
    inp2.mkdir()
    build_meta_pdf(inp2 / "doc.pdf")
    monkeypatch.setitem(sys.modules, "pypdf", None)
    receipt2 = _run_clean(inp2, out2)
    it2 = receipt2["items"][0]
    assert it2["status"] == "refused"
    assert it2["reason"] == "engine_unavailable"
    monkeypatch.undo()

    # the symlink rule stays as it is: the scan skips the link and the
    # receipt carries no row for it (POSIX - Windows CI cannot symlink)
    if _os.name != "nt":
        inp3 = tmp_path / "in3"
        inp3.mkdir()
        (inp3 / "plain.txt").write_bytes(b"plain body line\n")
        link = inp3 / "link.pdf"
        link.symlink_to(inp2 / "doc.pdf")
        out3 = tmp_path / "out3"
        receipt3 = _run_clean(inp3, out3)
        paths = [it.get("path") for it in receipt3["items"]]
        assert "link.pdf" not in paths
        assert "plain.txt" in paths


# ---------------------------------------------------------------------------
# the Lens 0.23.x location grammar pin (the 2026-11-21 ruling)

def test_lens023x_location_format_pinned(tmp_path):
    """The record extraction reads the words OUT of the location
    strings, so the 0.23.x grammar is pinned here: when Lens changes
    the shape this goes red instead of drifting silently.  The
    dependency is scheduled to dissolve in Lens 0.24 (a structured
    kind field on the observation segment)."""
    need_pypdf()
    from sieve_lens import SieveLensEngine
    from sieve_lens_ext.pdf import install

    inp = tmp_path / "in"
    inp.mkdir()
    build_six_kinds_pdf(inp / "six.pdf")

    engine = SieveLensEngine()
    install(engine)
    obs = engine.observe(inp / "six.pdf")
    hidden = [s for s in obs.segments if s.kind == "css_hidden"]
    assert [s.location for s in hidden] == SIX_KIND_LOCATIONS
    for (word, text), seg in zip(SIX_KIND_TEXTS.items(), hidden):
        assert seg.text == text
        assert word in seg.location
    assert obs.mask == "1001-000"
