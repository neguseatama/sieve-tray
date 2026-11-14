"""Seal 2.2 / S5 - the check code wired through gate/cohort and the
verify extension (request 3.1 C5, C8-C14).

The closed verify vocabulary keeps its shape: overall stays
match / differs / not_verifiable, the item reasons stay the published
7, and ONLY two words join the not_verifiable reasons -
code_key_missing (no key was given; the file-list check still runs)
and code_key_mismatch (the key identifier does not match).  A check
code whose value is wrong against the matching key rides in the
existing differs as the check_code item (C11).  The exit codes stay
0 / 1 / 2 (C12), gate/cohort/manifest/pack share --key-file (C5), and
verify gains --key-file and --root (C14).
"""
import hashlib
import json

import pytest

from pathlib import Path


def _run_manifest(folder, out, **kw):
    from sieve_tray import run_manifest
    return run_manifest(folder, out, **kw)


def _run_gate(folder, out, **kw):
    from sieve_tray import run_gate
    return run_gate(folder, out, **kw)


def _verify(receipt, **kw):
    from sieve_tray import verify_gate
    return verify_gate(receipt, **kw)


def _write_key(tmp_path, content=b"pass\n"):
    kf = tmp_path / "key.txt"
    kf.write_bytes(content)
    return kf


def _make_folder(root: Path) -> Path:
    d = root / "in"
    d.mkdir(parents=True)
    (d / "a.txt").write_bytes(b"alpha\n")
    (d / "b.txt").write_bytes(b"beta\n")
    return d


# ---------------------------------------------------------------------------
# SL-T10: the check code through manifest and verify

def test_t10_manifest_verify_with_key_matches(tmp_path):
    """C14: verify <receipt> --key-file <key> --root <folder> matches,
    exit vocabulary intact."""
    d = _make_folder(tmp_path)
    kf = _write_key(tmp_path)
    _run_manifest(d, tmp_path / "out", key_file=kf)
    result = _verify(tmp_path / "out" / "handoff"
                     / "manifest-receipt.json",
                     input_dir=d, key_file=kf)
    assert result["overall"] == "match"
    assert result["items"] == []


def test_t10_missing_key_still_checks_the_list(tmp_path):
    """C9: no key + a receipt that carries a check code -> overall
    not_verifiable with code_key_missing, but the file-list check
    still ran (the list matches, so no item differences)."""
    d = _make_folder(tmp_path)
    kf = _write_key(tmp_path)
    _run_manifest(d, tmp_path / "out", key_file=kf)
    result = _verify(tmp_path / "out" / "handoff"
                     / "manifest-receipt.json", input_dir=d)
    assert result["overall"] == "not_verifiable"
    assert result["not_verifiable_reason"] == "code_key_missing"
    assert result["items"] == []


def test_t10_key_identifier_mismatch(tmp_path):
    """C10: the wrong key -> not_verifiable with code_key_mismatch."""
    d = _make_folder(tmp_path)
    kf = _write_key(tmp_path, b"right key\n")
    _run_manifest(d, tmp_path / "out", key_file=kf)
    wrong = _write_key(tmp_path, b"wrong key\n")
    result = _verify(tmp_path / "out" / "handoff"
                     / "manifest-receipt.json", input_dir=d,
                     key_file=wrong)
    assert result["overall"] == "not_verifiable"
    assert result["not_verifiable_reason"] == "code_key_mismatch"


def test_t10_value_mismatch_rides_in_differs(tmp_path):
    """C11: a re-signed receipt whose check code does not match the
    key rides in the existing differs as the check_code item."""
    d = _make_folder(tmp_path)
    kf = _write_key(tmp_path)
    rp = tmp_path / "out" / "handoff" / "manifest-receipt.json"
    _run_manifest(d, tmp_path / "out", key_file=kf)
    # forge a different check code over the same body (the digest is
    # recomputed so the receipt stays internally consistent)
    obj = json.loads(rp.read_text(encoding="utf-8"))
    from sieve_tray import _gate_digest, _seal_check_code
    obj["check_code"]["value"] = "hmac-sha256:" + "0" * 64
    obj["digest"] = _gate_digest(obj)
    rp.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")) + "\n",
                  encoding="utf-8")
    result = _verify(rp, input_dir=d, key_file=kf)
    assert result["overall"] == "differs"
    cc = [e for e in result["items"] if e.get("path") == "check_code"]
    assert len(cc) == 1
    assert cc[0]["reason"] == "check_code_differs"


def test_t10_gate_and_cohort_share_the_key_file(tmp_path):
    """C5: gate and cohort accept --key-file and carry the check_code
    section plus the whole-folder checksum in the summary."""
    from sieve_tray import run_cohort
    d = _make_folder(tmp_path)
    kf = _write_key(tmp_path)
    greceipt = _run_gate(d, tmp_path / "gout", key_file=kf)
    assert greceipt["check_code"]["key_id"]
    assert greceipt["summary"]["overall_sha256"]
    assert greceipt["receipt_version"] == 1
    from sieve_tray import _seal_check_code
    assert greceipt["check_code"]["value"] == _seal_check_code(
        b"pass\n", greceipt["summary"]["overall_sha256"], greceipt)
    # a gate run without a key keeps the 2.1.1 shape (no section)
    gplain = _run_gate(d, tmp_path / "gout2")
    assert "check_code" not in gplain
    assert "overall_sha256" not in gplain["summary"]
    creceipt = run_cohort(d, tmp_path / "cout", key_file=kf)
    assert creceipt["check_code"]["key_id"]
    assert creceipt["summary"]["overall_sha256"]
    # and verify confirms the keyed gate receipt against the folder
    # (the gate outputs convention: the folder that HOLDS handoff/)
    result = _verify(tmp_path / "gout" / "handoff" / "gate-receipt.json",
                     input_dir=d,
                     output_dir=tmp_path / "gout" / "handoff",
                     key_file=kf)
    assert result["overall"] == "match"
    assert result["items"] == []


