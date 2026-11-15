"""SL-T15 (Seal 2.2, request §3.7): the GUI reorganization.

The three new sidebar pages (Manifest & Check Code / Rename / Draw)
join after the existing order, the scan operation row shows only on
the scan pages (the 2026-11-11 plan B ruling), the settings leave the
scan row and ride the menu (macOS relocates a PreferencesRole action
into the application menu; Windows/Linux keep it in the window menu -
the design ruling explicitly permits the window-menu host), every part
of the new pages carries a tooltip and the result field a placeholder,
and the new pages render uncut at the minimum size (880x560) under
ja/en and a dark palette, with last_page restoring them too.

Red stage: everything below fails on the missing attributes / i18n
keys until the §3.7 commit.  The GUI tests run only where a usable Qt
exists (the same _require_qt pattern as the other GUI modules).
"""

from pathlib import Path

import pytest

from test_v1_4_scan import _require_qt

REPO_ROOT = Path(__file__).resolve().parent.parent

# §3.7: the new pages join AFTER the existing order (no reordering).
EXISTING_KEYS = ("doc", "code", "text", "audit", "history",
                 "sanitize_history", "crowd", "gate", "cohort")
NEW_KEYS = ("manifest", "rename", "draw")
ALL_KEYS = EXISTING_KEYS + NEW_KEYS
# §3.7 plan B: the scan operation row lives on the scan pages only.
SCAN_PAGE_KEYS = ("doc", "code", "text", "audit")

# the §3.7 display names (the parentheses in the request text carry
# the English names; the product name stays out of the screen)
TAB_NAMES = {
    "en": ("Manifest & Check Code", "Rename", "Draw"),
    "ja": ("ファイル一覧と照合コード", "名前の整理", "抽選・班分け"),
}


def _make_window(tmp_path, lang=None):
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    return gui.MainWindow(storage=Storage(tmp_path / "history.db"),
                          lang=lang)


# ---------------------------------------------------------------------------
# the placement: the three pages join the sidebar after the existing
# order, with the i18n names, the full-text tooltips and no product
# name anywhere on the screen (§3.7 / addendum §3.2).

def test_sl_t15_three_new_pages_join_the_sidebar(tmp_path):
    _require_qt()
    from sieve_tray_i18n import tr
    win = _make_window(tmp_path)
    try:
        win.show()
        assert list(win._page_keys) == list(ALL_KEYS), win._page_keys
        for lang in ("en", "ja"):
            win2 = _make_window(tmp_path, lang=lang)
            try:
                for offset, key in enumerate(NEW_KEYS):
                    row = len(EXISTING_KEYS) + offset
                    item = win2.sidebar.item(row)
                    assert item.text() == tr(lang, key + "_tab"), \
                        (lang, key, item.text())
                    assert item.toolTip() == item.text()
                    # the product name stays in the README / About
                    assert "Seal" not in item.text()
            finally:
                win2.close()
        # selecting a new page switches the right-hand stack
        for key in NEW_KEYS:
            row = win._page_keys.index(key)
            win.sidebar.setCurrentRow(row)
            assert win.pages.currentIndex() == row, key
            assert win.pages.currentWidget() is win.pages.widget(row)
    finally:
        win.close()


# ---------------------------------------------------------------------------
# the scan operation row (plan B): visible on the four scan pages,
# hidden everywhere else; the settings button has left the row.

def test_sl_t15_scan_row_shows_only_on_scan_pages(tmp_path):
    _require_qt()
    win = _make_window(tmp_path)
    try:
        win.show()
        row = win.scan_row_widget
        # the scan controls still ride the scan row (the settings
        # button is the one that left)
        assert row is not None
        assert win.run_btn.parent() is row
        assert win.sanitize_btn.parent() is row
        assert win.sanitize_image_btn.parent() is row
        assert getattr(win, "settings_btn", None) is None, \
            "the settings button left the scan row"
        for key in SCAN_PAGE_KEYS:
            win._select_page(key)
            win.repaint()
            assert row.isVisible(), key
        for key in ("history", "sanitize_history", "crowd", "gate",
                    "cohort") + NEW_KEYS:
            win._select_page(key)
            win.repaint()
            assert not row.isVisible(), key
        # the initial page is a scan page: the row starts visible
        win._select_page("doc")
        win.repaint()
        assert row.isVisible()
    finally:
        win.close()


# ---------------------------------------------------------------------------
# the settings ride the menu: a PreferencesRole action (macOS moves it
# into the application menu; the window menu is the Windows/Linux host
# the design permits) and no settings button anywhere in the window.

