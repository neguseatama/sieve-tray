"""TR2-T01..T12 — v1.2.0 engine-import lane (red first).

The pins below were measured against the upstream repositories before
implementation:
  - Crowd upstream main def0053 (v0.9.0), tree a06c92a6105d9a06932c534aca831b5f306f9d10
  - Redact upstream tag v0.11.0 (ddde4bd) — pin refreshed for the M1
    Gate lane's re-vendoring
Pins refreshed at the v1.3.0 vendor update; the golden molds (TR2-T04/T05)
are unchanged and keep their pre-import values.
TR2-T09 (test_flagged_sentence_is_surfaced follows the upstream vocab) is
already satisfied on this base: commit 0d0540a re-derived the count from
the engine's runtime vocab, and the test passes against referee 1.5.0.

The golden molds (TR2-T04/T05) pin the pre-import behavior of the
Lens/Scope pipeline and the Redact wrapper, measured on this tree, so
any drift caused by the import fails here instead of silently shipping.
"""

import fnmatch
import hashlib
import importlib
import io
import json
import os
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

import sieve_tray
from sieve_tray import (
    ScanResult,
    UNOBSERVED_REASONS,
    audit_text,
    classify_observation,
    crowd_anonymize,
    crowd_inspect,
    render,
    render_text,
    sanitize_file,
)
import sieve_tray_i18n
from sieve_tray_i18n import STRINGS, tr

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Upstream pins (measured 2026-11-05 at the tags named above).
# ---------------------------------------------------------------------------

CROWD_UPSTREAM_VERSION = "0.9.0"
CHARTABLE_SHA256 = "c5ae4757bc9d07a2dcd1507d662460c3412c932d73318e54912569608242e605"
BUILTIN_PACK_SHA = "1fae5827a7048ca1e4b92c7d12792a755f5b21e63d6392bc2a1fbdb4e3dc66c4"
TEMPLATE_SHA2 = "0d5c35d82dc54004ad7f34b80be69103a80a0d20dccc4dae22f7e6412ba6c657"
RUN_TABLE_SHA = "b58249febc35c4feb6f6bfe1632aab92ca802c611759d31138d8ae040061500e"

REDACT_UPSTREAM_VERSION = "0.11.0"
REDACT_0100_SHA256 = "9203c7476fbac1eb0f25e75c6f31ea48732b4928b43ad2f641c5f5902c94e836"

FIXTURE_PINS = {
    "people.csv": "cf32626e9b45317efad3a35a8ff3721bd3b3dfe876422034a124d18774a289e9",
    "config.json": "92d6161279bac14a4a543f7096f553e3ce163a58c6fab1c485bb3e74ae32bb9e",
}

