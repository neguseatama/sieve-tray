"""sieve-tray v1.1.0 信頼性レーンのテスト（design doc TR-T01..T18）。

Red-first: 新 API（classify_observation / summarize_results / ScanResult.unobserved /
Storage の許可リスト・移行 / i18n 新キー）はテスト関数内で遅延取得し、実装前に
個別の失敗として実測できるようにする。既存動作の pin（TR-T12 のバイト一致ハッシュ、
TR-T16 の GUI エントリ順序）は現行で通ることを確認済み（v1.0.0 実測）。

計算の基準: v1.0.0（5587c4f）の render / render_text を、未観測 0 件の fixture で
実測した sha256（scripts/tray_render_hashes.py）。
"""
import builtins
import hashlib
import inspect
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import pytest

from sieve_tray import ScanResult, render, render_text, run_scan
from sieve_tray_storage import Storage

RENDER_SHA256_V100 = "d5051e5813f1c06eca06f49916360b2017c83e8ccdd14ff7f5de259de72b7690"
RENDER_TEXT_SHA256_V100 = "36c79efa1d8d3c6f09f172b18da4d7851924c59ed44ae5dcee8b8c5f269cab42"

KNOWN_REFUSAL_CODES = [
    "not_regular_file", "file_too_large", "too_many_entries", "part_too_large",
    "total_too_large", "too_many_elements", "doctype_not_allowed",
    "unsupported_encoding", "duplicate_part", "encrypted", "malformed_xml",
    "main_part_missing", "unsupported_namespace",
]

CROWD_ALLOWLIST_EXPECTED = {
    "input_path", "output_path", "records_in", "records_out", "suppressed",
    "k_achieved", "max_risk", "avg_risk", "status", "reason", "report_text",
}


def _core():
    import sieve_tray
    return sieve_tray


def _doc(path="g/f.txt", mask="1000-000", flagged=False, **extra):
    d = {"path": path, "mask": mask, "flagged": flagged,
         "h_states": {}, "evidence": {}}
    d.update(extra)
    return d


def _result(doc_results=None, unobserved=None):
    return ScanResult(
        groups=[("group_a", [Path("group_a/keep.py")])],
        doc_results=doc_results if doc_results is not None else [],
        code_pairs=[], text_pairs=[], audit_results=[],
        unobserved=unobserved or [])


# ---------------------------------------------------------------------------
# TR-T01: mask 0000-000（拒否の証拠なし）→ unobserved / parse_failed
# ---------------------------------------------------------------------------

def test_t01_mask_zero_without_refusal_is_unobserved_parse_failed():
    core = _core()
    out = core.classify_observation(_doc(mask="0000-000"))
    assert out == ("unobserved", "parse_failed", None)


def test_t01_flagged_stays_false_and_not_clean():
    core = _core()
    d = _doc(mask="0000-000", flagged=False)
    status, reason, detail = core.classify_observation(d)
    assert status == "unobserved" and status != "clean"
    assert d["flagged"] is False  # classify は入力を書き換えない


# ---------------------------------------------------------------------------
# TR-T02: 既知 13 符号の拒否 evidence → refused / detail=<code>
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", KNOWN_REFUSAL_CODES)
def test_t02_known_refusal_codes_parametrized(code):
    core = _core()
    d = _doc(mask="0000-000",
             evidence={"H1": ["Extraction refused: %s" % code]})
    assert core.classify_observation(d) == ("unobserved", "refused", code)


# ---------------------------------------------------------------------------
# TR-T03: 未知の符号文字列 → refused / detail=None（未知の文字列を載せない）
# ---------------------------------------------------------------------------

def test_t03_unknown_refusal_code_detail_is_none():
    core = _core()
    d = _doc(mask="0000-000",
             evidence={"H1": ["Extraction refused: some_future_code"]})
    assert core.classify_observation(d) == ("unobserved", "refused", None)


# ---------------------------------------------------------------------------
# TR-T04: error キー → unreadable（OSError 系）/ parse_failed（その他）
# ---------------------------------------------------------------------------

