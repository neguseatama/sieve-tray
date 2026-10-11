"""Worker completion handlers must run on the main thread.

Root cause of the v0.6.0 bundle crash (found by the manual release
smoke): SanitizeWorker.finished was connected to a bare lambda, so the
completion slot ran on the worker thread and QMessageBox.information
created a native NSAlert there - macOS aborts with
NSInternalInconsistencyException ("NSWindow should only be
instantiated on the main thread!"), SIGABRT.

A connection probe in this venv (PySide6 6.11.2) measured:
  lambda                          -> worker thread (the v0.6.0 crash)
  real bound method               -> main thread
  @Slot-decorated method          -> main thread
  signal-to-signal relay          -> main thread
  explicit QueuedConnection to a
  Python callable                 -> never delivered
Monkeypatching the handler before connect makes the measurement
unreliable (the connection then captures the patched closure, which
PySide6 delivers in the emitting thread), so the behavioral pin below
drives the REAL wiring and measures the PRODUCTION handler by
recording the thread inside the QMessageBox stub.
"""

import threading
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import sieve_tray_gui as gui
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


def test_finished_connections_are_bound_methods_not_lambdas():
    text = (Path(__file__).resolve().parent.parent
            / "sieve_tray_gui.py").read_text(encoding="utf-8")
    # A bare lambda has no receiver object, so PySide6 delivers the
    # signal in the emitting (worker) thread; native dialogs created
    # there abort the process on macOS.
    assert "lambda summary: self._on_sanitize_finished" not in text
    assert "lambda result: self._on_finished" not in text
    assert text.count(
        "self._sanitize_worker.finished.connect("
        "self._on_sanitize_finished)") == 1
    assert text.count(
        "self._worker.finished.connect(self._on_scan_finished)") == 1
    # the thread-quit connections stay bound to the QThread objects
    assert text.count(
        "self._sanitize_worker.finished.connect("
        "self._sanitize_thread.quit)") == 1
    assert text.count(
        "self._worker.finished.connect(self._thread.quit)") == 1


def test_sanitize_summary_dialog_is_created_on_main_thread(
        window, tmp_path, monkeypatch):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "a.txt").write_text("hello secret\n", encoding="utf-8")
    cfg = tmp_path / "rules.txt"
    cfg.write_text("rule secret:mosaic\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    window.storage.set_setting("export_dir", str(out_dir))
    window.path_edit.setText(str(input_dir))
    monkeypatch.setattr(
        gui.QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (str(cfg), "")))

    main_tid = threading.get_ident()
    seen = []

    class _DialogSpy:
        @classmethod
        def information(cls, *args, **kwargs):
            seen.append((threading.get_ident() == main_tid,
                         args[2] if len(args) > 2 else None))

        @classmethod
        def warning(cls, *args, **kwargs):
            seen.append((threading.get_ident() == main_tid,
                         args[2] if len(args) > 2 else None))

    monkeypatch.setattr(gui, "QMessageBox", _DialogSpy)

    window.sanitize_folder()

    deadline = time.time() + 15
    while not seen and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)

    assert seen, "summary dialog never shown"
    assert seen[0][0] is True, (
        "summary dialog was created on a non-main thread: the completion "
        "handler ran in the worker thread (creating a native NSWindow "
        "there aborts the process on macOS)")
    assert "Sanitized 1 of 1" in (seen[0][1] or "")
    rows = window.storage.load_sanitizations()
    assert len(rows) == 1

    deadline = time.time() + 5
    while window._sanitize_thread.isRunning() and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)
