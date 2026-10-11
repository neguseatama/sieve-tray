"""Folder-uniform image sanitize: sanitize_tree with region configs.

Contract (pinned against the vendored sieve_redact v0.6.0 engine):
  - region-only config  -> PNG targets; every other file is excluded
  - rule/builtin config -> TEXT_EXTS targets (unchanged); .png excluded
  - mixed config / unreadable config -> tree-level config_error,
    nothing is processed
  - per-file engine failures (out-of-range region, unsupported color
    type / bit depth) keep the tree running: rc 2 lands in failed
  - outputs mirror the relative structure; each receipt sits next to
    its output as <name>.receipt.json
"""

import json
from pathlib import Path

import pytest

from sieve_tray import sanitize_tree

FIXTURES = Path(__file__).parent / "fixtures"
BASE_PNG = FIXTURES / "image_sanitize_base.png"   # 32x16 RGB
RGBA_PNG = FIXTURES / "image_sanitize_rgba.png"   # 16x16 RGBA

IMG_EXCLUDED = "not a PNG (region config)"
TXT_EXCLUDED = "PNG not eligible (text config)"


def test_region_config_targets_png_and_excludes_the_rest(tmp_path):
    input_dir = tmp_path / "in"
    (input_dir / "sub").mkdir(parents=True)
    (input_dir / "a.png").write_bytes(BASE_PNG.read_bytes())
    (input_dir / "sub" / "b.png").write_bytes(RGBA_PNG.read_bytes())
    (input_dir / "notes.txt").write_text("hello\n", encoding="utf-8")
    (input_dir / "other.py").write_text("x = 1\n", encoding="utf-8")
    cfg = tmp_path / "cfg.txt"
    cfg.write_text("region 0,0,4,4:mosaic\n", encoding="utf-8")
    out_root = tmp_path / "out"

    summary = sanitize_tree(input_dir, cfg, out_root)

    assert set(summary.keys()) == {
        "n_files", "ok_count", "masked_total", "integrity_bad_count",
        "failed", "skipped", "excluded", "config_error"}
    assert summary["config_error"] is None
    assert summary["skipped"] is False
    assert summary["n_files"] == 2
    assert summary["ok_count"] == 2
    assert summary["masked_total"] == 2
    assert summary["integrity_bad_count"] == 0
    assert summary["failed"] == []
    assert summary["excluded"] == [
        (Path("notes.txt"), IMG_EXCLUDED),
        (Path("other.py"), IMG_EXCLUDED),
    ]
    assert (out_root / "a.png").is_file()
    assert (out_root / "sub" / "b.png").is_file()
    assert (out_root / "a.png.receipt.json").is_file()
    assert (out_root / "sub" / "b.png.receipt.json").is_file()
    receipt = json.loads(
        (out_root / "a.png.receipt.json").read_text(encoding="utf-8"))
    assert len(receipt["rects"]) == 1
    assert receipt["pixel_integrity_verified"] is True


def test_out_of_range_region_fails_one_file_and_continues(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "big.png").write_bytes(BASE_PNG.read_bytes())    # 32x16
    (input_dir / "small.png").write_bytes(RGBA_PNG.read_bytes())  # 16x16
    cfg = tmp_path / "cfg.txt"
    # 0,0,20,10 fits 32x16 but exceeds 16x16
    cfg.write_text("region 0,0,20,10:mosaic\n", encoding="utf-8")
    out_root = tmp_path / "out"

    summary = sanitize_tree(input_dir, cfg, out_root)

    assert summary["config_error"] is None
    assert summary["n_files"] == 2
    assert summary["ok_count"] == 1
    assert summary["masked_total"] == 1
    assert summary["integrity_bad_count"] == 0
    assert summary["excluded"] == []
    assert len(summary["failed"]) == 1
    rel, result = summary["failed"][0]
    assert rel == Path("small.png")
    assert result["rc"] == 2
    assert "exceeds image bounds" in result["stderr"]
    assert (out_root / "big.png").is_file()
    assert (out_root / "big.png.receipt.json").is_file()
    assert not (out_root / "small.png").exists()
    assert not (out_root / "small.png.receipt.json").exists()


def test_text_config_targets_text_and_excludes_png(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "doc.txt").write_text("secret here\n", encoding="utf-8")
    (input_dir / "pic.png").write_bytes(BASE_PNG.read_bytes())
    cfg = tmp_path / "cfg.txt"
    cfg.write_text("rule secret:mosaic\n", encoding="utf-8")
    out_root = tmp_path / "out"

    summary = sanitize_tree(input_dir, cfg, out_root)

    assert summary["config_error"] is None
    assert summary["n_files"] == 1
    assert summary["ok_count"] == 1
    assert summary["masked_total"] == 1
    assert summary["excluded"] == [(Path("pic.png"), TXT_EXCLUDED)]
    assert summary["failed"] == []
    assert (out_root / "doc.txt").is_file()
    assert not (out_root / "pic.png").exists()


