"""Crowd tab (integration step 4 of 8): the 7th tab wires the vendored
sieve-crowd engine into the GUI flow.

Contract (integration spec sections 2/3/4/8, user-approved):
  - a 7th tab "Crowd": file select -> inspect table + config template
    (role "?") -> dry-run (before/after alone) -> keygen -> output path
    (default <stem>_anonymized.<ext>) -> run -> result area with the
    receipt and the always-visible premise line
  - CrowdWorker runs dry_run/anonymize on a background thread
  - the identifier gate (sieve_crowd.hints, the _ID set via hint())
    asks before running when an identifier-like column stays in
    keep/sensitive
  - refused is a normal result (yellow), not an error (red); no output
    file is written; runs (both outcomes) land in crowd_runs history
Tests drive the pipeline synchronously (worker.run() called inline) so
no event-loop timing is involved.
"""

import json
import re
import stat
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

import sieve_tray_gui as gui
from sieve_tray import crowd_parse_config
from sieve_tray_i18n import tr
from sieve_tray_storage import Storage

CSV_3 = (
    b"name,age,city\n"
    b"Alice,34,Osaka\n"
    b"Bob,41,Tokyo\n"
    b"Carol,29,Kyoto\n"
)

CSV_5 = (
    b"name,age,city\n"
    b"Alice,30,Osaka\n"
    b"Bob,30,Osaka\n"
    b"Carol,40,Kyoto\n"
    b"Dave,40,Kyoto\n"
    b"Eve,25,Nara\n"
)

COLS_KEEP_NAME = {
    "name": {"role": "keep"},
    "age": {"role": "qi", "type": "numeric", "widths": [10]},
    "city": {"role": "qi", "type": "exact"},
}

COLS_DROP_NAME = {
    "name": {"role": "drop"},
    "age": {"role": "qi", "type": "numeric", "widths": [10]},
    "city": {"role": "qi", "type": "exact"},
}


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def window(qapp, tmp_path):
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    yield win
    win.close()


def _patch_question(monkeypatch, answer):
    calls = []

    class _Fake:
        @classmethod
        def question(cls, *args, **kwargs):
            calls.append(args)
            return answer

    monkeypatch.setattr(gui.QMessageBox, "question", _Fake.question)
    return calls


def _patch_critical(monkeypatch):
    calls = []

    class _Fake:
        @classmethod
        def critical(cls, *args, **kwargs):
            calls.append(args)
            return None

    monkeypatch.setattr(gui.QMessageBox, "critical", _Fake.critical)
    return calls


def test_crowd_tab_is_seventh_with_core_widgets(window):
    assert window.tabs.count() == 7
    assert window.tabs.tabText(window._crowd_tab_index) == tr("en", "crowd_tab")
    assert window.crowd_file_btn.isEnabled() is True
    assert window.crowd_inspect_btn.isEnabled() is False
    assert window.crowd_dry_run_btn.isEnabled() is False
    assert window.crowd_run_btn.isEnabled() is False
    assert window.crowd_config_edit.isReadOnly() is False
    assert window.crowd_receipt_view.isReadOnly() is True
    assert window.crowd_premise_label.text() == tr("en", "crowd_result_premise")
    assert window._crowd_worker is None and window._crowd_thread is None


def test_crowd_load_file_fills_inspect_table_and_config_template(
        window, tmp_path, monkeypatch):
    src = tmp_path / "people.csv"
    src.write_bytes(CSV_3)
    window.crowd_load_file(src)
    assert window._crowd_header == ["name", "age", "city"]
    assert len(window._crowd_rows) == 3
    assert window.crowd_inspect_table.rowCount() == 3
    assert window.crowd_input_label.text() == str(src)
    template = json.loads(window.crowd_config_edit.toPlainText())
    assert template["k"] == 5 and template["l"] == 1
    assert template["max_suppression"] == 0.05
    assert set(template["columns"]) == {"name", "age", "city"}
    assert all(spec["role"] == "?" for spec in template["columns"].values())
    assert template["columns"]["name"]["_hint"]
    assert window.crowd_output_edit.text() == str(tmp_path / "people_anonymized.csv")
    assert window.crowd_inspect_btn.isEnabled() is True
    assert window.crowd_dry_run_btn.isEnabled() is True
    assert window.crowd_run_btn.isEnabled() is True
    critical_calls = _patch_critical(monkeypatch)
    window.crowd_load_file(tmp_path / "unsupported.txt")
    assert len(critical_calls) == 1
    assert window._crowd_header == ["name", "age", "city"]


def test_crowd_config_error_blocks_then_dry_run_shows_before_after(
        window, tmp_path):
    src3 = tmp_path / "people3.csv"
    src3.write_bytes(CSV_3)
    window.crowd_load_file(src3)
    window.crowd_config_edit.setPlainText('{"k": 5, "columns": [')
    window.crowd_start_dry_run()
    label = window.crowd_config_error_label.text()
    assert label.startswith(tr("en", "crowd_config_json_error"))
    assert "not valid JSON" in label
    assert "line 1" in label
    assert window._crowd_worker is None
    assert window.crowd_dry_run_btn.isEnabled() is True
    src5 = tmp_path / "people5.csv"
    src5.write_bytes(CSV_5)
    window.crowd_load_file(src5)
    window.crowd_config_edit.setPlainText(json.dumps(
        {"k": 2, "l": 1, "max_suppression": 0.2, "columns": dict(COLS_DROP_NAME)}))
    cfg = crowd_parse_config(window.crowd_config_edit.toPlainText())
    worker = gui.CrowdWorker("dry_run", window._crowd_header,
                             window._crowd_rows, cfg, lang="en")
    captured = []
    worker.finished.connect(captured.append)
    worker.failed.connect(captured.append)
    worker.run()
    summary = captured[0]
    assert summary["ok"] is True
    window._on_crowd_dry_run_finished(summary)
    assert window.crowd_dry_run_label.text() == (
        f"{tr('en', 'crowd_dry_run_before')} {summary['before_alone']}"
        f" \u2192 {tr('en', 'crowd_dry_run_after')} {summary['after_alone']}")
    assert window.crowd_receipt_view.toPlainText() == summary["report_text"]
    assert "1" in window.crowd_dry_run_label.text()


