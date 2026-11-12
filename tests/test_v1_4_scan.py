"""TR4-T01..T16 (v1.4.0): the table observation (scan), the three-stage
coloring of unobserved rows, the input-notes shape, the distribution
verification means and the dependency floors.

Non-GUI tests run everywhere.  The GUI wiring tests call
``pytest.importorskip("PySide6.QtWidgets")`` first: environments
without a usable Qt (headless Linux has no libEGL, CI without the gui
extra) skip them, and the Mac / CI acceptance runs exercise them.

Contracts (design doc §2/§3):
  - scan's HTML is Crowd 0.9.0's output byte for byte (TRay never
    post-processes it); it never enters the history; the temp file is
    user-only and swept at the next start or at exit.
  - the unobserved rows get a three-stage background (remedy /
    environment / excluded); the exact partition of the closed 8-reason
    vocabulary is pinned here; the 0-unobserved reports stay
    byte-identical to v1.3.0 (402be10).
"""

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import sieve_tray
from sieve_tray import (UNOBSERVED_REASONS, ScanResult, classify_observation,
                        crowd_refusal_message, render, render_text)
from sieve_tray_storage import CROWD_PAYLOAD_ALLOWLIST, Storage
from test_v1_3_engine_updates import (
    CROWD_REFUSAL_CODES, CLEAN_TREE, MOLD_CLEAN_CORE, MOLD_CLEAN_RENDER,
    MOLD_CLEAN_RENDER_TEXT, MOLD_WITH_UNOBSERVED_CORE,
    MOLD_WITH_UNOBSERVED_RENDER, MOLD_WITH_UNOBSERVED_RENDER_TEXT, TREE,
    _core_hash, _write_tree_text, _xlsx_bytes)
from sieve_tray_i18n import tr

REPO_ROOT = Path(__file__).resolve().parent.parent


def _require_qt():
    """Skip (not error) where a usable Qt is missing.

    pytest.importorskip re-raises ImportErrors that are not
    ModuleNotFoundError (pytest >= 8.2), and PySide6.QtWidgets raises
    exactly that here (libEGL).  The GUI acceptance runs on the Mac and
    on CI, where the import succeeds.
    """
    try:
        import PySide6.QtWidgets  # noqa: F401
    except ImportError:
        pytest.skip("PySide6.QtWidgets unusable in this environment")

# --- golden hashes measured on the v1.3.0 baseline (402be10) -------------
RENDER_V130_CLEAN_SHA = (
    "9136614b0a53dc6eaebfc0e3a08820df4512be9f7380630f557a50ed49713c1a")
RENDER_TEXT_V130_CLEAN_SHA = (
    "fec061b2bdbe713d8362a8e343cc397b5003c39f6249aa074dcc2cb20bcdebca")
# record-only: the HTML report with unobserved rows intentionally changes
# in v1.4.0 (the three-stage CSS); the Markdown one must not change.
RENDER_V130_UNOBSERVED_SHA = (
    "233f3dc0569a1d32410b67c00202696988fa4f368e7156aa5a661cf8e7b2a998")
RENDER_TEXT_V130_UNOBSERVED_SHA = (
    "cdc7329634535995ab04d8e8d3613e88c955568158aa7d474cc385a4a212c1e1")

CSV_BYTES = b"name,age,city\nAlice,34,Osaka\nBob,41,Tokyo\n"
CONFIG_JSON = {
    "k": 2,
    "columns": {
        "name": {"role": "id"},
        "age": {"role": "qi", "type": "exact"},
        "city": {"role": "keep"},
    },
}


def _doc(path="g/f.txt", mask="1000-000", flagged=False, **extra):
    d = {"path": path, "mask": mask, "flagged": flagged,
         "h_states": {}, "evidence": {}}
    d.update(extra)
    return d


def _result(doc_results=None, unobserved=None):
    return ScanResult(
        groups=[("group_a", [Path("group_a/keep.py")])],
        doc_results=doc_results if doc_results is not None else [],
        code_pairs=[], text_pairs=[], audit_results=[],
        unobserved=unobserved or [])


_CLEAN = _result(doc_results=[
    _doc(path="group_a/keep.py", mask="1000-000"),
    _doc(path="group_a/note.txt", mask="1000-000"),
])

