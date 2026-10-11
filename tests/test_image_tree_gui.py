"""GUI: _on_sanitize_finished with config_error / excluded summaries.

Pins the GUI contract for config-kind routing:
- config_error summary -> the error text is shown and NO history row
  is saved (nothing was measured)
- excluded files are listed in the done message; the run itself is
  still recorded
- a plain summary behaves exactly as before (regression pin)

gui.QMessageBox is replaced with a capturing stub: the real call opens
a modal dialog that cannot be dismissed headless. The stub keeps the
message as an argument, so its content is verified here too.
"""

import pytest
from PySide6.QtWidgets import QApplication

import sieve_tray_gui as gui
from sieve_tray_i18n import tr
from sieve_tray_storage import Storage


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


class _FakeDialog:
    captured = []

    @classmethod
    def information(cls, *args, **kwargs):
        cls.captured.append(args[2] if len(args) > 2 else None)

    @classmethod
    def warning(cls, *args, **kwargs):
        cls.captured.append(args[2] if len(args) > 2 else None)


def _stub_dialog(monkeypatch):
    _FakeDialog.captured = []
    monkeypatch.setattr(gui, "QMessageBox", _FakeDialog)
    return _FakeDialog.captured


def _prime_sanitize_attrs(win, tmp_path):
    win._sanitize_input_dir = tmp_path / "in"
    win._sanitize_config_path = tmp_path / "cfg.txt"
    win._sanitize_out_root = tmp_path / "out"


def test_config_error_shown_and_not_recorded(window, tmp_path, monkeypatch):
    captured = _stub_dialog(monkeypatch)
    _prime_sanitize_attrs(window, tmp_path)
    summary = {"n_files": 0, "ok_count": 0, "masked_total": 0,
               "integrity_bad_count": 0, "failed": [], "skipped": False,
               "excluded": [],
               "config_error": "cannot read config: boom"}
    window._on_sanitize_finished(summary)
    assert "cannot read config: boom" in window.summary_label.text()
    assert captured and "cannot read config: boom" in captured[0]
    assert window.storage.load_sanitizations() == []


def test_excluded_files_listed_and_recorded(window, tmp_path, monkeypatch):
    captured = _stub_dialog(monkeypatch)
    _prime_sanitize_attrs(window, tmp_path)
    summary = {"n_files": 1, "ok_count": 1, "masked_total": 1,
               "integrity_bad_count": 0, "failed": [], "skipped": False,
               "excluded": [("notes.txt", "not a PNG (region config)")],
               "config_error": None}
    window._on_sanitize_finished(summary)
    text = window.summary_label.text()
    assert "notes.txt" in text
    assert "not a PNG (region config)" in text
    rows = window.storage.load_sanitizations()
    assert len(rows) == 1


def test_plain_summary_still_recorded(window, tmp_path, monkeypatch):
    _stub_dialog(monkeypatch)
    _prime_sanitize_attrs(window, tmp_path)
    summary = {"n_files": 2, "ok_count": 2, "masked_total": 3,
               "integrity_bad_count": 0, "failed": [], "skipped": False,
               "excluded": [], "config_error": None}
    window._on_sanitize_finished(summary)
    rows = window.storage.load_sanitizations()
    assert len(rows) == 1
    assert rows[0]["n_files"] == 2
    assert rows[0]["masked_total"] == 3


def test_i18n_config_error_and_excluded_keys_format():
    assert "X" in tr("en", "sanitize_config_error", err="X")
    assert "X" in tr("ja", "sanitize_config_error", err="X")
    assert "Y" in tr("en", "sanitize_excluded_files", files="Y")
    assert "Y" in tr("ja", "sanitize_excluded_files", files="Y")