def test_sl_t15_settings_rides_the_menu(tmp_path):
    _require_qt()
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QPushButton
    from sieve_tray_i18n import tr
    win = _make_window(tmp_path)
    try:
        win.show()
        wanted = tr("en", "settings_menu_action")
        found = [a for a in win.findChildren(QAction)
                 if a.text() == wanted
                 and a.menuRole() == QAction.MenuRole.PreferencesRole]
        assert found, "no PreferencesRole settings action in the menus"
        # the old button is gone: no push button carries the text
        buttons = [b for b in win.findChildren(QPushButton)
                   if b.text() == wanted]
        assert not buttons, buttons
    finally:
        win.close()


# ---------------------------------------------------------------------------
# the addendum §3.2/§3.3/§3.4 manners on the new pages: the written
# description, a tooltip on every part and the placeholder in the
# result field (the placeholder role keeps it readable in the dark
# palette too - the same rule as the Gate / Cohort pages).

def test_sl_t15_new_page_parts_carry_tooltips_and_placeholder(tmp_path):
    _require_qt()
    from PySide6.QtWidgets import (QCheckBox, QLineEdit, QPlainTextEdit,
                                   QPushButton, QSpinBox)
    win = _make_window(tmp_path)
    try:
        for key in NEW_KEYS:
            row = win._page_keys.index(key)
            page = win.pages.widget(row)
            assert page is not None, key
            # the description speaks the actual behavior
            desc = getattr(page, "desc_label", None)
            assert desc is not None and desc.text(), key
            # every interactive part carries a tooltip (Qt's internal
            # widgets - the spinbox's embedded line edit - are not
            # parts of the page and carry no tooltip)
            parts = (page.findChildren(QPushButton)
                     + page.findChildren(QLineEdit)
                     + page.findChildren(QCheckBox)
                     + page.findChildren(QSpinBox)
                     + page.findChildren(QPlainTextEdit))
            parts = [p for p in parts
                     if not p.objectName().startswith("qt_")]
            assert parts, key
            for part in parts:
                assert part.toolTip(), (key, part.objectName(),
                                        type(part).__name__)
            # the result field's placeholder rides the palette's own
            # placeholder role (dark-palette readability)
            summary = getattr(page, "summary_label", None)
            assert summary is not None and summary.text(), key
            from PySide6.QtGui import QPalette
            assert summary.foregroundRole() == \
                QPalette.ColorRole.PlaceholderText, key
    finally:
        win.close()


# ---------------------------------------------------------------------------
# the minimum size: the new pages render uncut at 880x560 under en and
# ja (the GU-T14 extension), and the same holds under a dark palette.

def test_sl_t15_new_pages_render_at_minimum_size(tmp_path):
    _require_qt()
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication
    for lang in ("en", "ja"):
        win = _make_window(tmp_path, lang=lang)
        try:
            win.resize(880, 560)
            win.show()
            for key in NEW_KEYS:
                # the render check must never fall back to another
                # page: the key has to exist before the selection
                assert key in win._page_keys, key
                win._select_page(key)
                win.repaint()
                QApplication.processEvents()
                page = win.pages.currentWidget()
                top = page.mapTo(win, QPoint(0, 0))
                assert top.x() >= 0, (lang, key, top)
                assert top.x() + page.width() <= win.width() + 1, \
                    (lang, key, top, page.width())
                assert page.width() >= 600, (lang, key, page.width())
                rendered = page.grab()
                assert not rendered.isNull(), (lang, key)
                assert rendered.width() >= 600, (lang, key)
        finally:
            win.close()


def test_sl_t15_new_pages_render_under_dark_palette(tmp_path):
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
            for key in NEW_KEYS:
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


# ---------------------------------------------------------------------------
# last_page rides the new pages too (§3.7): the save and the restore.

def test_sl_t15_last_page_restores_the_new_pages(tmp_path):
    _require_qt()
    from sieve_tray_storage import Storage
    db = str(tmp_path / "history.db")
    store = Storage(db)
    for key in ("draw", "manifest", "rename"):
        win = _make_window(tmp_path)
        try:
            win.show()
            win._select_page(key)
            win.close()
        except Exception:
            win.close()
            raise
        assert store.get_setting("last_page") == key
        win2 = _make_window(tmp_path)
        try:
            win2.show()
            assert win2._page_keys[win2.sidebar.currentRow()] == key
        finally:
            win2.close()
        store.set_setting("last_page", "no-such-page")
        win3 = _make_window(tmp_path)
        try:
            win3.show()
            assert win3.sidebar.currentRow() == 0
        finally:
            win3.close()


