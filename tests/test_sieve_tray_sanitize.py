"""Sanitize integration: the vendored Redact engine driven by the tray core.

The wrapper in sieve_tray.py runs the vendored sieve_redact in-process,
maps its exit-code contract (0 ok / 1 other / 2 usage / 3 strict) without
letting SystemExit escape, and exposes the receipt numbers the GUI must
surface: masked count, byte integrity, and the residue measurement.
"""

import json
import sys

import pytest

import sieve_tray as st

NOT_IMPL = "sieve_tray.sanitize_file is not implemented"


def _fn():
    return getattr(st, "sanitize_file", None)


def test_wrapper_exists():
    assert _fn() is not None, NOT_IMPL


def test_sanitize_reports_receipt_numbers(tmp_path):
    fn = _fn()
    assert fn is not None, NOT_IMPL
    inp = tmp_path / "in.txt"
    inp.write_text("call 090-1234-5678 now\n", encoding="utf-8")
    cfg = tmp_path / "rules.txt"
    cfg.write_text("builtin phone-jp:delete\n", encoding="utf-8")
    out = tmp_path / "out.txt"
    rec = tmp_path / "receipt.json"
    result = fn(inp, cfg, out, receipt_path=rec)
    assert result["ok"] is True
    assert result["rc"] == 0
    assert out.read_text(encoding="utf-8") == "call  now\n"
    data = json.loads(rec.read_text(encoding="utf-8"))
    assert data["total_redactions"] == 1
    assert result["masked_count"] == 1
    assert result["integrity_verified"] is True
    assert result["residue"] == "none"


def test_sanitize_usage_error_maps_to_rc2(tmp_path):
    fn = _fn()
    assert fn is not None, NOT_IMPL
    inp = tmp_path / "in.txt"
    inp.write_text("hello\n", encoding="utf-8")
    cfg = tmp_path / "rules.txt"
    cfg.write_text("bogus line\n", encoding="utf-8")
    result = fn(inp, cfg, tmp_path / "out.txt")
    assert result["ok"] is False
    assert result["rc"] == 2


def test_sanitize_missing_input_maps_to_rc1(tmp_path):
    # main() raises SystemExit on runtime failures; the wrapper maps the
    # code (documented contract: 1 = other failures) instead of leaking it.
    fn = _fn()
    assert fn is not None, NOT_IMPL
    cfg = tmp_path / "rules.txt"
    cfg.write_text("builtin phone-jp:delete\n", encoding="utf-8")
    result = fn(tmp_path / "missing.txt", cfg, tmp_path / "out.txt")
    assert result["ok"] is False
    assert result["rc"] == 1


def test_sanitize_skips_gracefully_without_module(tmp_path, monkeypatch):
    # Synthetic module absence: a None entry in sys.modules makes
    # "import sieve_redact" raise ImportError even though the file exists.
    fn = _fn()
    assert fn is not None, NOT_IMPL
    monkeypatch.setitem(sys.modules, "sieve_redact", None)
    inp = tmp_path / "in.txt"
    inp.write_text("hello\n", encoding="utf-8")
    cfg = tmp_path / "rules.txt"
    cfg.write_text("builtin phone-jp:delete\n", encoding="utf-8")
    result = fn(inp, cfg, tmp_path / "out.txt")
    assert result["ok"] is False
    assert result["skipped"] is True


def test_sanitize_zero_redactions(tmp_path):
    fn = _fn()
    assert fn is not None, NOT_IMPL
    inp = tmp_path / "in.txt"
    inp.write_text("nothing to mask here\n", encoding="utf-8")
    cfg = tmp_path / "rules.txt"
    cfg.write_text("builtin phone-jp:delete\n", encoding="utf-8")
    out = tmp_path / "out.txt"
    result = fn(inp, cfg, out)
    assert result["ok"] is True
    assert result["rc"] == 0
    assert result["masked_count"] == 0
    assert result["integrity_verified"] is True
    assert out.read_text(encoding="utf-8") == "nothing to mask here\n"