# covers all three stages: refused + parse_failed (remedy),
# unsupported-format -> engine_unavailable (environment),
# not_applicable + empty_input (excluded).
_UNOBSERVED = _result(
    doc_results=[
        _doc(path="g/a.txt", mask="1000-000"),
        _doc(path="g/b.pdf", mask="0000-000",
             evidence={"H1": ["Extraction refused: encrypted"]}),
        _doc(path="g/c.xyz", mask="0000-000",
             evidence={"H1": ["Unsupported format: .xyz"]}),
        _doc(path="g/d.py", mask=""),
    ],
    unobserved=[
        {"file": "g/link.txt", "engine": "tray",
         "reason": "symlink_skipped", "detail": None},
        {"file": "g/big.bin", "engine": "tray",
         "reason": "too_large", "detail": None},
        {"file": "g/mystery.py", "engine": "scope",
         "reason": "not_applicable", "detail": None},
        {"file": "g/e.txt", "engine": "referee",
         "reason": "empty_input", "detail": None},
    ])


def _cli_scan_bytes(input_path: Path, *, lang: str,
                    config_path=None) -> bytes:
    """The vendored CLI's scan output on stdout (the byte reference)."""
    cmd = [sys.executable, "-m", "sieve_crowd", "scan", str(input_path),
           "--lang", lang, "-o", "-"]
    if config_path is not None:
        cmd += ["-c", str(config_path)]
    p = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True,
                       timeout=180)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    return p.stdout


# ---------------------------------------------------------------------------
# TR4-T01: scan's HTML is the Crowd CLI output, byte for byte
# ---------------------------------------------------------------------------

def test_t01_scan_html_matches_cli_byte_for_byte(tmp_path):
    csv = tmp_path / "t01.csv"
    csv.write_bytes(CSV_BYTES)
    cfg = tmp_path / "t01.json"
    cfg.write_text(json.dumps(CONFIG_JSON), encoding="utf-8")
    for lang in ("en", "ja"):
        for cp in (None, cfg):
            expected = _cli_scan_bytes(csv, lang=lang, config_path=cp)
            actual = sieve_tray.crowd_scan_bytes(csv, lang=lang,
                                                 config_path=cp)
            assert actual == expected, (lang, cp is not None)
            assert actual.startswith(b"<!DOCTYPE html>")


# ---------------------------------------------------------------------------
# TR4-T02: CSV (UTF-8 / CP932) and .xlsx inputs; refusals show the code
# wording - no values, no traceback
# ---------------------------------------------------------------------------

def test_t02_scan_inputs_csv_cp932_xlsx_and_refusal_wording(tmp_path):
    utf8_csv = tmp_path / "u.csv"
    utf8_csv.write_bytes(CSV_BYTES)
    out = sieve_tray.crowd_scan_bytes(utf8_csv, lang="en", config_path=None)
    assert out.startswith(b"<!DOCTYPE html>")

    cp_bytes = "名前,年齢\n佐藤,34\n".encode("cp932")
    with pytest.raises(UnicodeDecodeError):
        cp_bytes.decode("utf-8")          # the CP932 path is really taken
    cp_csv = tmp_path / "c.csv"
    cp_csv.write_bytes(cp_bytes)
    out = sieve_tray.crowd_scan_bytes(cp_csv, lang="ja", config_path=None)
    assert out.startswith(b"<!DOCTYPE html>")

    xlsx = tmp_path / "t.xlsx"
    xlsx.write_bytes(_xlsx_bytes(
        [("Sheet1", [["name", "age"], ["Alice", "34"]])],
        ["name", "age", "Alice", "34"]))
    out = sieve_tray.crowd_scan_bytes(xlsx, lang="en", config_path=None)
    assert out.startswith(b"<!DOCTYPE html>")

    # refusal: a UTF-16-BOM CSV is refused with the closed-vocabulary code
    bad = tmp_path / "b.csv"
    bad.write_bytes(b"\xff\xfeA\x00,\x00B\x00\n")
    from sieve_crowd.model import InputRefused
    with pytest.raises(InputRefused) as ei:
        sieve_tray.crowd_scan_bytes(bad, lang="en", config_path=None)
    assert ei.value.code == "unsupported_encoding"
    for lang in ("en", "ja"):
        msg = crowd_refusal_message(ei.value.code, lang)
        assert msg and msg != "unsupported_encoding"
        assert str(bad) not in msg and "Traceback" not in msg
        assert "A\x00" not in msg


# ---------------------------------------------------------------------------
# TR4-T03: no history entry; user-only temp file; sweep at start and at
# exit; save-as writes the same bytes
# ---------------------------------------------------------------------------