def test_crowd_identifier_gate_blocks_keep_and_confirms(
        window, tmp_path, monkeypatch):
    src = tmp_path / "people.csv"
    src.write_bytes(CSV_3)
    window.crowd_load_file(src)
    window.crowd_config_edit.setPlainText(json.dumps(
        {"k": 2, "l": 1, "max_suppression": 0.2, "columns": dict(COLS_KEEP_NAME)}))
    cfg = crowd_parse_config(window.crowd_config_edit.toPlainText())
    assert window._crowd_identifier_conflicts(cfg) == ["name"]
    calls = _patch_question(monkeypatch, QMessageBox.No)
    assert window._crowd_identifier_gate(cfg) is False
    assert len(calls) == 1
    window.crowd_start_run()
    assert window._crowd_worker is None
    assert window.crowd_run_btn.isEnabled() is True
    _patch_question(monkeypatch, QMessageBox.Yes)
    assert window._crowd_identifier_gate(cfg) is True
    key = b"ab" * 16
    cfg_with_key = crowd_parse_config(window.crowd_config_edit.toPlainText(),
                                      key=key)
    assert cfg_with_key.key == key


def test_crowd_run_refused_and_anonymized_are_results_with_history(
        window, tmp_path):
    src3 = tmp_path / "people3.csv"
    src3.write_bytes(CSV_3)
    window.crowd_load_file(src3)
    cfg = crowd_parse_config(json.dumps(
        {"k": 5, "l": 1, "max_suppression": 0.0, "columns": dict(COLS_DROP_NAME)}))
    out3 = Path(window.crowd_output_edit.text())
    worker = gui.CrowdWorker("run", window._crowd_header, window._crowd_rows,
                             cfg, io=("csv", "csv"), output_path=out3,
                             lang="en")
    finished = []
    failures = []
    worker.finished.connect(finished.append)
    worker.failed.connect(failures.append)
    worker.run()
    assert failures == []
    summary = finished[0]
    assert summary["status"] == "refused" and summary["reason"] == "infeasible"
    assert not out3.exists()
    window._on_crowd_run_finished(summary)
    assert tr("en", "crowd_result_refused") in window.crowd_result_label.text()
    assert "infeasible" in window.crowd_result_label.text()
    assert "background" in window.crowd_result_label.styleSheet()
    assert window.crowd_receipt_view.toPlainText() == summary["report_text"]
    src5 = tmp_path / "people5.csv"
    src5.write_bytes(CSV_5)
    window.crowd_load_file(src5)
    cfg5 = crowd_parse_config(json.dumps(
        {"k": 2, "l": 1, "max_suppression": 0.2, "columns": dict(COLS_DROP_NAME)}))
    out5 = Path(window.crowd_output_edit.text())
    worker5 = gui.CrowdWorker("run", window._crowd_header, window._crowd_rows,
                              cfg5, io=("csv", "csv"), output_path=out5,
                              lang="en")
    finished5 = []
    worker5.finished.connect(finished5.append)
    worker5.failed.connect(failures.append)
    worker5.run()
    assert failures == []
    summary5 = finished5[0]
    assert summary5["status"] == "anonymized"
    assert out5.exists()
    window._on_crowd_run_finished(summary5)
    assert "anonymized" in window.crowd_result_label.text()
    assert tr("en", "crowd_result_k_achieved") in window.crowd_result_label.text()
    assert window.crowd_receipt_view.toPlainText() == summary5["report_text"]
    runs = window.storage.load_crowd_runs()
    assert len(runs) == 2
    assert runs[0]["status"] == "anonymized"
    assert runs[0]["output_path"] == str(out5)
    assert runs[1]["status"] == "refused"
    assert runs[1]["output_path"] is None
    assert runs[1]["input_path"] == str(src3)
    assert "refused" in runs[1]["report_text"]


def test_crowd_keygen_writes_mode_600_key_and_confirms_overwrite(
        window, tmp_path, monkeypatch):
    key_path = tmp_path / "key.txt"
    window.crowd_keygen_to(key_path)
    first = key_path.read_text(encoding="ascii")
    assert re.fullmatch(r"[0-9a-f]{64}\n", first)
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert window._crowd_key_path == key_path
    calls = _patch_question(monkeypatch, QMessageBox.No)
    window.crowd_keygen_to(key_path)
    assert len(calls) == 1
    assert key_path.read_text(encoding="ascii") == first
    _patch_question(monkeypatch, QMessageBox.Yes)
    window.crowd_keygen_to(key_path)
    second = key_path.read_text(encoding="ascii")
    assert re.fullmatch(r"[0-9a-f]{64}\n", second)
    assert second != first
