"""Tests for the v0.8.0 quantifier audit lane integration in sieve_tray.

These tests deliberately do NOT touch the existing 89 tests - they are
additive, and the audit lane is gated behind sieve-referee >=1.3.0 (the
test environment installs it via the test workflow). When the engine
or audit_documents() is unavailable the audit lane returns ([], None)
and the tests skip gracefully so this file stays green on minimal CI.
"""

import tempfile
import unittest
from pathlib import Path

import sieve_tray
from sieve_tray import (
    ScanResult,
    audit_text,
    run_scan,
    render,
    DEFAULT_MODIFIER_VOCAB_PATH,
)


try:
    import sieve_referee  # noqa: F401
    HAS_REFEREE = True
except ImportError:
    HAS_REFEREE = False


class TestScanResultAuditField(unittest.TestCase):
    """ScanResult.audit_results should serialize and round-trip cleanly."""

    def test_default_audit_results_is_empty_list(self):
        r = ScanResult()
        self.assertEqual(r.audit_results, [])

    def test_to_dict_includes_audit_results(self):
        r = ScanResult(audit_results=[{"file": "a.txt", "signal": "RED"}])
        d = r.to_dict()
        self.assertIn("audit_results", d)
        self.assertEqual(d["audit_results"], [{"file": "a.txt", "signal": "RED"}])

    def test_from_dict_round_trips_audit_results(self):
        original = ScanResult(audit_results=[
            {"file": "a.txt", "signal": "RED", "pattern_name": "UNBACKED_UNIVERSAL"},
            {"file": "b.txt", "signal": "YELLOW", "pattern_name": "SAMPLE_ONLY_UNIVERSAL"},
        ])
        round_tripped = ScanResult.from_dict(original.to_dict())
        self.assertEqual(round_tripped.audit_results, original.audit_results)

    def test_from_dict_tolerates_missing_audit_results_key(self):
        # Pre-v0.8.0 history entries do not have audit_results - the
        # from_dict path must accept them (forward-compatible).
        legacy = {
            "groups": [["g", ["/tmp/x.txt"]]],
            "doc_results": [],
            "code_pairs": [],
            "text_pairs": [],
        }
        r = ScanResult.from_dict(legacy)
        self.assertEqual(r.audit_results, [])


class TestAuditText(unittest.TestCase):
    """audit_text() wraps sieve_referee.audit_documents() into a flat
    list of flagged-sentence dicts plus a receipt summary."""

    def setUp(self):
        if not HAS_REFEREE:
            self.skipTest("sieve-referee not installed")

    def test_empty_text_map_returns_empty(self):
        results, summary = audit_text({})
        self.assertEqual(results, [])
        self.assertIsNone(summary)

    def test_flagged_sentence_is_surfaced(self):
        docs = {
            "group_a/essay.txt": (
                "すべての自然数は偶数である。"
                "これは明白に真である。"
            ),
        }
        results, summary = audit_text(docs)
        self.assertTrue(any(r["signal"] == "RED" for r in results),
                        f"expected at least one RED signal, got: {results}")
        # The audit entry must carry the provenance fields.
        red = next(r for r in results if r["signal"] == "RED")
        self.assertEqual(red["file"], "group_a/essay.txt")
        self.assertTrue(red["sentence_sha256"])  # 64-hex
        self.assertIn(red["backing"], {"unbacked", "theorem", "enumerated", "sample"})
        self.assertIn(red["scope"], {"universal", "measured"})
        self.assertEqual(red["pattern_name"], "UNBACKED_UNIVERSAL")
        # modifier vocab provenance must be present (bundled default).
        self.assertTrue(red["modifier_vocab_sha256"])
        self.assertEqual(red["modifier_vocab_count"], 10)

    def test_green_sentences_are_not_surfaced(self):
        # A measured statement with no universal-scope vocabulary should
        # not appear in audit_results (only YELLOW/RED are flagged).
        docs = {
            "group_a/measured.txt": "3個のリンゴがある。",  # factual, no universal
        }
        results, _ = audit_text(docs)
        # Either no flagged sentences, or only YELLOW/RED signals.
        for r in results:
            self.assertIn(r["signal"], {"YELLOW", "RED"})

    def test_custom_modifier_vocab_path_overrides_default(self):
        # A custom vocab file with a single marker pattern.
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("# custom test vocab\n")
            f.write("確実に\n")
            custom_path = f.name
        try:
            docs = {"group_a/test.txt": "確実に正しい。すべて正しい。"}
            results, summary = audit_text(docs, modifier_vocab_path=custom_path)
            if results:
                # The vocab count must reflect the custom file (1 pattern).
                self.assertEqual(results[0]["modifier_vocab_count"], 1)
        finally:
            Path(custom_path).unlink(missing_ok=True)


