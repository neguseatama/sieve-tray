"""Canon 2.3.0 / stage 8 - the three new GUI pages (CN-T20, request
§3.7): the placement at the end of the existing order, the tooltips on
every interactive part, the placeholder result fields, the real engine
run, the minimum size (880x560) under en / ja / a dark palette, the
15-item sidebar with the last item reachable by selection, the
last_page restore, and no product name anywhere on the screen.
"""
import json

from pathlib import Path

import pytest

import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))

from test_v1_4_scan import _require_qt  # noqa: E402
from test_seal_s8_gui import _make_window  # noqa: E402

CANON_KEYS = ("clean", "normalize", "table_diff")


def test_three_pages_join_at_the_end(tmp_path):
    _require_qt()
    from sieve_tray_i18n import tr
    win = _make_window(tmp_path)
    try:
        assert len(win._page_keys) == 15, win._page_keys
        assert win._page_keys[-3:] == list(CANON_KEYS)
        for lang in ("en", "ja"):
            win2 = _make_window(tmp_path, lang=lang)
            try:
                for offset, key in enumerate(CANON_KEYS):
                    item = win2.sidebar.item(12 + offset)
                    assert item.text() == tr(lang, key + "_tab"), \
                        (lang, key, item.text())
                    assert item.toolTip() == item.text()
            finally:
                win2.close()
        # the product name stays out of the screen (§3.7-1)
        for key in CANON_KEYS:
            page = win.pages.widget(win._page_keys.index(key))
            texts = []
            for attr in ("desc_label", "summary_label"):
                w = getattr(page, attr, None)
                if w is not None:
                    texts.append(w.text())
            joined = " ".join(texts)
            assert "Canon" not in joined, key
    finally:
        win.close()


def test_new_page_parts_carry_tooltips_and_placeholder(tmp_path):
    _require_qt()
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QLineEdit,
                                   QPlainTextEdit, QPushButton)
    from PySide6.QtGui import QPalette
    win = _make_window(tmp_path)
    try:
        for key in CANON_KEYS:
            page = win.pages.widget(win._page_keys.index(key))
            assert getattr(page, "desc_label", None) is not None, key
            parts = (page.findChildren(QPushButton)
                     + page.findChildren(QLineEdit)
                     + page.findChildren(QCheckBox)
                     + page.findChildren(QComboBox)
                     + page.findChildren(QPlainTextEdit))
            parts = [p for p in parts
                     if not p.objectName().startswith("qt_")]
            assert parts, key
            for part in parts:
                assert part.toolTip(), (key, part.objectName(),
                                        type(part).__name__)
            summary = page.summary_label
            assert summary.text(), key
            assert summary.foregroundRole() == \
                QPalette.ColorRole.PlaceholderText, key
    finally:
        win.close()


def test_sidebar_15_items_last_reachable_by_selection(tmp_path):
    """§3.7-3: the sidebar grows to 15 items; the last item enters the
    viewport when selected (the QListWidget scrolls to the
    selection)."""
    _require_qt()
    from PySide6.QtWidgets import QApplication
    win = _make_window(tmp_path)
    try:
        win.resize(880, 560)
        win.show()
        QApplication.processEvents()
        sb = win.sidebar
        assert sb.count() == 15
        sb.setCurrentRow(14)          # the last page (Compare Tables)
        QApplication.processEvents()
        rect = sb.visualItemRect(sb.item(14))
        vh = sb.viewport().height()
        assert rect.isValid(), rect
        assert rect.top() >= -1, rect
        assert rect.bottom() <= vh, (rect, vh)
    finally:
        win.close()


def test_new_pages_render_at_minimum_size(tmp_path):
    _require_qt()
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication
    for lang in ("en", "ja"):
        win = _make_window(tmp_path, lang=lang)
        try:
            win.resize(880, 560)
            win.show()
            for key in CANON_KEYS:
                assert key in win._page_keys, key
                win._select_page(key)
                win.repaint()
                QApplication.processEvents()
                page = win.pages.currentWidget()
                top = page.mapTo(win, QPoint(0, 0))
                assert top.x() >= 0, (lang, key, top)
                assert top.x() + page.width() <= win.width() + 1, \
                    (lang, key, top, page.width())
                rendered = page.grab()
                assert not rendered.isNull(), (lang, key)
                assert rendered.width() >= 600, (lang, key)
        finally:
            win.close()


