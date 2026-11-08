"""GUI tests must not accumulate widgets across the pytest session.

Found by the 2.0.0 acceptance run (r3, 2026-11-09): every GUI test
leaked its whole MainWindow tree (~250 widgets) because the fixtures
only win.close() and pytest keeps the fixture values alive for the
whole session; by test 147 the process held 5,500 widgets and 44
top-level windows, and the first heavy event-pumping test
(test_sanitize_thread_affinity) segfaulted on macOS inside
processEvents.  The session quiesce fixture in conftest.py now
reclaims each test's top-level widgets; this guard pins the mechanism
so the accumulation cannot silently return.
"""

import gc

import pytest

from test_v1_4_scan import _require_qt


def _quiesce(app):
    """Mirror of the session quiesce in conftest.py (kept local so this
    guard exercises the mechanism itself)."""
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    app.processEvents()
    for widget in QApplication.topLevelWidgets():
        widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()


def test_main_windows_are_reclaimed_between_tests(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from PySide6.QtWidgets import QApplication
    from sieve_tray_storage import Storage

    app = QApplication.instance()
    assert app is not None
    before = len(QApplication.allWidgets())
    # In the full acceptance session this must stay small: the quiesce
    # fixture reclaims every previous test's windows.  A regression
    # (+~250 widgets per GUI test) crosses this bound long before test
    # 147, where macOS used to segfault.
    assert before <= 30, (
        f"{before} widgets alive at test start - the session quiesce "
        "in conftest.py is not reclaiming (macOS segfaults past ~4000)")
    for i in range(3):
        win = gui.MainWindow(storage=Storage(tmp_path / f"h{i}.db"))
        win.close()
        del win
        _quiesce(app)
    after = len(QApplication.allWidgets())
    assert after <= before + 5, (before, after)
