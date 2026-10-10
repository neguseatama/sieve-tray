"""MainWindow image entry: output path helper, button, sync run core.

tray v0.5 image UX (single-PNG scope), final wiring. The modal flow
(file dialog + editor dialog) is verified by a manual checklist because
QFileDialog/QDialog modality cannot be exercised headless; the
synchronous core (run_image_sanitize) is fully pinned here:
- receipt written next to the output (sanitize_tree convention)
- history row saved unless the engine is unavailable (folder-flow
  convention: failures are recorded too, not only successes)
"""

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import sieve_tray_gui as gui
from sieve_tray_i18n import tr
from sieve_tray_storage import Storage

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASE_PNG = FIXTURES / "image_sanitize_base.png"

NOT_IMPL = "sieve_tray_gui.%s is not implemented"


def _fn(name):
    return getattr(gui, name, None)


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


def test_image_output_paths():
    fn = _fn("image_output_paths")
    assert fn is not None, NOT_IMPL % "image_output_paths"
    cfg, out = fn("/tmp/exp/scan.png", "/tmp/exp")
    assert cfg == Path("/tmp/exp/scan_regions.txt")
    assert out == Path("/tmp/exp/scan_sanitized.png")
    cfg2, out2 = fn(Path("deep/dir/photo.PNG"), Path("exp"))
    assert cfg2 == Path("exp/photo_regions.txt")
    assert out2 == Path("exp/photo_sanitized.png")


def test_sanitize_image_button_present_and_enabled(window):
    btn = getattr(window, "sanitize_image_btn", None)
    assert btn is not None, NOT_IMPL % "sanitize_image_btn"
    assert btn.text() == tr("en", "sanitize_image_button")
    assert btn.isEnabled() is True


def test_run_image_sanitize_success(window, tmp_path):
    out_path = tmp_path / "image_sanitize_base_sanitized.png"
    cfg_path = tmp_path / "image_sanitize_base_regions.txt"
    cfg_path.write_text("region 4,4,8,8:delete\n", encoding="utf-8")
    result = window.run_image_sanitize(str(BASE_PNG), cfg_path, out_path)
    assert result["ok"] is True, result
    assert result["rc"] == 0
    assert result["masked_count"] == 1
    assert result["integrity_verified"] is True
    assert result["byte_integrity_applicable"] is False
    assert out_path.exists()
    rec_path = tmp_path / "image_sanitize_base_sanitized.png.receipt.json"
    assert rec_path.exists()
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    assert rec["pixel_integrity_verified"] is True
    rows = window.storage.load_sanitizations()
    assert len(rows) == 1


def test_run_image_sanitize_rc2_records_row(window, tmp_path):
    out_path = tmp_path / "image_sanitize_base_sanitized.png"
    cfg_path = tmp_path / "image_sanitize_base_regions.txt"
    cfg_path.write_text("region 30,0,8,8:delete\n", encoding="utf-8")
    result = window.run_image_sanitize(str(BASE_PNG), cfg_path, out_path)
    assert result["ok"] is False
    assert result["rc"] == 2
    assert not out_path.exists()
    rows = window.storage.load_sanitizations()
    assert len(rows) == 1
