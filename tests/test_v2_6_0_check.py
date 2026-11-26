"""Tray 2.6.0 - the check command (CK-T01..T06, CK-T13).

``sieve-tray check PATH...`` observes files and folders the way the
Gate does (the same engine, the same closed vocabularies) and reports
hidden text and invisible characters - nothing is written out.  The
exit code is 0 (nothing found) / 1 (something found) / 2 (the check
cannot run); files the engine cannot observe are reported with a
closed-set reason word and, by default, do not move the exit code.

Red-first: these tests enter before the implementation and fail on the
tree without the subcommand (argparse refuses the unknown command, so
every CLI test goes red with exit code 2).  The measured expectations:
the six-kind PDF carries tr3/tr7/tiny_font/off_page/off_layer/
white_text on page 1, a display:none HTML section hides its text, and
U+200B / U+2060 are the invisible strip kinds.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from px_pdf_builders import build_six_kinds_pdf, need_pypdf

REPO_ROOT = Path(__file__).resolve().parent.parent
MARK = "LEAKMARK"


def _run_cli(args, cwd):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "sieve_tray.py"), "check"]
        + [str(a) for a in args],
        capture_output=True, cwd=str(cwd), timeout=300)


def _write_adversarial_html(path):
    """Hidden section, metadata and a title that all carry the marker
    the output must never echo."""
    path.write_text(
        "<html><head><title>%s-title</title>"
        '<meta name="author" content="%s-meta"></head>'
        '<body><p style="display:none">%s-hidden</p>'
        "<p>plain visible line</p></body></html>"
        % (MARK, MARK, MARK), encoding="utf-8")


# ---------------------------------------------------------------------------
# CK-T01: hidden text and the exit codes

def test_ck_t01_hidden_text_found_exit_codes(tmp_path):
    """CK-T01: a folder with hidden text exits 1 and the json names
    the kind words with their pages; a clean folder exits 0."""
    inp = tmp_path / "in"
    inp.mkdir()
    need_pypdf()
    build_six_kinds_pdf(inp / "six.pdf")
    (inp / "plain.txt").write_text("plain line\n", encoding="utf-8")
    proc = _run_cli(["in", "--format", "json"], cwd=tmp_path)
    assert proc.returncode == 1, proc.stdout[-500:] + proc.stderr[-500:]
    data = json.loads(proc.stdout.decode("utf-8"))
    assert data["check_version"] == 1
    assert data["kind"] == "sieve-check"
    assert data["tool"] == {"name": "sieve-tray",
                            "version": __import__("sieve_tray").__version__}
    by = {item["path"]: item for item in data["items"]}
    six = by[str(Path("in") / "six.pdf")]
    assert six["status"] == "found"
    words = {k["word"] for k in six["hidden_text"]["kinds"]}
    assert {"tr3", "tr7", "tiny_font", "off_page", "off_layer",
            "white_text"} <= words
    tr3 = next(k for k in six["hidden_text"]["kinds"]
               if k["word"] == "tr3")
    assert tr3["count"] == 1
    assert tr3["pages"] == [1]
    assert by[str(Path("in") / "plain.txt")]["status"] == "clean"
    assert data["summary"]["found"] == 1

    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "a.txt").write_text("hi\n", encoding="utf-8")
    proc2 = _run_cli(["clean", "--format", "json"], cwd=tmp_path)
    assert proc2.returncode == 0
    data2 = json.loads(proc2.stdout.decode("utf-8"))
    assert all(i["status"] == "clean" for i in data2["items"])


# ---------------------------------------------------------------------------
# CK-T02: invisible characters and --only-hidden

def test_ck_t02_invisible_characters_and_only_hidden(tmp_path):
    """CK-T02: the invisible strip kinds are counted per word; with
    --only-hidden the invisible characters are ignored (a file with
    only invisible characters turns clean)."""
    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "zw.txt").write_text("a\u200bb\u2060c\n", encoding="utf-8")
    proc = _run_cli(["in", "--format", "json"], cwd=tmp_path)
    assert proc.returncode == 1
    data = json.loads(proc.stdout.decode("utf-8"))
    item = data["items"][0]
    counts = {k["word"]: k["count"] for k in item["invisible"]["kinds"]}
    assert counts == {"zero_width_space": 1, "word_joiner": 1}
    assert item["hidden_text"]["count"] == 0
    proc2 = _run_cli(["in", "--format", "json", "--only-hidden"],
                     cwd=tmp_path)
    assert proc2.returncode == 0
    data2 = json.loads(proc2.stdout.decode("utf-8"))
    assert data2["items"][0]["invisible"]["kinds"] == []


# ---------------------------------------------------------------------------
# CK-T03: no free-form strings, no absolute paths

def test_ck_t03_no_free_strings_or_absolute_paths(tmp_path):
    """CK-T03: layer names, hidden sentences, metadata values and
    titles never reach the output - text, json and github alike, raw
    bytes; the paths echo the given relative form only."""
    inp = tmp_path / "in"
    inp.mkdir()
    need_pypdf()
    build_six_kinds_pdf(inp / "six.pdf")
    _write_adversarial_html(inp / "adv.html")
    absolute = str(tmp_path).encode("utf-8")
    for fmt in ("text", "json", "github"):
        proc = _run_cli(["in", "--format", fmt], cwd=tmp_path)
        assert proc.returncode == 1
        raw = proc.stdout + proc.stderr
        for needle in (MARK.encode("utf-8"), b"SIEVE-LAYER-Z9",
                       absolute):
            assert needle not in raw, (fmt, needle)
    proc = _run_cli(["in", "--format", "github"], cwd=tmp_path)
    assert b"::error file=in/six.pdf" in proc.stdout


# ---------------------------------------------------------------------------
# CK-T04: exit code 2 and the unobservable files

def test_ck_t04_exit_two_and_unobservable(tmp_path):
    """CK-T04: a missing target exits 2; broken and encrypted files
    are reported with their closed reason words and leave the exit
    code at 0; --strict turns any unobservable file into 1."""
    inp = tmp_path / "in"
    inp.mkdir()
    proc = _run_cli(["missing-dir"], cwd=tmp_path)
    assert proc.returncode == 2

    need_pypdf()
    (inp / "broken.pdf").write_bytes(b"%PDF-1.4 this is not a pdf\n")
    build_six_kinds_pdf(inp / "enc-src.pdf")
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(inp / "enc-src.pdf")
    writer = PdfWriter()
    writer.append(reader)
    writer.encrypt("secret")
    with open(inp / "encrypted.pdf", "wb") as fh:
        writer.write(fh)
    proc = _run_cli(["in", "--format", "json"], cwd=tmp_path)
    assert proc.returncode == 1  # the six-kind file rides along
    data = json.loads(proc.stdout.decode("utf-8"))
    by = {item["path"]: item for item in data["items"]}
    assert by[str(Path("in") / "broken.pdf")]["status"] == "unobservable"
    assert by[str(Path("in") / "broken.pdf")]["reason"] == "parse_failed"
    assert by[str(Path("in") / "encrypted.pdf")]["status"] == "unobservable"
    assert by[str(Path("in") / "encrypted.pdf")]["reason"] == "refused"
    assert data["summary"]["unobservable"] == 2

    proc2 = _run_cli(["in", "--format", "json", "--strict"], cwd=tmp_path)
    assert proc2.returncode == 1


# ---------------------------------------------------------------------------
# CK-T05: --exclude, determinism, writes nothing

def test_ck_t05_exclude_determinism_writes_nothing(tmp_path):
    """CK-T05: excluded patterns leave the items; two runs are
    byte-identical; the run writes nothing anywhere."""
    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "a.txt").write_text("one\n", encoding="utf-8")
    (inp / "b.log").write_text("skip me\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in sorted(inp.rglob("*"))}
    proc1 = _run_cli(["in", "--format", "json", "--exclude", "*.log"],
                     cwd=tmp_path)
    proc2 = _run_cli(["in", "--format", "json", "--exclude", "*.log"],
                     cwd=tmp_path)
    assert proc1.returncode == proc2.returncode == 0
    assert proc1.stdout == proc2.stdout
    data = json.loads(proc1.stdout.decode("utf-8"))
    assert [i["path"] for i in data["items"]] == [str(Path("in") / "a.txt")]
    assert data["items"][0]["status"] == "clean"
    after = {p: p.read_bytes() for p in sorted(inp.rglob("*"))}
    assert before == after
    assert sorted(p.name for p in tmp_path.iterdir()) == ["in"]


# ---------------------------------------------------------------------------
# CK-T06: check_paths returns the CLI json shape

def test_ck_t06_check_paths_matches_cli_json(tmp_path):
    """CK-T06: the public function returns exactly the --format json
    shape (the contract Sieve-MCP builds on)."""
    inp = tmp_path / "in"
    inp.mkdir()
    need_pypdf()
    build_six_kinds_pdf(inp / "six.pdf")
    proc = _run_cli(["in", "--format", "json"], cwd=tmp_path)
    assert proc.returncode == 1
    from sieve_tray import check_paths
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = check_paths(["in"])
    finally:
        os.chdir(cwd)
    assert json.loads(proc.stdout.decode("utf-8")) == json.loads(
        json.dumps(result, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")) + "\n")


# ---------------------------------------------------------------------------
# CK-T13: the default exclusions

def test_ck_t13_default_exclusions(tmp_path):
    """CK-T13: .obsidian/ and .trash/ drop out of folder targets (the
    count lands in excluded_dirs, no paths); a direct file target is
    still observed; --include-hidden-dirs keeps them; other dot
    folders are not touched; the Gate folder ingest prunes the same
    two names."""
    inp = tmp_path / "in"
    (inp / ".obsidian").mkdir(parents=True)
    (inp / ".trash").mkdir()
    (inp / ".git").mkdir()
    (inp / ".obsidian" / "note.md").write_text("vault note\n",
                                               encoding="utf-8")
    (inp / ".trash" / "old.md").write_text("deleted note\n",
                                           encoding="utf-8")
    (inp / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (inp / "keep.txt").write_text("keep\n", encoding="utf-8")

    proc = _run_cli(["in", "--format", "json"], cwd=tmp_path)
    assert proc.returncode == 0
    data = json.loads(proc.stdout.decode("utf-8"))
    assert data["excluded_dirs"] == 2
    paths = [i["path"] for i in data["items"]]
    assert str(Path("in") / "keep.txt") in paths
    assert not any(".obsidian" in p or ".trash" in p for p in paths)

    direct = _run_cli([inp / ".obsidian" / "note.md", "--format", "json"],
                      cwd=tmp_path)
    assert direct.returncode == 0
    ddata = json.loads(direct.stdout.decode("utf-8"))
    assert ddata["items"][0]["path"] == str(inp / ".obsidian" / "note.md")
    assert ddata["items"][0]["status"] == "clean"

    wide = _run_cli(["in", "--format", "json", "--include-hidden-dirs"],
                    cwd=tmp_path)
    assert wide.returncode == 0
    wdata = json.loads(wide.stdout.decode("utf-8"))
    assert wdata["excluded_dirs"] == 0
    wpaths = [i["path"] for i in wdata["items"]]
    assert str(Path("in") / ".obsidian" / "note.md") in wpaths
    assert str(Path("in") / ".trash" / "old.md") in wpaths

    from sieve_tray import run_gate
    out = tmp_path / "gate-out"
    receipt = run_gate(inp, out)
    gpaths = [str(i.get("path", "")) for i in receipt["items"]]
    assert not any(".obsidian" in p or ".trash" in p for p in gpaths)
    assert any("keep.txt" in p for p in gpaths)

    # the exclusion is Gate-only: the Cohort lane rides the same walk
    # and keeps seeing every file (the 2.5.1 behavior is unchanged)
    from sieve_tray import run_cohort
    out2 = tmp_path / "cohort-out"
    cohort_receipt = run_cohort(inp, out2)
    cpaths = [str(i.get("path", "")) for i in cohort_receipt["items"]]
    assert any(".obsidian" in p and p.endswith("note.md")
               for p in cpaths), \
        "Cohort lost a vault folder file (the exclusion must be Gate-only)"
    assert any(".trash" in p and p.endswith("old.md") for p in cpaths)