class TestRunScanAuditIntegration(unittest.TestCase):
    """run_scan() should populate audit_results via the audit lane."""

    def setUp(self):
        if not HAS_REFEREE:
            self.skipTest("sieve-referee not installed")

    def test_run_scan_populates_audit_results(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "group_a").mkdir()
            (p / "group_a" / "essay.txt").write_text(
                "すべての自然数は偶数である。", encoding="utf-8")
            (p / "group_b").mkdir()
            (p / "group_b" / "essay.txt").write_text(
                "Some primes are even.", encoding="utf-8")
            result = run_scan(p, progress=lambda m: None)
            self.assertIsInstance(result.audit_results, list)
            # The Japanese hallucination sentence should surface as RED.
            self.assertTrue(any(
                r["file"] == "group_a/essay.txt" and r["signal"] == "RED"
                for r in result.audit_results),
                f"expected RED flag for group_a/essay.txt, got: {result.audit_results}")

    def test_run_scan_audit_results_round_trips_storage(self):
        # The audit_results field must survive to_dict -> from_dict,
        # which is what sieve_tray_storage uses to persist and reload runs.
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "g").mkdir()
            (p / "g" / "f.txt").write_text(
                "すべての自然数は偶数である。", encoding="utf-8")
            result = run_scan(p, progress=lambda m: None)
            round_tripped = ScanResult.from_dict(result.to_dict())
            self.assertEqual(round_tripped.audit_results, result.audit_results)


class TestRenderAuditSection(unittest.TestCase):
    """render() must include a Quantifier Audit section in the HTML."""

    def test_render_with_no_audit_results_shows_placeholder(self):
        r = ScanResult(audit_results=[])
        html_out = render(r)
        self.assertIn("Quantifier Audit", html_out)
        self.assertIn("No flagged universalization candidates.", html_out)

    def test_render_with_audit_results_shows_table(self):
        r = ScanResult(audit_results=[{
            "file": "group_a/essay.txt",
            "sentence_sha256": "a" * 64,
            "sentence_text": "すべての自然数は偶数である。",
            "patterns": ["すべて"],
            "backing": "unbacked",
            "scope": "universal",
            "signal": "RED",
            "pattern_name": "UNBACKED_UNIVERSAL",
            "reason": "裏付けのない全称文",
            "certainty_markers": ["明白に"],
            "modifier_vocab_sha256": "b" * 64,
            "modifier_vocab_count": 10,
        }])
        html_out = render(r)
        self.assertIn("Quantifier Audit", html_out)
        self.assertIn("group_a/essay.txt", html_out)
        self.assertIn("UNBACKED_UNIVERSAL", html_out)
        self.assertIn("unbacked", html_out)
        self.assertIn("明白に", html_out)


class TestDefaultModifierVocabPath(unittest.TestCase):
    """The bundled default modifier-vocab file must exist and match the
    sieve-referee canonical fingerprint (fb6aa9a6...)."""

    def test_bundled_vocab_file_exists(self):
        self.assertTrue(
            DEFAULT_MODIFIER_VOCAB_PATH.exists(),
            f"bundled vocab file missing at {DEFAULT_MODIFIER_VOCAB_PATH}")

    @unittest.skipUnless(HAS_REFEREE, "sieve-referee not installed")
    def test_bundled_vocab_matches_referee_fingerprint(self):
        import hashlib
        digest = hashlib.sha256(
            DEFAULT_MODIFIER_VOCAB_PATH.read_bytes()).hexdigest()
        # Canonical fingerprint from sieve-referee v1.3.0's
        # epistemic_modifiers_ja_v1.txt.
        self.assertEqual(
            digest,
            "fb6aa9a6522f90992ba827e0636b2d9d2c0bfccd4c65d0c5abace0dd65f03252")


class TestVersionBump(unittest.TestCase):
    """v0.8.0 marker - guards against accidental version revert."""

    def test_version_is_0_8_0(self):
        self.assertEqual(sieve_tray.__version__, "0.8.0")


if __name__ == "__main__":
    unittest.main()