# Every file of upstream sieve_crowd/ at v0.9.0 (sha256 per file).
PINNED_CROWD_090_SHA256 = {
    "__init__.py": "8d0099cc26b14df1c5b14c2b037875811cdb970bc96e4fe81cf45e8cc41663ad",
    "__main__.py": "935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d",
    "audit.py": "ccbe07c7f0e1a647bea7b64aaa785264b517484961bfdc6e1a62253ac4f21684",
    "chartable.py": "4a01afa04a9678d86a0562ae48a2b578b2dd547247d941762088fcf32405b7a5",
    "chartable_v1.json": "c5ae4757bc9d07a2dcd1507d662460c3412c932d73318e54912569608242e605",
    "cli.py": "a4887a7100fe642a1f2b6119be0456297e6297992a5a00813c578a5f95b8fa29",
    "config.py": "3fc0b1f9e95b7f05c88b4bf00f37faa6f529fd9e1c3fa000c54c137bd16d3a3d",
    "csvio.py": "80a90e8e714093e385a1245e53ab1c83bc942b81c5fb0a1359f817beb2a985b5",
    "derived.py": "2123cc0d4b2ef5dc5e2ecccf718827512278339e7cf3e02379fa4518e82076f8",
    "engine.py": "d7384c5eb5c6012f731ab9af04e0483ca92316b6b73b980f4a88a3541616dc5d",
    "generalize.py": "a5c0c7fdb306e028ade1c51b69872f030a6d13e54d9b1cb6c57023037839cea0",
    "hidden_chars.py": "47bd0aa3a83b0b33a39ef8a3d353efd4251f713eefcbfcb834f25317a5a672f5",
    "hintpack.py": "8aa8282680f32ccf7c67a5ada9692c82ecd291374db233a7fcab3f19f607267e",
    "hintpack_builtin.py": "6af10633a228aa5fd0f58312af63e120ff5d1a72153db1eac22eadd2b281aed9",
    "hints.py": "a0d79c844380a2ac0d21900be0ad7d7d65a64f064266516a5674cf23ff8271d3",
    "jsonio.py": "60a5b1ea05137ad3f6ab710eb11879b19b528658e95452db7c15f98cc8891cd9",
    "measure.py": "21ed70795ae40971c3447674736e58f06c0569cab14b8c3c52d946231b853a15",
    "model.py": "620bb06b38a17a264e01853d7458b0a8fcc9e32ddbb9d4cd547ed8a79a9a6a0f",
    "prng.py": "8e8eefe63cb711c72e5bd2da43ea198245361692796a1529b402d72bc5728594",
    "pseudonym.py": "e58d3b62d78b75d6e871bc4bf0acf3960d7ecf41a2b597be6aeb1c5b54e6769b",
    "report.py": "9ff81387e24e5e8ca2ab4153a2e3a677a2c66be08e83e44ec98c932f377b7c6a",
    "scan.py": "482ee976cf25735ffeb4990c8feb5ef3ab859fca4312aec0ba30cb96b066d906",
    "search.py": "b782ecb5a9c771e325782a6d08bc4081cde21bb1dbc98f00dc94c2e6967efbb4",
    "tableio.py": "cdd8ae2722e1ffb2f18f9e5e084c80a3caffabaac0f37db0fc8970f1b88ff6b4",
    "tabular.py": "b838bf53429320f42c7d4a10be640e233dd41bd2c00648ff56f66530996c9179",
    "xlsx_reader.py": "a7c6e8c3a4aa6dad1d56fcaf9b457ab3aad7d995781e529a3886e215fdee4da9",
    "xmlio.py": "640eb6c9714f8b3396f175d5e1a3b36ada9d9e852d5943036ef1722dde3cebac",
}

# Golden molds (TR2-T04/T05), measured on the pre-import tree at 0d0540a.
# v1.4.0 note: the with-unobserved HTML render intentionally changed with
# the three-stage coloring (stage classes + stage CSS; see TR4-T08) - the
# v1.3.0 value was cd8181ec8b48d88e11284fa8ec886cea2a76fe231d6f8553dbe44e
# b0b2cb7b58. The core and the Markdown render molds are unchanged.
MOLD_WITH_UNOBSERVED_CORE = (
    "73b31e81dd945de0be39a4bb01c2c80884d32260f599e3e5cf9ce78cec5287cd")
MOLD_WITH_UNOBSERVED_RENDER = (
    "05677e669b5b6ea281b7fb3c4ef29a69d7140061716ccfc7be47fc8e32a547ed")
MOLD_WITH_UNOBSERVED_RENDER_TEXT = (
    "c3b7e923cf8fbbb4f1661ab829ca2323f2969f7fcbbeb1176c9ade232c03eebb")
MOLD_CLEAN_CORE = (
    "1cee593b8807c137bac079351537bdf7439d676cd4e8fb7bbc91dec3005f16bb")
MOLD_CLEAN_RENDER = (
    "d5e1624c5661cc6b60891ac3190e04f61f55a9c7ffb263a017552da29cddde82")
MOLD_CLEAN_RENDER_TEXT = (
    "d525c98bb7f10e400c851fb0ce49c04149cf04cedaca75d84d62efd93a7176dd")
MOLD_REDACT_OUT = (
    "b58cd1e841d1f8296a7236ca309c436fbf1876df01a9673a1586c6db98b00f94")

PY_A = ("import os\n\n\ndef total(values):\n    \"\"\"Sum values.\"\"\"\n"
        "    acc = 0\n    for v in values:\n        acc += v\n"
        "    return acc\n\n\nprint(total([1, 2, 3]))\n")
