"""One QApplication for the whole pytest process.

Each GUI test module creates and destroys its own module-scoped
QApplication. Re-creating a QApplication after destroying the previous
one leaves the macOS cocoa event dispatcher in an inconsistent state,
and the first test that actually pumps the event loop
(test_sanitize_thread_affinity) segfaults in sendPostedEvents /
activateTimers. Holding a single session-scoped instance keeps every
module's `QApplication.instance()` returning the same app, so no second
QApplication is ever created and none is destroyed. Test modules stay
unchanged.
"""

import gc
import sys

import pytest

# Acceptance runs use `python -m pytest`, which puts the repo root on
# sys.path; importing sieve_crowd from the tree then writes __pycache__
# into the working copy. Stop test runs from leaving bytecode caches.
sys.dont_write_bytecode = True

try:
    from PySide6.QtWidgets import QApplication
except ImportError:          # non-GUI runs (e.g. CI without gui extra)
    QApplication = None


@pytest.fixture(scope="session", autouse=True)
def _single_qapplication():
    if QApplication is None:
        yield None
        return
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _reclaim_widgets_between_tests():
    """Reclaim every test's top-level widgets between tests.

    Found by the 2.0.0 acceptance run (r3, 2026-11-09): the GUI
    fixtures only win.close(), pytest keeps the fixture values alive
    for the whole session, and one MainWindow tree is ~250 widgets -
    so the session accumulated 5,500 widgets and 44 top-level windows
    by test 147, where the first heavy event-pumping test
    (test_sanitize_thread_affinity) segfaulted on macOS inside
    processEvents (the v0.6 crash class, back through a different
    door).  Deliver pending events while the current test's widgets
    are still alive, then delete every top-level widget, flush the
    deferred deletes and collect, so nothing accumulates across the
    session.
    """
    yield
    if QApplication is None:
        return
    app = QApplication.instance()
    if app is None:
        return
    from PySide6.QtCore import QEvent
    app.processEvents()
    for widget in QApplication.topLevelWidgets():
        widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()
