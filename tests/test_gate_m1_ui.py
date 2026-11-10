"""Tray 2.0.0 Gate GUI wiring (request §3.6).

GUI tests run only where a usable Qt exists (Mac / CI); this sandbox
has no libEGL, so _require_qt() skips them (the same pattern as
test_v1_4_scan.py).  Red stage: the Gate tab and its strings arrive
with the fix commit, so the assertions fail on a machine with Qt until
then.  The sandbox measurement therefore never exercises this file.
"""

import pytest

from test_v1_4_scan import _require_qt


def _gate_tab(main_window):
    # v2.1.0 (addendum 2): the tab row became the sidebar + the page
    # stack; the Gate page is looked up by its key (the observation is
    # unchanged: the same controls on the same page)
    keys = main_window._page_keys
    if "gate" not in keys:
        return None
    return main_window.pages.widget(keys.index("gate"))


def test_gate_tab_present(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        assert _gate_tab(win) is not None, "no Gate tab in the main window"
    finally:
        win.close()


def test_gate_tab_controls(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        tab = _gate_tab(win)
        # §3.6: input folder, output folder, settings, run, summary,
        # report opener, handoff opener, verify button, self-check.
        for name in ("gate_input_edit", "gate_output_edit",
                     "gate_run_button", "gate_verify_button",
                     "gate_selfcheck_button", "gate_open_report_button",
                     "gate_open_handoff_button"):
            assert getattr(tab, name, None) is not None, name
    finally:
        win.close()


def test_gate_tab_i18n(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    from sieve_tray_i18n import tr
    for lang in ("en", "ja"):
        win = gui.MainWindow(storage=Storage(tmp_path / f"h-{lang}.db"),
                             lang=lang)
        try:
            tab = _gate_tab(win)
            row = win._page_keys.index("gate")
            assert tr(lang, "gate_tab") == win.sidebar.item(row).text()
        finally:
            win.close()


def test_gate_self_check_button(tmp_path, monkeypatch):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    from sieve_tray import gate_self_check
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        tab = _gate_tab(win)
        shown = []
        monkeypatch.setattr(tab, "show_selfcheck_result",
                            lambda res: shown.append(res))
        tab.run_self_check()
        assert shown and shown[0]["expected"] == shown[0]["matching"]
    finally:
        win.close()


def test_gate_selfcheck_without_pack_reports_error(tmp_path, monkeypatch):
    """Packaging guard: without the sample pack the button logs the
    unavailable message instead of raising KeyError."""
    _require_qt()
    import sieve_tray
    import sieve_tray_gui as gui
    from sieve_tray_i18n import tr
    from sieve_tray_storage import Storage
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        tab = _gate_tab(win)
        monkeypatch.setattr(sieve_tray, "gate_self_check",
                            lambda progress=None: {
                                "error": "sample_pack_not_available",
                                "detail": "/tmp/nowhere/samples/gate"})
        tab.run_self_check()
        assert tr("en", "gate_selfcheck_unavailable",
                  detail="/tmp/nowhere/samples/gate") in \
            tab.gate_log.toPlainText()
    finally:
        win.close()
