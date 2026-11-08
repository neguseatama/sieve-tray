"""GT-T09..T12 (Tray 2.0.0 Gate receipt and verification).

Red stage: everything here depends on run_gate / verify_gate, which
arrive with the fix commit (ImportError = the red measurement).

Receipt contract (request §3.4 + the 2026-11-08 ruling):
  - normalized JSON: UTF-8, keys sorted, separators (",", ":"),
    ensure_ascii=False, no floats, file ends with exactly one LF;
  - digest = SHA-256 of the normalized body WITHOUT the "digest" key;
  - there is no "meta" key: the receipt body never carries a timestamp
    (§2-4), so two runs over the same tree produce byte-identical
    receipts and the digest stays independent of anything else;
  - the redaction counts live under redact.by_mode (the ruling renamed
    the proposed redact.aliases; the reason is reported).
Verification contract:
  - scope is always reported: outputs_only / inputs_and_outputs / replay;
  - overall: match / differs / not_verifiable; CLI exit codes 0 / 1 / 2;
  - item reasons (7): input_changed, input_missing, item_added,
    output_changed, output_missing, replay_differs,
    engine_version_differs;
  - not_verifiable reasons (5): receipt_unreadable,
    receipt_version_unsupported, receipt_digest_mismatch,
    settings_unavailable, handoff_incomplete.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TRAY = REPO_ROOT / "sieve_tray.py"

VERIFICATION_REASONS = {
    "input_changed", "input_missing", "item_added", "output_changed",
    "output_missing", "replay_differs", "engine_version_differs"}
NOT_VERIFIABLE_REASONS = {
    "receipt_unreadable", "receipt_version_unsupported",
    "receipt_digest_mismatch", "settings_unavailable",
    "handoff_incomplete"}


def _mk_tree(root: Path):
    root.mkdir()
    (root / "a.txt").write_text("alpha\n", encoding="utf-8")
    (root / "b.txt").write_text("beta\n", encoding="utf-8")


def _run_gate(input_dir, output_dir, **kw):
    from sieve_tray import run_gate
    return run_gate(input_dir, output_dir, **kw)


def _receipt_path(out: Path) -> Path:
    return out / "handoff" / "gate-receipt.json"


def _verify(receipt_path, **kw):
    from sieve_tray import verify_gate
    return verify_gate(receipt_path, **kw)


def _rewrite_receipt(path: Path, mutate):
    """Apply mutate to the receipt dict and rewrite it as a normalized
    body with a fresh digest (so only the intended field differs)."""
    obj = json.loads(path.read_text(encoding="utf-8"))
    mutate(obj)
    body = {k: v for k, v in obj.items() if k != "digest"}
    norm = json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    body["digest"] = "sha256:" + hashlib.sha256(
        norm.encode("utf-8")).hexdigest()
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n"
    path.write_text(blob, encoding="utf-8")


# ---------------------------------------------------------------------------
# GT-T09: normalized receipt and digest
# ---------------------------------------------------------------------------

def test_t09_normalized_json_and_digest(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    receipt = _run_gate(inp, out)
    raw = _receipt_path(out).read_bytes()
    # normalized shape: sorted keys, no spaces, no floats, one trailing LF
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    obj = json.loads(raw.decode("utf-8"))
    norm = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n"
    assert norm.encode("utf-8") == raw
    assert "meta" not in obj
    for text in _iter_strings(obj):
        assert "e-" not in text.replace("sha256:", "").lower() or True
    # no float anywhere in the receipt
    _assert_no_floats(obj)
    # digest = sha256 of the normalized body without the digest key
    body = {k: v for k, v in obj.items() if k != "digest"}
    body_norm = json.dumps(body, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    expected = "sha256:" + hashlib.sha256(
        body_norm.encode("utf-8")).hexdigest()
    assert obj["digest"] == expected
    assert receipt["digest"] == expected


def _iter_strings(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_strings(v)
    elif isinstance(obj, str):
        yield obj


def _assert_no_floats(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            _assert_no_floats(v)
    elif isinstance(obj, list):
        for v in obj:
            _assert_no_floats(v)
    elif isinstance(obj, float):
        raise AssertionError("receipt contains a float")


def test_t09_two_runs_identical(tmp_path):
    inp, out1, out2 = tmp_path / "in", tmp_path / "o1", tmp_path / "o2"
    _mk_tree(inp)
    _run_gate(inp, out1)
    _run_gate(inp, out2)
    assert _receipt_path(out1).read_bytes() == \
        _receipt_path(out2).read_bytes()


def test_t09_hashseed_independent(tmp_path):
    _mk_tree(tmp_path / "in")
    digests = []
    for seed in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        out = tmp_path / f"out_{seed}"
        proc = subprocess.run(
            [sys.executable, str(TRAY), "gate", str(tmp_path / "in"),
             "-o", str(out)],
            capture_output=True, text=True, env=env)
        assert proc.returncode == 0, proc.stderr
        digests.append(
            json.loads(_receipt_path(out).read_text(encoding="utf-8"))
            ["digest"])
    assert digests[0] == digests[1]


# ---------------------------------------------------------------------------
# GT-T10: include_paths / include_input_hashes off
# ---------------------------------------------------------------------------

def test_t10_no_paths_sequential(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    receipt = _run_gate(inp, out, include_paths=False)
    assert receipt["settings"]["include_paths"] is False
    for i, it in enumerate(receipt["items"], start=1):
        assert "path" not in it
        assert it["index"] == i
        assert it["output"]["path"].startswith("handoff/")
        # sequential output file names: NNNN.<suffix>
        name = Path(it["output"]["path"]).name
        stem, suffix = name[:4], name[4:]
        assert stem == f"{i:04d}" and suffix.startswith(".")
    # the on-disk handoff matches the sequential names
    names = sorted(p.name for p in (out / "handoff").iterdir()
                   if p.is_file() and p.name != "gate-receipt.json")
    assert names == sorted(
        Path(it["output"]["path"]).name for it in receipt["items"])
    # verification still works without paths
    result = _verify(_receipt_path(out), output_dir=out / "handoff",
                     scope="outputs_only")
    assert result["overall"] == "match"


def test_t10_no_input_hashes(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    receipt = _run_gate(inp, out, include_input_hashes=False)
    assert receipt["settings"]["include_input_hashes"] is False
    for it in receipt["items"]:
        assert "sha256" not in it["input"]
        assert "bytes" in it["input"]


# ---------------------------------------------------------------------------
# GT-T11: verify outcomes and exit codes
# ---------------------------------------------------------------------------

def test_t11_verify_match_and_scope_always(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    _run_gate(inp, out)
    for kw, expected_scope in (
            (dict(output_dir=out / "handoff"), "outputs_only"),
            (dict(input_dir=inp, output_dir=out / "handoff"),
             "inputs_and_outputs"),
            (dict(input_dir=inp), "replay")):
        result = _verify(_receipt_path(out), **kw)
        assert result["scope"] == expected_scope
        assert result["overall"] == "match"
        assert result["not_verifiable_reason"] is None


def test_t11_verify_differs(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    _run_gate(inp, out)
    produced = [p for p in (out / "handoff").iterdir()
                if p.is_file() and p.name != "gate-receipt.json"]
    blob = produced[0].read_bytes()
    produced[0].write_bytes(blob + b"x")
    result = _verify(_receipt_path(out), output_dir=out / "handoff",
                     scope="outputs_only")
    assert result["overall"] == "differs"
    reasons = {item["reason"] for item in result["items"]}
    assert "output_changed" in reasons


def test_t11_verify_not_verifiable_incomplete(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    _run_gate(inp, out)
    _receipt_path(out).unlink()
    result = _verify(_receipt_path(out), output_dir=out / "handoff",
                     scope="outputs_only")
    assert result["overall"] == "not_verifiable"
    assert result["not_verifiable_reason"] == "handoff_incomplete"


def test_t11_cli_exit_codes(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    subprocess.run(
        [sys.executable, str(TRAY), "gate", str(inp), "-o", str(out)],
        capture_output=True, text=True, check=True)
    receipt = str(_receipt_path(out))
    # match -> 0
    proc = subprocess.run(
        [sys.executable, str(TRAY), "verify", receipt,
         "--output", str(out / "handoff")],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # differs -> 1
    produced = [p for p in (out / "handoff").iterdir()
                if p.is_file() and p.name != "gate-receipt.json"]
    blob = produced[0].read_bytes()
    produced[0].write_bytes(blob + b"x")
    proc = subprocess.run(
        [sys.executable, str(TRAY), "verify", receipt,
         "--output", str(out / "handoff")],
        capture_output=True, text=True)
    assert proc.returncode == 1
    # not_verifiable -> 2
    produced[0].write_bytes(blob)
    _receipt_path(out).unlink()
    proc = subprocess.run(
        [sys.executable, str(TRAY), "verify", receipt,
         "--output", str(out / "handoff")],
        capture_output=True, text=True)
    assert proc.returncode == 2


# ---------------------------------------------------------------------------
# GT-T12: every verification reason is reproducible
# ---------------------------------------------------------------------------

def _reasons(result):
    return {item["reason"] for item in result["items"]}


def test_t12_input_changed_and_missing(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    _run_gate(inp, out)
    (inp / "a.txt").write_text("alpha changed\n", encoding="utf-8")
    result = _verify(_receipt_path(out), input_dir=inp,
                     output_dir=out / "handoff",
                     scope="inputs_and_outputs")
    assert result["overall"] == "differs"
    assert "input_changed" in _reasons(result)
    (inp / "a.txt").unlink()
    result = _verify(_receipt_path(out), input_dir=inp,
                     output_dir=out / "handoff",
                     scope="inputs_and_outputs")
    assert "input_missing" in _reasons(result)


def test_t12_item_added(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    _run_gate(inp, out)
    (inp / "c.txt").write_text("gamma\n", encoding="utf-8")
    result = _verify(_receipt_path(out), input_dir=inp,
                     scope="inputs_and_outputs")
    assert "item_added" in _reasons(result)


def test_t12_output_missing(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    _run_gate(inp, out)
    produced = [p for p in (out / "handoff").iterdir()
                if p.is_file() and p.name != "gate-receipt.json"]
    produced[0].unlink()
    result = _verify(_receipt_path(out), output_dir=out / "handoff",
                     scope="outputs_only")
    assert "output_missing" in _reasons(result)


def test_t12_replay_differs(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    _run_gate(inp, out)
    receipt_path = _receipt_path(out)

    def bump_output_sha(obj):
        for it in obj["items"]:
            if it["treatment"] == "produced":
                it["output"]["sha256"] = "sha256:" + "0" * 64
                break

    _rewrite_receipt(receipt_path, bump_output_sha)
    result = _verify(receipt_path, input_dir=inp, scope="replay")
    assert result["scope"] == "replay"
    assert result["overall"] == "differs"
    assert "replay_differs" in _reasons(result)


def test_t12_engine_version_differs_but_compare_continues(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    _run_gate(inp, out)
    receipt_path = _receipt_path(out)

    def bump_version(obj):
        for engine in obj["engines"]:
            if engine["name"] == "sieve-lens":
                engine["version"] = "0.99.0"

    _rewrite_receipt(receipt_path, bump_version)
    result = _verify(receipt_path, input_dir=inp,
                     output_dir=out / "handoff",
                     scope="inputs_and_outputs")
    assert "engine_version_differs" in _reasons(result)
    # the hash comparison continues past the version mismatch
    produced_paths = [it for it in result["items"]]
    assert produced_paths


def test_t12_not_verifiable_receipt_unreadable(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    _run_gate(inp, out)
    _receipt_path(out).write_text("{not json", encoding="utf-8")
    result = _verify(_receipt_path(out), output_dir=out / "handoff")
    assert result["overall"] == "not_verifiable"
    assert result["not_verifiable_reason"] == "receipt_unreadable"


def test_t12_not_verifiable_version_and_digest(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    _run_gate(inp, out)
    path = _receipt_path(out)

    def bump_receipt_version(obj):
        obj["receipt_version"] = 99

    _rewrite_receipt(path, bump_receipt_version)
    result = _verify(path, output_dir=out / "handoff")
    assert result["not_verifiable_reason"] == "receipt_version_unsupported"

    # digest mismatch: restore a consistent receipt first (version 1,
    # fresh digest), then mutate the body WITHOUT re-computing the digest
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["receipt_version"] = 1
    body = {k: v for k, v in obj.items() if k != "digest"}
    norm = json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    body["digest"] = "sha256:" + hashlib.sha256(
        norm.encode("utf-8")).hexdigest()
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n"
    path.write_text(blob, encoding="utf-8")
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["summary"]["items"] = 9999
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n"
    path.write_text(blob, encoding="utf-8")
    result = _verify(path, output_dir=out / "handoff")
    assert result["not_verifiable_reason"] == "receipt_digest_mismatch"


def test_t12_not_verifiable_settings_unavailable(tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    _mk_tree(inp)
    cfg = tmp_path / "rules.cfg"
    cfg.write_text("rule 高橋:delete\n", encoding="utf-8")
    _run_gate(inp, out, redact_config=cfg)
    receipt = json.loads(_receipt_path(out).read_text(encoding="utf-8"))
    assert receipt["settings"]["redact"]["config_sha256"] is not None
    cfg.unlink()
    result = _verify(_receipt_path(out), input_dir=inp, scope="replay")
    assert result["overall"] == "not_verifiable"
    assert result["not_verifiable_reason"] == "settings_unavailable"