def test_t10_pack_receipt_verifies_against_the_root(tmp_path):
    """A pack receipt carries the whole-folder checksum; verify
    --root confirms the folder still matches it."""
    from sieve_tray import run_pack
    d = _make_folder(tmp_path)
    kf = _write_key(tmp_path)
    run_pack(d, tmp_path / "z.zip", key_file=kf)
    result = _verify(tmp_path / "handoff" / "pack-receipt.json",
                     input_dir=d, key_file=kf)
    assert result["overall"] == "match"


def test_t10_manifest_root_checks_the_file_list(tmp_path):
    """C9's file-list check: a changed file is input_changed, an added
    file is item_added, a missing file is input_missing - the closed
    item reasons."""
    d = _make_folder(tmp_path)
    kf = _write_key(tmp_path)
    rp = tmp_path / "out" / "handoff" / "manifest-receipt.json"
    _run_manifest(d, tmp_path / "out")
    (d / "b.txt").write_bytes(b"changed\n")   # changed
    (d / "new.txt").write_bytes(b"new\n")     # added
    (d / "a.txt").unlink()                    # missing
    result = _verify(rp, input_dir=d)
    reasons = {e["path"]: e["reason"] for e in result["items"]}
    # the whole-folder checksum binds the directories too, so the
    # changed tree also raises the root entry
    assert reasons == {"a.txt": "input_missing",
                       "b.txt": "input_changed",
                       "new.txt": "item_added",
                       ".": "input_changed"}
    assert result["overall"] == "differs"


# ---------------------------------------------------------------------------
# SL-T11: the vocabulary and the exit codes stay closed

def test_t11_not_verifiable_reasons_gain_exactly_two():
    """C8: the published 5 not_verifiable reasons + exactly 2 new
    words; nothing else moved."""
    from sieve_tray import SEAL_NOT_VERIFIABLE_REASONS
    assert SEAL_NOT_VERIFIABLE_REASONS == frozenset({
        "handoff_incomplete", "receipt_unreadable",
        "receipt_version_unsupported", "receipt_digest_mismatch",
        "settings_unavailable",
        # the two Seal words (C9/C10):
        "code_key_missing", "code_key_mismatch"})


def test_t11_exit_codes_stay_0_1_2(tmp_path):
    """C12: the CLI mapping stays match 0 / differs 1 /
    not_verifiable 2."""
    from sieve_tray import _gate_main
    d = _make_folder(tmp_path)
    kf = _write_key(tmp_path)
    _run_manifest(d, tmp_path / "out", key_file=kf)
    rp = str(tmp_path / "out" / "handoff" / "manifest-receipt.json")
    assert _gate_main(["verify", rp, "--root", str(d),
                       "--key-file", str(kf)]) == 0
    # a missing key is not_verifiable -> 2
    assert _gate_main(["verify", rp, "--root", str(d)]) == 2
    # a changed folder is differs -> 1
    (d / "b.txt").write_bytes(b"changed\n")
    assert _gate_main(["verify", rp, "--root", str(d),
                       "--key-file", str(kf)]) == 1


def test_t11_differs_dominates_not_verifiable(tmp_path):
    """A real difference wins over the unconfirmable code: the report
    stays differs (1) even without the key."""
    d = _make_folder(tmp_path)
    kf = _write_key(tmp_path)
    rp = tmp_path / "out" / "handoff" / "manifest-receipt.json"
    _run_manifest(d, tmp_path / "out", key_file=kf)
    (d / "b.txt").write_bytes(b"changed\n")
    result = _verify(rp, input_dir=d)   # no key, but a real difference
    assert result["overall"] == "differs"
    assert result["items"]


# ---------------------------------------------------------------------------
# SL-T18 (C13): the claim limitation and the forbidden words

def test_t18_forbidden_words_absent():
    """署名 / 改ざんできない / 認証 / 作成者の証明 appear nowhere in
    the implementation or the spec document."""
    import sieve_tray
    src = Path(sieve_tray.__file__).read_text(encoding="utf-8")
    doc = (Path(sieve_tray.__file__).parent / "docs"
           / "manifest-format.md").read_text(encoding="utf-8")
    for word in ("署名", "改ざんできない", "認証", "作成者の証明",
                 "改ざん", "authentic", "tamper-proof", "signature"):
        assert word not in src, f"forbidden word in code: {word}"
        assert word not in doc, f"forbidden word in doc: {word}"


def test_t18_claim_limitation_is_stated():
    """C13: the document states the limited claim - the code only
    tells that a key holder made it, nothing stronger."""
    doc = (Path(__file__).resolve().parent.parent / "docs"
           / "manifest-format.md").read_text(encoding="utf-8")
    assert "主張の範囲はそれだけ" in doc
    assert "キーを持っていない者" in doc
