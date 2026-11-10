"""CH-T01..T19 (Tray 2.1.0 Cohort core).

Acceptance tests for the M2 Cohort lane (request doc §3.1/§3.6/§3.7/§3.8
+ the design-chat rulings of 2026-11-09/10).  The Cohort core (run_cohort,
verify on sieve-cohort, cohort_self_check, the cohort_runs table) arrives
with the fix commits, so every test that needs it fails with ImportError
during the red stage; the count of those failures is the red measurement.

Closed vocabularies pinned here (request §3.1):
  item status: compared / not_compared; a not_compared reason is one of
  the existing 8 unobserved reasons (UNOBSERVED_REASONS) - no new words.

Receipt discipline (request §3.7): the receipt lists the FLAGGED pairs
only (GREEN lives in the summary counts), pairs carry counts and total
lengths only (no positions, no bodies), and CH-T07 sweeps the whole
handoff/ folder for the same reason.

The generic lane (request §3.5, the 2026-11-10 rulings): a pair is
flagged when EITHER side reaches 700 ‰, the recorded match_per_mille is
the triggering (higher) side, and the rule is stated in the receipt
settings and the report.
"""

import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import sqlite3
import zipfile
from pathlib import Path

import pytest

import sieve_tray

REPO_ROOT = Path(__file__).resolve().parent.parent
TRAY = REPO_ROOT / "sieve_tray.py"

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63f8cfc0f01f0005000105a52d8e300000000049454e44"
    "ae426082")

# The base (starter) sentence that essay_a carries verbatim (request §3.3:
# the base file is passed via --base and never enters the comparison
# folder; the exclusion is measured on the document lane by the referee's
# own 16-char strip).
BASE_TEXT = (
    "共通の指示文: 本課題では与えられた資料を読み、自分の言葉でまとめて提出する"
    "。引用する場合は出典を明示すること。")

ESSAY_BODY = (
    "提出物の本文である。観察した事実を順に並べ、それぞれに短い考察を添える。"
    "結論は最後の段落で、観察と考察からだけを根拠に述べる。")
ESSAY_ALT = (
    "提出物の本文をここに書く。見た事実を順番に並べて、それぞれへ短い考察を"
    "付け加える。最後の段落で結論を、観察と考察だけを根拠にして述べる。")

REPORT_SHARED = (
    "測定の方法: 同じ条件で三回ずつ測り、平均とばらつきを表にまとめた。")
REPORT_A_ONLY = "追加で検討したのは、測定回数を増やしたときの誤差の動きである。"
REPORT_B_ONLY = "さらに検討したのは、温度を変えたときの値のふれ幅である。"


def _cohort_tree(root: Path):
    """The §3.1 fixture: two flagged document pairs, one flagged scope
    pair, a unique document (GREEN pairs) and a non-lane image."""
    docs = root / "docs"
    code = root / "code"
    uniq = root / "unique"
    img = root / "img"
    for d in (docs, code, uniq, img):
        d.mkdir(parents=True)
    (docs / "essay_a.txt").write_text(
        BASE_TEXT + ESSAY_BODY, encoding="utf-8")
    (docs / "essay_b.txt").write_text(
        BASE_TEXT + ESSAY_ALT, encoding="utf-8")
    (docs / "report_a.txt").write_text(
        REPORT_SHARED + REPORT_A_ONLY, encoding="utf-8")
    (docs / "report_b.txt").write_text(
        REPORT_SHARED + REPORT_B_ONLY, encoding="utf-8")
    (uniq / "notes.txt").write_text(
        "この提出物は他と重なる部分が意図的にほとんどない。"
        "観測の種類を一つずつ確認するための対照用の文である。"
        "数値の例としては 3.14 や 2718 を含む。", encoding="utf-8")
    (code / "mod_a.py").write_text(
        "def area(width, height):\n"
        "    total = width * height\n"
        "    return total\n",
        encoding="utf-8")
    (code / "mod_b.py").write_text(
        "def zone(w, h):\n"
        "    sum_v = w * h\n"
        "    return sum_v\n",
        encoding="utf-8")
    (img / "figure.png").write_bytes(PNG_1X1)


def _base_file(tmp_path: Path) -> Path:
    p = tmp_path / "assignment-base.txt"
    p.write_text(BASE_TEXT, encoding="utf-8")
    return p


def _run_cohort(input_dir, output_dir, **kw):
    """Indirection so the red stage fails in each test, not at import."""
    from sieve_tray import run_cohort
    return run_cohort(input_dir, output_dir, **kw)


def _receipt_path(out: Path) -> Path:
    return out / "handoff" / "cohort-receipt.json"


def _report_path(out: Path) -> Path:
    return out / "local" / "cohort-report.html"


def _verify(receipt, *extra, input_dir=None, output_dir=None):
    """Run the verify CLI (the M1 shape) and return the CompletedProcess."""
    argv = [sys.executable, str(TRAY), "verify", str(receipt)]
    if input_dir is not None:
        argv.append(str(input_dir))
    if output_dir is not None:
        argv += ["--output", str(output_dir)]
    for e in extra:
        if isinstance(e, (list, tuple)):
            argv.extend(str(x) for x in e)
        else:
            argv.append(str(e))
    return subprocess.run(argv, capture_output=True, text=True,
                          cwd=str(REPO_ROOT))


def _pair_key(p) -> tuple:
    return (p["a"], p["b"])


def _pairs_map(receipt) -> dict:
    return {_pair_key(p): p for p in receipt.get("pairs", [])}


# ---------------------------------------------------------------------------
# CH-T01: output structure - the report goes first, the receipt is
# written last (the mtime assertion); the output folder rules are Gate's.
# ---------------------------------------------------------------------------

