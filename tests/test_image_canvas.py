"""Image canvas: drag rectangle selection on a QLabel pixmap view.

tray v0.5 image UX (single-PNG scope). ImageCanvas is a QLabel subclass
that shows the source PNG 1:1 (scrolling is handled by the parent view),
draws confirmed regions as translucent overlays, and emits region_selected
with integer pixel coordinates (canvas position == pixel position, no
zoom: the 1:1 display is the deliberate design that removes coordinate
mapping from the risk surface).

Overlay pixel pin measured on this machine (offscreen, PySide6 6.11.2):
white base + QColor(255, 0, 0, 128) rectangle at (2, 2, 5, 5) renders
inside (4, 4) as (255, 127, 127, 255) and outside (12, 12) as white.
"""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import sieve_tray_gui as gui

NOT_IMPL = "sieve_tray_gui.%s is not implemented"


def _fn(name):
    return getattr(gui_mod(name), name, None) if False else getattr(gui, name, None)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# --- pure geometry helpers --------------------------------------------------


def test_normalize_rect_direction_agnostic():
    fn = _fn("normalize_rect")
    assert fn is not None, NOT_IMPL % "normalize_rect"
    assert fn(4, 5, 12, 11) == {"x": 4, "y": 5, "w": 8, "h": 6}
    assert fn(12, 11, 4, 5) == {"x": 4, "y": 5, "w": 8, "h": 6}


def test_clamp_point():
    fn = _fn("clamp_point")
    assert fn is not None, NOT_IMPL % "clamp_point"
    assert fn(-5, -1, 32, 16) == (0, 0)
    assert fn(40, 20, 32, 16) == (31, 15)
    assert fn(4, 5, 32, 16) == (4, 5)


# --- ImageCanvas ------------------------------------------------------------


def _white_pixmap(w, h):
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.white)
    return pm


def test_canvas_overlay_pixels(qapp):
    cls = _fn("ImageCanvas")
    assert cls is not None, NOT_IMPL % "ImageCanvas"
    canvas = cls()
    canvas.set_image(_white_pixmap(16, 16))
    canvas.set_regions([{"x": 2, "y": 2, "w": 5, "h": 5}])
    canvas.resize(16, 16)
    img = canvas.grab().toImage()
    assert img.pixelColor(4, 4).getRgb() == (255, 127, 127, 255)
    assert img.pixelColor(12, 12).getRgb() == (255, 255, 255, 255)


def test_canvas_drag_emits_region(qapp):
    cls = _fn("ImageCanvas")
    assert cls is not None, NOT_IMPL % "ImageCanvas"
    canvas = cls()
    canvas.set_image(_white_pixmap(32, 16))
    got = []
    canvas.region_selected.connect(
        lambda x, y, w, h: got.append((x, y, w, h)))
    canvas.show()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, QPoint(4, 5))
    QTest.mouseMove(canvas, QPoint(10, 7))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, QPoint(12, 11))
    assert got == [(4, 5, 8, 6)]


def test_canvas_drag_clamped_to_image(qapp):
    cls = _fn("ImageCanvas")
    assert cls is not None, NOT_IMPL % "ImageCanvas"
    canvas = cls()
    canvas.set_image(_white_pixmap(32, 16))
    got = []
    canvas.region_selected.connect(
        lambda x, y, w, h: got.append((x, y, w, h)))
    canvas.show()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, QPoint(40, 20))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, QPoint(30, 3))
    assert got == [(30, 3, 1, 12)]


def test_canvas_zero_area_drag_ignored(qapp):
    cls = _fn("ImageCanvas")
    assert cls is not None, NOT_IMPL % "ImageCanvas"
    canvas = cls()
    canvas.set_image(_white_pixmap(32, 16))
    got = []
    canvas.region_selected.connect(
        lambda x, y, w, h: got.append((x, y, w, h)))
    canvas.show()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, QPoint(4, 5))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, QPoint(4, 5))
    assert got == []
