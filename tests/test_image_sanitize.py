"""Image sanitize plumbing: tray helpers and the wrapper's image branch.

tray v0.5 image UX (single-PNG scope). The tray core builds a region-only
config file, drives the vendored Redact engine through sanitize_file, and
must report the image receipt honestly: pixel_integrity_verified is the
measured integrity; byte_integrity_verified is null in the engine contract
(PNG re-encoding changes bytes structurally) and must never be surfaced as
a failure.

Fixtures (committed, monochrome):
- image_sanitize_base.png: 32x16 RGB, all pixels (30, 60, 90)
- image_sanitize_rgba.png: 16x16 RGBA, all pixels (10, 20, 30, 128)
"""

import json
from pathlib import Path

import pytest
from PIL import Image

import sieve_redact
import sieve_tray as st

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASE_PNG = FIXTURES / "image_sanitize_base.png"
RGBA_PNG = FIXTURES / "image_sanitize_rgba.png"

NOT_IMPL = "sieve_tray.%s is not implemented"


def _fn(name):
    return getattr(st, name, None)


# --- pure helpers (construction + validation) ------------------------------


def test_make_region_spec_basic():
    fn = _fn("make_region_spec")
    assert fn is not None, NOT_IMPL % "make_region_spec"
    assert fn(4, 4, 8, 8, "delete") == "4,4,8,8:delete"
    assert fn(0, 0, 10, 5, "mosaic", "8") == "0,0,10,5:mosaic:8"
    assert fn(1, 2, 3, 4, "replace", "AD") == "1,2,3,4:replace:AD"


def test_make_region_spec_rejects_colon_in_arg():
    fn = _fn("make_region_spec")
    assert fn is not None, NOT_IMPL % "make_region_spec"
    with pytest.raises(ValueError):
        fn(0, 0, 1, 1, "label", "a:b")


def test_validate_region_spec_agrees_with_engine():
    make = _fn("make_region_spec")
    validate = _fn("validate_region_spec")
    assert make is not None, NOT_IMPL % "make_region_spec"
    assert validate is not None, NOT_IMPL % "validate_region_spec"
    for spec in ("4,4,8,8:delete", "0,0,10,5:mosaic:8",
                 "1,2,3,4:replace:AD", "0,0,2,2:decor:FF0000"):
        assert validate(spec) == sieve_redact.parse_region_spec(spec)


def test_validate_region_spec_rejects_invalid():
    validate = _fn("validate_region_spec")
    assert validate is not None, NOT_IMPL % "validate_region_spec"
    for spec in ("4,4,8,8:blur", "4,4,8,8:delete:extra",
                 "4,4,0,8:delete", "4,4,8,8:replace"):
        with pytest.raises(ValueError):
            validate(spec)


def test_build_region_config_format():
    fn = _fn("build_region_config")
    assert fn is not None, NOT_IMPL % "build_region_config"
    cfg = fn(["4,4,8,8:delete", "0,0,2,2:mosaic:4"])
    assert cfg.split("\n") == ["region 4,4,8,8:delete",
                               "region 0,0,2,2:mosaic:4"]


def test_validate_rect_bounds():
    fn = _fn("validate_rect")
    assert fn is not None, NOT_IMPL % "validate_rect"
    assert fn({"x": 4, "y": 4, "w": 8, "h": 8}, 32, 16) is True
    assert fn({"x": 0, "y": 0, "w": 32, "h": 16}, 32, 16) is True
    assert fn({"x": 24, "y": 8, "w": 8, "h": 8}, 32, 16) is True
    assert fn({"x": 4, "y": 4, "w": 0, "h": 8}, 32, 16) is False
    assert fn({"x": -1, "y": 0, "w": 8, "h": 8}, 32, 16) is False
    assert fn({"x": 25, "y": 0, "w": 8, "h": 8}, 32, 16) is False
    assert fn({"x": 0, "y": 9, "w": 8, "h": 8}, 32, 16) is False


# --- wrapper: image receipt branch -----------------------------------------


def test_sanitize_file_image_delete(tmp_path):
    fn = _fn("sanitize_file")
    assert fn is not None, NOT_IMPL % "sanitize_file"
    cfg = tmp_path / "regions.txt"
    cfg.write_text("region 4,4,8,8:delete\n", encoding="utf-8")
    out = tmp_path / "out.png"
    rec = tmp_path / "receipt.json"
    result = fn(BASE_PNG, cfg, out, receipt_path=rec)
    assert result["ok"] is True, result
    assert result["rc"] == 0
    assert result["masked_count"] == 1, result
    assert result["integrity_verified"] is True, result
    assert result["byte_integrity_applicable"] is False
    with Image.open(out) as im:
        assert im.mode == "RGB"
        assert im.size == (32, 16)
        px = im.load()
        assert px[8, 8] == (255, 255, 255)
        assert px[0, 0] == (30, 60, 90)
        assert px[31, 15] == (30, 60, 90)
    data = json.loads(rec.read_text(encoding="utf-8"))
    assert data["input_format"] == "PNG"
    assert data["input_mode"] == "RGB"
    assert data["byte_integrity_verified"] is None
    assert data["pixel_integrity_verified"] is True
    assert len(data["rects"]) == 1


def test_sanitize_file_image_rgba_outside_preserved(tmp_path):
    fn = _fn("sanitize_file")
    assert fn is not None, NOT_IMPL % "sanitize_file"
    cfg = tmp_path / "regions.txt"
    cfg.write_text("region 2,2,4,4:delete\n", encoding="utf-8")
    out = tmp_path / "out.png"
    result = fn(RGBA_PNG, cfg, out)
    assert result["ok"] is True, result
    assert result["masked_count"] == 1
    assert result["integrity_verified"] is True
    assert result["byte_integrity_applicable"] is False
    with Image.open(out) as im:
        assert im.mode == "RGBA"
        px = im.load()
        assert px[10, 10] == (10, 20, 30, 128)
        assert px[0, 0] == (10, 20, 30, 128)


def test_sanitize_file_image_out_of_range_region_rc2(tmp_path):
    fn = _fn("sanitize_file")
    assert fn is not None, NOT_IMPL % "sanitize_file"
    cfg = tmp_path / "regions.txt"
    cfg.write_text("region 30,0,8,8:delete\n", encoding="utf-8")
    out = tmp_path / "out.png"
    result = fn(BASE_PNG, cfg, out)
    assert result["ok"] is False
    assert result["rc"] == 2
