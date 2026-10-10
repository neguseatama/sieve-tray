"""Editor dialog sizing: previews must not blow up the dialog minimum.

Manual-checklist finding (v0.5 image UX): the preview QLabel was added
to the layout directly, so its minimum size equalled the full output
pixmap; for large images the dialog minimum exceeded the screen and the
button row (OK) was unreachable. The pinned contract is structural:
both the canvas and the preview live inside height-capped scroll areas,
so the dialog can shrink and the buttons stay on-screen.
"""

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QScrollArea

import sieve_tray_gui as gui

from pathlib import Path

NOT_IMPL = "sieve_tray_gui.%s is not implemented"


def _cls():
    return getattr(gui, "ImageRegionEditorDialog", None)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_preview_and_canvas_are_capped_scrolls(qapp, tmp_path):
    p = tmp_path / "big.png"
    Image.new("RGB", (800, 600), (10, 20, 30)).save(p)
    cls = _cls()
    assert cls is not None, NOT_IMPL % "ImageRegionEditorDialog"
    dlg = cls(str(p), "en")
    dlg.add_region(0, 0, 10, 10, "delete", None)
    dlg.run_preview()
    assert dlg.preview_label.pixmap() is not None
    assert dlg.preview_scroll.widget() is dlg.preview_label
    assert dlg.preview_scroll.maximumHeight() <= 240
    assert dlg.canvas_scroll.widget() is dlg.canvas
    assert dlg.canvas_scroll.maximumHeight() <= 480
    assert dlg.isSizeGripEnabled() is True
    assert dlg.minimumSizeHint().height() <= 768
