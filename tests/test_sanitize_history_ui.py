"""Sanitize history tab (v0.6 subject 2): the saved sanitizations
surface in a dedicated tab of their own.

Contract (案A, decided):
  - a 5th tab labelled "Sanitize History ({n})" holding a 7-column
    table: Timestamp / Folder (keys reused from the scan history) +
    Config / Output / Files (ok) / Masked / Integrity fail (new)
  - rows mirror storage.load_sanitizations() (latest first); the row
    id is stashed on column 0's UserRole like the scan history does
  - the initial tab label shows count 0 and tracks the row count
  - _on_sanitize_finished refreshes the table immediately after
    save_sanitization (same if-block, directly after the save)
The current implementation never saves skipped rows, so no Skipped
column exists; if skipped rows start being saved, a column is added
(recorded in PLAN-v0.6).
"""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
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


EXPECTED_HEADERS = [
    tr("en", "history_header_timestamp"),
    tr("en", "history_header_folder"),
    tr("en", "sanitize_history_header_config"),
    tr("en", "sanitize_history_header_output"),
    tr("en", "sanitize_history_header_files"),
    tr("en", "sanitize_history_header_masked"),
    tr("en", "sanitize_history_header_integrity"),
]


class _FakeDialog:
    captured = []

    @classmethod
    def information(cls, *args, **kwargs):
        cls.captured.append(args[2] if len(args) > 2 else None)

    @classmethod
    def warning(cls, *args, **kwargs):
        cls.captured.append(args[2] if len(args) > 2 else None)


def test_sanitize_history_tab_structure(window):
    table = getattr(window, "sanitize_history_table", None)
    assert table is not None, \
        "MainWindow is missing the sanitize history table"
    assert table.columnCount() == 7
    headers = [table.horizontalHeaderItem(c).text() for c in range(7)]
    assert headers == EXPECTED_HEADERS
    assert window.tabs.count() == 5
    label = window.tabs.tabText(window._sanitize_history_tab_index)
    assert label == tr("en", "sanitize_history_tab", n=0), \
        "initial tab label must show count 0"


def test_sanitize_history_rows(window, tmp_path):
    rid1 = window.storage.save_sanitization(
        {"n_files": 3, "ok_count": 2, "masked_total": 5,
         "integrity_bad_count": 1, "skipped": False},
        Path("/a/in"), Path("/a/cfg.txt"), Path("/a/out"))
    rid2 = window.storage.save_sanitization(
        {"n_files": 1, "ok_count": 1, "masked_total": 2,
         "integrity_bad_count": 0, "skipped": False},
        Path("/b/in"), Path("/b/cfg.txt"), Path("/b/out"))
    window._refresh_sanitize_history_table()
    t = window.sanitize_history_table
    assert t.rowCount() == 2
    # latest first (load_sanitizations orders by id DESC)
    assert t.item(0, 0).data(Qt.UserRole) == rid2
    assert t.item(1, 0).data(Qt.UserRole) == rid1
    assert t.item(0, 0).text() != ""
    assert t.item(0, 1).text() == "/b/in"
    assert t.item(1, 1).text() == "/a/in"
    assert t.item(0, 2).text() == "/b/cfg.txt"
    assert t.item(0, 3).text() == "/b/out"
    assert t.item(0, 4).text() == "1 (1)"
    assert t.item(1, 4).text() == "3 (2)"
    assert t.item(0, 5).text() == "2"
    assert t.item(1, 5).text() == "5"
    assert t.item(0, 6).text() == "0"
    assert t.item(1, 6).text() == "1"


def test_sanitize_history_tab_label_tracks_row_count(window, tmp_path):
    label = window.tabs.tabText(window._sanitize_history_tab_index)
    assert label == tr("en", "sanitize_history_tab", n=0)
    window.storage.save_sanitization(
        {"n_files": 1, "ok_count": 1, "masked_total": 1,
         "integrity_bad_count": 0, "skipped": False},
        Path("/a/in"), Path("/a/cfg.txt"), Path("/a/out"))
    window.storage.save_sanitization(
        {"n_files": 2, "ok_count": 0, "masked_total": 0,
         "integrity_bad_count": 2, "skipped": False},
        Path("/a/in"), Path("/a/cfg.txt"), Path("/a/out"))
    window._refresh_sanitize_history_table()
    assert window.tabs.tabText(
        window._sanitize_history_tab_index) == tr(
        "en", "sanitize_history_tab", n=2)


def test_on_sanitize_finished_refreshes_immediately(
        window, tmp_path, monkeypatch):
    _FakeDialog.captured = []
    monkeypatch.setattr(gui, "QMessageBox", _FakeDialog)
    window._sanitize_input_dir = tmp_path / "in"
    window._sanitize_config_path = tmp_path / "cfg.txt"
    window._sanitize_out_root = tmp_path / "out"
    summary = {"n_files": 2, "ok_count": 2, "masked_total": 3,
               "integrity_bad_count": 0, "failed": [], "skipped": False,
               "excluded": [], "config_error": None}
    window._on_sanitize_finished(summary)
    t = window.sanitize_history_table
    assert t.rowCount() == 1, \
        "sanitize history must refresh immediately after the save"
    assert window.tabs.tabText(
        window._sanitize_history_tab_index) == tr(
        "en", "sanitize_history_tab", n=1)