def test_t04_error_key_classification():
    core = _core()
    assert core.classify_observation(
        _doc(mask="0000-000", error="PermissionError")
    ) == ("unobserved", "unreadable", None)
    assert core.classify_observation(
        _doc(mask="0000-000", error="ValueError")
    ) == ("unobserved", "parse_failed", None)


def test_t04_error_reason_is_closed_vocabulary():
    core = _core()
    for err in ("PermissionError", "IsADirectoryError", "UnicodeDecodeError",
                "ValueError", "KeyError", "SomeCustomError"):
        status, reason, detail = core.classify_observation(
            _doc(mask="0000-000", error=err))
        assert status == "unobserved"
        assert reason in core.UNOBSERVED_REASONS
        assert detail is None  # 型名以外（メッセージ）は載らない


# ---------------------------------------------------------------------------
# TR-T05: 拡張・エンジンの欠落 → engine_unavailable（黙ってスキップしない）
# ---------------------------------------------------------------------------

def test_t05_unsupported_format_evidence_is_engine_unavailable():
    core = _core()
    d = _doc(path="x.pdf", mask="0000-000",
             evidence={"H1": ["Unsupported format: .pdf"]})
    assert core.classify_observation(d) == ("unobserved", "engine_unavailable", None)


def test_t05_missing_lens_marks_all_docs_engine_unavailable(tmp_path, monkeypatch):
    import sieve_tray
    f = tmp_path / "note.txt"
    f.write_text("hello", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "sieve_lens", None)
    results = sieve_tray.observe_documents([f])
    assert len(results) == 1
    r = results[0]
    assert r["status"] == "unobserved"
    assert r["unobserved_reason"] == "engine_unavailable"
    assert r["flagged"] is False
    assert r.get("error") == "ImportError"  # 既存契約どおり型名のみ