def test_t03_scan_never_reaches_history_and_temp_lifecycle(tmp_path):
    st = Storage(db_path=tmp_path / "history.db")
    csv = tmp_path / "t03.csv"
    csv.write_bytes(CSV_BYTES)
    data = sieve_tray.crowd_scan_bytes(csv, lang="en", config_path=None)
    assert st.load_crowd_runs() == []     # the scan never enters the history

    if os.name == "posix":
        p = sieve_tray.new_scan_temp_file(data, directory=tmp_path)
        assert p.parent == tmp_path
        assert p.name.startswith("sieve_tray_scan_")
        assert p.suffix == ".html"
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        assert p.read_bytes() == data
    else:
        p = sieve_tray.new_scan_temp_file(data, directory=tmp_path)
        assert p.read_bytes() == data

    # "save as" writes exactly the generated bytes
    target = tmp_path / "saved.html"
    sieve_tray.save_scan_html(target, data)
    assert target.read_bytes() == data

    # the next start sweeps only the prefixed leftovers
    leftover = tmp_path / "sieve_tray_scan_leftover.html"
    leftover.write_bytes(b"<html></html>")
    keeper = tmp_path / "unrelated.html"
    keeper.write_bytes(b"<html>keep</html>")
    removed = sieve_tray.sweep_scan_temp_files(directory=tmp_path)
    assert removed >= 1
    assert not leftover.exists() and keeper.exists()

    # the exit-time removal takes the tracked file away (a fresh file,
    # since the sweep above already cleared the earlier ones)
    p2 = sieve_tray.new_scan_temp_file(data, directory=tmp_path)
    assert p2.exists()
    sieve_tray.remove_scan_temp_file(p2)
    assert not p2.exists()


# ---------------------------------------------------------------------------
# TR4-T04: the browser is opened on the temp file path; no network
# ---------------------------------------------------------------------------

def test_t04_browser_open_receives_the_temp_path(tmp_path, monkeypatch):
    csv = tmp_path / "t04.csv"
    csv.write_bytes(CSV_BYTES)
    calls = []
    real_open = sieve_tray.open_in_browser
    monkeypatch.setattr(sieve_tray, "open_in_browser",
                        lambda p: calls.append(Path(p)))
    got = sieve_tray.crowd_scan_open(csv, lang="en", config_path=None,
                                     directory=tmp_path)
    assert len(calls) == 1 and calls[0] == got
    assert got.name.startswith("sieve_tray_scan_")
    assert got.read_bytes() == _cli_scan_bytes(csv, lang="en")

    # the production wrapper opens a local file: URI only (no network)
    opened = []
    monkeypatch.setattr(sieve_tray, "open_in_browser", real_open)
    monkeypatch.setattr(sieve_tray.webbrowser, "open",
                        lambda u, *a, **k: opened.append(u) or True)
    sieve_tray.open_in_browser(got)
    assert opened and str(opened[0]).startswith("file://")


# ---------------------------------------------------------------------------
# TR4-T05: the scan wording exists in en and ja, placeholders symmetric
# ---------------------------------------------------------------------------

def test_t05_scan_wording_exists_in_en_and_ja():
    import sieve_tray_i18n
    for key in ("crowd_scan_button", "crowd_scan_save_button",
                "input_notes_heading"):
        en = sieve_tray_i18n.tr("en", key)
        ja = sieve_tray_i18n.tr("ja", key)
        assert en and ja
        assert en != key and ja != key
        # the wording carries no placeholders on either side, so the
        # replacement positions trivially match (en/ja symmetric)
        assert "{" not in en and "}" not in en
        assert "{" not in ja and "}" not in ja


# ---------------------------------------------------------------------------
# TR4-T06: the three stages partition the closed 8-reason vocabulary
# ---------------------------------------------------------------------------

