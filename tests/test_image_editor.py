"""Image region editor dialog: spec list, ARG contracts, config export.

tray v0.5 image UX (single-PNG scope). The dialog owns an ImageCanvas
(drag tested in test_image_canvas.py), a MODE combo (engine REGION_MODES
order), an ARG field, a spec-string list, and a synchronous preview that
runs the vendored engine through sanitize_file into a temp output.

Region addition pre-validates with the tray core helpers (validate_rect
for bounds, validate_region_spec for engine grammar), so out-of-range
rects are rejected before any engine run. The preview path is the second
layer: engine-level rejections (e.g. unsupported PNG bit depth) surface
as rc 2 in the preview result.

Receipt pins derive from the committed fixtures:
- image_sanitize_base.png 32x16 RGB + region 4,4,8,8:delete -> ok/masked 1/
  pixel-verified/byte-not-applicable (measured in test_image_sanitize.py)
"""

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

import sieve_redact
import sieve_tray as st
import sieve_tray_gui as gui

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASE_PNG = FIXTURES / "image_sanitize_base.png"

NOT_IMPL = "sieve_tray_gui.%s is not implemented"


def _cls():
    return getattr(gui, "ImageRegionEditorDialog", None)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _dialog():
    cls = _cls()
    assert cls is not None, NOT_IMPL % "ImageRegionEditorDialog"
    return cls(str(BASE_PNG), "en")


def test_dialog_constructs_and_modes_match_engine(qapp):
    dlg = _dialog()
    assert dlg.canvas._pixmap.width() == 32
    assert dlg.canvas._pixmap.height() == 16
    modes = [dlg.mode_combo.itemText(i) for i in range(dlg.mode_combo.count())]
    assert modes == list(sieve_redact.REGION_MODES)
    assert dlg.mode_combo.currentText() == "delete"


def test_add_region_and_config_text(qapp):
    dlg = _dialog()
    dlg.add_region(4, 4, 8, 8, "delete", None)
    dlg.add_region(0, 0, 2, 2, "mosaic", "4")
    assert dlg.regions() == ["4,4,8,8:delete", "0,0,2,2:mosaic:4"]
    assert dlg.config_text() == ("region 4,4,8,8:delete\n"
                                 "region 0,0,2,2:mosaic:4")
    # overlay rects parsed back through the engine parser
    assert dlg.canvas._regions == [
        {"x": 4, "y": 4, "w": 8, "h": 8, "mode": "delete", "arg": None},
        {"x": 0, "y": 0, "w": 2, "h": 2, "mode": "mosaic", "arg": "4"},
    ]


def test_canvas_signal_adds_region(qapp):
    dlg = _dialog()
    dlg.canvas.region_selected.emit(4, 5, 8, 6)
    assert dlg.regions() == ["4,5,8,6:delete"]


def test_replace_requires_arg(qapp):
    dlg = _dialog()
    with pytest.raises(ValueError):
        dlg.add_region(0, 0, 2, 2, "replace", None)


def test_decor_requires_rrggbb(qapp):
    dlg = _dialog()
    for bad in ("FF00", "ZZZZZZ", ""):
        with pytest.raises(ValueError):
            dlg.add_region(0, 0, 2, 2, "decor", bad)


def test_arg_colon_rejected(qapp):
    dlg = _dialog()
    with pytest.raises(ValueError):
        dlg.add_region(0, 0, 2, 2, "label", "a:b")


def test_out_of_bounds_region_rejected(qapp):
    dlg = _dialog()
    with pytest.raises(ValueError):
        dlg.add_region(30, 0, 8, 8, "delete", None)


def test_delete_selected_region(qapp):
    dlg = _dialog()
    dlg.add_region(4, 4, 8, 8, "delete", None)
    dlg.add_region(0, 0, 2, 2, "mosaic", "4")
    dlg.spec_list.setCurrentRow(1)
    dlg.delete_selected_region()
    assert dlg.regions() == ["4,4,8,8:delete"]
    assert dlg.config_text() == "region 4,4,8,8:delete"


def test_preview_success_pins_receipt(qapp):
    dlg = _dialog()
    dlg.add_region(4, 4, 8, 8, "delete", None)
    dlg.run_preview()
    r = dlg.preview_result()
    assert r["ok"] is True
    assert r["rc"] == 0
    assert r["masked_count"] == 1
    assert r["integrity_verified"] is True
    assert r["byte_integrity_applicable"] is False
    assert dlg.preview_label.pixmap() is not None
    assert dlg.preview_label.pixmap().width() == 32


def test_preview_rc2_on_unsupported_png(qapp, tmp_path):
    p = tmp_path / "deep.png"
    Image.new("I;16", (8, 8), 1000).save(p)
    cls = _cls()
    dlg = cls(str(p), "en")
    dlg.add_region(0, 0, 2, 2, "delete", None)
    dlg.run_preview()
    r = dlg.preview_result()
    assert r["ok"] is False
    assert r["rc"] == 2