def test_sanitize_tree_preserves_structure_and_receipts(tmp_path):
    fn = getattr(st, "sanitize_tree", None)
    assert fn is not None, "sieve_tray.sanitize_tree is not implemented"
    src = tmp_path / "submissions"
    (src / "a").mkdir(parents=True)
    (src / "a" / "b").mkdir(parents=True)
    (src / "a" / "b.txt").write_text("call 090-1234-5678 now\n", encoding="utf-8")
    (src / "a" / "b" / "c.md").write_text("see 03-1234-5678 ok\n", encoding="utf-8")
    cfg = tmp_path / "rules.txt"
    cfg.write_text("builtin phone-jp:delete\n", encoding="utf-8")
    out_root = tmp_path / "out"
    summary = fn(src, cfg, out_root)
    assert summary["skipped"] is False
    assert summary["n_files"] == 2
    assert summary["ok_count"] == 2
    b = out_root / "a" / "b.txt"
    c = out_root / "a" / "b" / "c.md"
    assert b.exists() and b.read_text(encoding="utf-8") == "call  now\n"
    assert c.exists() and c.read_text(encoding="utf-8") == "see  ok\n"
    assert (out_root / "a" / "b.txt.receipt.json").exists()
    assert (out_root / "a" / "b" / "c.md.receipt.json").exists()
    assert summary["masked_total"] == 2
    assert summary["integrity_bad_count"] == 0


def test_sanitize_tree_zero_files(tmp_path):
    fn = getattr(st, "sanitize_tree", None)
    assert fn is not None, "sieve_tray.sanitize_tree is not implemented"
    src = tmp_path / "submissions"
    src.mkdir()
    (src / "note.bin").write_bytes(b"\x00\x01")
    cfg = tmp_path / "rules.txt"
    cfg.write_text("builtin phone-jp:delete\n", encoding="utf-8")
    summary = fn(src, cfg, tmp_path / "out")
    assert summary["n_files"] == 0
    assert summary["ok_count"] == 0
    assert summary["masked_total"] == 0
    assert summary["skipped"] is False


def test_sanitize_tree_skips_gracefully(tmp_path, monkeypatch):
    fn = getattr(st, "sanitize_tree", None)
    assert fn is not None, "sieve_tray.sanitize_tree is not implemented"
    monkeypatch.setitem(sys.modules, "sieve_redact", None)
    src = tmp_path / "submissions"
    src.mkdir()
    (src / "a.txt").write_text("hello\n", encoding="utf-8")
    cfg = tmp_path / "rules.txt"
    cfg.write_text("builtin phone-jp:delete\n", encoding="utf-8")
    summary = fn(src, cfg, tmp_path / "out")
    assert summary["skipped"] is True
    assert summary["ok_count"] == 0


def test_sanitize_tree_reports_failures(tmp_path):
    fn = getattr(st, "sanitize_tree", None)
    assert fn is not None, "sieve_tray.sanitize_tree is not implemented"
    src = tmp_path / "submissions"
    src.mkdir()
    (src / "a.txt").write_text("hello\n", encoding="utf-8")
    cfg = tmp_path / "broken.txt"
    cfg.write_text("bogus line\n", encoding="utf-8")
    summary = fn(src, cfg, tmp_path / "out")
    assert summary["n_files"] == 1
    assert summary["ok_count"] == 0
    assert len(summary["failed"]) == 1
    assert str(summary["failed"][0][0]) == "a.txt"


def test_sanitize_failure_handler_is_thin():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent
            / "sieve_tray_gui.py").read_text(encoding="utf-8")
    lines = text.split("\n")
    i = [k for k, ln in enumerate(lines)
         if ln == "    def _on_sanitize_failed(self, message: str):"]
    assert len(i) == 1, "failure handler missing or duplicated"
    rest = lines[i[0] + 1:]
    j = 0
    while j < len(rest) and not rest[j].startswith("    def "):
        j += 1
    body = "\n".join(rest[:j])
    assert "QFileDialog" not in body, \
        "failure handler re-runs sanitize (old synchronous body absorbed)"
    assert "sanitize_file(" not in body, \
        "failure handler re-runs sanitize (old synchronous body absorbed)"
    assert text.count("    sanitize_tree,\n") == 1, "duplicate sanitize_tree import"
    assert text.count("    sanitize_file,\n") == 1, "duplicate sanitize_file import"