def test_t06_three_stages_partition_the_reason_vocabulary():
    stages = sieve_tray.UNOBSERVED_STAGES
    assert set(stages) == {"remedy", "environment", "excluded"}
    union = set()
    for members in stages.values():
        union |= set(members)
    assert union == set(UNOBSERVED_REASONS)
    assert len(UNOBSERVED_REASONS) == 8
    # exactly one stage per reason: pairwise disjoint
    names = sorted(stages)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            assert not (set(stages[names[i]]) & set(stages[names[j]]))
    # the design's mapping, pinned
    assert set(stages["remedy"]) == {
        "refused", "parse_failed", "unreadable", "too_large",
        "symlink_skipped"}
    assert set(stages["environment"]) == {"engine_unavailable"}
    assert set(stages["excluded"]) == {"not_applicable", "empty_input"}
    # no unknown reason anywhere in the table; the function agrees
    for reason in UNOBSERVED_REASONS:
        assert sieve_tray.unobserved_stage(reason) in names
    with pytest.raises(ValueError):
        sieve_tray.unobserved_stage("no_such_reason")


# ---------------------------------------------------------------------------
# TR4-T07: the GUI row background follows the stage; the reason text
# stays in the row (GUI: skipped where Qt is unusable)
# ---------------------------------------------------------------------------

def test_t07_gui_row_background_follows_the_stage(tmp_path, monkeypatch):
    _require_qt()
    import sieve_tray_gui as gui
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        result = _result(doc_results=[
            _doc(path="g/b.pdf", mask="0000-000",
                 evidence={"H1": ["Extraction refused: encrypted"]}),
            _doc(path="g/c.xyz", mask="0000-000",
                 evidence={"H1": ["Unsupported format: .xyz"]}),
        ])
        win._populate_result_tables(result)
        # measured on a real Qt (v1.4.0 fix1): the population re-enables
        # sorting, so the table re-sorts by the header's default indicator
        # (column 0, descending) - rows are located by path, never by
        # position
        rows = {}
        for row in range(win.doc_table.rowCount()):
            rows[win.doc_table.item(row, 0).text()] = row
        remedy_item = win.doc_table.item(rows["g/b.pdf"], 2)
        env_item = win.doc_table.item(rows["g/c.xyz"], 2)
        assert remedy_item.background().color().name() == "#fff4d6"
        assert env_item.background().color().name() == "#f0f0f0"
        # the reason text stays in the row - the color is never the only
        # carrier (design §3.2)
        assert "refused" in remedy_item.text()
        assert "engine_unavailable" in env_item.text() or \
            tr(win.lang, "reason_engine_unavailable") in env_item.text()
    finally:
        win.close()


# ---------------------------------------------------------------------------
# TR4-T08: HTML report - stage classes; CSS only when unobserved exist;
# the 0-unobserved report is byte-identical to v1.3.0
# ---------------------------------------------------------------------------

def test_t08_html_zero_case_is_byte_identical_and_stage_css_is_conditional():
    clean_html = render(_CLEAN)
    assert hashlib.sha256(clean_html.encode("utf-8")).hexdigest() == \
        RENDER_V130_CLEAN_SHA
    assert "Unobserved" not in clean_html
    assert "unobserved-" not in clean_html

    html_out = render(_UNOBSERVED)
    assert "class='unobserved unobserved-remedy'" in html_out
    assert "class='unobserved unobserved-environment'" in html_out
    assert "class='unobserved unobserved-excluded'" in html_out
    assert "tr.unobserved-remedy { background: #fff4d6; }" in html_out
    assert "tr.unobserved-environment { background: #f0f0f0; }" in html_out
    assert "tr.unobserved-excluded { background: #f8f8f8; }" in html_out
    # the aggregate line shows only when there is something to count
    assert "Unobserved: 7." in html_out


# ---------------------------------------------------------------------------
# TR4-T09: the Markdown report is byte-identical to v1.3.0 (no colors)
# ---------------------------------------------------------------------------

def test_t09_markdown_report_is_byte_identical_to_v1_3_0():
    assert hashlib.sha256(render_text(_CLEAN).encode("utf-8")).hexdigest() \
        == RENDER_TEXT_V130_CLEAN_SHA
    assert hashlib.sha256(render_text(_UNOBSERVED).encode("utf-8")
                          ).hexdigest() == RENDER_TEXT_V130_UNOBSERVED_SHA


# ---------------------------------------------------------------------------
# TR4-T10: the aggregate line shows only for 1+ unobserved items
# ---------------------------------------------------------------------------

def test_t10_aggregate_line_only_when_unobserved_exist():
    assert "Unobserved" not in render(_CLEAN)
    assert "Unobserved" not in render_text(_CLEAN)
    assert "Unobserved: 7." in render(_UNOBSERVED)
    assert ". Unobserved: 7" in render_text(_UNOBSERVED)