def test_new_pages_render_under_dark_palette(tmp_path):
    _require_qt()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    saved = app.palette()
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor(43, 43, 43))
    dark.setColor(QPalette.ColorRole.WindowText, QColor(221, 221, 221))
    dark.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    dark.setColor(QPalette.ColorRole.Text, QColor(221, 221, 221))
    dark.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    dark.setColor(QPalette.ColorRole.ButtonText, QColor(221, 221, 221))
    dark.setColor(QPalette.ColorRole.PlaceholderText,
                  QColor(138, 138, 138))
    try:
        app.setPalette(dark)
        win = _make_window(tmp_path)
        try:
            win.resize(880, 560)
            win.show()
            for key in CANON_KEYS:
                win._select_page(key)
                win.repaint()
                QApplication.processEvents()
                page = win.pages.currentWidget()
                rendered = page.grab()
                assert not rendered.isNull(), key
                assert rendered.width() >= 600, (key, rendered.width())
                assert page.mapTo(win, QPoint(0, 0)).x() >= 0, key
        finally:
            win.close()
    finally:
        app.setPalette(saved)
        app.processEvents()


def test_normalize_page_runs_the_real_engine(tmp_path):
    _require_qt()
    from PySide6.QtWidgets import QApplication
    src = tmp_path / "in"
    src.mkdir()
    (src / "note.txt").write_bytes(b"a\r\nb\r\n")
    out = tmp_path / "out"
    win = _make_window(tmp_path)
    try:
        win.show()
        QApplication.processEvents()
        page = win.normalize_page
        page.clean_input_edit if False else None
        page.normalize_input_edit.setText(str(src))
        page.normalize_output_edit.setText(str(out))
        page.run_normalize()
        QApplication.processEvents()
        receipt_path = out / "handoff" / "normalize-receipt.json"
        assert receipt_path.is_file()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["summary"]["produced"] == 1
        assert (out / "handoff" / "note.txt").read_bytes() == b"a\nb\n"
        # the result field left the placeholder role (it now speaks)
        from PySide6.QtGui import QPalette
        assert page.summary_label.foregroundRole() == \
            QPalette.ColorRole.Text
        assert "1" in page.summary_label.text()
    finally:
        win.close()


def test_last_page_restores_the_new_pages(tmp_path):
    _require_qt()
    from sieve_tray_storage import Storage
    storage = Storage(tmp_path / "history.db")
    storage.set_setting("last_page", "normalize")
    import sieve_tray_gui as gui
    win = gui.MainWindow(storage=storage)
    try:
        assert win.sidebar.currentRow() == \
            win._page_keys.index("normalize")
    finally:
        win.close()


# ---------------------------------------------------------------------------
# PX-T03 entry half (2.4.0 request §3.3): the clean page carries all
# four entry paths - the folder walk, the file selection, the drop and
# the CLI (the CLI/core half is pinned in tests/test_px_pdf_exchange.py;
# this file is the GUI half and runs on the Qt-capable environments).

def test_clean_page_file_select_and_drop_entries(tmp_path):
    _require_qt()
    from PySide6.QtCore import QUrl
    import sieve_tray_gui as gui

    win = _make_window(tmp_path)
    try:
        page = win.clean_page
        # the file-select entry exists and its filter derives from the
        # clean extensions (PDF joined in 2.4.0)
        assert page._clean_file_filter().startswith("Metadata files (")
        assert "*.pdf" in page._clean_file_filter()
        assert "*.png" in page._clean_file_filter()
        # the drop entry fills the input field and accepts local files
        dropped = tmp_path / "drop-me.pdf"
        dropped.write_bytes(b"%PDF-1.4\n")

        class _FakeMime:
            def urls(self):
                return [QUrl.fromLocalFile(str(dropped))]

        class _FakeEvent:
            def mimeData(self):
                return _FakeMime()

            def acceptProposedAction(self):
                pass

        fake = _FakeEvent()
        page.dropEvent(fake)
        assert page.clean_input_edit.text() == str(dropped)
    finally:
        win.close()
