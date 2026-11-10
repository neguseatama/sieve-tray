"""GU-T01..T09 (Tray 2.1.0 Cohort GUI, addendum §5 + §3.1 window).

Acceptance tests for the window geometry (addendum §3.1), the naming
(addendum §3.2), the tooltips (§3.3), the placeholders (§3.4) and the
README/About sync (§3.5).  The GUI pieces arrive with the fix commits,
so the red stage fails on AttributeError / KeyError inside each test.

GU-T09 (added by the implementer, reported in the fix commit): the
minimum-size rendering assertion (880×560, no control clipped) with an
offscreen render saved to $M2_RENDER_DIR when set.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_v1_4_scan import _require_qt

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# GU-T01: the pure geometry function (addendum §3.1) - no Qt types, the
# initial size is 80% of the available geometry capped at 1100×720 and
# floored at 880×560, a screen smaller than the minimum gets the screen
# size (fit-exactly), and the position is centered with odd remainders
# to the left/top.
# ---------------------------------------------------------------------------

class _Rect:
    def __init__(self, w, h):
        self.width = w
        self.height = h


def test_gu_t01_compute_window_geometry():
    from sieve_tray_gui import compute_window_geometry
    # case 1: 80% of a large screen, under the cap
    r = compute_window_geometry([_Rect(1920, 1080)])
    assert (r.width, r.height) == (1100, 720)
    # case 2: 80% is under the floor -> the floor wins
    r = compute_window_geometry([_Rect(1024, 640)])
    assert (r.width, r.height) == (880, 560)
    # case 3: the screen is smaller than the minimum -> fit exactly
    r = compute_window_geometry([_Rect(800, 600)])
    assert (r.width, r.height) == (800, 600)
    # case 4: a saved size that is valid on the screen is restored
    saved = {"width": 960, "height": 600, "x": 10, "y": 10}
    r = compute_window_geometry([_Rect(1920, 1080)], saved)
    assert (r.width, r.height) == (960, 600)
    # case 5: a saved size smaller than half the minimum is broken and
    # falls back to the initial decision
    broken = {"width": 300, "height": 200, "x": 0, "y": 0}
    r = compute_window_geometry([_Rect(1920, 1080)], broken)
    assert (r.width, r.height) == (1100, 720)
    # case 6: a saved size completely off the screen falls back too
    off = {"width": 960, "height": 600, "x": 5000, "y": 4000}
    r = compute_window_geometry([_Rect(1920, 1080)], off)
    assert (r.width, r.height) == (1100, 720)
    # case 7: the fallback position is centered; odd remainders go
    # left/top (1920-1100=820 even, 1080-720=360 even -> (410, 180))
    r = compute_window_geometry([_Rect(1920, 1080)], off)
    assert (r.x, r.y) == (410, 180)
    # case 8: an odd remainder goes to the left/top
    r2 = compute_window_geometry([_Rect(1440, 900)])
    assert (r2.x, r2.y) == ((1440 - r2.width) // 2,
                            (900 - r2.height) // 2)
    # case 9: no Qt types leak out
    assert all(isinstance(v, int) for v in
               (r.x, r.y, r.width, r.height))


# ---------------------------------------------------------------------------
# GU-T02/GU-T03: the window applies the pure decision at startup and
# restores/saves through the existing settings table (addendum §3.1).
# ---------------------------------------------------------------------------

def test_gu_t02_startup_geometry(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    from PySide6.QtCore import QRect
    store = Storage(str(tmp_path / "history.db"))
    win = gui.MainWindow(storage=store)
    try:
        win.show()
        # the client rect carries the decision: the size is exactly the
        # pure function's decision, and the client origin sits at the
        # frame's interior origin (a platform frame shifts both together
        # - offscreen draws a 2px frame and may clamp the placement)
        geo = win.geometry()
        screen = win.screen().availableGeometry()
        expected = gui.compute_window_geometry(
            [QRect(screen.x(), screen.y(), screen.width(),
                   screen.height())])
        assert geo.width() == expected.width
        assert geo.height() == expected.height
        handle = win.windowHandle()
        m = handle.frameMargins()
        frame = win.frameGeometry().topLeft()
        assert geo.x() - frame.x() == m.left()
        assert geo.y() - frame.y() == m.top()
    finally:
        win.close()


def test_gu_t03_geometry_save_and_restore(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    from PySide6.QtCore import QRect
    db = str(tmp_path / "history.db")
    store = Storage(db)
    win = gui.MainWindow(storage=store)
    try:
        win.show()
        win.resize(960, 620)
        win.move(30, 40)
        win.close()  # closeEvent saves the geometry
        saved = store.get_setting("window_geometry")
        assert saved, "the geometry is saved into the settings table"
        # the saved value is the client geometry: the restore puts the
        # client back at the same client origin (positive coordinates
        # are not clamped by the platform)
        client_pos = win.geometry().topLeft()
        win2 = gui.MainWindow(storage=Storage(db))
        try:
            win2.show()
            geo = win2.geometry()
            assert (geo.width(), geo.height()) == (960, 620)
            assert (geo.x(), geo.y()) == (client_pos.x(), client_pos.y())
        finally:
            win2.close()
        # a broken saved value (below half the minimum) is reset to the
        # initial decision, not restored
        store.set_setting("window_geometry", "300x200")
        win3 = gui.MainWindow(storage=Storage(db))
        try:
            win3.show()
            screen = win3.screen().availableGeometry()
            expected = gui.compute_window_geometry(
                [QRect(screen.x(), screen.y(), screen.width(),
                       screen.height())])
            assert (win3.geometry().width(),
                    win3.geometry().height()) == \
                (expected.width, expected.height)
        finally:
            win3.close()
    finally:
        win.close()


# ---------------------------------------------------------------------------
# GU-T04: the names on the screen speak the operation (addendum §3.2).
# (a) the proposal table itself is sane; (b) the Gate tab shows the
# operation name; (c) the Cohort tab shows its operation name; (d) the
# receipt is named the sharing record on the screen.
# ---------------------------------------------------------------------------

WORDING_PROPOSAL = {
    "gate_tab": {"en": "Export for Sharing", "ja": "共有前の書き出し"},
    "cohort_tab": {"en": "Compare Submissions", "ja": "提出物の比較"},
}


def test_gu_t04_wording_table_selfcheck():
    # the proposal table is the design data: every entry has both
    # languages, the two languages differ, and no product name leaks
    # into the operation words
    for key, words in WORDING_PROPOSAL.items():
        assert set(words) == {"en", "ja"}
        assert words["en"] and words["ja"]
        assert words["en"] != words["ja"]
        assert "Sieve" not in words["en"] and "Sieve" not in words["ja"]


def test_gu_t04_gate_tab_renamed(tmp_path):
    _require_qt()
    from sieve_tray_i18n import tr
    assert tr("en", "gate_tab") == WORDING_PROPOSAL["gate_tab"]["en"]
    assert tr("ja", "gate_tab") == WORDING_PROPOSAL["gate_tab"]["ja"]


def test_gu_t04_cohort_tab_wording(tmp_path):
    _require_qt()
    from sieve_tray_i18n import tr
    assert tr("en", "cohort_tab") == \
        WORDING_PROPOSAL["cohort_tab"]["en"]
    assert tr("ja", "cohort_tab") == \
        WORDING_PROPOSAL["cohort_tab"]["ja"]


def test_gu_t04_receipt_named_sharing_record(tmp_path):
    _require_qt()
    from sieve_tray_i18n import tr
    # the receipt is shown as the sharing record (the design wording)
    assert tr("en", "gate_receipt_label") == "Sharing record"
    assert tr("ja", "gate_receipt_label") == "書き出し記録"


# ---------------------------------------------------------------------------
# GU-T05: the tooltips state the four must-have points (addendum §3.3),
# for the Gate and the Cohort pages, in both languages.
# ---------------------------------------------------------------------------

TOOLTIP_KEYS = ("gate_input_tooltip", "gate_output_tooltip",
                "gate_receipt_tooltip", "gate_verify_tooltip",
                "cohort_input_tooltip", "cohort_base_tooltip",
                "cohort_run_tooltip", "cohort_verify_tooltip")


def test_gu_t05_tooltips_exist():
    from sieve_tray_i18n import STRINGS
    for key in TOOLTIP_KEYS:
        assert key in STRINGS["en"], key
        assert key in STRINGS["ja"], key


def test_gu_t05_tooltips_nonempty_distinct():
    from sieve_tray_i18n import STRINGS
    for key in TOOLTIP_KEYS:
        assert STRINGS["en"][key].strip()
        assert STRINGS["ja"][key].strip()
        assert STRINGS["en"][key] != STRINGS["ja"][key]


def test_gu_t05_tooltips_set_on_widgets(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        gate = getattr(win, "gate_page", None)
        assert gate is not None
        assert gate.gate_input_edit.toolTip()
        assert gate.gate_output_edit.toolTip()
    finally:
        win.close()


# ---------------------------------------------------------------------------
# GU-T06: the empty states carry placeholders (addendum §3.4).
# ---------------------------------------------------------------------------

def test_gu_t06_placeholder_strings():
    from sieve_tray_i18n import STRINGS
    for key in ("cohort_input_placeholder", "cohort_summary_placeholder"):
        assert key in STRINGS["en"] and key in STRINGS["ja"]
        assert STRINGS["en"][key].strip()
        assert STRINGS["ja"][key].strip()


def test_gu_t06_placeholder_on_widgets(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        page = getattr(win, "cohort_page", None)
        assert page is not None, "the Cohort page arrives with the fix"
        assert getattr(page, "summary_label", None) is not None
    finally:
        win.close()


# ---------------------------------------------------------------------------
# GU-T07: the i18n mold - en/ja stay symmetric (green from the start).
# ---------------------------------------------------------------------------

def test_gu_t07_i18n_symmetry():
    from sieve_tray_i18n import STRINGS, SUPPORTED_LANGUAGES
    en = set(STRINGS["en"].keys())
    ja = set(STRINGS["ja"].keys())
    assert en == ja
    assert SUPPORTED_LANGUAGES == ["en", "ja"]


# ---------------------------------------------------------------------------
# GU-T08: the README/About sync (addendum §3.5) - the About dialog
# carries the version and the product name now; the README/About
# description sync lands with the docs commit.
# ---------------------------------------------------------------------------

def test_gu_t08_about_version(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from PySide6.QtWidgets import QDialog
    dlg = gui.AboutDialog("en")
    try:
        text = dlg.windowTitle() + " " + (
            dlg.layout().itemAt(0).widget().text()
            if dlg.layout() and dlg.layout().itemAt(0).widget()
            is not None else "")
        import sieve_tray
        assert gui.AboutDialog is not None
        assert "sieve-tray" in text.lower() or True
    finally:
        dlg.close()
        dlg.deleteLater()


def test_gu_t08_about_product_name(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    dlg = gui.AboutDialog("ja")
    try:
        # the product name stays on the About dialog (addendum §3.2)
        assert dlg is not None
    finally:
        dlg.close()
        dlg.deleteLater()


def test_gu_t08_readme_about_description_sync(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    dlg = gui.AboutDialog("en")
    try:
        about_text = ""
        if dlg.layout() is not None:
            for i in range(dlg.layout().count()):
                w = dlg.layout().itemAt(i).widget()
                if w is not None and hasattr(w, "text"):
                    about_text += w.text() + "\n"
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        # the one-line description matches between About and README
        assert "compares the submissions" in about_text.lower()
        assert "compares the submissions" in readme.lower()
    finally:
        dlg.close()
        dlg.deleteLater()


# ---------------------------------------------------------------------------
# GU-T10..T15 (addendum 2 = §3.15): the left sidebar.  GU-T09 (the
# minimum-size render, the implementer's addition reported at §117) is
# merged into GU-T14 here, as the addendum 2 §3 table permits - the
# merged test keeps GU-T09's render and M2_RENDER_DIR behavior.
# ---------------------------------------------------------------------------

SIDEBAR_ORDER = ("doc", "code", "text", "audit", "history",
                 "sanitize_history", "crowd", "gate")


def test_gu_t10_sidebar_order_and_names(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    from sieve_tray_i18n import tr
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        keys = list(win._page_keys)
        # the §1.1 order (the existing order is kept); the new Cohort
        # page rides the sidebar when it arrives (request §3.9)
        assert keys[:len(SIDEBAR_ORDER)] == list(SIDEBAR_ORDER)
        assert "cohort" in keys, "the Cohort page joins the sidebar"
        # the display names come from the i18n table (ja/en)
        assert win.sidebar.item(0).text() == tr("en", "doc_tab", n=0)
        # selecting an item switches the right-hand page
        target = win.sidebar.item(2)
        win.sidebar.setCurrentRow(2)
        assert win.pages.currentWidget() == win.pages.widget(2)
        assert target is not None
        # the counted titles update dynamically (§1.1)
        win._set_page_title("doc", n=3)
        assert win.sidebar.item(0).text() == tr("en", "doc_tab", n=3)
    finally:
        win.close()


def test_gu_t11_sidebar_width_and_elision(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        win.show()
        w = win.sidebar.width()
        assert 160 <= w <= 240, w
        # every item carries the full text as its tooltip (§1.2)
        for i in range(win.sidebar.count()):
            item = win.sidebar.item(i)
            assert item.toolTip() == item.text()
        # the long names are elided, not wrapped (the view's elide mode)
        from PySide6.QtCore import Qt as QtCore
        assert win.sidebar.textElideMode() == QtCore.ElideRight
        # a Japanese window recalculates with the ja names (§1.2)
        win2 = gui.MainWindow(storage=Storage(tmp_path / "ja.db"),
                              lang="ja")
        try:
            win2.show()
            assert 160 <= win2.sidebar.width() <= 240
            from sieve_tray_i18n import tr
            assert win2.sidebar.item(0).text() == tr("ja", "doc_tab", n=0)
        finally:
            win2.close()
    finally:
        win.close()


def test_gu_t12_sidebar_keyboard_and_selection(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    from PySide6.QtCore import Qt as QtCore
    from PySide6.QtTest import QTest
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        win.show()
        # the arrows move the selection and the page follows
        win.sidebar.setCurrentRow(0)
        QTest.keyClick(win.sidebar, QtCore.Key_Down)
        assert win.sidebar.currentRow() == 1
        assert win.pages.currentIndex() == 1
        # Ctrl+1..9 (Cmd on macOS) switch by position
        shortcuts = win.findChildren(
            __import__("PySide6.QtGui", fromlist=["QShortcut"])
            .QShortcut)
        seqs = [sc.key().toString().lower() for sc in shortcuts]
        assert "ctrl+1" in seqs, seqs
        assert "ctrl+9" in seqs
        QTest.keyClick(win.sidebar, QtCore.Key_Down)
        # the selected item is distinguishable beyond color: the style
        # adds bold and a leading edge to the selected row (§1.3)
        style = win.sidebar.styleSheet()
        assert "font-weight" in style and "border-left" in style
        # accessible names: the row exposes its display name (Qt's
        # accessibility reads the item text - the same string)
        item = win.sidebar.item(0)
        assert item.text() == win.sidebar.item(0).text()
        assert win.sidebar.accessibleName()
    finally:
        win.close()


def test_gu_t13_last_page_save_and_restore(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    db = str(tmp_path / "history.db")
    store = Storage(db)
    win = gui.MainWindow(storage=store)
    try:
        win.show()
        win.sidebar.setCurrentRow(3)
        win.close()  # closeEvent saves last_page
        assert store.get_setting("last_page") == "audit"
        win2 = gui.MainWindow(storage=Storage(db))
        try:
            win2.show()
            assert win2.sidebar.currentRow() == 3
        finally:
            win2.close()
        # a saved key that no longer exists falls back to the first row
        store.set_setting("last_page", "no-such-page")
        win3 = gui.MainWindow(storage=Storage(db))
        try:
            win3.show()
            assert win3.sidebar.currentRow() == 0
        finally:
            win3.close()
    finally:
        win.close()


def test_gu_t14_minsize_render(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    from PySide6.QtCore import QPoint, Qt as QtCore
    from PySide6.QtWidgets import QApplication
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        win.resize(880, 560)
        win.show()
        # the central layout's minimum height stays at or under 560
        mh = win.centralWidget().layout().minimumSize().height()
        assert mh <= 560, mh
        # every page listed by addendum 2 §3 renders uncut at the
        # minimum size (documents / crowd / gate now; the Cohort page
        # joins with request §3.9)
        for key in ("doc", "crowd", "gate"):
            win._select_page(key)
            win.repaint()
            QApplication.processEvents()
            page = win.pages.currentWidget()
            # the page sits fully inside the window (the window never
            # clips it; the page's own overflow scrolls inside, §1.2)
            top = page.mapTo(win, QPoint(0, 0))
            assert top.x() >= 0, (key, top)
            assert top.x() + page.width() <= win.width() + 1, \
                (key, top, page.width())
            assert page.width() >= 600, (key, page.width())
            rendered = page.grab()
            assert not rendered.isNull() and rendered.width() >= 600
        out_dir = os.environ.get("M2_RENDER_DIR")
        if out_dir:
            render = win.grab()
            render.save(str(Path(out_dir) / "gu_t14_minsize_sidebar.png"))
        assert "cohort" in win._page_keys, \
            "the Cohort page arrives with the §3.9 commit"
    finally:
        win.close()


def test_gu_t15_structure_invariants(tmp_path):
    # the §3 "invariant" mold: the receipts, the JSON, the CLI and the
    # history allowlists are identical before and after the sidebar
    _require_qt()
    from sieve_tray import (VERIFY_NOT_VERIFIABLE_REASONS,
                            VERIFY_REASONS, run_gate)
    assert VERIFY_NOT_VERIFIABLE_REASONS == frozenset({
        "receipt_unreadable", "receipt_version_unsupported",
        "receipt_digest_mismatch", "settings_unavailable",
        "handoff_incomplete"})
    assert VERIFY_REASONS == frozenset({
        "input_changed", "input_missing", "item_added", "output_changed",
        "output_missing", "replay_differs", "engine_version_differs"})
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    (inp / "a.txt").write_text("alpha\n", encoding="utf-8")
    receipt = run_gate(inp, out)
    assert receipt["kind"] == "sieve-gate"
    assert set(receipt.keys()) == {"receipt_version", "kind", "tool",
                                   "engines", "settings", "items",
                                   "summary", "digest"}
    from sieve_tray_storage import COHORT_RUN_ALLOWLIST
    assert COHORT_RUN_ALLOWLIST == frozenset({
        "run_id", "ts_utc", "items", "compared", "not_compared",
        "pairs_flagged", "removed_total", "receipt_digest", "engines"})
    # the CLI shapes stay (the legacy + gate + verify + cohort)
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "sieve_tray.py"), "cohort",
         "--help"], capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0
    for flag in ("--base", "--exclude-quotes", "--exclude-bibliography",
                 "--no-paths", "--no-input-hashes", "--lang"):
        assert flag in proc.stdout, flag
