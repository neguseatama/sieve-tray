"""Tray 2.6.0 - the engine lanes (CK-T07 / CK-T08 / CK-T10).

Lens 0.24.0 brings the structured kind fields (``how`` - the closed
nine-word vocabulary - and the 1-based ``page``) on hidden PDF
segments; the local kind record now reads those fields and never the
location label string.  The vendored Redact moves to the published
0.12.0 (same-value MODE), and the Gate grows an explicit same-value
choice (CLI flag + a GUI checkbox) that stays OFF by default so the
default settings remain the 2.5.1 bytes.

Red-first: the CK-T07/T08 tests enter before the implementation and
fail on the 2.5.1 tree (lens 0.24.0 installed; the measured structured
order of the six-kind probe is tr3, tr7, tiny_font, off_page,
off_layer, white_text on page 1).  CK-T10 is the green-at-birth guard:
the default settings fixture was captured from a real 2.5.1 run.
"""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import sieve_tray
from px_pdf_builders import build_six_kinds_pdf, need_pypdf

REPO_ROOT = Path(__file__).resolve().parent.parent

REDACT_0120_SHA256 = (
    "7c4bf9160c5333f9a2b42ce82520317b2d1860bd4d9f1b9d52be827427dd1621")

STRUCTURED_SIX = [
    {"page": "page 1", "word": "tr3"},
    {"page": "page 1", "word": "tr7"},
    {"page": "page 1", "word": "tiny_font"},
    {"page": "page 1", "word": "off_page"},
    {"page": "page 1", "word": "off_layer"},
    {"page": "page 1", "word": "white_text"},
]


def _run_gate(input_dir, output_dir, **kwargs):
    from sieve_tray import run_gate
    return run_gate(Path(input_dir), Path(output_dir), **kwargs)


# ---------------------------------------------------------------------------
# CK-T07: the structured kind fields

def test_ck_t07_kind_words_are_the_nine_word_closed_set():
    """CK-T07: the record's word list is the closed nine-word
    vocabulary of Lens 0.24.0's structured field, imported from the
    engine itself (the tray list follows the engine's list, never its
    own copy)."""
    from sieve_tray import GATE_KIND_WORDS
    from sieve_lens_ext.pdf import PDF_HIDDEN_HOWS
    assert GATE_KIND_WORDS == PDF_HIDDEN_HOWS
    assert len(GATE_KIND_WORDS) == 9
    for word in ("tr3", "tr7", "tiny_font", "off_page", "off_layer",
                 "white_text", "transparent", "clipped", "same_color"):
        assert word in GATE_KIND_WORDS


def test_ck_t07_entries_read_the_structured_fields():
    """CK-T07: the entries come from the structured fields - the page
    number becomes the ``page N`` form and the kind word rides the
    closed list; the three new words ride the same record."""
    from sieve_tray import _gate_hidden_kinds_entries
    for how, page in (("tiny_font", 3), ("transparent", 2),
                      ("clipped", 4), ("same_color", 7), ("tr3", 1)):
        seg = SimpleNamespace(text="x", visible=False, kind="body",
                              location="page %d (unused)" % page,
                              how=how, page=page)
        assert _gate_hidden_kinds_entries(seg) == [
            {"page": "page %d" % page, "word": how}]


def test_ck_t07_location_strings_are_never_read():
    """CK-T07: a segment without the structured page records nothing -
    even when its location label carries a page position and a known
    word; a bare location string (the old call shape) also records
    nothing."""
    from sieve_tray import _gate_hidden_kinds_entries
    seg = SimpleNamespace(text="x", visible=False, kind="body",
                          location="page 1 (invisible text, Tr 3)")
    assert _gate_hidden_kinds_entries(seg) == []
    assert _gate_hidden_kinds_entries(
        "page 1 (invisible text, Tr 3)") == []
    assert _gate_hidden_kinds_entries(None) == []


def test_ck_t07_word_outside_the_closed_list_records_position_only():
    """CK-T07: a structured word outside the closed list invents no
    new word - the position alone is recorded."""
    from sieve_tray import _gate_hidden_kinds_entries
    seg = SimpleNamespace(text="x", visible=False, kind="body",
                          location="page 9 (future_label)",
                          how="future_label", page=9)
    assert _gate_hidden_kinds_entries(seg) == [{"page": "page 9"}]


def test_ck_t07_gate_record_uses_the_structured_words(tmp_path):
    """CK-T07: a gate run over the six-kind PDF writes the local kind
    record with the structured words (the lowercase render-mode words
    included) and the page positions - the location labels never
    surface."""
    need_pypdf()
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    build_six_kinds_pdf(inp / "six.pdf")
    receipt = _run_gate(inp, out)
    record = json.loads(
        (out / "local" / "gate-hidden-kinds.json").read_text("utf-8"))
    assert record["record_version"] == 1
    assert record["kind"] == "sieve-gate-hidden-kinds"
    assert len(record["items"]) == 1
    assert record["items"][0]["item"] == 1
    assert record["items"][0]["entries"] == STRUCTURED_SIX
    for raw in (b"Tr 3", b"Tr 7", b"SIEVE-LAYER-Z9"):
        assert raw not in (out / "local" / "gate-hidden-kinds.json").read_bytes()
    _ = receipt