def test_t05_failed_extension_marks_affected_files(tmp_path, monkeypatch):
    import importlib
    import sieve_tray
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    real = importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name in ("sieve_lens_ext.pdf", "sieve_lens_ext.pdf_images"):
            raise ImportError("simulated: %s" % name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    results = sieve_tray.observe_documents([pdf])
    assert len(results) == 1
    r = results[0]
    assert r["status"] == "unobserved"
    assert r["unobserved_reason"] == "engine_unavailable"
    assert r["flagged"] is False


# ---------------------------------------------------------------------------
# TR-T06: 金型 — 観測成立 mask は従来どおり clean / flagged
# ---------------------------------------------------------------------------

def test_t06_observed_masks_keep_clean_and_flagged():
    core = _core()
    assert core.classify_observation(_doc(mask="1000-000")) == ("clean", None, None)
    assert core.classify_observation(
        _doc(mask="1100-000", flagged=True))[0] == "flagged"
    assert core.classify_observation(
        _doc(mask="1000-101", flagged=True))[0] == "flagged"


# ---------------------------------------------------------------------------
# TR-T07: H1=0 のコードファイルはペアでなくファイル単位で unobserved
# ---------------------------------------------------------------------------

def test_t07_unparseable_code_file_is_file_level_unobserved(tmp_path):
    a = tmp_path / "group_a"; a.mkdir()
    b = tmp_path / "group_b"; b.mkdir()
    (a / "bad.py").write_text("def f(:\n", encoding="utf-8")
    (b / "ok.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    result = run_scan(tmp_path)
    entries = [e for e in result.unobserved if e["file"].endswith("bad.py")]
    assert entries, "H1=0 のコードファイルが unobserved に載っていない"
    assert entries[0]["reason"] == "parse_failed"
    assert not any(p["a"].endswith("bad.py") or p["b"].endswith("bad.py")
                   for p in result.code_pairs)


# ---------------------------------------------------------------------------
# TR-T08: 空 __init__.py は not_applicable・空でない組の結果は不変
# ---------------------------------------------------------------------------

def _make_tree(base, with_empty):
    a = base / "group_a"; a.mkdir(parents=True)
    b = base / "group_b"; b.mkdir(parents=True)
    (a / "real1.py").write_text("def calc(a, b):\n    return a + b\n",
                                encoding="utf-8")
    (b / "real2.py").write_text("def calc(x, y):\n    return x + y\n",
                                encoding="utf-8")
    if with_empty:
        (a / "__init__.py").write_text("", encoding="utf-8")
        (b / "__init__.py").write_text("# comment only\n", encoding="utf-8")


def test_t08_empty_py_not_applicable_and_pairs_unchanged(tmp_path):
    t1 = tmp_path / "t1"; t1.mkdir()
    t2 = tmp_path / "t2"; t2.mkdir()
    _make_tree(t1, with_empty=False)
    _make_tree(t2, with_empty=True)
    r1, r2 = run_scan(t1), run_scan(t2)
    assert r1.code_pairs == r2.code_pairs
    na = [e for e in r2.unobserved if e["reason"] == "not_applicable"]
    assert len(na) == 2
    assert all(e["file"].endswith("__init__.py") for e in na)


# ---------------------------------------------------------------------------
# TR-T09: 空・読めないテキスト → empty_input / unreadable（Referee 経路）
# ---------------------------------------------------------------------------

def test_t09_empty_and_unreadable_text_reported(tmp_path):
    a = tmp_path / "group_a"; a.mkdir()
    b = tmp_path / "group_b"; b.mkdir()
    (a / "empty.txt").write_text("", encoding="utf-8")
    (b / "empty.txt").write_text("", encoding="utf-8")
    result = run_scan(tmp_path)
    emp = [e for e in result.unobserved if e["reason"] == "empty_input"]
    assert len(emp) == 2
    assert result.text_pairs == []

    secret = a / "secret.txt"
    secret.write_text("secret words here", encoding="utf-8")
    secret.chmod(0o000)
    try:
        r2 = run_scan(tmp_path)
        un = [e for e in r2.unobserved if e["file"].endswith("secret.txt")]
        assert un and un[0]["reason"] == "unreadable"
        assert not any("secret words" in json.dumps(p) for p in r2.text_pairs)
    finally:
        secret.chmod(0o644)


# ---------------------------------------------------------------------------
# TR-T10: 上限超過 → too_large・読み込みは上限+1 バイトまで
# ---------------------------------------------------------------------------

def test_t10_oversized_file_is_too_large_and_reads_at_most_limit_plus_one(
        tmp_path, monkeypatch):
    import sieve_tray
    a = tmp_path / "group_a"; a.mkdir()
    big = a / "big.py"
    big.write_text("x = 1\n" * 40, encoding="utf-8")  # 240 bytes > 100

    orig_open = builtins.open
    reads = []

    class _Counting:
        def __init__(self, fh):
            self._fh = fh

        def read(self, n=-1):
            reads.append(n)
            return self._fh.read(n)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self._fh.__exit__(*exc)

        def close(self):
            return self._fh.close()

    def counting_open(file, mode="r", *args, **kwargs):
        fh = orig_open(file, mode, *args, **kwargs)
        if "b" in str(mode):
            return _Counting(fh)
        return fh

    monkeypatch.setattr(builtins, "open", counting_open)
    monkeypatch.setattr(sieve_tray, "TRAY_READ_LIMIT_BYTES", 100)
    result = run_scan(tmp_path)
    entries = [e for e in result.unobserved if e["file"].endswith("big.py")]
    assert entries and entries[0]["reason"] == "too_large"
    assert reads, "read が上限+1 の制約で呼ばれていない"
    assert max(reads) <= sieve_tray.TRAY_READ_LIMIT_BYTES + 1


# ---------------------------------------------------------------------------
# TR-T11: シンボリックリンク・FIFO を読まず、根の外も読まれない
# ---------------------------------------------------------------------------

def test_t11_symlinks_and_fifo_are_not_read(tmp_path):
    root = tmp_path / "scan_root"
    ga = root / "group_a"; ga.mkdir(parents=True)
    out = tmp_path / "outside"; out.mkdir()
    (out / "target.py").write_text("OUTSIDE_MARKER = 1\n", encoding="utf-8")
    (ga / "link.py").symlink_to(out / "target.py")
    (ga / "linkdir").symlink_to(out)
    os.mkfifo(ga / "pipe.py")
    (ga / "normal.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    result = run_scan(root)
    link_entries = [e for e in result.unobserved
                    if e["file"].endswith("link.py")]
    assert link_entries and link_entries[0]["reason"] == "symlink_skipped"
    fifo_entries = [e for e in result.unobserved
                    if e["file"].endswith("pipe.py")]
    assert fifo_entries and fifo_entries[0]["reason"] == "unreadable"

    blob = json.dumps([result.doc_results, result.code_pairs,
                       result.unobserved], default=str)
    assert "OUTSIDE_MARKER" not in blob, "根の外のファイル内容が読まれている"
    assert "target.py" not in blob, "リンク先ディレクトリを辿っている"


# ---------------------------------------------------------------------------
# TR-T12: 未観測 0 件の出力は v1.0.0 とバイト一致・3 状態の表示
# ---------------------------------------------------------------------------

def test_t12_render_without_unobserved_is_byte_identical_to_v1_0_0():
    r = _result(doc_results=[_doc(path="group_a/note.txt", mask="1000-000")])
    assert hashlib.sha256(
        render(r).encode("utf-8")).hexdigest() == RENDER_SHA256_V100
    assert hashlib.sha256(
        render_text(r).encode("utf-8")).hexdigest() == RENDER_TEXT_SHA256_V100


def test_t12_render_with_unobserved_shows_third_state():
    r = _result(
        doc_results=[_doc(path="g/x<>.pdf", mask="0000-000",
                          evidence={"H1": ["Extraction refused: encrypted"]})],
        unobserved=[{"file": "g/bad.py", "engine": "scope",
                     "reason": "parse_failed", "detail": None}])
    html_out = render(r)
    assert "Unobserved" in html_out
    assert "unobserved (refused: encrypted)" in html_out
    assert "Unobserved: 2." in html_out
    assert "x&lt;&gt;.pdf" in html_out  # パスは escape される
    text_out = render_text(r)
    assert "## Unobserved" in text_out
    assert "unobserved (refused: encrypted)" in text_out
    assert "Unobserved: 2." in text_out


# ---------------------------------------------------------------------------
# TR-T13: 履歴の往復と旧レコードの status 導出
# ---------------------------------------------------------------------------

def test_t13_history_roundtrip_preserves_status(tmp_path):
    st = Storage(db_path=tmp_path / "history.db")
    r = ScanResult(
        groups=[("g", [Path("g/a.txt")])],
        doc_results=[_doc(path="g/a.txt", mask="0000-000", flagged=False,
                          evidence={"H1": ["Extraction refused: encrypted"]},
                          status="unobserved", unobserved_reason="refused",
                          unobserved_detail="encrypted")],
        code_pairs=[], text_pairs=[], audit_results=[])
    rid = st.save_run(Path("g"), r)
    loaded = st.load_run(rid)
    d0 = loaded.doc_results[0]
    assert d0["status"] == "unobserved"
    assert d0["unobserved_reason"] == "refused"
    assert d0["unobserved_detail"] == "encrypted"
    assert d0["flagged"] is False  # 既存キーの意味は不変
    assert d0["mask"] == "0000-000"


def test_t13_old_records_derive_status(tmp_path):
    st = Storage(db_path=tmp_path / "history.db")
    r = ScanResult(
        groups=[("g", [Path("g/a.txt")])],
        doc_results=[_doc(path="g/a.txt", mask="1000-000"),
                     _doc(path="g/b.txt", mask="0000-000")],
        code_pairs=[], text_pairs=[], audit_results=[])
    rid = st.save_run(Path("g"), r)

    # v1.0.0 形に戻す（status 系キーを剥がす・導出不能の第 3 件を足す）
    conn = sqlite3.connect(tmp_path / "history.db")
    raw = json.loads(conn.execute(
        "SELECT result_json FROM runs WHERE id = ?", (rid,)).fetchone()[0])
    for d in raw["doc_results"]:
        for k in ("status", "unobserved_reason", "unobserved_detail"):
            d.pop(k, None)
    raw["doc_results"].append({"path": "g/c.txt", "flagged": False})
    conn.execute("UPDATE runs SET result_json = ? WHERE id = ?",
                 (json.dumps(raw), rid))
    conn.commit()
    conn.close()

    loaded = st.load_run(rid)
    a, b, c = loaded.doc_results
    assert a["status"] == "clean"
    assert b["status"] == "unobserved" and b["unobserved_reason"] == "parse_failed"
    assert c["status"] == "unobserved" and c["unobserved_reason"] == "parse_failed"


# ---------------------------------------------------------------------------
# TR-T14: Crowd 履歴は許可リスト方式・旧レコードの無害化と冪等移行
# ---------------------------------------------------------------------------

def _legacy_payload():
    return json.dumps({
        "ok": True, "status": "anonymized", "reason": None,
        "header": ["name"], "rows": [["alice"]],
        "report_text": "R", "report_json": "{}",
        "records_in": 1, "records_out": 1, "suppressed": 0,
        "k_requested": 2, "k_achieved": 2, "max_risk": 1.0, "avg_risk": 1.0,
        "before_alone": 0, "after_alone": 0, "io": {},
    })


def _insert_legacy_row(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO crowd_runs (timestamp, status, reason, records_in,"
        " records_out, suppressed, k_requested, k_achieved, max_risk,"
        " avg_risk, before_alone, after_alone, payload_json)"
        " VALUES ('2026-01-01T00:00:00+00:00','anonymized',NULL,1,1,0,2,2,"
        " 1.0,1.0,0,0,?)", (_legacy_payload(),))
    conn.execute("DELETE FROM settings WHERE key = 'crowd_payload_scrub_v1_1_0'")
    conn.commit()
    conn.close()


def test_t14_new_payload_is_allowlisted(tmp_path):
    st = Storage(db_path=tmp_path / "history.db")
    summary = {
        "ok": True, "status": "anonymized", "reason": None,
        "header": ["age"], "rows": [["30"]],
        "report_text": "R", "report_json": "{}",
        "records_in": 5, "records_out": 4, "suppressed": 1,
        "k_requested": 2, "k_achieved": 2, "max_risk": 0.5, "avg_risk": 0.25,
        "before_alone": 1, "after_alone": 0, "io": {"input_format": "csv"},
        "input_path": "/x.csv", "output_path": "/y.csv", "config_path": None,
    }
    st.save_crowd_run(summary)
    rec = st.load_crowd_runs()[0]
    assert "header" not in rec and "rows" not in rec
    keys = set(k for k in rec if k not in ("id", "timestamp"))
    assert keys == CROWD_ALLOWLIST_EXPECTED
    assert rec["records_in"] == 5 and rec["status"] == "anonymized"
    assert rec["report_text"] == "R"


def test_t14_migration_scrubs_legacy_rows_once(tmp_path):
    db = tmp_path / "history.db"
    Storage(db_path=db)          # スキーマ作成
    _insert_legacy_row(db)       # v1.0.0 形の行を直接注入（フラグも剥がす）
    st2 = Storage(db_path=db)    # 起動時移行が走る
    rec = st2.load_crowd_runs()[0]
    assert "header" not in rec and "rows" not in rec
    assert st2.get_setting("crowd_payload_scrub_v1_1_0") == "done"

    raw1 = sqlite3.connect(db).execute(
        "SELECT payload_json FROM crowd_runs").fetchone()[0]
    Storage(db_path=db)          # 2 回目: 冪等・何も変えない
    raw2 = sqlite3.connect(db).execute(
        "SELECT payload_json FROM crowd_runs").fetchone()[0]
    assert raw1 == raw2


# ---------------------------------------------------------------------------
# TR-T15: i18n の新キーは en/ja 対称・置換位置一致
# ---------------------------------------------------------------------------

def test_t15_i18n_new_keys_symmetric():
    from sieve_tray_i18n import STRINGS
    new_keys = ["status_unobserved", "unobserved_note"] + [
        "reason_refused", "reason_parse_failed", "reason_unreadable",
        "reason_too_large", "reason_symlink_skipped",
        "reason_engine_unavailable", "reason_not_applicable",
        "reason_empty_input",
    ]
    for key in new_keys:
        assert key in STRINGS["en"], key
        assert key in STRINGS["ja"], key
        assert STRINGS["en"][key] != key and STRINGS["ja"][key] != key
        pe = set(re.findall(r"{(\w+)}", STRINGS["en"][key]))
        pj = set(re.findall(r"{(\w+)}", STRINGS["ja"][key]))
        assert pe == pj, key


# ---------------------------------------------------------------------------
# TR-T16: GUI エントリポイントの freeze_support 順序（GUI 環境でのみ実行）
# ---------------------------------------------------------------------------

def test_t16_gui_entry_calls_freeze_support_before_qapplication():
    pytest.importorskip("PySide6")
    import sieve_tray_gui
    src = inspect.getsource(sieve_tray_gui)
    guard = src.split('if __name__ == "__main__":')[1]
    assert guard.index("freeze_support()") < guard.index("main()")


def test_t16_cli_entry_calls_freeze_support():
    core = _core()
    src = inspect.getsource(core.main)
    assert "freeze_support()" in src


# ---------------------------------------------------------------------------
# TR-T17: pyproject の package-data が sieve_crowd の非 .py を漏らさない
# ---------------------------------------------------------------------------

def test_t17_package_data_covers_vendored_crowd_files():
    import fnmatch
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10: tomli arrives with pytest
        import tomli as tomllib
    root = Path(__file__).resolve().parent.parent
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    pkgdata = data["tool"]["setuptools"].get("package-data", {})
    patterns = pkgdata.get("sieve_crowd", [])
    assert patterns, "package-data for sieve_crowd is missing"
    crowd = root / "sieve_crowd"
    extras = [p.name for p in crowd.iterdir()
              if p.is_file() and p.suffix != ".py"]
    for name in extras:
        assert any(fnmatch.fnmatch(name, pat) for pat in patterns), name


# ---------------------------------------------------------------------------
# TR-T18: 集計の純関数
# ---------------------------------------------------------------------------

def test_t18_summarize_results_counts_and_reason_bounds():
    core = _core()
    results = [
        _doc(mask="1000-000"),
        _doc(mask="1100-000", flagged=True),
        _doc(mask="0000-000"),
        _doc(mask="0000-000", error="PermissionError"),
        _doc(path="x.pdf", mask="0000-000",
             evidence={"H1": ["Unsupported format: .pdf"]}),
    ]
    s = core.summarize_results(results)
    assert s["flagged"] + s["clean"] + s["unobserved"] == len(results)
    assert s["clean"] == 1 and s["flagged"] == 1 and s["unobserved"] == 3
    assert set(s["unobserved_by_reason"]) == set(core.UNOBSERVED_REASONS)
    assert s["unobserved_by_reason"]["unreadable"] == 1
    assert s["unobserved_by_reason"]["engine_unavailable"] == 1
    assert s["unobserved_by_reason"]["parse_failed"] == 1


# ---------------------------------------------------------------------------
# ScanResult の後方互換（unobserved フィールドの追加と既定値）
# ---------------------------------------------------------------------------

def test_scanresult_unobserved_default_and_roundtrip():
    r = ScanResult()
    assert r.unobserved == []
    d = r.to_dict()
    assert "unobserved" in d
    r2 = ScanResult.from_dict(d)
    assert r2.unobserved == []
