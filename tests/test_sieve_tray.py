"""
Basic regression tests for sieve_tray.py.
Run with: pytest
"""
from pathlib import Path

import pytest

from sieve_tray import run_scan, render, scan, split_files, CODE_EXTS, DOC_EXTS

FIXTURES = Path(__file__).parent / "fixtures"
TEXT_FIXTURES = Path(__file__).parent / "fixtures_text"


def test_scan_finds_two_groups():
    groups = scan(FIXTURES)
    names = [name for name, _ in groups]
    assert names == ["group_a", "group_b"]


def test_split_files_routes_by_extension():
    groups = dict(scan(FIXTURES))
    code, doc = split_files(groups["group_a"])
    assert [f.name for f in code] == ["calc.py"]
    assert [f.name for f in doc] == ["note.txt"]


def test_run_scan_end_to_end():
    progress_log = []
    result = run_scan(FIXTURES, progress=progress_log.append)

    assert len(result.groups) == 2
    assert len(result.doc_results) == 1
    assert result.doc_results[0]["path"].endswith("note.txt")

    # calc.py in group_a and group_b differ only by parameter names
    # (a, b) vs (x, y) -> this is exactly the "variable laundering"
    # case Sieve-Scope is designed to catch, so it must be reported
    # as a pair, not silently short-circuited away.
    assert len(result.code_pairs) == 1
    pair = result.code_pairs[0]
    assert {pair["a"].split("/")[0], pair["b"].split("/")[0]} == {"group_a", "group_b"}

    assert progress_log, "progress callback should receive status updates"


def test_render_produces_valid_css_no_double_percent():
    result = run_scan(FIXTURES)
    html_out = render(result)

    # Regression test for the "100%%" CSS bug found during Phase 0.
    assert "%%" not in html_out
    assert "width: 100%;" in html_out
    assert "<table>" in html_out


def test_run_scan_on_empty_directory(tmp_path):
    result = run_scan(tmp_path)
    assert result.groups == []
    assert result.doc_results == []
    assert result.code_pairs == []
    assert result.text_pairs == []
    # render() must not crash on an empty result
    html_out = render(result)
    assert "0 groups scanned" in html_out


def test_run_scan_detects_paraphrased_text_pair():
    # group_a/essay.txt and group_b/essay.txt say the same thing in
    # different words - Sieve-Referee should flag this as a paraphrase,
    # not as an independently-written pair (GREEN).
    result = run_scan(TEXT_FIXTURES)

    assert len(result.text_pairs) == 1
    pair = result.text_pairs[0]
    assert {pair["a"].split("/")[0], pair["b"].split("/")[0]} == {"group_a", "group_b"}
    assert pair["signal"] in {"RED", "YELLOW"}
    assert pair["pattern_name"]
    assert pair["reason"]
    assert set(pair["h_states"]) == {"H1", "H2", "H3", "H4"}
    assert 0.0 <= pair["scores"]["max_content_similarity"] <= 1.0


def test_render_includes_text_pairs_section():
    result = run_scan(TEXT_FIXTURES)
    html_out = render(result)
    assert "Text Pairs" in html_out
    assert "PARAPHRASE_DETECTED" in html_out or "RED" in html_out