def test_ch_t01_report_before_receipt(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    receipt = _run_cohort(inp, out)
    handoff = out / "handoff"
    assert (handoff / "cohort-receipt.json").is_file()
    assert _report_path(out).is_file()
    assert receipt["kind"] == "sieve-cohort"
    assert receipt["tool"] == {"name": "sieve-tray",
                               "version": receipt["tool"]["version"]}
    # The receipt is written last: no handoff output is newer.
    rc_mtime = (handoff / "cohort-receipt.json").stat().st_mtime_ns
    for p in handoff.rglob("*"):
        if p.is_file() and p.name != "cohort-receipt.json":
            assert p.stat().st_mtime_ns <= rc_mtime, \
                f"{p.name} written after the receipt"


def test_ch_t01_out_dir_fail_closed(tmp_path):
    inp = tmp_path / "in"
    _cohort_tree(inp)
    # the output inside the input is refused
    with pytest.raises(ValueError):
        _run_cohort(inp, inp / "out")
    # a non-empty existing output folder is refused
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        _run_cohort(inp, out)


# ---------------------------------------------------------------------------
# CH-T02: the receipt lists the flagged pairs only (GREEN lives in the
# summary), each pair carries exactly one lane key and count-only spans.
# ---------------------------------------------------------------------------

def test_ch_t02_pairs_flagged_only(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    receipt = _run_cohort(inp, out)
    pairs = receipt["pairs"]
    summary = receipt["summary"]
    assert summary["flagged"] == len(pairs)
    assert len(pairs) >= 2, "the fixture must flag at least two pairs"
    for p in pairs:
        lanes = [k for k in ("referee", "scope", "generic") if k in p]
        assert len(lanes) == 1, lanes
        spans = p["spans"]
        assert set(spans.keys()) == {"count", "total_length"}
        assert isinstance(spans["count"], int)
        assert isinstance(spans["total_length"], int)
    # the essay pair and the scope pair are among the flagged
    pm = _pairs_map(receipt)
    assert ("docs/essay_a.txt", "docs/essay_b.txt") in pm
    assert ("code/mod_a.py", "code/mod_b.py") in pm
    # GREEN never appears as an individual entry (the summary holds it)
    ref = summary.get("referee") or {}
    if ref:
        assert ref["GREEN"] == ref["total"] - ref["RED"] - ref["YELLOW"]
        assert ref["GREEN"] >= 1


def test_ch_t02_hidden_counts_only(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    receipt = _run_cohort(inp, out)
    blob = json.dumps(receipt, ensure_ascii=False)
    # no submission body text ever reaches the receipt
    for needle in (ESSAY_BODY[:20], REPORT_A_ONLY[:20], REPORT_B_ONLY[:20]):
        assert needle not in blob
    for it in receipt["items"]:
        if "hidden_segments" in it:
            hs = it["hidden_segments"]
            assert isinstance(hs.get("count", 0), int)


# ---------------------------------------------------------------------------
# CH-T03: the closed status vocabulary - compared / not_compared, and a
# not_compared reason is one of the existing 8 words (request §3.1).
# ---------------------------------------------------------------------------

def test_ch_t03_status_vocabulary(tmp_path):
    from sieve_tray import UNOBSERVED_REASONS
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    receipt = _run_cohort(inp, out)
    statuses = {it["status"] for it in receipt["items"]}
    assert statuses <= {"compared", "not_compared"}
    assert "compared" in statuses and "not_compared" in statuses
    reasons = [it["unobserved_reason"] for it in receipt["items"]
               if it["status"] == "not_compared"]
    assert set(reasons) <= set(UNOBSERVED_REASONS), \
        "not_applicable"


def test_ch_t03_generic_flag_either_side():
    # The 2026-11-10 ruling: the generic lane flags a pair when EITHER
    # side reaches the threshold (700 per mille, provisional) - a small
    # file contained in a larger one must not be missed.  The recorded
    # match_per_mille is the triggering (higher) side.
    import sieve_scope
    from sieve_tray import _cohort_generic_pairs
    small = ("function calc(x) { return x * 2; }\n"
             "function add(y) { return y + 1; }\n")
    big = ("function alpha() { let seed = 1; for (let i = 0; i < 10; "
           "i++) { seed = (seed * 31 + i) % 9973; } return seed; }\n"
           "function beta(q) { return q.map(function (v) { return "
           "v * v; }).filter(function (v) { return v > 3; }); }\n") * 6 \
          + small + "function gamma(a, b) { var t = a; a = b; b = t; "\
                    "return [a, b]; }\n" * 3
    # the precondition: exactly one side reaches the threshold
    pm = (sieve_scope.language_agnostic_pair(small, big)
          .get("match_per_mille") or {})
    assert max(pm.get("a", 0), pm.get("b", 0)) >= 700
    assert min(pm.get("a", 0), pm.get("b", 0)) < 700
    pairs, all_pairs, _removal, _emptied = _cohort_generic_pairs(
        {"s_small.js": small, "t_big.js": big}, None, lambda m: None)
    assert len(pairs) == 1
    entry = pairs[0]
    assert entry["a"] == "s_small.js" and entry["b"] == "t_big.js"
    assert entry["generic"]["match_per_mille"] >= 700
    # the counter-case: two unrelated files stay unflagged
    c1 = "function one() { return 1; }" * 3
    c2 = "class Box { constructor(w) { this.w = w; } area() { return " \
         "this.w * this.w; } }" * 3
    pairs2, all2, _r2, _e2 = _cohort_generic_pairs(
        {"u_one.js": c1, "v_two.js": c2}, None, lambda m: None)
    assert pairs2 == [] and all2[0]["flagged"] is False


# ---------------------------------------------------------------------------
# CH-T04: exclusion counts (base / quotes / bibliography) appear in the
# report and the receipt only when a selection was made.
# ---------------------------------------------------------------------------

def test_ch_t04_exclusion_counts_appear(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    base = _base_file(tmp_path)
    receipt = _run_cohort(inp, out, base_paths=[base],
                          exclude_quotes=True, exclude_bibliography=True)
    by_name = {}
    for it in receipt["items"]:
        by_name[it.get("path", str(it.get("index")))] = it
    essay = by_name["docs/essay_a.txt"]
    removed = essay.get("removed") or {}
    assert int(removed.get("base", {}).get("length", 0)) > 0
    # the recorded base hashes are a list of the "sha256:..." form, one
    # per given base file, in order (the §3.7 wording: それぞれの SHA-256)
    recorded = receipt["settings"]["base"]["sha256"]
    assert isinstance(recorded, list) and len(recorded) == 1
    assert recorded[0].startswith("sha256:")
    assert recorded[0] == "sha256:" + hashlib.sha256(
        base.read_bytes()).hexdigest()
    report = _report_path(out).read_text(encoding="utf-8")
    assert "base" in report.lower()


def test_ch_t04_no_selection_no_fields(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    receipt = _run_cohort(inp, out)
    assert "removed" not in json.dumps(receipt, ensure_ascii=False)
    report = _report_path(out).read_text(encoding="utf-8")
    assert "removed" not in report.lower()


def test_ch_t04_generic_rule_recorded(tmp_path):
    # the 2026-11-10 ruling: the flag threshold and the side rule are
    # written into the receipt settings
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    receipt = _run_cohort(inp, out)
    settings = receipt["settings"]
    assert settings["generic_flag_per_mille"] == 700
    assert settings["generic_flag_side"] == "either"


# ---------------------------------------------------------------------------
# CH-T05: the report HTML - listing order, <mark> spans, escaping, the
# 20,000-char per-document cap, the 50-pair cap, no external requests.
# ---------------------------------------------------------------------------

def test_ch_t05_report_structure_and_marks(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    _run_cohort(inp, out)
    report = _report_path(out).read_text(encoding="utf-8")
    # the leading line (request §3.6): the flagged pairs are an
    # observation worth checking, never a conclusion - stated first
    assert report.index("not a conclusion") < report.index("<table")
    # the flagged pairs are listed first, then the rest by name
    pm = _pairs_map(json.loads(
        _receipt_path(out).read_text(encoding="utf-8")))
    flagged_names = [n for k, n in
                     [("a", "docs/essay_a.txt"), ("b", "docs/essay_b.txt")]]
    assert "docs/essay_a.txt" in report
    # a flagged pair's matched spans render as <mark> in the side-by-side
    assert "<mark>" in report
    # the report is plain HTML: no script blocks, no external references
    assert "<script" not in report.lower()
    assert "http://" not in report and "https://" not in report


def test_ch_t05_report_20000_char_cap(tmp_path):
    # two near-identical documents longer than the 20,000-char cap: the
    # side-by-side section truncates each document and shows the omitted
    # count (request §3.6: 超過は件数)
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    filler_a = ("測定の記録である。各段の値を並べ、平均を求め、表にまとめる。"
                ) * 690
    filler_b = ("測定の記録をここに残す。各段の値を並べて平均を求め、表に"
                "まとめる。") * 690
    assert len(filler_a) > 20000 and len(filler_b) > 20000
    (inp / "long_a.txt").write_text(filler_a, encoding="utf-8")
    (inp / "long_b.txt").write_text(filler_b, encoding="utf-8")
    _run_cohort(inp, out)
    report = _report_path(out).read_text(encoding="utf-8")
    m = re.search(r"(\d[\d,]*) characters omitted", report)
    assert m is not None, "the omitted count is shown, not the cap value"
    assert int(m.group(1).replace(",", "")) > 0


def test_ch_t05_report_no_external_requests(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    _run_cohort(inp, out)
    report = _report_path(out).read_text(encoding="utf-8")
    assert "src=" not in report.lower() or "src=\"/\"".lower() in \
        report.lower()
    out2 = tmp_path / "out2"
    _run_cohort(inp, out2, lang="ja")
    report2 = _report_path(out2).read_text(encoding="utf-8")
    assert ("結論ではない" in report2
            or "要確認" in report)


def test_ch_t05_report_generic_rule_and_graph_note(tmp_path):
    # the 2026-11-10 rulings: the generic flag rule (either side, 700
    # per mille) is stated in the report, and the graph carries the
    # reason its regions are connected components (no public cluster
    # API in Referee)
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    _run_cohort(inp, out)
    report = _report_path(out).read_text(encoding="utf-8")
    assert "either side" in report
    assert "700" in report
    # the 2026-11-10 ruling: the recorded match_per_mille is the
    # higher of the two sides (stated in the report and the README)
    assert "higher of the two sides" in report
    assert "connected components" in report
    out2 = tmp_path / "out2"
    _run_cohort(inp, out2, lang="ja")
    report2 = _report_path(out2).read_text(encoding="utf-8")
    assert "いずれか一方の側" in report2
    assert "高い側の値" in report2
    assert "連結成分" in report2


# ---------------------------------------------------------------------------
# CH-T06: the graph - deterministic SVG, no JavaScript, edges
# distinguishable without color, coordinates rounded to 1 decimal.
# ---------------------------------------------------------------------------

def test_ch_t06_svg_deterministic(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    _run_cohort(inp, out)
    report = _report_path(out).read_text(encoding="utf-8")
    m = re.search(r"<svg.*</svg>", report, re.S)
    assert m is not None, "the flagged-pairs graph is an inline SVG"
    svg = m.group(0)
    assert "<script" not in svg.lower()
    assert "javascript" not in svg.lower()
    assert "xmlns" not in svg
    # every coordinate is rounded to 1 decimal
    assert not re.search(r'c[xy]="-?\d+\.\d{2,}"', svg)
    assert re.search(r'c[xy]="-?\d+\.\d"', svg)
    # the edges differ by more than color: the heavy class and the
    # dashed class both appear (request §3.6)
    assert re.search(r'stroke-width="2\.5"', svg)
    assert re.search(r'stroke-width="1\.5"', svg)
    assert 'stroke-dasharray' in svg
    # determinism: a second run renders the same SVG bytes
    out2 = tmp_path / "out2"
    _run_cohort(inp, out2)
    report2 = _report_path(out2).read_text(encoding="utf-8")
    svg2 = re.search(r"<svg.*</svg>", report2, re.S).group(0)
    assert svg == svg2


# ---------------------------------------------------------------------------
# CH-T07: handoff/ carries the receipt only, and no submission body text
# reaches any handoff file (the sweep is over every handoff file).
# ---------------------------------------------------------------------------

def test_ch_t07_handoff_receipt_only(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    _run_cohort(inp, out)
    handoff = out / "handoff"
    files = [p for p in handoff.rglob("*") if p.is_file()]
    assert [p.name for p in files] == ["cohort-receipt.json"]
    blobs = [p.read_bytes() for p in files]
    joined = b"\n".join(blobs).decode("utf-8", "replace")
    for needle in (ESSAY_BODY[:16], ESSAY_ALT[:16], REPORT_A_ONLY[:16],
                   REPORT_B_ONLY[:16]):
        assert needle not in joined


# ---------------------------------------------------------------------------
# CH-T08: the strings and the README - the Cohort i18n keys exist in
# en/ja, the README intro lists the capability, and the verify vocabulary
# sentence (the closed word receipt_unreadable) is present in en/ja.
# ---------------------------------------------------------------------------

def test_ch_t08_cohort_strings_en_ja():
    from sieve_tray_i18n import STRINGS
    en_cohort = {k for k in STRINGS["en"] if k.startswith("cohort_")}
    ja_cohort = {k for k in STRINGS["ja"] if k.startswith("cohort_")}
    assert en_cohort, "the Cohort strings arrive with the fix commit"
    assert en_cohort == ja_cohort


def test_ch_t08_readme_intro_lists_cohort():
    en = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    ja = (REPO_ROOT / "README.ja.md").read_text(encoding="utf-8")
    # the intro enumerates what the tools do before anything else
    assert "Cohort" in en[:2000]
    assert "Cohort" in ja[:2000]


def test_ch_t08_readme_verify_vocabulary():
    en = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    ja = (REPO_ROOT / "README.ja.md").read_text(encoding="utf-8")
    assert "receipt_unreadable" in en
    assert "receipt_unreadable" in ja
    assert "辻褄" in ja


# ---------------------------------------------------------------------------
# CH-T09: the receipt shape - the M1 v1 envelope, the settings (the
# explanation constants are read from the engine modules), the digest
# form (normalized JSON, digest = the body's SHA-256 without the digest
# key), the item shape, and the --no-paths serial numbering.
# ---------------------------------------------------------------------------

def test_ch_t09_receipt_envelope(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    receipt = _run_cohort(inp, out)
    assert receipt["receipt_version"] == 1
    assert receipt["kind"] == "sieve-cohort"
    assert set(receipt["tool"]) == {"name", "version"}
    engines = {e["name"] for e in receipt["engines"]}
    assert engines <= {"sieve-lens", "sieve-order", "sieve-referee",
                       "sieve-scope"}
    summary = receipt["summary"]
    for key in ("items", "compared", "not_compared", "flagged"):
        assert key in summary


def test_ch_t09_receipt_settings(tmp_path):
    from sieve_referee.fingerprint import FINGERPRINT_K as ref_k
    import sieve_scope
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    receipt = _run_cohort(inp, out)
    settings = receipt["settings"]
    assert settings["exclude_quotes"] is False
    assert settings["exclude_bibliography"] is False
    assert settings["include_paths"] is True
    assert settings["include_input_hashes"] is True
    exp = settings["explanation"]
    assert exp["referee"]["k"] == 8 and exp["referee"]["w"] == 5
    assert exp["referee"]["min"] == 16
    assert exp["scope"]["k"] == 5 and exp["scope"]["w"] == 4
    assert exp["scope"]["min"] == 10
    # the constants really are the engine modules' own values
    assert exp["referee"]["k"] == ref_k
    assert exp["scope"]["k"] == sieve_scope.FINGERPRINT_K


def test_ch_t09_receipt_digest_form(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    _run_cohort(inp, out)
    raw = _receipt_path(out).read_text(encoding="utf-8")
    assert raw.endswith("\n")
    obj = json.loads(raw)
    body = {k: v for k, v in obj.items() if k != "digest"}
    norm = json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    assert obj["digest"] == "sha256:" + hashlib.sha256(
        norm.encode("utf-8")).hexdigest()
    # the file holds the same normalized body with the digest key back
    body2 = json.loads(raw)
    assert body2["digest"] == obj["digest"]


def test_ch_t09_items_kind_and_input(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    receipt = _run_cohort(inp, out)
    by_name = {it.get("path", ""): it for it in receipt["items"]}
    assert by_name["docs/essay_a.txt"]["kind"] == "document"
    assert by_name["code/mod_a.py"]["kind"] == "code"
    img = by_name["img/figure.png"]
    assert img["kind"] == "other"
    assert img["status"] == "not_compared"
    assert img["unobserved_reason"] == "not_applicable"
    for it in receipt["items"]:
        assert it["input"]["bytes"] >= 0


def test_ch_t09_no_paths_serial(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    receipt = _run_cohort(inp, out, include_paths=False)
    indexes = [it["index"] for it in receipt["items"]]
    assert indexes == list(range(1, len(indexes) + 1))
    assert all("path" not in it for it in receipt["items"])


def test_ch_t09_no_paths_pairs_serial(tmp_path):
    # the 2026-11-10 receipt ruling (request §2-5): a record without
    # paths identifies items by sequence number, and the flagged pairs
    # carry the submission file names - which is where the personal
    # names live - so the pairs take the same numbers, and no
    # submission file name reaches the handoff receipt at all.  The
    # report (local/) keeps the names (it never leaves this machine).
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    receipt = _run_cohort(inp, out, include_paths=False)
    n = len(receipt["items"])
    assert receipt["pairs"], "the fixture flags at least one pair"
    for p in receipt["pairs"]:
        assert isinstance(p["a"], int) and 1 <= p["a"] <= n, p
        assert isinstance(p["b"], int) and 1 <= p["b"] <= n, p
    raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
    for name in ("docs/essay_a.txt", "docs/essay_b.txt",
                 "docs/report_a.txt", "docs/report_b.txt",
                 "code/mod_a.py", "code/mod_b.py",
                 "unique/notes.txt", "img/figure.png",
                 "essay_a", "essay_b", "report_a", "report_b",
                 "mod_a", "mod_b", "notes.txt", "figure.png"):
        assert name not in raw, name
    # the report is local-only and keeps the submission names
    report = _report_path(out).read_text(encoding="utf-8")
    assert "essay_a" in report and "mod_a" in report


# ---------------------------------------------------------------------------
# CH-T10: verify on a sieve-cohort receipt - the M1 vocabulary and exit
# codes (0 match / 1 differs / 2 not_verifiable), the receipt-only
# handoff defaulting to outputs_only, and the recorded base files.
# ---------------------------------------------------------------------------

def test_ch_t10_verify_outputs_only_default(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    _run_cohort(inp, out)
    proc = _verify(_receipt_path(out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    obj = json.loads(proc.stdout)
    assert obj["scope"] == "outputs_only" and obj["overall"] == "match"


def test_ch_t10_verify_differs_and_not_verifiable(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    _run_cohort(inp, out)
    # a missing receipt is not_verifiable, not a crash
    proc = _verify(tmp_path / "nope.json")
    assert proc.returncode == 2
    obj = json.loads(proc.stdout)
    assert obj["overall"] == "not_verifiable"
    assert obj["not_verifiable_reason"] == "handoff_incomplete"
    # a receipt whose digest no longer matches is not_verifiable
    tampered = tmp_path / "tampered.json"
    obj = json.loads(_receipt_path(out).read_text(encoding="utf-8"))
    obj["summary"]["flagged"] = obj["summary"]["flagged"] + 1
    tampered.write_text(json.dumps(obj, ensure_ascii=False,
                                   sort_keys=True, separators=(",", ":")),
                        encoding="utf-8")
    proc = _verify(tampered)
    assert proc.returncode == 2
    obj = json.loads(proc.stdout)
    assert obj["overall"] == "not_verifiable"
    assert obj["not_verifiable_reason"] == "receipt_digest_mismatch"


def test_ch_t10_verify_base_hash_mismatch(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    base = _base_file(tmp_path)
    _run_cohort(inp, out, base_paths=[base])
    other = tmp_path / "other-base.txt"
    other.write_text(BASE_TEXT + "（改変）", encoding="utf-8")
    proc = _verify(_receipt_path(out), ["--base", str(other)])
    assert proc.returncode == 2, proc.stdout + proc.stderr
    obj = json.loads(proc.stdout)
    assert obj["overall"] == "not_verifiable"
    assert obj["not_verifiable_reason"] == "settings_unavailable"


def test_ch_t10_verify_replay_match(tmp_path):
    # the replay re-runs the whole comparison; the reproduced receipt
    # must be byte-identical - the digest covers the summary counts, so
    # the GREEN counts (summary-only, no individual GREEN pairs in the
    # receipt) are included in the 照合 by construction
    inp = tmp_path / "in"
    _cohort_tree(inp)
    out = tmp_path / "out"
    _run_cohort(inp, out)
    proc = _verify(_receipt_path(out), input_dir=inp)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    obj = json.loads(proc.stdout)
    assert obj["scope"] == "replay" and obj["overall"] == "match"


def test_ch_t10_verify_base_replay_match(tmp_path):
    # replay with the recorded base files reproduces the receipt too
    inp = tmp_path / "in"
    _cohort_tree(inp)
    base = _base_file(tmp_path)
    out = tmp_path / "out"
    _run_cohort(inp, out, base_paths=[base])
    proc = _verify(_receipt_path(out), ["--base", str(base)],
                   input_dir=inp)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    obj = json.loads(proc.stdout)
    assert obj["scope"] == "replay" and obj["overall"] == "match"


def test_ch_t10_verify_summary_arithmetic_broken(tmp_path):
    # the GREEN 照合 (the 2026-11-10 ruling): the receipt lists the
    # flagged pairs only, so verify cross-checks the summary arithmetic
    # (flagged == listed pairs, per-lane counts, GREEN == total - RED
    # - YELLOW).  A receipt whose numbers do not hold together is not
    # a verifiable record - even when its self-digest is consistent.
    # The 2026-11-10 ruling keeps the verify vocabulary closed (the M1
    # published contract, request §2-7): the broken summary is reported
    # with the existing receipt_unreadable word; the distinction is
    # carried by the human-readable wording (README / report), not by
    # a new vocabulary word.
    inp = tmp_path / "in"
    _cohort_tree(inp)
    out = tmp_path / "out"
    _run_cohort(inp, out)
    obj = json.loads(_receipt_path(out).read_text(encoding="utf-8"))
    assert obj["pairs"], "the §3.1 tree must flag at least one pair"
    obj["pairs"] = obj["pairs"][1:]  # drop one flagged pair
    from sieve_tray import _gate_digest
    obj["digest"] = _gate_digest(obj)
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(obj, ensure_ascii=False,
                                   sort_keys=True,
                                   separators=(",", ":")),
                        encoding="utf-8")
    proc = _verify(tampered)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    o = json.loads(proc.stdout)
    assert o["overall"] == "not_verifiable"
    assert o["not_verifiable_reason"] == "receipt_unreadable"


# ---------------------------------------------------------------------------
# CH-T11: the sample pack and the self-check (expected observations,
# never a digest).
# ---------------------------------------------------------------------------

def test_ch_t11_samples_and_manifest():
    pack = REPO_ROOT / "samples" / "cohort"
    manifest_path = pack / "MANIFEST.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest.keys()) == {"items", "pairs", "run"}
    run = manifest["run"]
    assert run["exclude_quotes"] is True
    assert run["exclude_bibliography"] is True
    assert isinstance(run["base"], list) and run["base"]
    roles = set()
    for entry in manifest["items"]:
        assert {"file", "sha256"} <= set(entry.keys())
        p = pack / entry["file"]
        assert p.is_file(), entry["file"]
        assert entry["sha256"] == hashlib.sha256(
            p.read_bytes()).hexdigest(), entry["file"]
        roles.add(entry.get("role", "submission"))
    assert roles == {"submission", "base"}
    assert len(manifest["pairs"]) >= 1
    for pr in manifest["pairs"]:
        assert {"a", "b", "expect"} <= set(pr.keys())


def test_ch_t11_regen_byte_identical(tmp_path):
    pack = REPO_ROOT / "samples" / "cohort"
    target = tmp_path / "regen"
    proc = subprocess.run(
        [sys.executable, str(pack / "generate.py"), str(target)],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    manifest = json.loads((pack / "MANIFEST.json").read_text(
        encoding="utf-8"))
    names = [e["file"] for e in manifest["items"]] + ["MANIFEST.json"]
    for name in names:
        assert (target / name).read_bytes() == (pack / name).read_bytes(), \
            name


def test_ch_t11_self_check_matches():
    from sieve_tray import cohort_self_check
    result = cohort_self_check()
    assert result["expected"] == 19
    assert result["matching"] == 19
    assert result["differences"] == []


def test_ch_t11_self_check_exit_codes(tmp_path):
    # rc 0 = the expected observations matched, 1 = a difference,
    # 2 = the self-check could not run (the 2026-11-10 ruling)
    proc = subprocess.run(
        [sys.executable, str(TRAY), "cohort", "--self-check"],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # the run's progress lines precede the machine-readable result
    obj = json.loads(proc.stdout[proc.stdout.index("{"):])
    assert obj["matching"] == obj["expected"]
    # a tree without the pack: rc 2 (the pack is a repository resource)
    lone = tmp_path / "lone"
    lone.mkdir()
    (lone / "sieve_tray.py").write_bytes(TRAY.read_bytes())
    proc2 = subprocess.run(
        [sys.executable, str(lone / "sieve_tray.py"), "cohort",
         "--self-check"], capture_output=True, text=True)
    assert proc2.returncode == 2, proc2.stdout + proc2.stderr
    obj2 = json.loads(proc2.stdout[proc2.stdout.index("{"):])
    assert obj2["error"] == "sample_pack_not_available"


# ---------------------------------------------------------------------------
# CH-T12: the progress callback receives the run's messages.
# ---------------------------------------------------------------------------

def test_ch_t12_progress_messages(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _cohort_tree(inp)
    seen = []
    receipt = _run_cohort(inp, out, progress=seen.append)
    assert receipt["kind"] == "sieve-cohort"
    assert seen and all(isinstance(m, str) for m in seen)
    assert any("Cohort" in m for m in seen)


# ---------------------------------------------------------------------------
# CH-T13: the history discipline - the existing tables stay untouched,
# the cohort_runs allowlist drops every non-allowlisted key, and
# load_cohort_runs returns the allowlist keys newest first.
# ---------------------------------------------------------------------------

def test_ch_t13_allowlist_drops_extra_keys(tmp_path):
    from sieve_tray_storage import Storage
    db = tmp_path / "h.db"
    storage = Storage(str(db))
    storage.record_cohort_run({
        "run_id": "cohort-x", "ts_utc": "2026-01-01T00:00:00+00:00",
        "items": 5, "compared": 4, "not_compared": 1,
        "pairs_flagged": 2, "removed_total": 33,
        "receipt_digest": "sha256:abc",
        "engines": "lens 0.22.0 / order 1.1.0 / referee 1.6.0 / scope 1.5.0",
        # every key below is structurally dropped (request §3.7)
        "path": "/tmp/secret", "body": "submission text",
        "fragment": "matched span text",
    })
    rows = storage.load_cohort_runs()
    assert len(rows) == 1
    row = rows[0]
    allowed = {"run_id", "ts_utc", "items", "compared", "not_compared",
               "pairs_flagged", "removed_total", "receipt_digest",
               "engines"}
    assert set(row.keys()) <= allowed
    assert "id" not in row
    blob = json.dumps(row, ensure_ascii=False)
    assert "/tmp/secret" not in blob and "submission text" not in blob
    assert "matched span text" not in blob


def test_ch_t13_load_newest_first(tmp_path):
    from sieve_tray_storage import Storage
    db = tmp_path / "h.db"
    storage = Storage(str(db))
    storage.record_cohort_run({
        "run_id": "cohort-first", "ts_utc": "2026-01-01T00:00:00+00:00",
        "items": 3, "compared": 2, "not_compared": 1,
        "pairs_flagged": 0, "removed_total": 0,
        "receipt_digest": "sha256:first", "engines": "eng-1"})
    storage.record_cohort_run({
        "run_id": "cohort-second", "ts_utc": "2026-01-02T00:00:00+00:00",
        "items": 3, "compared": 3, "not_compared": 0,
        "pairs_flagged": 1, "removed_total": 9,
        "receipt_digest": "sha256:second", "engines": "eng-2"})
    rows = storage.load_cohort_runs()
    assert [r["receipt_digest"] for r in rows] == \
        ["sha256:second", "sha256:first"]
    assert all(set(r.keys()) <= {"run_id", "ts_utc", "items", "compared",
                                 "not_compared", "pairs_flagged",
                                 "removed_total", "receipt_digest",
                                 "engines"} for r in rows)


def test_ch_t13_existing_tables_intact(tmp_path):
    from sieve_tray_storage import Storage
    db = tmp_path / "h.db"
    Storage(str(db))
    con = sqlite3.connect(str(db))
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"runs", "sanitizations", "settings", "crowd_runs",
            "gate_runs"} <= tables


def test_ch_t13_storage_wired_into_run_cohort(tmp_path):
    # the §3.7 wiring: run_cohort(storage_path=...) records one
    # allowlisted cohort_runs row per run, newest first
    from sieve_tray_storage import Storage
    inp = tmp_path / "in"
    _cohort_tree(inp)
    out = tmp_path / "out"
    db = tmp_path / "h.db"
    receipt = _run_cohort(inp, out, storage_path=db)
    rows = Storage(str(db)).load_cohort_runs()
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"].startswith("cohort-")
    assert row["receipt_digest"] == receipt["digest"]
    assert row["items"] == receipt["summary"]["items"]
    assert row["compared"] == receipt["summary"]["compared"]
    assert row["not_compared"] == receipt["summary"]["not_compared"]
    assert row["pairs_flagged"] == receipt["summary"]["flagged"]
    allowed = {"run_id", "ts_utc", "items", "compared", "not_compared",
               "pairs_flagged", "removed_total", "receipt_digest",
               "engines"}
    assert set(row.keys()) <= allowed
    # a second run appends and loads newest-first; a broken storage
    # path never fails the run itself (the gate rule)
    out2 = tmp_path / "out2"
    receipt2 = _run_cohort(inp, out2, storage_path=db)
    rows = Storage(str(db)).load_cohort_runs()
    assert [r["receipt_digest"] for r in rows] == \
        [receipt2["digest"], receipt["digest"]]
    out3 = tmp_path / "out3"
    receipt3 = _run_cohort(inp, out3,
                           storage_path=tmp_path / "no" / "dir" / "x.db")
    assert receipt3["digest"] == receipt2["digest"]


# ---------------------------------------------------------------------------
# CH-T14: the distribution smoke (request §3.10) - the wheel installs
# into a fresh venv and both self-checks run without the repo tree.
# ---------------------------------------------------------------------------

# the engines and the HTML-lane extras the self-checks need.  They ride
# from the RUNNING environment: the smoke measures the wheel's own
# completeness (the code and the sample pack), not the engines, which
# are external distributions (the 2026-11-10 measured plan).
SMOKE_MODULES = (
    "sieve_lens", "sieve_lens_ext", "sieve_scope", "sieve_referee",
    "tinycss2", "cssselect2", "webencodings", "pypdf",
)


def _stage_smoke_modules(dest: Path) -> None:
    """Copy the engine/extra top-level packages from the running
    environment into a staging folder that rides as PYTHONPATH.  A
    single-module distribution travels as its .py file, a package as
    its folder (the same shape they sit in site-packages)."""
    import shutil as _shutil
    for name in SMOKE_MODULES:
        mod = importlib.import_module(name)
        src = Path(mod.__file__)
        if src.name == "__init__.py":
            _shutil.copytree(src.parent, dest / name,
                             ignore=_shutil.ignore_patterns("__pycache__"))
        else:
            _shutil.copy2(src, dest / src.name)


def test_ch_t14_wheel_smoke(tmp_path):
    import venv as venv_mod
    # the smoke needs the M2 engines (the cohort lane strips the base
    # with the Scope 1.5.0 API and the 1.6.0 Referee lanes); without
    # them the self-checks cannot be exercised - same skip philosophy
    # as the GUI tests' _require_qt
    try:
        import sieve_referee  # noqa: F401
        import sieve_scope
        if not hasattr(sieve_scope, "strip_base_sources"):
            raise ImportError("sieve-scope without strip_base_sources")
    except ImportError:
        pytest.skip("M2 engines (sieve-scope 1.5.0 / sieve-referee 1.6.0) "
                    "unusable in this environment")
    dist = tmp_path / "dist"
    build = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "-w", str(dist), str(REPO_ROOT)],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert build.returncode == 0, build.stdout + build.stderr
    wheels = list(dist.glob("sieve_tray-*.whl"))
    assert len(wheels) == 1
    # venv.create() returns None on 3.12+ (measured 2026-11-10) - the
    # interpreter path is built from the created folder instead
    venv_dir = tmp_path / "venv"
    venv_mod.create(str(venv_dir), with_pip=True)
    py = venv_dir / ("bin/python" if sys.platform != "win32"
                     else "Scripts/python.exe")
    proc = subprocess.run(
        [str(py), "-m", "pip", "install", "--no-deps", str(wheels[0])],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # the engines travel from the running environment (see above) - the
    # staging folder rides as PYTHONPATH, never inside the fresh venv
    staging = tmp_path / "engines"
    staging.mkdir()
    _stage_smoke_modules(staging)
    env = dict(os.environ, PYTHONPATH=str(staging))

    def run_self_check(lane):
        # cwd stays neutral: `python -m` puts the current directory at
        # sys.path[0], and the repo tree must not shadow the wheel
        return subprocess.run(
            [str(py), "-m", "sieve_tray", lane, "--self-check"],
            capture_output=True, text=True, cwd=str(tmp_path), env=env)

    # gate --self-check runs from the wheel
    gate = run_self_check("gate")
    assert gate.returncode == 0, gate.stdout + gate.stderr
    # cohort --self-check runs from the wheel too: the pack travels in
    # the wheel (request §3.10 - the distribution smoke).  The progress
    # lines ride before the JSON, so the object is sliced off the tail
    cohort = run_self_check("cohort")
    assert cohort.returncode == 0, cohort.stdout + cohort.stderr
    obj = json.loads(cohort.stdout[cohort.stdout.index("{"):])
    assert obj["matching"] == obj["expected"]
    assert obj["differences"] == []


# ---------------------------------------------------------------------------
# CH-T15: the Tray entrance (request §3.9) - the GUI exposes the Cohort
# page (the CLI entrance is covered by the runs above).
# ---------------------------------------------------------------------------

def test_ch_t15_gui_cohort_page(tmp_path):
    from test_v1_4_scan import _require_qt
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage
    win = gui.MainWindow(storage=Storage(tmp_path / "history.db"))
    try:
        page = getattr(win, "cohort_page", None)
        assert page is not None, "no Cohort page in the main window"
    finally:
        win.close()


# ---------------------------------------------------------------------------
# CH-T16: the molds - the shapes that were true before Cohort and stay
# true (green from the start, by design).
# ---------------------------------------------------------------------------

def test_ch_t16_mold_gate_receipt_v1(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    (inp / "a.txt").write_text("alpha\n", encoding="utf-8")
    from sieve_tray import run_gate
    receipt = run_gate(inp, out)
    assert receipt["kind"] == "sieve-gate"
    assert receipt["receipt_version"] == 1
    assert set(receipt.keys()) == {"receipt_version", "kind", "tool",
                                   "engines", "settings", "items",
                                   "summary", "digest"}


def test_ch_t16_mold_verify_vocabulary():
    from sieve_tray import VERIFY_NOT_VERIFIABLE_REASONS, VERIFY_REASONS
    assert VERIFY_NOT_VERIFIABLE_REASONS == frozenset({
        "receipt_unreadable", "receipt_version_unsupported",
        "receipt_digest_mismatch", "settings_unavailable",
        "handoff_incomplete"})
    assert VERIFY_REASONS == frozenset({
        "input_changed", "input_missing", "item_added", "output_changed",
        "output_missing", "replay_differs", "engine_version_differs"})


def test_ch_t16_mold_settings_table(tmp_path):
    from sieve_tray_storage import Storage, DEFAULT_SETTINGS
    db = tmp_path / "h.db"
    storage = Storage(str(db))
    assert storage.get_setting("export_dir") == DEFAULT_SETTINGS[
        "export_dir"]
    storage.set_setting("window_geometry", "880x560")
    assert storage.get_setting("window_geometry") == "880x560"


def test_ch_t16_mold_crowd_allowlist(tmp_path):
    from sieve_tray_storage import Storage
    db = tmp_path / "h.db"
    storage = Storage(str(db))
    storage.save_crowd_run({
        "mode": "inspect", "ts_utc": "2026-01-01T00:00:00+00:00",
        "rows": 3, "payload": {"kept": 1},
        # structurally dropped: not in the crowd allowlist
        "secret_path": "/tmp/x", "body": "cell text"})
    rows = storage.load_crowd_runs()
    assert len(rows) == 1
    blob = json.dumps(rows[0], ensure_ascii=False)
    assert "/tmp/x" not in blob and "cell text" not in blob


# ---------------------------------------------------------------------------
# CH-T17: the dependency floors (request §3.13) - raised to the
# published referee 1.6.0 / scope 1.5.0 after both are published
# (the hand-over order in the design ruling; the intentional red
# ended with the floors commit - PyPI measured 2026-11-10).
# ---------------------------------------------------------------------------

def test_ch_t17_dependency_floors():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "sieve-referee>=1.6.0" in text
    assert "sieve-scope>=1.5.0" in text
    assert "sieve-lens>=0.22.0" in text


# ---------------------------------------------------------------------------
# CH-T18: the README structure - the en/ja headings align, no section
# enumerates limitations, and the Cohort section exists in both.
# ---------------------------------------------------------------------------

def test_ch_t18_readme_headings_align():
    en = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    ja = (REPO_ROOT / "README.ja.md").read_text(encoding="utf-8")
    en_h = [ln for ln in en.splitlines() if ln.startswith("## ")]
    ja_h = [ln for ln in ja.splitlines() if ln.startswith("## ")]
    assert len(en_h) == len(ja_h)


def test_ch_t18_readme_no_limitations():
    # the Cohort section (request §3.9) leads with what it does and
    # never enumerates limitations; while the section is absent the
    # rule holds vacuously
    for name in ("README.md", "README.ja.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        lines = text.splitlines()
        start = None
        for i, ln in enumerate(lines):
            if ln.startswith("## ") and "Cohort" in ln:
                start = i
                break
        if start is None:
            continue
        section = []
        for ln in lines[start + 1:]:
            if ln.startswith("## "):
                break
            section.append(ln)
        body = "\n".join(section).lower()
        assert "限界" not in body and "limitation" not in body, name


def test_ch_t18_readme_cohort_section():
    en = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    ja = (REPO_ROOT / "README.ja.md").read_text(encoding="utf-8")
    assert "## 👥 Cohort" in en
    assert "## 👥 Cohort" in ja


# ---------------------------------------------------------------------------
# CH-T19: the spans unit line (request §3.6 + the 2026-11-09 ruling ②):
# the README states the unit in one line - documents count characters,
# code counts tokens.
# ---------------------------------------------------------------------------

def test_ch_t19_readme_spans_unit():
    en = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    ja = (REPO_ROOT / "README.ja.md").read_text(encoding="utf-8")
    assert "characters" in en and "tokens" in en
    assert "文字" in ja and "トークン" in ja


# ---------------------------------------------------------------------------
# CH-T20: the release workflow runs the two self-checks on each OS's
# frozen artifact (request §3.10, the 2026-11-11 ruling).  The M2
# acceptance found the distribution half of §3.10 unfulfilled: the
# release.yml carried only samples/gate in its --add-data lists and no
# self-check step at all, so a tagged bundle would ship without the
# cohort pack and its cohort --self-check would return exit 2 (the
# sample_pack_not_available error dict).  Static pins:
#   - every build command bundles BOTH packs (Windows ';', macOS ':');
#   - the self-check steps follow the build directly on the frozen
#     artifact and fail the release on any exit code but 0;
#   - workflow_dispatch joins the tag push for the no-publish trial
#     run, and every Release attach sits behind the push guard;
#   - the frozen GUI entry routes the two self-check shapes to the
#     headless CLI before QApplication, so a self-check run never
#     opens a window (measured on Linux: exit 0 without a display;
#     the macOS/Windows legs are measured by the workflow_dispatch
#     trial run on the runners).
# ---------------------------------------------------------------------------

def test_ch_t20_release_workflow_frozen_self_check_static():
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8")
    # every build command bundles both packs
    assert text.count('--add-data "samples/gate') == 2
    assert text.count('--add-data "samples/cohort') == 2
    # the self-check steps run the frozen artifact on every OS image
    assert "gate --self-check" in text and "cohort --self-check" in text
    assert "dist\\SieveTray.exe" in text
    assert "dist/SieveTray.app/Contents/MacOS/SieveTray" in text
    # the release fails when the exit code is not 0 (1 = a difference,
    # 2 = the self-check could not run)
    assert "ExitCode -ne 0" in text
    # the no-publish trial: workflow_dispatch joins the tag push and
    # every release attach sits behind the push guard (the attach step
    # in the build job, the release-extras job, the SHA256SUMS attach)
    assert "workflow_dispatch:" in text
    assert text.count("github.event_name == 'push'") == 3
    # the frozen app runs the self-checks headlessly: the GUI entry
    # dispatches to the CLI before QApplication opens any window
    gui = (REPO_ROOT / "sieve_tray_gui.py").read_text(encoding="utf-8")
    assert '"--self-check" in sys.argv[2:]' in gui
    assert "from sieve_tray import _gate_main" in gui
    assert gui.index("--self-check") < gui.index("QApplication(sys.argv)")