def test_mixed_config_is_a_tree_level_error(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "a.png").write_bytes(BASE_PNG.read_bytes())
    (input_dir / "doc.txt").write_text("secret\n", encoding="utf-8")
    cfg = tmp_path / "cfg.txt"
    cfg.write_text("rule secret:mosaic\nregion 0,0,4,4:mosaic\n",
                   encoding="utf-8")
    out_root = tmp_path / "out"

    summary = sanitize_tree(input_dir, cfg, out_root)

    assert isinstance(summary["config_error"], str)
    assert summary["config_error"] != ""
    assert summary["n_files"] == 0
    assert summary["ok_count"] == 0
    assert summary["failed"] == []
    assert summary["excluded"] == []
    assert summary["skipped"] is False
    assert not (out_root / "a.png").exists()
    assert not (out_root / "doc.txt").exists()


def test_unsupported_png_variants_fail_per_file(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    input_dir = tmp_path / "in"
    input_dir.mkdir()
    src = Image.open(BASE_PNG)
    src.convert("P").save(input_dir / "palette.png")
    src.convert("L").save(input_dir / "gray.png")
    src.convert("I;16").save(input_dir / "gray16.png")
    cfg = tmp_path / "cfg.txt"
    cfg.write_text("region 0,0,4,4:mosaic\n", encoding="utf-8")
    out_root = tmp_path / "out"

    summary = sanitize_tree(input_dir, cfg, out_root)

    assert summary["config_error"] is None
    assert summary["n_files"] == 3
    assert summary["ok_count"] == 0
    assert summary["masked_total"] == 0
    assert summary["integrity_bad_count"] == 0
    assert len(summary["failed"]) == 3
    by_rel = {rel: result for rel, result in summary["failed"]}
    assert set(by_rel) == {Path("palette.png"), Path("gray.png"),
                           Path("gray16.png")}
    for rel in (Path("palette.png"), Path("gray.png")):
        assert by_rel[rel]["rc"] == 2
        assert "unsupported PNG color type" in by_rel[rel]["stderr"]
    assert by_rel[Path("gray16.png")]["rc"] == 2
    assert "unsupported PNG bit depth" in by_rel[Path("gray16.png")]["stderr"]
    assert not out_root.exists() or not any(
        p.is_file() for p in out_root.rglob("*"))


def test_comments_only_config_behaves_as_text_mode(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "doc.txt").write_text("hello\n", encoding="utf-8")
    (input_dir / "pic.png").write_bytes(BASE_PNG.read_bytes())
    cfg = tmp_path / "cfg.txt"
    cfg.write_text("# no rules here\n\n", encoding="utf-8")
    out_root = tmp_path / "out"

    summary = sanitize_tree(input_dir, cfg, out_root)

    assert summary["config_error"] is None
    assert summary["n_files"] == 1
    assert summary["ok_count"] == 1
    assert summary["masked_total"] == 0
    assert summary["excluded"] == [(Path("pic.png"), TXT_EXCLUDED)]


def test_unreadable_config_is_a_tree_level_error(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "doc.txt").write_text("hello\n", encoding="utf-8")
    cfg = tmp_path / "missing.txt"   # never created
    out_root = tmp_path / "out"

    summary = sanitize_tree(input_dir, cfg, out_root)

    assert isinstance(summary["config_error"], str)
    assert summary["config_error"] != ""
    assert summary["n_files"] == 0
    assert summary["failed"] == []
    assert summary["excluded"] == []
    assert not (out_root / "doc.txt").exists()


def test_unknown_config_kind_surfaces_engine_message(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "doc.txt").write_text("hello\n", encoding="utf-8")
    cfg = tmp_path / "cfg.txt"
    cfg.write_text("wat secret:mosaic\n", encoding="utf-8")
    out_root = tmp_path / "out"

    summary = sanitize_tree(input_dir, cfg, out_root)

    assert isinstance(summary["config_error"], str)
    assert "不明な kind" in summary["config_error"]
    assert summary["n_files"] == 0


def test_region_config_with_no_pngs_yields_empty_attempted_set(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "notes.txt").write_text("hello\n", encoding="utf-8")
    cfg = tmp_path / "cfg.txt"
    cfg.write_text("region 0,0,4,4:mosaic\n", encoding="utf-8")
    out_root = tmp_path / "out"

    summary = sanitize_tree(input_dir, cfg, out_root)

    assert summary["config_error"] is None
    assert summary["n_files"] == 0
    assert summary["ok_count"] == 0
    assert summary["excluded"] == [(Path("notes.txt"), IMG_EXCLUDED)]
    assert summary["failed"] == []