# ---------------------------------------------------------------------------
# TR4-T11: the input notes shape (GUI: skipped where Qt is unusable)
# ---------------------------------------------------------------------------

def test_t11_input_notes_shape_en_ja(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_i18n import tr as _tr
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        cp_csv = tmp_path / "cp.csv"
        cp_csv.write_bytes("名前,年齢\n佐藤,34\n".encode("cp932"))
        win.crowd_load_file(cp_csv)
        # measured on a real Qt (v1.4.0 fix1): QTabWidget hides the
        # non-current pages, so the visibility of the notes only means
        # something once the Crowd tab is the current one
        win._select_page("crowd")
        heading = win.crowd_notes_heading
        notes = win.crowd_notes_label
        assert heading.isVisibleTo(win) and notes.isVisibleTo(win)
        assert heading.text() == _tr(win.lang, "input_notes_heading")
        lines = notes.text().splitlines()
        assert lines and all(line.startswith("• ") for line in lines)
        assert any("cp932" in line for line in lines)
        # no color, no icon, no values: the label carries no stylesheet
        # and the cell value 佐藤 never appears
        assert notes.styleSheet() == ""
        assert heading.styleSheet() == ""
        assert "佐藤" not in notes.text() and str(cp_csv) not in notes.text()

        # UTF-8, single sheet -> nothing is shown
        utf8_csv = tmp_path / "u.csv"
        utf8_csv.write_bytes(CSV_BYTES)
        win.crowd_load_file(utf8_csv)
        assert not heading.isVisibleTo(win)
        assert not notes.isVisibleTo(win)
    finally:
        win.close()


# ---------------------------------------------------------------------------
# TR4-T12: release.yml - SHA256SUMS + provenance attestation, static check
# ---------------------------------------------------------------------------

def test_t12_release_workflow_hashes_and_attestation_static():
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8")
    # the existing three-asset build stays
    for asset in ("SieveTray-windows.zip", "SieveTray-macos-arm64.zip",
                  "SieveTray-macos-intel.zip"):
        assert asset in text
    assert "actions/checkout@" in text and "actions/upload-artifact@" in text
    # SHA-256 list: generated, uploaded and attached to the release
    assert "SHA256SUMS.txt" in text
    assert "sha256sum" in text
    # provenance attestation: the official action and the permissions
    # (measured 2026-11-06: actions/attest@v4 is the action the official
    # README recommends for new implementations - attest-build-provenance
    # v4 is its wrapper - and artifact-metadata: write is the permission
    # GA'd on 2026-01-13 for the artifact storage record)
    assert "actions/attest@" in text
    assert "id-token: write" in text
    assert "attestations: write" in text
    assert "artifact-metadata: write" in text
    # still tag-only
    assert "tags:" in text


# ---------------------------------------------------------------------------
# 2.1.1: the Test workflow rides the same three OS legs the release
# build proves (static check, the TR4-T12 shape)
# ---------------------------------------------------------------------------

def test_ci_workflow_three_os_matrix_static():
    text = (REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8")
    # the three release OS legs, with the ubuntu pin that dodged the
    # 26 image migration (run 43053398991: the apt step died with exit
    # code 100 before the suite ever started on the migrated image)
    assert "ubuntu-24.04" in text
    assert "windows-latest" in text
    assert "macos-15" in text
    # the matrix drives runs-on; one leg failing must not kill the rest
    assert "runs-on: ${{ matrix.os }}" in text
    assert "fail-fast: false" in text
    # the Qt library install is Linux-only (the PySide6 wheels need
    # nothing extra on Windows/macOS) and the vendored sieve_redact
    # check is cross-platform via the python shell (sha256sum /
    # python3 / curl are not portable across the three runners)
    assert "if: runner.os == 'Linux'" in text
    assert "shell: python" in text
    # the offscreen platform and the pytest invocation stay
    assert "QT_QPA_PLATFORM: offscreen" in text
    assert "python -m pytest -v" in text


# ---------------------------------------------------------------------------
# 2.1.1 (three-OS Test matrix, round 2): the vendored-hash verification is
# checkout-normalization-proof - the windows runner image ships
# core.autocrlf and its git may hand the hasher CRLF bytes while the pin
# certifies the canonical LF blob (run 43210414712: windows-latest died on
# the verify step, exit 1, in 54s, before the suite ever started)
# ---------------------------------------------------------------------------

def test_ci_workflow_vendor_verify_lf_canonical_static():
    text = (REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8")
    # the vendored bytes pass through the LF canonical form before hashing
    assert 'replace(b"\\r\\n", b"\\n")' in text
    # the normalization is justified where it happens, not buried
    assert "core.autocrlf" in text


# ---------------------------------------------------------------------------
# 2.1.1 (three-OS Test matrix, round 3): the repo pins its own checkout
# normalization - the pytest byte-pins hash the disk bytes and the windows
# runner image's git checks text files out with CRLF, so the pins cannot
# certify bytes the working tree does not hold (run #83: windows-latest
# died in "Run tests", exit 1, while ubuntu-24.04 / macos-15 hashing
# identical bytes passed)
# ---------------------------------------------------------------------------

def test_repo_gitattributes_pins_lf_checkout_static():
    attr = REPO_ROOT / ".gitattributes"
    assert attr.exists(), (
        ".gitattributes is missing - the working-tree line endings are "
        "then whatever each runner image's git config makes of the index, "
        "and the byte-pins cannot certify that")
    # the pin itself is checkout-normalization-proof, the run-43210414712
    # shape: assertions run on the canonical LF form
    text = attr.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    # every text file checks out in the canonical LF form on all three
    # runners; the binary assets stay byte-exact
    assert "* text=auto eol=lf" in text

# ---------------------------------------------------------------------------
# TR4-T13: README (en/ja) - the first-launch section; heading structure
# symmetric; no limitations section added
# ---------------------------------------------------------------------------

def test_t13_readme_first_launch_section_en_ja():
    en = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    ja = (REPO_ROOT / "README.ja.md").read_text(encoding="utf-8")
    assert any(line.startswith("## ") and "First launch" in line
               for line in en.splitlines())
    assert any(line.startswith("## ") and "初回起動" in line
               for line in ja.splitlines())
    en_heads = [line for line in en.splitlines()
                if line.startswith("## ")]
    ja_heads = [line for line in ja.splitlines()
                if line.startswith("## ")]
    assert len(en_heads) == len(ja_heads) > 0
    # the limitations enumeration is not increased (the v1.3.0 baseline
    # carries exactly one such section on each side)
    assert sum("Limitation" in h for h in en_heads) <= 1
    assert sum("制限" in h for h in ja_heads) <= 1
    # the SHA-256 verification hint is present in both
    assert "SHA256SUMS.txt" in en and "SHA256SUMS.txt" in ja
    assert "SHA-256" in en or "SHA256" in en
    assert "SHA-256" in ja or "SHA256" in ja


# ---------------------------------------------------------------------------
# TR4-T14: dependency floors are published versions only
# ---------------------------------------------------------------------------

def test_t14_dependency_floors_are_published_versions():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # v2.1.0 (M2, request §3.13): refreshed to the published engines.
    assert '"sieve-lens>=0.22.0"' in text
    assert '"sieve-scope>=1.5.0"' in text
    assert '"sieve-referee>=1.6.0"' in text


# ---------------------------------------------------------------------------
# TR4-T15: the golden mold (v1.3.0) holds: reasons, allowlist, reports
# ---------------------------------------------------------------------------

def _make_frozen_docx(path: Path):
    """A minimal .docx whose word/document.xml carries a DOCTYPE -
    Lens refuses it with the known code doctype_not_allowed (the same
    extra the TR3-T03 mold scan uses)."""
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.'
            'openxmlformats.org/package/2006/content-types"><Default '
            'Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><!DOCTYPE w:document [<!ENTITY x "y">]>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body><w:p/></w:body>'
            '</w:document>')


def test_t15_golden_mold_v130_unchanged():
    assert set(UNOBSERVED_REASONS) == {
        "refused", "parse_failed", "unreadable", "too_large",
        "symlink_skipped", "engine_unavailable", "not_applicable",
        "empty_input"}
    assert set(CROWD_PAYLOAD_ALLOWLIST) == {
        "input_path", "output_path", "records_in", "records_out",
        "suppressed", "k_achieved", "max_risk", "avg_risk", "status",
        "reason", "report_text"}
    assert len(CROWD_PAYLOAD_ALLOWLIST) == 11
    # the Lens/Scope pipeline mold: the same trees as TR3-T03, the v1.3.0
    # hashes (the TR3 constants are the v1.2.0 molds that v1.3.0 kept)
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _write_tree_text(root, TREE)
        _make_frozen_docx(root / "in/g2/frozen.docx")
        os.symlink("note.txt", root / "in/g1/link.txt")
        old = os.getcwd()
        os.chdir(root)
        try:
            result = sieve_tray.run_scan(Path("in"))
        finally:
            os.chdir(old)
        assert _core_hash(result) == MOLD_WITH_UNOBSERVED_CORE
        assert hashlib.sha256(
            render(result).encode("utf-8")).hexdigest() == \
            MOLD_WITH_UNOBSERVED_RENDER
        assert hashlib.sha256(
            render_text(result).encode("utf-8")).hexdigest() == \
            MOLD_WITH_UNOBSERVED_RENDER_TEXT
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _write_tree_text(root, CLEAN_TREE)
        old = os.getcwd()
        os.chdir(root)
        try:
            result = sieve_tray.run_scan(Path("in"))
        finally:
            os.chdir(old)
        assert _core_hash(result) == MOLD_CLEAN_CORE
        assert hashlib.sha256(
            render(result).encode("utf-8")).hexdigest() == MOLD_CLEAN_RENDER
        assert hashlib.sha256(
            render_text(result).encode("utf-8")).hexdigest() == \
            MOLD_CLEAN_RENDER_TEXT
    # the refusal wording table (14 codes) keeps its en/ja keys
    for code in CROWD_REFUSAL_CODES:
        for lang in ("en", "ja"):
            msg = crowd_refusal_message(code, lang)
            assert msg and msg != code, (code, lang)


# ---------------------------------------------------------------------------
# TR4-T16: version pin (refreshed at 2.1.0 - the M2 Cohort lane; the
# 2.0.0 section stays in the CHANGELOG)
# ---------------------------------------------------------------------------

def test_t16_version_pins():
    assert sieve_tray.__version__ == "2.1.0"
    # pyproject keeps the single-source wiring (dynamic version read
    # from sieve_tray.__version__)
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text
    assert 'version = { attr = "sieve_tray.__version__" }' in text
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [2.1.0]" in changelog


# ---------------------------------------------------------------------------
# GUI wiring: the scan button, the save button, the refusal display and
# the exit-time temp removal (skipped where Qt is unusable)
# ---------------------------------------------------------------------------

def test_gui_scan_open_flow_saves_and_cleans(tmp_path, monkeypatch):
    _require_qt()
    import sieve_tray_gui as gui
    from PySide6.QtWidgets import QFileDialog
    csv = tmp_path / "flow.csv"
    csv.write_bytes(CSV_BYTES)
    opened = []
    monkeypatch.setattr(sieve_tray, "open_in_browser",
                        lambda p: opened.append(Path(p)))
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        win.crowd_load_file(csv)
        assert win.crowd_scan_btn.text() == tr(win.lang, "crowd_scan_button")
        assert win.crowd_scan_save_btn.text() == tr(
            win.lang, "crowd_scan_save_button")
        win.crowd_scan()
        assert len(opened) == 1
        temp_path = win._scan_temp_path
        assert temp_path == opened[0]
        assert temp_path.read_bytes() == _cli_scan_bytes(csv, lang=win.lang)
        assert win.crowd_scan_save_btn.isEnabled()

        # a real save dialog can only return a path in an existing
        # folder, so the target sits directly in tmp_path (v1.4.0 fix1)
        target = tmp_path / "scan.html"
        monkeypatch.setattr(QFileDialog, "getSaveFileName",
                            staticmethod(
                                lambda *a, **k: (str(target), "")))
        win.crowd_scan_save()
        assert target.read_bytes() == temp_path.read_bytes()
    finally:
        win.close()


def test_gui_scan_refusal_shows_the_code_wording(tmp_path, monkeypatch):
    _require_qt()
    import sieve_tray_gui as gui
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: shown.append(a)))
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        bad = tmp_path / "b.csv"
        bad.write_bytes(b"\xff\xfeA\x00,\x00B\x00\n")
        win.crowd_scan_file(bad)      # must not raise
        assert shown, "the refusal must surface as a message box"
        title, text = str(shown[0][1]), str(shown[0][2])
        assert text == crowd_refusal_message("unsupported_encoding",
                                             win.lang)
        assert str(bad) not in text and "Traceback" not in text
    finally:
        win.close()


def test_gui_close_event_removes_the_scan_temp_file(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    p = sieve_tray.new_scan_temp_file(b"<html></html>")
    win._scan_temp_path = p
    win.close()
    assert not p.exists()