# ---------------------------------------------------------------------------
# the pages run the real engines (the descriptions speak the actual
# behavior): manifest writes the receipt, rename plans (and applies on
# request, leaving the source untouched), draw deals the roster and
# keeps the names out of the handoff folder.

def test_sl_t15_manifest_page_runs_the_engine(tmp_path):
    _require_qt()
    import json
    win = _make_window(tmp_path)
    try:
        win.show()
        page = win.manifest_page
        inp = tmp_path / "in"
        inp.mkdir()
        (inp / "a.txt").write_bytes(b"alpha\n")
        (inp / "b.txt").write_bytes(b"beta\n")
        out = tmp_path / "out"
        page.manifest_input_edit.setText(str(inp))
        page.manifest_output_edit.setText(str(out))
        page.run_manifest()
        receipt_path = out / "handoff" / "manifest-receipt.json"
        assert receipt_path.is_file()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["kind"] == "sieve-manifest"
        assert receipt["summary"]["items"] == 2
        # the summary placeholder gave way to the result
        assert page.summary_label.text() != \
            __import__("sieve_tray_i18n", fromlist=["tr"]).tr(
                "en", "manifest_summary_placeholder")
        assert page.manifest_log.toPlainText()
    finally:
        win.close()


def test_sl_t15_rename_page_plans_and_applies(tmp_path):
    _require_qt()
    import json
    win = _make_window(tmp_path)
    try:
        win.show()
        page = win.rename_page
        inp = tmp_path / "in"
        inp.mkdir()
        (inp / "report draft.txt").write_bytes(b"alpha\n")
        out = tmp_path / "out"
        page.rename_input_edit.setText(str(inp))
        page.rename_output_edit.setText(str(out))
        page.rename_pattern_edit.setText("{seq:3}_{stem}{ext}")
        # the default is the plan only: nothing changes on disk
        page.rename_apply_cb.setChecked(False)
        page.run_rename()
        assert not (out / "renamed").exists()
        plan_path = out / "local" / "rename-plan.json"
        assert plan_path.is_file()
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        assert plan["apply"] is False
        assert plan["mapping"][0]["to"] == "001_report draft.txt"
        assert (inp / "report draft.txt").read_bytes() == b"alpha\n"
        receipt = json.loads(
            (out / "handoff" / "rename-receipt.json")
            .read_text(encoding="utf-8"))
        assert receipt["kind"] == "sieve-rename"
        # with the apply checked, the renamed copy is built and the
        # source stays byte-identical
        out2 = tmp_path / "out2"
        page.rename_output_edit.setText(str(out2))
        page.rename_apply_cb.setChecked(True)
        page.run_rename()
        copy = out2 / "renamed" / "001_report draft.txt"
        assert copy.is_file()
        assert copy.read_bytes() == b"alpha\n"
        assert (inp / "report draft.txt").read_bytes() == b"alpha\n"
    finally:
        win.close()


def test_sl_t15_draw_page_runs_the_engine(tmp_path):
    _require_qt()
    import json
    win = _make_window(tmp_path)
    try:
        win.show()
        page = win.draw_page
        roster = tmp_path / "roster.txt"
        names = ["山田太郎", "鈴木花子", "佐藤次郎", "高橋四郎"]
        roster.write_text(
            "".join(n + "\n" for n in names), encoding="utf-8")
        out = tmp_path / "out"
        page.draw_roster_edit.setText(str(roster))
        page.draw_seed_edit.setText("2026-11-14 class draw")
        page.draw_groups_spin.setValue(2)
        page.draw_size_spin.setValue(0)
        page.draw_output_edit.setText(str(out))
        page.run_draw()
        receipt_path = out / "handoff" / "draw-receipt.json"
        assert receipt_path.is_file()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["kind"] == "sieve-draw"
        assert receipt["summary"]["items"] == 4
        assert receipt["summary"]["groups"] == 2
        # the names never ride in the handoff folder
        raw = receipt_path.read_text(encoding="utf-8")
        for name in names:
            assert name not in raw, name
        # the groups with the names land in the local folder
        result_path = out / "local" / "draw-result.json"
        assert result_path.is_file()
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert sum(len(g) for g in result["groups"]) == 4
        # the seed lands in the receipt (it is published by design)
        assert receipt["settings"]["seed"] == "2026-11-14 class draw"
    finally:
        win.close()