def test_ck_t07_handoff_receipt_keeps_its_shape(tmp_path):
    """CK-T07: the handoff receipt keeps its exact top-level keys, and
    the kind record rides outside it (local/ only) - no new key, no
    kind word anywhere in the receipt bytes."""
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    (inp / "plain.txt").write_text("hello\n", encoding="utf-8")
    receipt = _run_gate(inp, out)
    assert set(receipt.keys()) == {
        "receipt_version", "kind", "tool", "engines", "settings",
        "items", "summary", "digest"}
    receipt_bytes = json.dumps(receipt, sort_keys=True).encode("utf-8")
    assert b"gate-hidden-kinds" not in receipt_bytes
    assert b"hidden_kinds" not in receipt_bytes
    assert (out / "local" / "gate-hidden-kinds.json").exists() is False


# ---------------------------------------------------------------------------
# CK-T08: the vendored Redact 0.12.0 and the same-value choice

def test_ck_t08_vendored_redact_is_0_12_0():
    """CK-T08: the vendored engine is the published 0.12.0 - the
    version string and the whole-file sha256 both pin it."""
    import hashlib
    import sieve_redact
    assert sieve_redact.VERSION == "0.12.0"
    blob = (REPO_ROOT / "sieve_redact.py").read_bytes()
    assert hashlib.sha256(blob).hexdigest() == REDACT_0120_SHA256


def test_ck_t08_lens_floor_is_0_24_0():
    """CK-T08: the dependency floor names the published 0.24.0 (the
    0.23.0 floor is gone)."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text("utf-8")
    assert '"sieve-lens[pdf,html-css-full]>=0.24.0"' in pyproject
    assert '"sieve-lens[pdf,html-css-full]>=0.23.0"' not in pyproject


def test_ck_t08_same_value_mode_end_to_end(tmp_path):
    """CK-T08: --redact-same-value turns the same-value MODE on for one
    run: the receipt records mode "same-value" and the produced output
    gives the same value the same symbol while a different value gets
    a different one.  The default run keeps "label"."""
    inp, out_default, out_same = (tmp_path / "in", tmp_path / "out-d",
                                  tmp_path / "out-s")
    inp.mkdir()
    (inp / "mails.txt").write_text(
        "reach me at tarou@example.com any time\n"
        "again: tarou@example.com or hanako@example.com\n",
        encoding="utf-8")
    base = [sys.executable, str(REPO_ROOT / "sieve_tray.py"), "gate"]
    proc = subprocess.run(base + [str(inp), "-o", str(out_default)],
                          capture_output=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    proc = subprocess.run(
        base + [str(inp), "-o", str(out_same), "--redact-same-value"],
        capture_output=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    default_receipt = json.loads(
        (out_default / "handoff" / "gate-receipt.json").read_text("utf-8"))
    same_receipt = json.loads(
        (out_same / "handoff" / "gate-receipt.json").read_text("utf-8"))
    assert default_receipt["settings"]["redact"]["mode"] == "label"
    assert same_receipt["settings"]["redact"]["mode"] == "same-value"
    default_vis = (out_default / "handoff" / "mails.txt.visible.txt"
                   ).read_text("utf-8")
    same_vis = (out_same / "handoff" / "mails.txt.visible.txt"
                ).read_text("utf-8")
    assert default_vis != same_vis
    # the default run numbers every occurrence in order of appearance;
    # the same-value run gives the repeated address one symbol and the
    # third address its own
    import re

    def _syms(text):
        return re.findall(r"\[REDACTED\](\d+)", text)

    assert sorted(_syms(default_vis)) == ["1", "2", "3"]
    assert sorted(_syms(same_vis)) == ["1", "1", "2"]


def test_ck_t08_gate_checkbox_has_both_language_tooltips():
    """CK-T08: the Gate page carries the same-value checkbox (default
    unchecked) with a visible label and a tooltip in both languages."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QCheckBox
    import sieve_tray_gui
    assert QApplication.instance() is not None
    tooltips = {}
    for lang in ("ja", "en"):
        page = sieve_tray_gui.GatePage(lang)
        try:
            target = None
            for box in page.findChildren(QCheckBox):
                if box.objectName() == "gate_same_value":
                    target = box
                    break
            assert target is not None, "the same-value checkbox is missing"
            assert target.isChecked() is False
            assert target.text(), "the checkbox label is empty"
            tooltips[lang] = target.toolTip()
            assert tooltips[lang], "tooltip missing for %s" % lang
        finally:
            page.deleteLater()
    assert tooltips["ja"] != tooltips["en"]


# ---------------------------------------------------------------------------
# CK-T10: the default settings stay the 2.5.1 bytes

_FIXTURE = (REPO_ROOT / "tests" / "fixtures"
            / "gate_settings_2_5_1.json").read_text("utf-8").strip()


def _settings_canon(settings):
    return json.dumps(settings, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def test_ck_t10_default_settings_match_2_5_1(tmp_path):
    """CK-T10: a default gate run's settings are byte-identical (the
    canonical form) to the fixture captured from the 2.5.1 tree."""
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    (inp / "plain.txt").write_text("hello\n", encoding="utf-8")
    receipt = _run_gate(inp, out)
    assert _settings_canon(receipt["settings"]) == _FIXTURE


def test_ck_t10_same_value_changes_only_the_mode(tmp_path):
    """CK-T10: the same-value choice lands in settings.redact.mode
    alone - builtins, strip kinds, path/hash switches stay put."""
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    (inp / "plain.txt").write_text("hello\n", encoding="utf-8")
    receipt = _run_gate(inp, out, redact_mode="same-value")
    settings = json.loads(_FIXTURE)
    settings["redact"]["mode"] = "same-value"
    assert _settings_canon(receipt["settings"]) == _settings_canon(settings)