PY_B = ("import re\n\n\ndef shrink(text):\n    \"\"\"Collapse spaces.\"\"\"\n"
        "    return re.sub(r\"\\s+\", \" \", text)\n\n\n"
        "print(shrink(\"a  b\"))\n")

TREE = {
    "in/g1/a.py": PY_A,
    "in/g1/b.py": PY_A.replace("[1, 2, 3]", "[1, 2, 4]"),
    "in/g1/note.txt": "このメモは第一版である。修正は金曜日に行う。\n",
    "in/g2/note.txt": "このメモは第三版である。修正は月曜日に行う。\n",
    "in/g2/doc.md": "# Memo alpha\n\nplain text with no findings\n",
    "in/g2/hidden.txt": "visible​hidden-zwsp\u200b tail\n",
    "in/g2/empty.txt": "",
}
CLEAN_TREE = {
    "in/g1/a.py": PY_A,
    "in/g2/b.py": PY_B,
    "in/g1/doc.md": "# Alpha\n\nfirst document body\n",
    "in/g2/doc.md": "# Beta\n\nsecond document body entirely different\n",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_tree(root: Path, tree: dict):
    for rel, content in tree.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        # newline="" keeps the fixtures LF on every OS: write_text's
        # default newline=None translates \n to os.linesep on Windows,
        # and the engines read the input as bytes, so CRLF fixtures
        # drift the byte pins (run #84: MOLD_REDACT_OUT, the core
        # hashes).
        p.write_text(content, encoding="utf-8", newline="")


def _make_frozen_docx(path: Path):
    """A minimal .docx whose word/document.xml carries a DOCTYPE — Lens
    refuses it with the known code doctype_not_allowed (measured on
    Lens 0.21.1; the docx extractor is a Lens built-in everywhere)."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"><Default Extension="xml" '
            'ContentType="application/xml"/></Types>')
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><!DOCTYPE w:document [<!ENTITY x "y">]>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body><w:p/></w:body></w:document>')


def _core_hash(result: ScanResult) -> str:
    blob = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)
    return _sha256(blob.encode("utf-8"))


def _load_pyproject() -> dict:
    try:
        import tomllib
        with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
            return tomllib.load(fh)
    except ImportError:
        # Python 3.10 fallback: minimal parse of the two sections the
        # assertions need. Not used on CI (3.12).
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        deps = re.search(r'^dependencies\s*=\s*\[(.*?)\]', text, re.S | re.M)
        data = re.search(r'sieve_crowd\s*=\s*\[(.*?)\]', text, re.S)
        return {
            "project": {"dependencies": re.findall(r'"([^"]+)"', deps.group(1))},
            "tool": {"setuptools": {"package-data": {
                "sieve_crowd": re.findall(r'"([^"]+)"', data.group(1))}}},
        }


class TR2_T01_VendoredCrowdMatchesUpstream082(unittest.TestCase):
    """TR2-T01: the vendored sieve_crowd/ is byte-identical to upstream
    0.9.0 (pin refreshed at the v1.3.0 vendor update), and the engine
    reproduces upstream's own golden pins."""

    def setUp(self):
        self.vendored = REPO_ROOT / "sieve_crowd"

    def test_vendored_files_match_pins(self):
        self.assertTrue(self.vendored.is_dir(), "vendored sieve_crowd/ missing")
        actual = {}
        for path in sorted(self.vendored.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                actual[str(path.relative_to(self.vendored))] = _sha256(
                    path.read_bytes())
        missing = sorted(set(PINNED_CROWD_090_SHA256) - set(actual))
        extra = sorted(set(actual) - set(PINNED_CROWD_090_SHA256))
        self.assertEqual(missing, [], "missing vendored files")
        self.assertEqual(extra, [], "unexpected vendored files")
        diff = [name for name, sha in sorted(PINNED_CROWD_090_SHA256.items())
                if actual[name] != sha]
        self.assertEqual(diff, [],
                         "files differing from upstream v0.8.2: " + ", ".join(diff))

    def test_chartable_sha256(self):
        chartable = self.vendored / "chartable_v1.json"
        self.assertTrue(chartable.is_file(), "chartable_v1.json not vendored")
        self.assertEqual(_sha256(chartable.read_bytes()), CHARTABLE_SHA256)

    def test_builtin_pack_bytes_are_pinned(self):
        mod = importlib.import_module("sieve_crowd.hintpack_builtin")
        self.assertEqual(_sha256(mod.BUILTIN_PACK_BYTES), BUILTIN_PACK_SHA)

    def _run_cli(self, argv):
        from sieve_crowd.cli import main
        buf_out, buf_err = io.StringIO(), io.StringIO()
        import contextlib
        try:
            with contextlib.redirect_stdout(buf_out), \
                    contextlib.redirect_stderr(buf_err):
                main(argv)
        except SystemExit as exc:
            code = exc.code
            if code is None:
                return 0
            return code if isinstance(code, int) else 1
        return 0

    def test_run_table_matches_golden_sha(self):
        fixtures = (Path(__file__).resolve().parent / "fixtures_crowd_082")
        self.assertEqual(_sha256((fixtures / "people.csv").read_bytes()),
                         FIXTURE_PINS["people.csv"])
        self.assertEqual(_sha256((fixtures / "config.json").read_bytes()),
                         FIXTURE_PINS["config.json"])
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.csv"
            rc = self._run_cli([
                "run", str(fixtures / "people.csv"),
                "-c", str(fixtures / "config.json"),
                "-o", str(out), "--quiet"])
            self.assertEqual(rc, 0)
            self.assertEqual(_sha256(out.read_bytes()), RUN_TABLE_SHA)

    def test_inspect_template_matches_golden_sha(self):
        fixtures = (Path(__file__).resolve().parent / "fixtures_crowd_082")
        with tempfile.TemporaryDirectory() as d:
            tpl = Path(d) / "t.json"
            rc = self._run_cli([
                "inspect", str(fixtures / "people.csv"),
                "--config-out", str(tpl)])
            self.assertEqual(rc, 0)
            self.assertEqual(_sha256(tpl.read_bytes()), TEMPLATE_SHA2)


class TR2_T02_ChartableShipsInPackageData(unittest.TestCase):
    """TR2-T02: chartable_v1.json (and every non-.py vendored file) is
    covered by the package-data patterns — static check, no build."""

    def test_chartable_is_covered_by_package_data(self):
        pyproject = _load_pyproject()
        patterns = (pyproject["tool"]["setuptools"]
                    ["package-data"]["sieve_crowd"])
        chartable = REPO_ROOT / "sieve_crowd" / "chartable_v1.json"
        self.assertTrue(chartable.is_file(), "chartable_v1.json not vendored")
        self.assertTrue(
            any(fnmatch.fnmatch("chartable_v1.json", p) for p in patterns),
            f"chartable_v1.json matches no package-data pattern: {patterns}")

    def test_every_non_py_file_is_covered(self):
        pyproject = _load_pyproject()
        patterns = (pyproject["tool"]["setuptools"]
                    ["package-data"]["sieve_crowd"])
        vendored = REPO_ROOT / "sieve_crowd"
        uncovered = []
        for path in sorted(vendored.rglob("*")):
            if not path.is_file() or path.suffix == ".py":
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                # Bytecode caches appear when a local `python -m pytest`
                # imports the repo-tree copy of sieve_crowd. TR2-T01 and
                # test_crowd_vendor_sync skip them too; they are build
                # artifacts, never vendored data.
                continue
            rel = str(path.relative_to(vendored))
            if not any(fnmatch.fnmatch(rel, p) for p in patterns):
                uncovered.append(rel)
        self.assertEqual(uncovered, [],
                         "non-.py vendored files not covered by package-data")


class TR2_T03_VendoredRedactMatchesUpstream090(unittest.TestCase):
    """TR2-T03: the vendored sieve_redact.py is byte-identical to
    upstream 0.10.0 (pin refreshed at the v1.3.0 vendor update)."""

    def test_vendored_module_matches_pin(self):
        vendored = REPO_ROOT / "sieve_redact.py"
        self.assertTrue(vendored.is_file(), "vendored sieve_redact.py missing")
        actual = _sha256(vendored.read_bytes())
        self.assertEqual(actual, REDACT_0100_SHA256)


class TR2_T04_GoldenMoldLensScopeReport(unittest.TestCase):
    """TR2-T04: the Lens/Scope pipeline and both report renderings are
    byte-identical across the import, on inputs with and without
    unobserved files."""

    def _scan(self, tmp: str, tree: dict, with_extras: bool):
        root = Path(tmp)
        _write_tree(root, tree)
        if with_extras:
            _make_frozen_docx(root / "in/g2/frozen.docx")
            os.symlink("note.txt", root / "in/g1/link.txt")
        old = os.getcwd()
        os.chdir(root)
        try:
            result = sieve_tray.run_scan(Path("in"))
        finally:
            os.chdir(old)
        return result

    def test_report_identical_with_unobserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._scan(tmp, TREE, with_extras=True)
            self.assertEqual(len(result.audit_results), 0)
            self.assertEqual(_core_hash(result), MOLD_WITH_UNOBSERVED_CORE)
            self.assertEqual(_sha256(render(result).encode("utf-8")),
                             MOLD_WITH_UNOBSERVED_RENDER)
            self.assertEqual(_sha256(render_text(result).encode("utf-8")),
                             MOLD_WITH_UNOBSERVED_RENDER_TEXT)

    def test_report_identical_without_unobserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._scan(tmp, CLEAN_TREE, with_extras=False)
            self.assertEqual(len(result.audit_results), 0)
            self.assertEqual(_core_hash(result), MOLD_CLEAN_CORE)
            self.assertEqual(_sha256(render(result).encode("utf-8")),
                             MOLD_CLEAN_RENDER)
            self.assertEqual(_sha256(render_text(result).encode("utf-8")),
                             MOLD_CLEAN_RENDER_TEXT)


class TR2_T05_GoldenMoldRedact(unittest.TestCase):
    """TR2-T05: the Redact wrapper's result on the existing input is
    identical across the import (measured on 0.6.0)."""

    def test_sanitize_result_identical(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d)
            sample = work / "s.txt"
            sample.write_text(
                "連絡先 taro.yamada@example.com / 090-1234-5678\n"
                "担当 佐藤花子 識別 MY-654321\n",
                encoding="utf-8", newline="")  # fixed-LF sample (run #84)
            cfg = work / "c.txt"
            cfg.write_text(
                "builtin email:delete\nbuiltin phone-jp:delete\n"
                "rule 佐藤花子:replace:<REDACTED>\nrule MY-[0-9]{6}:delete\n",
                encoding="utf-8")
            out = work / "o.txt"
            res = sanitize_file(sample, cfg, out)
            self.assertTrue(res["ok"])
            self.assertEqual(res["rc"], 0)
            self.assertEqual(res["masked_count"], 3)
            self.assertTrue(res["integrity_verified"])
            self.assertEqual(res["residue"], "none")
            self.assertEqual(_sha256(out.read_bytes()), MOLD_REDACT_OUT)


class TR2_T06_Crowd082ItemsTrayReads(unittest.TestCase):
    """TR2-T06: every output item the Tray crowd screen reads exists in
    the 0.8.2 output under the same name and type."""

    HEADER = ["name", "age", "city", "zip"]
    ROWS = [
        ["Alice", "34", "Tokyo", "1000001"],
        ["Bob", "41", "Osaka", "5300001"],
        ["Carol", "34", "Tokyo", "1000002"],
        ["Dave", "29", "Nagoya", "4600001"],
        ["Erin", "41", "Osaka", "5300002"],
        ["Frank", "34", "Tokyo", "1000003"],
    ]
    CFG = {"k": 2, "columns": {
        "name": {"role": "id"},
        "age": {"role": "qi", "type": "numeric", "widths": [10]},
        "city": {"role": "qi", "type": "category"},
        "zip": {"role": "qi", "type": "prefix", "length": 3},
    }}

    def test_vendored_crowd_is_090(self):
        import sieve_crowd
        self.assertEqual(sieve_crowd.__version__, CROWD_UPSTREAM_VERSION)

    def test_summary_keys_survive_082(self):
        # The real caller parses config text through crowd_parse_config
        # (0.8.2 requires a Config object - a raw dict no longer works).
        cfg = sieve_tray.crowd_parse_config(json.dumps(self.CFG))
        # io is the (input_format, output_format) pair the GUI passes for
        # the receipt; it is recorded only when given (measured on both
        # 0.2.0 and 0.8.2).
        summary = crowd_anonymize(self.HEADER, self.ROWS, cfg, lang="en",
                                  io=("csv", "csv"))
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["status"], "anonymized")
        self.assertEqual(summary["records_in"], 6)
        self.assertGreaterEqual(summary["records_out"], 1)
        self.assertLessEqual(summary["suppressed"], summary["records_in"])
        self.assertEqual(summary["k_requested"], 2)
        # 0.8.2's lattice search may reach a stronger crowd than the
        # requested k (measured: 6 on this fixture, 0.2.0 found 2) - the
        # contract is k_achieved >= k_requested, not a fixed number.
        self.assertGreaterEqual(summary["k_achieved"],
                                summary["k_requested"])
        self.assertIsInstance(summary["max_risk"], float)
        self.assertIsInstance(summary["avg_risk"], float)
        self.assertIsInstance(summary["before_alone"], int)
        self.assertIsInstance(summary["after_alone"], int)
        self.assertLessEqual(summary["after_alone"], summary["before_alone"])
        self.assertIsNotNone(summary["report_text"])
        self.assertIsNotNone(summary["report_json"])
        self.assertIsNotNone(summary["io"])
        # header/rows are the ANONYMIZED OUTPUT table, not the input
        # echo: the id column is dropped and qi values are generalized
        # (measured identical in shape on 0.2.0 and 0.8.2).
        self.assertIsInstance(summary["header"], list)
        self.assertIsInstance(summary["rows"], list)
        self.assertTrue(summary["rows"])
        self.assertEqual(len(summary["rows"][0]), len(summary["header"]))
        self.assertTrue(set(summary["header"]) <= set(self.HEADER))

    def test_inspect_keys_survive_082(self):
        columns = crowd_inspect(self.HEADER, self.ROWS)
        self.assertEqual(len(columns), len(self.HEADER))
        for col in columns:
            for key in ("name", "distinct", "empty", "unique_ratio", "shape"):
                self.assertIn(key, col)


class TR2_T07_CrowdHistoryAllowlist(unittest.TestCase):
    """TR2-T07: the allowlist still never stores table data, new summary
    keys are not stored implicitly, and pre-existing history rows load."""

    FORBIDDEN = {"header", "rows", "report_json", "io", "ok",
                 "before_alone", "after_alone", "k_requested", "config_path"}

    def _summary(self):
        return {
            "input_path": "in/table.csv", "output_path": "out/table.csv",
            "records_in": 6, "records_out": 5, "suppressed": 1,
            "k_requested": 2, "k_achieved": 2, "max_risk": 0.5,
            "avg_risk": 0.3, "before_alone": 2, "after_alone": 0,
            "status": "anonymized", "reason": None,
            "report_text": "Records: 6 in, 5 out (1 suppressed, 16.7%)",
            # items 0.8.2 adds and everything that must never persist:
            "missing_suppressed": 1, "missing_value_policy": "error",
            "header": ["name", "age"], "rows": [["Alice", "34"]],
        }

    def test_allowlist_excludes_table_data_keys(self):
        from sieve_tray_storage import CROWD_PAYLOAD_ALLOWLIST
        overlap = CROWD_PAYLOAD_ALLOWLIST & self.FORBIDDEN
        self.assertEqual(overlap, set())

    def test_new_keys_scrubbed_old_keys_saved(self):
        from sieve_tray_storage import Storage
        with tempfile.TemporaryDirectory() as d:
            st = Storage(Path(d) / "history.db")
            run_id = st.save_crowd_run(self._summary())
            records = st.load_crowd_runs(limit=5)
            self.assertEqual(len(records), 1)
            rec = records[0]
            self.assertEqual(rec["id"], run_id)
            for key in ("input_path", "output_path", "records_in",
                        "records_out", "suppressed", "k_achieved",
                        "max_risk", "avg_risk", "status", "report_text"):
                self.assertIn(key, rec)
            for key in ("header", "rows", "report_json", "io", "ok",
                        "missing_suppressed", "missing_value_policy"):
                self.assertNotIn(key, rec)

    def test_v110_history_row_still_loads(self):
        from sieve_tray_storage import Storage
        with tempfile.TemporaryDirectory() as d:
            st = Storage(Path(d) / "history.db")
            legacy = {
                "input_path": "old.csv", "records_in": 3, "records_out": 3,
                "suppressed": 0, "k_achieved": 2, "status": "anonymized",
                "report_text": "Records: 3 in, 3 out (0 suppressed, 0.0%)",
                # a pre-allowlist row that stored table data:
                "header": ["secret"], "rows": [["x"]],
            }
            st.save_crowd_run(legacy)
            rec = st.load_crowd_runs(limit=5)[0]
            self.assertEqual(rec["input_path"], "old.csv")
            self.assertNotIn("header", rec)
            self.assertNotIn("rows", rec)


class TR2_T08_Referee17VocabFlows(unittest.TestCase):
    """TR2-T08: sentences flagged via the 7 vocab items referee 1.5.0
    added reach the screen data, both report renderings and history,
    with the vocab names displayed as-is (measured: no i18n keys exist
    for vocab names — they are engine strings shown directly)."""

    NEW_WORDS = ["必然的に", "不可避的に", "自ずと", "おのずと",
                 "疑いようがない", "疑いようもない", "言うまでもなく"]

    def setUp(self):
        try:
            import sieve_referee  # noqa: F401
        except ImportError:
            self.skipTest("sieve-referee not installed")
        # The 7 words below exist only from referee 1.5.0 (measured:
        # 1.3.0 embeds the first 10). On an older referee the words
        # themselves are absent upstream, so there is nothing to flow.
        from sieve_referee.quantifier_audit import DEFAULT_MODIFIER_VOCAB
        if len(DEFAULT_MODIFIER_VOCAB) < 17:
            self.skipTest(
                "referee vocab has no 1.5.0 additions ("
                f"{len(DEFAULT_MODIFIER_VOCAB)} items)")

    def _rows(self):
        docs = {}
        for i, word in enumerate(self.NEW_WORDS):
            docs[f"f{i}.txt"] = f"すべての顧客は{word}保存に同意する。"
        rows, _summary = audit_text(docs)
        return rows

    def test_new_vocab_rows_are_surfaced(self):
        rows = self._rows()
        markers = set()
        for r in rows:
            markers.update(r.get("certainty_markers", []))
        for word in self.NEW_WORDS:
            self.assertIn(word, markers,
                          f"new vocab {word!r} produced no audit row")

    def test_new_vocab_rows_reach_both_reports(self):
        rows = self._rows()
        result = ScanResult(audit_results=rows)
        html = render(result)
        md = render_text(result)
        for word in self.NEW_WORDS:
            self.assertIn(word, html)
            self.assertIn(word, md)

    def test_new_vocab_rows_round_trip_history(self):
        from sieve_tray_storage import Storage
        rows = self._rows()
        with tempfile.TemporaryDirectory() as d:
            st = Storage(Path(d) / "history.db")
            run_id = st.save_run(Path(d), ScanResult(audit_results=rows))
            loaded = st.load_run(run_id)
            self.assertIsNotNone(loaded)
            markers = set()
            for r in loaded.audit_results:
                markers.update(r.get("certainty_markers", []))
            for word in self.NEW_WORDS:
                self.assertIn(word, markers)

    def test_certainty_i18n_keys_are_symmetric(self):
        en_keys = {k for k in STRINGS["en"] if k.startswith("detail_certainty")}
        ja_keys = {k for k in STRINGS["ja"] if k.startswith("detail_certainty")}
        self.assertEqual(en_keys, ja_keys)


class TR2_T10_NeutralUnsupportedFormatWording(unittest.TestCase):
    """TR2-T10: the display wording for 'Unsupported format: <suffix>'
    is neutral (Lens cannot distinguish a missing optional extension
    from a truly unknown suffix — measured on Lens 0.21.1, where both
    are the same null observation). en/ja symmetric; the classification
    vocabulary stays the closed 8-item set."""

    RAW = "Unsupported format: .pdf"

    def test_classification_unchanged_and_vocab_stays_8(self):
        status, reason, detail = classify_observation({
            "mask": "0000-000",
            "evidence": {"H1": [self.RAW]},
        })
        self.assertEqual((status, reason, detail),
                         ("unobserved", "engine_unavailable", None))
        self.assertEqual(len(UNOBSERVED_REASONS), 8)
        self.assertIn("engine_unavailable", UNOBSERVED_REASONS)

    def test_neutral_wording_key_is_symmetric(self):
        for lang in ("en", "ja"):
            text = tr(lang, "unobserved_format_neutral")
            self.assertTrue(text, f"{lang} key must be non-empty")
            self.assertNotIn("Unsupported", text)

    def test_helper_maps_raw_engine_text_to_neutral(self):
        neutral = sieve_tray_i18n.neutral_unobserved_text
        for lang in ("en", "ja"):
            mapped = neutral(self.RAW, lang)
            self.assertNotEqual(mapped, self.RAW)
            self.assertEqual(mapped, tr(lang, "unobserved_format_neutral"))
        # Anything else passes through unchanged.
        self.assertEqual(neutral("Extraction refused: encrypted", "en"),
                         "Extraction refused: encrypted")
        self.assertEqual(neutral("parsed successfully", "ja"),
                         "parsed successfully")

    def test_detail_dialog_shows_neutral_text(self):
        try:
            from PySide6.QtWidgets import (QApplication, QMainWindow,
                                           QPlainTextEdit)
        except ImportError:
            self.skipTest("PySide6 not installed")
        from sieve_tray_gui import DOC_AXIS_LABELS, DetailDialog
        if QApplication.instance() is None:
            QApplication([])
        parent = QMainWindow()
        for lang in ("en", "ja"):
            dialog = DetailDialog(
                "t", {"H1": 0}, DOC_AXIS_LABELS[lang], lang,
                evidence={"H1": [self.RAW]}, parent=parent)
            view = dialog.findChild(QPlainTextEdit)
            self.assertIsNotNone(view)
            text = view.toPlainText()
            self.assertNotIn("Unsupported format:", text)
            self.assertIn(tr(lang, "unobserved_format_neutral"), text)
        parent.close()


class TR2_T11_DependencyFloors(unittest.TestCase):
    """TR2-T11: pyproject dependency floors match the measured values
    (lens floor fixed by the design doc; refreshed at the v2.1.0 M2
    update - the scope/referee floors are the published 1.5.0 / 1.6.0,
    measured installing the PyPI wheels in a fresh venv)."""

    def test_lens_floor_is_0220(self):
        # v2.0.0 (M1 Gate): raised to the published 0.22.0 (Gate
        # consumes visible_text; UTF-8 results stay byte-identical).
        # v2.2.0 (Seal, §3.8-4): the dependency rides the html-css-full
        # extra - the floor itself is unchanged.
        deps = _load_pyproject()["project"]["dependencies"]
        self.assertIn("sieve-lens[html-css-full]>=0.22.0", deps)

    def test_other_floors_match_measurement(self):
        deps = _load_pyproject()["project"]["dependencies"]
        # v2.1.0 (M2, request §3.13): raised to the published engines
        # (scope 1.5.0 carries strip_base_sources, referee 1.6.0 the
        # explanation spans) - both on PyPI at the raise time.
        self.assertIn("sieve-scope>=1.5.0", deps)
        self.assertIn("sieve-referee>=1.6.0", deps)


class TR2_T12_Version140(unittest.TestCase):
    """TR2-T12: version across __version__, pyproject and the
    CHANGELOG (pin refreshed for the 2.1.1 release)."""

    def test_version_is_2_0_0(self):
        self.assertEqual(sieve_tray.__version__, "2.1.1")

    def test_pyproject_reads_version_from_module(self):
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('attr = "sieve_tray.__version__"', text)

    def test_changelog_has_140_section(self):
        text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [2.1.1]", text)


if __name__ == "__main__":
    unittest.main()
