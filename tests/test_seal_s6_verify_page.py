"""Seal 2.2 / S6 - verify.html (request 3.5, SL-T12/SL-T13).

`--verify-page` on manifest / pack writes a self-contained
handoff/verify.html BEFORE the receipt (the receipt stays the last
write) and records the page's sha256 in the receipt (the optional
verify_page section).  The page carries no external reference (no
http, no src/href, no import, no fetch), embeds the file list as
application/json, and hashes the received folder with a pure-JS
SHA-256 core (script id seal-sha256-core, free of page words) so the
behavior is one fixed implementation even where the standard crypto
API exists.  The receiver's comparison is the closed 4 statuses
same / changed / missing / extra, shown on screen only; the check
code is NOT verified in the page - one line says so, in ja and en.

SL-T12 runs the core against the 4 known values (empty, abc, the
64-byte boundary, one million a) with node; SL-T13 runs the
classification through node with the smallest possible stub (a
FileReader that drains a node Blob) over real bytes, including a
file larger than the read chunk so the Blob.slice path is exercised.
node が無ければ skip する（skip の理由は報告に書く）。
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess

import pytest

from pathlib import Path

NODE = shutil.which("node")


def _make_src(root: Path) -> Path:
    d = root / "src"
    (d / "sub").mkdir(parents=True)
    (d / "a.txt").write_bytes(b"alpha\n")
    (d / "sub" / "data.txt").write_bytes(b"data\n")
    (d / "日本語.txt").write_bytes(b"nihongo\n")
    return d


def _run_manifest(folder, out, **kw):
    from sieve_tray import run_manifest
    return run_manifest(folder, out, **kw)


def _run_pack(folder, zip_path, **kw):
    from sieve_tray import run_pack
    return run_pack(folder, zip_path, **kw)


def _page_bytes(out: Path) -> bytes:
    return (out / "handoff" / "verify.html").read_bytes()


def _script(html: str, sid: str) -> str:
    m = re.search(r'<script id="' + sid + r'"[^>]*>(.*?)</script>',
                  html, re.S)
    assert m, "no script block: %s" % sid
    return m.group(1)


def _data(html: str) -> dict:
    m = re.search(r'<script id="seal-data" type="application/json">'
                  r'(.*?)</script>', html, re.S)
    assert m, "no embedded data block"
    return json.loads(m.group(1))


def _node(script: Path, *args) -> str:
    r = subprocess.run([NODE, str(script)] + [str(a) for a in args],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


# ---------------------------------------------------------------------------
# SL-T12: the self-contained page and its receipt record

def test_t12_manifest_writes_the_page_and_records_its_sha(tmp_path):
    src = _make_src(tmp_path)
    out = tmp_path / "out"
    receipt = _run_manifest(src, out, verify_page=True)
    raw = _page_bytes(out)
    assert raw.decode("utf-8").startswith("<!DOCTYPE html>")
    expect = "sha256:" + hashlib.sha256(raw).hexdigest()
    assert receipt["verify_page"]["name"] == "verify.html"
    assert receipt["verify_page"]["sha256"] == expect
    # the digest covers the section (recomputed over the written body)
    body = {k: v for k, v in receipt.items() if k != "digest"}
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    assert receipt["digest"] == "sha256:" + hashlib.sha256(blob).hexdigest()


def test_t12_the_page_is_written_before_the_receipt(tmp_path, monkeypatch):
    import sieve_tray
    src = _make_src(tmp_path)
    out = tmp_path / "out"
    real = sieve_tray._gate_write_atomic

    def failing(path, data):
        if path.name.endswith("manifest-receipt.json"):
            raise OSError("the receipt write fails (order probe)")
        return real(path, data)

    monkeypatch.setattr(sieve_tray, "_gate_write_atomic", failing)
    with pytest.raises(OSError):
        _run_manifest(src, out, verify_page=True)
    # the page is already on disk: it is written BEFORE the receipt
    assert (out / "handoff" / "verify.html").exists()


def test_t12_without_the_flag_nothing_changes(tmp_path):
    src = _make_src(tmp_path)
    out = tmp_path / "out"
    receipt = _run_manifest(src, out)
    assert "verify_page" not in receipt
    assert not (out / "handoff" / "verify.html").exists()


def test_t12_no_external_reference(tmp_path):
    src = _make_src(tmp_path)
    out = tmp_path / "out"
    _run_manifest(src, out, verify_page=True)
    html = _page_bytes(out).decode("utf-8")
    for probe in ("http://", "https://", "<script src", "<link", "href=",
                  "src=", "@import", "import ", "fetch(", "XMLHttpRequest",
                  "WebSocket", "sendBeacon", "url("):
        assert probe not in html, probe
    # the data rides as application/json; the code rides in two blocks
    assert 'id="seal-data" type="application/json"' in html
    _script(html, "seal-sha256-core")
    _script(html, "seal-app")


def test_t12_sha256_core_matches_the_known_values(tmp_path):
    if NODE is None:
        pytest.skip("node is not available on this machine (SL-T12: "
                    "the skip reason is reported)")
    src = _make_src(tmp_path)
    out = tmp_path / "out"
    _run_manifest(src, out, verify_page=True)
    html = _page_bytes(out).decode("utf-8")
    core = _script(html, "seal-sha256-core")
    # the core block is free of page words: it must run anywhere
    for word in ("document", "window", "FileReader", "Blob", "navigator"):
        assert word not in core, word
    vectors = []
    for raw in (b"", b"abc", b"a" * 64, b"a" * 1000000):
        vectors.append({"b64": base64.b64encode(raw).decode("ascii"),
                        "hex": hashlib.sha256(raw).hexdigest()})
    vec_path = tmp_path / "vectors.json"
    vec_path.write_text(json.dumps(vectors), encoding="utf-8")
    harness = tmp_path / "harness_core.js"
    harness.write_text(
        'const fs = require("fs");\n'
        'const html = fs.readFileSync(process.argv[2], "utf8");\n'
        'const m = html.match(/<script id="seal-sha256-core"[^>]*>'
        '([\\s\\S]*?)<\\/script>/);\n'
        'if (!m) { console.error("no core block"); process.exit(2); }\n'
        'eval(m[1]);\n'
        'const vecs = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));\n'
        'let bad = 0;\n'
        'for (const v of vecs) {\n'
        '  const raw = Buffer.from(v.b64, "base64");\n'
        '  const h = new Sha256();\n'
        '  h.update(new Uint8Array(raw));\n'
        '  if (h.hex() === v.hex) { console.log("ok"); }\n'
        '  else { console.log("FAIL " + v.hex + " got " + h.hex()); bad++; }\n'
        '}\n'
        '// chunked: the biggest vector through odd-sized updates\n'
        '{\n'
        '  const v = vecs[vecs.length - 1];\n'
        '  const raw = Buffer.from(v.b64, "base64");\n'
        '  const h = new Sha256();\n'
        '  for (let off = 0; off < raw.length; off += 65537) {\n'
        '    h.update(new Uint8Array(raw.subarray(off,\n'
        '        Math.min(off + 65537, raw.length))));\n'
        '  }\n'
        '  if (h.hex() === v.hex) { console.log("ok"); }\n'
        '  else { console.log("FAIL chunked"); bad++; }\n'
        '}\n'
        'process.exit(bad ? 1 : 0);\n',
        encoding="utf-8")
    page = out / "handoff" / "verify.html"
    out_line = _node(harness, page, vec_path)
    assert out_line.count("ok") == 5
    assert "FAIL" not in out_line


def test_t12_the_page_embeds_the_file_list(tmp_path):
    src = _make_src(tmp_path)
    out = tmp_path / "out"
    receipt = _run_manifest(src, out, verify_page=True)
    data = _data(_page_bytes(out).decode("utf-8"))
    assert data["entries"] == [
        {"path": it["path"], "bytes": it["bytes"], "sha256": it["sha256"]}
        for it in receipt["items"]]
    assert data["overall_sha256"] == receipt["summary"]["overall_sha256"]


def test_t12_pack_writes_the_page_next_to_the_zip(tmp_path):
    src = _make_src(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    zp = out / "pack.zip"
    receipt = _run_pack(src, zp, verify_page=True)
    page = (zp.parent / "handoff" / "verify.html").read_bytes()
    expect = "sha256:" + hashlib.sha256(page).hexdigest()
    assert receipt["verify_page"]["name"] == "verify.html"
    assert receipt["verify_page"]["sha256"] == expect
    data = _data(page.decode("utf-8"))
    assert data["overall_sha256"] == receipt["summary"]["overall_sha256"]
    assert {e["path"] for e in data["entries"]} == {
        "a.txt", "sub/data.txt", "日本語.txt"}


def test_t12_a_diff_refuses_the_page(tmp_path):
    a = _make_src(tmp_path)
    b = _make_src(tmp_path / "other")
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        _run_manifest(a, out, against=b, verify_page=True)


def test_t12_a_name_that_is_not_utf8_refuses_the_page(tmp_path):
    d = tmp_path / "src"
    d.mkdir()
    (d / "a.txt").write_bytes(b"x")
    with open(os.path.join(os.fsencode(str(d)), b"bad\xff.txt"),
              "wb") as fh:
        fh.write(b"y")
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        _run_manifest(d, out, verify_page=True)


# ---------------------------------------------------------------------------
# SL-T13: the classification, driven through node with real bytes

def test_t13_the_page_carries_both_languages(tmp_path):
    src = _make_src(tmp_path)
    out = tmp_path / "out"
    _run_manifest(src, out, verify_page=True)
    html = _page_bytes(out).decode("utf-8")
    assert "照合コードの確認は、Sieve Tray の verify で行います。" in html
    assert "Check codes are verified with Sieve Tray's verify." in html


def test_t13_classification_in_node(tmp_path):
    if NODE is None:
        pytest.skip("node is not available on this machine (SL-T13: "
                    "the skip reason is reported)")
    src = tmp_path / "src"
    src.mkdir()
    (src / "keep.txt").write_bytes(b"keep\n")
    (src / "change.txt").write_bytes(b"old\n")
    (src / "gone.txt").write_bytes(b"gone\n")
    # 1,572,864 bytes: bigger than the 1 MiB read chunk, so the
    # Blob.slice loop really runs more than once
    (src / "big.bin").write_bytes(bytes(range(256)) * 6144)
    out = tmp_path / "out"
    receipt = _run_manifest(src, out, verify_page=True)
    # the folder the receiver picked: keep is intact, change was
    # touched, gone is absent, extra was added, big is intact
    recv = tmp_path / "recv" / "got"
    recv.mkdir(parents=True)
    (recv / "keep.txt").write_bytes(b"keep\n")
    (recv / "change.txt").write_bytes(b"NEW\n")
    (recv / "big.bin").write_bytes(bytes(range(256)) * 6144)
    (recv / "extra.txt").write_bytes(b"extra\n")
    harness = tmp_path / "harness_classify.js"
    harness.write_text(
        'const fs = require("fs");\n'
        'const path = require("path");\n'
        'const html = fs.readFileSync(process.argv[2], "utf8");\n'
        'function block(id) {\n'
        '  const m = html.match(new RegExp("<script id=\\"" + id + "\\"'
        '[^>]*>([\\\\s\\\\S]*?)<\\\\/script>"));\n'
        '  if (!m) { console.error("no " + id); process.exit(2); }\n'
        '  return m[1];\n'
        '}\n'
        'const dm = html.match(/<script id="seal-data" '
        'type="application\\/json">([\\s\\S]*?)<\\/script>/);\n'
        'const data = JSON.parse(dm[1]);\n'
        'class FileReader {\n'
        '  readAsArrayBuffer(blob) {\n'
        '    blob.arrayBuffer().then(\n'
        '      (b) => { this.onload({ target: { result: b } }); },\n'
        '      (e) => { this.onerror(e); });\n'
        '  }\n'
        '}\n'
        'globalThis.FileReader = FileReader;\n'
        'eval(block("seal-sha256-core"));\n'
        'eval(block("seal-app"));\n'
        'const root = process.argv[3];\n'
        'const files = [];\n'
        '(function walk(dir, rel) {\n'
        '  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {\n'
        '    const rp = rel ? rel + "/" + e.name : e.name;\n'
        '    if (e.isDirectory()) { walk(path.join(dir, e.name), rp); '
        'continue; }\n'
        '    const buf = fs.readFileSync(path.join(dir, e.name));\n'
        '    files.push({\n'
        '      name: e.name,\n'
        '      webkitRelativePath: path.basename(root) + "/" + rp,\n'
        '      size: buf.length,\n'
        '      slice: (a, b) => new Blob([buf.subarray(a, b)])\n'
        '    });\n'
        '  }\n'
        '})(root, "");\n'
        'SEAL_VERIFY.computeResults(data, files).then((res) => {\n'
        '  process.stdout.write(JSON.stringify(res));\n'
        '}).catch((e) => { console.error(String(e)); process.exit(1); });\n',
        encoding="utf-8")
    page = out / "handoff" / "verify.html"
    res = json.loads(_node(harness, page, recv))
    assert res["counts"] == {"same": 2, "changed": 1, "missing": 1,
                             "extra": 1}
    by = {r["path"]: r["status"] for r in res["results"]}
    assert by == {"keep.txt": "same", "change.txt": "changed",
                  "gone.txt": "missing", "extra.txt": "extra",
                  "big.bin": "same"}
    # the receiver-side hash is the embedded one for the intact file
    entry = next(e for e in _data(_page_bytes(out).decode("utf-8"))
                 ["entries"] if e["path"] == "keep.txt")
    row = next(r for r in res["results"] if r["path"] == "keep.txt")
    assert row["sha256"] == entry["sha256"]
    assert receipt["summary"]["overall_sha256"] == res["overall"]
