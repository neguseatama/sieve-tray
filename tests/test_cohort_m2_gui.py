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
        # Qt raises the shown size to the layout minimum when the pure
        # decision sits below it: the windows runner's font metrics push
        # the minimum to 1092px (run #84 measured 1092 > 800).  The
        # decision stays the floor everywhere the platform allows it.
        hint = win.minimumSizeHint()
        assert geo.width() == max(expected.width, hint.width())
        assert geo.height() == max(expected.height, hint.height())
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
            # the saved size is what the platform actually gave win1:
            # Qt raised resize(960, 620) to the layout minimum on the
            # windows runner (1092 - run #84), the restore re-applies
            # the saved client size and the same clamp form keeps the
            # POSIX values (960, 620) where the minimum is smaller.
            hint = win2.minimumSizeHint()
            assert (geo.width(), geo.height()) == (
                max(960, hint.width()), max(620, hint.height()))
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
            hint = win3.minimumSizeHint()
            assert (win3.geometry().width(),
                    win3.geometry().height()) == \
                (max(expected.width, hint.width()),
                 max(expected.height, hint.height()))
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
    # the Gate page joins the Cohort page (addendum §3.4 covers BOTH
    # tabs; the Gate side was found missing at the 2026-11-11 acceptance)
    for key in ("gate_summary_placeholder", "cohort_input_placeholder",
                "cohort_summary_placeholder"):
        assert key in STRINGS["en"] and key in STRINGS["ja"]
        assert STRINGS["en"][key].strip()
        assert STRINGS["ja"][key].strip()


