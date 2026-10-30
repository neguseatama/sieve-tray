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

import pytest

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