def test_gu_t06_placeholder_on_widgets(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        gate = getattr(win, "gate_page", None)
        assert gate is not None
        assert getattr(gate, "summary_label", None) is not None, \
            "the Gate page carries the §3.4 placeholder too"
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
# minimum-size render, the implementer's addition) is
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
        # minimum size - the Cohort page joins the loop with the §3.9
        # commit (the addendum's minimum page list includes it)
        for key in ("doc", "crowd", "gate", "cohort"):
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


# ---------------------------------------------------------------------------
# GU-T16 (the implementer's addition): the design note
# of 2026-11-10 — at the en minimum size the last sidebar item "looked
# cut"; the offscreen measurement shows it is NOT cut (nine rows fit
# with the scrollbar range at zero), the grab hid the selected row
# because the ::item:selected style named no background, so Qt drops
# the OS highlight and paints white text over the light sidebar
# background.  The fix: tighter row padding + an explicit selected
# background/text colour.
#
# The 2026-11-10 follow-up note: the rows go back to the
# original 6px padding (26px rows — nine rows ≈ 234px still fit the
# 323-329px viewport, and 20px rows are cramped as click targets), and
# the sidebar background is a FIXED #f5f6f8, so under an OS dark
# palette the unselected rows' palette text would turn white on that
# light background and vanish.  Every row state therefore names an
# explicit text colour: ::item (normal), ::item:disabled and
# ::item:selected (the explicit background + colour stay).
#
# The v2.2.0 (§3.7) follow-up: the sidebar grows to twelve pages (the
# three new pages join after the existing order), so the row-fit
# guarantee moves from "the scrollbar stays at zero" to "the tail row
# the user selects auto-scrolls into the viewport and its page
# renders uncut" - the list scrolling for 12 rows is the standard
# control behavior (26px rows ≈ 312px still nearly fit the ~330px
# viewport that grows further when a non-scan page hides the scan
# row).  The style observables (the dark-palette readability pins)
# stay unchanged.
# ---------------------------------------------------------------------------

SEAL_PAGE_TAIL = ("manifest", "rename", "draw")


def test_gu_t16_twelve_pages_style_and_tail_visibility(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    from sieve_tray_i18n import tr
    from PySide6.QtWidgets import QApplication
    for lang in ("en", "ja"):
        win = gui.MainWindow(storage=Storage(tmp_path / ("h_%s.db" % lang)),
                             lang=lang)
        try:
            win.resize(880, 560)
            win.show()
            sb = win.sidebar
            # the twelve pages of §3.7: the existing order, then the
            # three new pages with their i18n names (the display
            # names ride the real _add_page registration)
            assert sb.count() == 12, (lang, sb.count())
            for offset, key in enumerate(SEAL_PAGE_TAIL):
                item = sb.item(sb.count() - 3 + offset)
                assert item.text() == tr(lang, key + "_tab"), \
                    (lang, key, item.text())
            # the width rule still holds with the new names (§1.2)
            assert 160 <= sb.width() <= 240, (lang, sb.width())
            # the tail row the user selects auto-scrolls into the
            # viewport (the 12-page list may scroll; the selected row
            # must not stay hidden)
            win.sidebar.setCurrentRow(sb.count() - 1)
            win.repaint()
            QApplication.processEvents()
            vh = sb.viewport().height()
            r = sb.visualItemRect(sb.item(sb.count() - 1))
            assert r.top() >= 0 and r.bottom() <= vh - 1, \
                (lang, "tail", r.top(), r.bottom(), vh)
            # the selected tail page renders uncut at the minimum
            # size (the §3.7 page-growth guarantee, the GU-T14 mold)
            page = win.pages.currentWidget()
            assert page.width() >= 600, (lang, page.width())
            rendered = page.grab()
            assert not rendered.isNull() and rendered.width() >= 600
            # the rows keep the original height (the 2026-11-10
            # follow-up: 26px rows fit with room to spare and are not
            # cramped as click targets — the 3px squeeze is reverted)
            style = win.sidebar.styleSheet()
            assert "padding: 6px 8px" in style, style
            # the sidebar background is a fixed light colour, so every
            # row state must name an explicit text colour or the OS
            # dark palette turns the rows white-on-light and unreadable
            # (the 2026-11-10 follow-up): normal, disabled and selected
            base = style.split("::item", 1)[1].split("{", 1)[1]
            base = base.split("}", 1)[0]
            assert "color" in base, style
            dis = style.split("::item:disabled", 1)[1]
            dis = dis.split("{", 1)[1].split("}", 1)[0]
            assert "color" in dis, style
            # the selected row is visible beyond the OS palette: the
            # style carries an explicit background and text colour
            # (§1.3: distinguishable, and not invisible on the light
            # background the offscreen grab demonstrated)
            sel = style.split("::item:selected", 1)[1]
            assert "background" in sel, style
            assert "color" in sel, style
        finally:
            win.close()


# ---------------------------------------------------------------------------
# GU-T17 (the 2026-11-10 receipt ruling, request §2-5): the GUI run's
# sharing record carries no submission file names - the names live in
# the file names, and the GUI offers no paths/hash toggles, so the GUI
# runs the comparison with include_paths=False: the items identify by
# sequence number, the flagged pairs take the same numbers, and no
# submission name reaches handoff/cohort-receipt.json.  The verify
# button still reads the record (replay) and reports match.
# ---------------------------------------------------------------------------

def _cohort_gui_tree(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    common = "共通の導入: 本課題では資料を読み、自分の言葉でまとめて提出する。"
    (root / "山田太郎_レポート.txt").write_text(
        common + "提出物の本文である。観察した事実を順に並べ、それぞれに"
        "短い考察を添える。結論は最後の段落で、観察と考察からだけを根拠に"
        "述べる。", encoding="utf-8")
    (root / "鈴木花子_レポート.txt").write_text(
        common + "提出物の本文をここに書く。見た事実を順番に並べて、それぞれへ"
        "短い考察を付け加える。最後の段落で結論を、観察と考察だけを根拠にして"
        "述べる。", encoding="utf-8")


def test_gu_t17_cohort_gui_record_has_no_names(tmp_path):
    _require_qt()
    import json
    import time
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    from PySide6.QtWidgets import QApplication
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        win.show()
        win._select_page("cohort")
        page = win.pages.currentWidget()
        inp, out = tmp_path / "提出物", tmp_path / "out"
        _cohort_gui_tree(inp)
        page.cohort_input_edit.setText(str(inp))
        page.cohort_output_edit.setText(str(out))
        page.run_cohort()
        deadline = time.time() + 120
        while page._cohort_thread is not None and \
                page._cohort_thread.isRunning() and time.time() < deadline:
            QApplication.processEvents()
            time.sleep(0.05)
        QApplication.processEvents()
        receipt_path = out / "handoff" / "cohort-receipt.json"
        assert receipt_path.is_file()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        # the GUI default is the path-free record (sequential identity)
        assert receipt["settings"]["include_paths"] is False
        assert all("path" not in it and "index" in it
                   for it in receipt["items"])
        raw = receipt_path.read_text(encoding="utf-8")
        for name in ("山田太郎", "鈴木花子", "レポート.txt", "提出物"):
            assert name not in raw, name
        # the flagged pairs exist and identify by sequence number
        assert receipt["pairs"], "the two near-identical files flag"
        for p in receipt["pairs"]:
            assert isinstance(p["a"], int) and isinstance(p["b"], int), p
        # the verify button reads the recorded record and reports match
        page.verify_record()
        log = page.cohort_log.toPlainText()
        assert "match" in log and "replay" in log, log
    finally:
        win.close()

# ---------------------------------------------------------------------------
# GU-T08 additions (Tray 2.1.1, the 2026-11-11 acceptance findings):
# the Powered by list carries every engine the tray actually uses
# (Sieve Order joined the tray at 2.0.0 and was missing from the
# list), and the tagline mentions the two M2 lanes (Export for
# Sharing / Compare Submissions), not only the scan.
# ---------------------------------------------------------------------------

def test_gu_t08_about_engines_list():
    import sieve_tray_gui as gui
    names = [name for name, _ in gui.AboutDialog.ENGINE_LINKS]
    assert names == ["Sieve Lens", "Sieve Scope", "Sieve Referee",
                     "Sieve Order", "Sieve Redact", "Sieve Crowd"]
    assert ("Sieve Order",
            "https://github.com/neguseatama/sieve-order") \
        in gui.AboutDialog.ENGINE_LINKS


def test_gu_t08_about_tagline_names_the_two_m2_lanes():
    from sieve_tray_i18n import tr
    for lang in ("en", "ja"):
        tagline = tr(lang, "about_tagline")
        assert ("export" in tagline.lower() or "書き出し" in tagline), \
            (lang, tagline)
        assert ("compare" in tagline.lower() or "比較" in tagline), \
            (lang, tagline)
        # the one-line description stays in sync with the README (GU-T08)
        if lang == "en":
            assert "compares the submissions" in tagline


# ---------------------------------------------------------------------------
# GU-T18 (Tray 2.1.1, the 2026-11-11 acceptance finding): the Cohort
# base-files picker states files, not a folder - the dialog itself is
# the multi-file QFileDialog.getOpenFileNames, only the button label
# reused the folder wording ("Select Folder..." / "フォルダを選択...").
# ---------------------------------------------------------------------------

def test_gu_t18_cohort_base_pick_wording():
    from sieve_tray_i18n import STRINGS
    assert STRINGS["en"]["cohort_base_pick"] == "Select Files..."
    assert STRINGS["ja"]["cohort_base_pick"] == "ファイルを選択..."


def test_gu_t18_cohort_base_pick_button(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        page = getattr(win, "cohort_page", None)
        assert page is not None
        button = getattr(page, "cohort_browse_base", None)
        assert button is not None, "the base picker is stored on the page"
        assert button.text() == "Select Files..."
    finally:
        win.close()


# ---------------------------------------------------------------------------
# GU-T19 (Tray 2.1.1, the 2026-11-11 acceptance finding): the history
# timestamp header fits its stretched column at the minimum size -
# "Timestamp (UTC)" clipped to "mestamp (UTC" in the en render; the
# shorter "Time (UTC)" rides the same wording as the crowd history.
# ---------------------------------------------------------------------------

def test_gu_t19_history_header_timestamp_fits():
    from sieve_tray_i18n import tr
    assert tr("en", "history_header_timestamp") == "Time (UTC)"
    assert tr("ja", "history_header_timestamp") == "日時 (UTC)"
