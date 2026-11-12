"""TR3-T01..T19 — v1.3.0 engine-update lane (red first).

Pins measured before implementation:
  - Crowd upstream main def0053 (v0.9.0), tree a06c92a6105d9a06932c534aca831b5f306f9d10
  - Redact upstream tag v0.11.0 (ddde4bd),
    sieve_redact.py sha256 9203c747…6836 (72,655 bytes) — refreshed for
    the M1 Gate lane's re-vendoring (0.11.0 is the certified M1
    implementation; the 0.10.0 outputs keep their molds)
  - Pillow floor 10.0.0 measured: getbbox(alpha_only=False) works
    (keyword-only arg present in 10.0.0 and 10.0.1).
  - Redact 0.9.0 (current vendored) leaves the full-width long-vowel
    phone forms 090-1234-5678 and 090-1234-5678 unmasked, and has no
    MAX_IMAGE_PIXELS constant (measured, red basis for TR3-T04/T05).

Golden molds (TR3-T03) re-pin the same values TR2-T04/T05 measured on
the pre-import tree (0d0540a), which also hold on this base (cb083d8):
any drift caused by the engine import fails here.
"""

import hashlib
import importlib
import io
import json
import os
import re
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

import sieve_tray
from sieve_tray import (
    ScanResult,
    UNOBSERVED_REASONS,
    render,
    render_text,
    run_scan,
    sanitize_file,
)
import sieve_tray_i18n
from sieve_tray_i18n import STRINGS

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Upstream pins (measured 2026-11-06).
# ---------------------------------------------------------------------------

CROWD_UPSTREAM_VERSION = "0.9.0"
CLI_090_SHA256 = (
    "a4887a7100fe642a1f2b6119be0456297e6297992a5a00813c578a5f95b8fa29")
BUILTIN_PACK_SHA = (
    "1fae5827a7048ca1e4b92c7d12792a755f5b21e63d6392bc2a1fbdb4e3dc66c4")
TEMPLATE_SHA2 = (
    "0d5c35d82dc54004ad7f34b80be69103a80a0d20dccc4dae22f7e6412ba6c657")
RUN_TABLE_SHA = (
    "b58249febc35c4feb6f6bfe1632aab92ca802c611759d31138d8ae040061500e")

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

# The 8 frozen files keep their v0.8.2 bytes in v0.9.0 (measured identical).
FROZEN_082_SHA256 = {
    "config.py": "3fc0b1f9e95b7f05c88b4bf00f37faa6f529fd9e1c3fa000c54c137bd16d3a3d",
    "engine.py": "d7384c5eb5c6012f731ab9af04e0483ca92316b6b73b980f4a88a3541616dc5d",
    "audit.py": "ccbe07c7f0e1a647bea7b64aaa785264b517484961bfdc6e1a62253ac4f21684",
    "derived.py": "2123cc0d4b2ef5dc5e2ecccf718827512278339e7cf3e02379fa4518e82076f8",
    "chartable.py": "4a01afa04a9678d86a0562ae48a2b578b2dd547247d941762088fcf32405b7a5",
    "hidden_chars.py": "47bd0aa3a83b0b33a39ef8a3d353efd4251f713eefcbfcb834f25317a5a672f5",
    "hintpack.py": "8aa8282680f32ccf7c67a5ada9692c82ecd291374db233a7fcab3f19f607267e",
    "chartable_v1.json": "c5ae4757bc9d07a2dcd1507d662460c3412c932d73318e54912569608242e605",
}

REDACT_UPSTREAM_VERSION = "0.11.0"
REDACT_0100_SHA256 = (
    "9203c7476fbac1eb0f25e75c6f31ea48732b4928b43ad2f641c5f5902c94e836")

# Golden molds (TR3-T03): the TR2-T04/T05 values, which also hold on the
# v1.2.0 base (160 passed includes them) and must keep holding after the
# engine import.
MOLD_WITH_UNOBSERVED_CORE = (
    "73b31e81dd945de0be39a4bb01c2c80884d32260f599e3e5cf9ce78cec5287cd")
# v1.4.0 (design §3.2, TR4): the with-unobserved HTML report intentionally
# changed - the three-stage coloring appends the stage classes to the
# unobserved rows and the stage CSS (the 0-unobserved report and the
# Markdown rendering are byte-identical to v1.3.0; see TR4-T08/T09).
# The v1.3.0 value was cd8181ec8b48d88e11284fa8ec886cea2a76fe231d6f8553d
# be44eb0b2cb7b58.
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

# The 14 refusal codes Crowd 0.9.0's InputRefused can carry (model.py).
CROWD_REFUSAL_CODES = (
    "not_regular_file", "file_too_large", "too_many_entries",
    "part_too_large", "total_too_large", "too_many_elements",
    "doctype_not_allowed", "unsupported_encoding", "duplicate_part",
    "encrypted", "malformed_xml", "main_part_missing",
    "unsupported_namespace", "unsupported_format",
)

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

_FIXTURE_HEADER = ["name", "age", "city", "note"]
_FIXTURE_ROWS = [
    ["Alice", "34", "東京", "memo"],
    ["Bob", "41", "大阪", "note"],
    ["Carol", "34", "東京", "info"],
]
_FIXTURE_CSV_TEXT = (
    "name,age,city,note\n"
    "Alice,34,東京,memo\n"
    "Bob,41,大阪,note\n"
    "Carol,34,東京,info\n")
_FIXTURE_XLSX_SHARED = [
    "name", "age", "city", "note",
    "Alice", "34", "東京", "memo",
    "Bob", "41", "大阪", "note",
    "Carol", "info",
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_tree_text(root: Path, tree: dict):
    for rel, content in tree.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        # newline="" keeps the fixtures LF on every OS: write_text's
        # default newline=None translates \n to os.linesep on Windows,
        # and the engines read the input as bytes, so CRLF fixtures
        # drift the byte pins (run #84: MOLD_REDACT_OUT, the core
        # hashes).
        p.write_text(content, encoding="utf-8", newline="")


def _core_hash(result: ScanResult) -> str:
    blob = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)
    return _sha256(blob.encode("utf-8"))


def _xlsx_bytes(sheets, shared, active=1) -> bytes:
    """Build a minimal .xlsx in memory.

    ``sheets`` is a list of (name, rows[, state]) tuples — state defaults
    to "visible" and may be "hidden". ``shared`` is the shared string
    table (list of str). Every row is [[str_or_int, ...], ...]. Built as
    a sharedStrings-based workbook, the shape the upstream 0.9.0 reader
    consumes.
    """
    import zipfile

    norm = []
    for item in sheets:
        if len(item) == 3:
            name, rows, state = item
        else:
            name, rows, state = item[0], item[1], "visible"
        norm.append((name, rows, state))

    overrides = "".join(
        '<Override PartName="/xl/worksheets/sheet%d.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.spreadsheetml.'
        'worksheet+xml"/>' % (i + 1)
        for i in range(len(norm)))
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
          'content-types">'
          '<Default Extension="rels" ContentType="application/vnd.'
          'openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/'
          'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          + overrides +
          '<Override PartName="/xl/sharedStrings.xml" ContentType='
          '"application/vnd.openxmlformats-officedocument.spreadsheetml.'
          'sharedStrings+xml"/></Types>')

    sheet_names = "".join(
        '<sheet name="%s" sheetId="%d" r:id="rId%d"%s/>'
        % (name, i + 1, i + 1,
           "" if state == "visible" else ' state="%s"' % state)
        for i, (name, _rows, state) in enumerate(norm))
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
        '2006/main" xmlns:r="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships"><sheets>' + sheet_names +
        '</sheets><bookViews><workbookView activeTab="%d"/></bookViews>'
        '</workbook>' % (active - 1))

    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
        '2006/relationships">' +
        "".join(
            '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.'
            'org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1)
            for i in range(len(norm))) +
        '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/sharedStrings" '
        'Target="sharedStrings.xml"/></Relationships>'
        % (len(norm) + 1))

    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/'
        'main" count="%d" uniqueCount="%d">%s</sst>'
        % (len(shared), len(shared),
           "".join("<si><t>%s</t></si>" % s for s in shared)))

    col_names = ["A", "B", "C", "D", "E", "F", "G", "H"]
    sheet_parts = []
    for _name, rows, _state in norm:
        row_xml = []
        for r, row in enumerate(rows, start=1):
            cells = []
            for c, val in enumerate(row):
                ref = col_names[c] + str(r)
                if isinstance(val, int):
                    cells.append('<c r="%s"><v>%d</v></c>' % (ref, val))
                else:
                    idx = shared.index(val)
                    cells.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, idx))
            row_xml.append('<row r="%d">%s</row>' % (r, "".join(cells)))
        sheet_parts.append(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>'
            % "".join(row_xml))

    buf = io.BytesIO()
    names = (
        ["[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
         "xl/_rels/workbook.xml.rels", "xl/sharedStrings.xml"]
        + ["xl/worksheets/sheet%d.xml" % (i + 1) for i in range(len(norm))])
    datas = [
        ct.encode("utf-8"),
        ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
         '2006/relationships"><Relationship Id="rId1" Type="http://'
         'schemas.openxmlformats.org/officeDocument/2006/relationships/'
         'officeDocument" Target="xl/workbook.xml"/></Relationships>'
         ).encode("utf-8"),
        workbook.encode("utf-8"),
        wb_rels.encode("utf-8"),
        shared_xml.encode("utf-8"),
    ] + [p.encode("utf-8") for p in sheet_parts]
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in zip(names, datas):
            z.writestr(n, d)
    return buf.getvalue()


class TR3_T01_VendoredCrowdMatchesUpstream090(unittest.TestCase):
    """TR3-T01: the vendored sieve_crowd/ is byte-identical to upstream
    v0.9.0 (main def0053, tree a06c92a6…9d10); frozen files keep their
    v0.8.2 bytes; cli.py and the pack pins hold."""

    def test_vendored_files_match_090_pins(self):
        vendored = REPO_ROOT / "sieve_crowd"
        self.assertTrue(vendored.is_dir(), "vendored sieve_crowd/ missing")
        actual = {}
        for path in sorted(vendored.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                actual[str(path.relative_to(vendored))] = _sha256(
                    path.read_bytes())
        missing = sorted(set(PINNED_CROWD_090_SHA256) - set(actual))
        extra = sorted(set(actual) - set(PINNED_CROWD_090_SHA256))
        self.assertEqual(missing, [], "missing vendored files")
        self.assertEqual(extra, [], "unexpected vendored files")
        diff = [name for name, sha in sorted(PINNED_CROWD_090_SHA256.items())
                if actual[name] != sha]
        self.assertEqual(diff, [],
                         "files differing from upstream v0.9.0: "
                         + ", ".join(diff))

    def test_frozen_files_keep_082_bytes(self):
        vendored = REPO_ROOT / "sieve_crowd"
        for name, sha in sorted(FROZEN_082_SHA256.items()):
            f = vendored / name
            self.assertTrue(f.is_file(), "frozen file missing: " + name)
            self.assertEqual(_sha256(f.read_bytes()), sha,
                             "frozen file drifted: " + name)

    def test_cli_sha256_pin(self):
        cli = REPO_ROOT / "sieve_crowd" / "cli.py"
        self.assertEqual(_sha256(cli.read_bytes()), CLI_090_SHA256)

    def test_pack_pins_hold(self):
        mod = importlib.import_module("sieve_crowd.hintpack_builtin")
        self.assertEqual(_sha256(mod.BUILTIN_PACK_BYTES), BUILTIN_PACK_SHA)
        self.assertEqual(
            _sha256((REPO_ROOT / "sieve_crowd" / "chartable_v1.json")
                    .read_bytes()),
            FROZEN_082_SHA256["chartable_v1.json"])
        fixtures = Path(__file__).resolve().parent / "fixtures_crowd_082"
        import contextlib
        buf_out, buf_err = io.StringIO(), io.StringIO()
        from sieve_crowd.cli import main as crowd_cli_main
        with tempfile.TemporaryDirectory() as d:
            tpl = Path(d) / "t.json"
            try:
                with contextlib.redirect_stdout(buf_out), \
                        contextlib.redirect_stderr(buf_err):
                    crowd_cli_main([
                        "inspect", str(fixtures / "people.csv"),
                        "--config-out", str(tpl)])
                rc = 0
            except SystemExit as exc:
                rc = exc.code if isinstance(exc.code, int) else 1
            self.assertEqual(rc, 0)
            self.assertEqual(_sha256(tpl.read_bytes()), TEMPLATE_SHA2)
            out = Path(d) / "out.csv"
            try:
                with contextlib.redirect_stdout(buf_out), \
                        contextlib.redirect_stderr(buf_err):
                    crowd_cli_main([
                        "run", str(fixtures / "people.csv"),
                        "-c", str(fixtures / "config.json"),
                        "-o", str(out), "--quiet"])
                rc = 0
            except SystemExit as exc:
                rc = exc.code if isinstance(exc.code, int) else 1
            self.assertEqual(rc, 0)
            self.assertEqual(_sha256(out.read_bytes()), RUN_TABLE_SHA)


class TR3_T02_VendoredRedactMatchesUpstream0110(unittest.TestCase):
    """TR3-T02: the vendored sieve_redact.py is byte-identical to
    upstream v0.11.0 (pin refreshed for the M1 Gate lane; the constant
    keeps its 0100 name for diffing)."""

    def test_vendored_module_matches_pin(self):
        vendored = REPO_ROOT / "sieve_redact.py"
        self.assertTrue(vendored.is_file(), "vendored sieve_redact.py missing")
        actual = _sha256(vendored.read_bytes())
        self.assertEqual(actual, REDACT_0100_SHA256)


class TR3_T03_GoldenMoldLensScopeReportUnchanged(unittest.TestCase):
    """TR3-T03: the Lens/Scope pipeline, unobserved classification and
    both report renderings stay byte-identical to v1.2.0, with and
    without unobserved files."""

    def _scan(self, tmp: str, tree: dict, with_extras: bool):
        root = Path(tmp)
        _write_tree_text(root, tree)
        if with_extras:
            self._make_frozen_docx(root / "in/g2/frozen.docx")
            os.symlink("note.txt", root / "in/g1/link.txt")
        old = os.getcwd()
        os.chdir(root)
        try:
            result = run_scan(Path("in"))
        finally:
            os.chdir(old)
        return result

    @staticmethod
    def _make_frozen_docx(path: Path):
        """A minimal .docx whose word/document.xml carries a DOCTYPE —
        Lens refuses it with the known code doctype_not_allowed."""
        import zipfile
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><Types xmlns="http://schemas.'
                'openxmlformats.org/package/2006/content-types"><Default '
                'Extension="xml" ContentType="application/xml"/></Types>')
            z.writestr(
                "word/document.xml",
                '<?xml version="1.0"?><!DOCTYPE w:document [<!ENTITY x "y">]>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p/></w:body>'
                '</w:document>')

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


class TR3_T04_RedactPhoneLongVowelForms(unittest.TestCase):
    """TR3-T04: the existing text anonymization mold is unchanged, and
    the long-vowel phone forms are observed and masked."""

    def test_mold_unchanged_and_phone_forms_observed(self):
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
            self.assertEqual(_sha256(out.read_bytes()), MOLD_REDACT_OUT)

        with tempfile.TemporaryDirectory() as d:
            work = Path(d)
            sample = work / "s.txt"
            sample.write_text(
                "連絡先 090-1234-5678 / 090ー1234ー5678 / 090ｰ1234ｰ5678\n",
                encoding="utf-8")
            cfg = work / "c.txt"
            cfg.write_text("builtin phone-jp:delete\n", encoding="utf-8")
            out = work / "o.txt"
            res = sanitize_file(sample, cfg, out)
            self.assertTrue(res["ok"])
            self.assertEqual(res["rc"], 0)
            text = out.read_text(encoding="utf-8")
            self.assertNotIn("090", text,
                             "long-vowel phone forms left unmasked: " + text)
            self.assertNotIn("1234", text)
            # each of the three forms contributed a redaction
            self.assertGreaterEqual(res["masked_count"], 3)


class TR3_T05_RedactPixelLimitRefusal(unittest.TestCase):
    """TR3-T05: images beyond Redact's pixel limit are refused by the
    engine with a readable message through Tray's existing error path,
    without a traceback."""

    def test_engine_carries_max_image_pixels(self):
        mod = importlib.import_module("sieve_redact")
        self.assertTrue(hasattr(mod, "MAX_IMAGE_PIXELS"),
                        "sieve_redact.py has no MAX_IMAGE_PIXELS constant")
        self.assertEqual(mod.MAX_IMAGE_PIXELS, 64_000_000)

    def test_pixel_limit_refusal_is_readable_no_traceback(self):
        # A PNG that declares 8192x8192 (67,108,864 > 64,000,000 pixels)
        # in its IHDR but carries a single pixel of data. CRCs are valid.
        # 0.10.0 reads the dimensions and refuses before decoding.
        def chunk(ctype, payload):
            c = ctype + payload
            return (struct.pack(">I", len(payload)) + c
                    + struct.pack(">I", zlib.crc32(c) & 0xffffffff))

        ihdr = struct.pack(">IIBBBBB", 8192, 8192, 8, 6, 0, 0, 0)
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
               + chunk(b"IDAT", zlib.compress(b"\x00\x40\x50\x60\xff"))
               + chunk(b"IEND", b""))
        with tempfile.TemporaryDirectory() as d:
            work = Path(d)
            img = work / "big.png"
            img.write_bytes(png)
            cfg = work / "c.txt"
            cfg.write_text("region 0,0,10,10:delete\n", encoding="utf-8")
            out = work / "o.png"
            res = sanitize_file(img, cfg, out)
            self.assertFalse(res["ok"])
            self.assertEqual(res["rc"], 2)
            self.assertIn("image too large", res["stderr"],
                          "refusal message does not name the pixel limit: "
                          + res["stderr"])
            self.assertIn("limit", res["stderr"])
            self.assertNotIn("Traceback", res["stderr"],
                             "a traceback leaked through the error path")


class TR3_T06_PillowFloorSupportsAlphaOnly(unittest.TestCase):
    """TR3-T06: the gui extra's Pillow floor supports the call Redact
    0.10.0 makes (measured: 10.0.0 and 10.0.1 both provide the
    keyword-only alpha_only argument)."""

    def test_pyproject_pillow_floor_and_signature(self):
        import tomllib
        with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
            proj = tomllib.load(fh)["project"]
        pillow = [d for d in proj["optional-dependencies"]["gui"]
                  if d.lower().startswith("pillow")]
        self.assertEqual(pillow, ["Pillow>=10.0"])
        import inspect
        from PIL import Image
        params = inspect.signature(Image.Image.getbbox).parameters
        self.assertIn("alpha_only", params)
        p = params["alpha_only"]
        self.assertTrue(p.kind in (p.KEYWORD_ONLY, p.POSITIONAL_OR_KEYWORD))
        self.assertEqual(p.default, True)


class TR3_T07_CrowdTabReadsThroughV090InputLayer(unittest.TestCase):
    """TR3-T07: the Crowd tab's input read goes through the 0.9.0 input
    layer. UTF-8 CSV results are identical to the v1.2.0 path; CP932 CSV
    and .xlsx match the same-content UTF-8 CSV."""

    def _legacy_read(self, path: Path):
        """The v1.2.0 read path (read_any), for the identity pin."""
        from sieve_crowd.tableio import detect_format, read_any
        data = path.read_bytes()
        fmt = detect_format(path.suffix)
        return read_any(data, fmt)

    def test_utf8_csv_matches_v120_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "people.csv"
            p.write_text(_FIXTURE_CSV_TEXT, encoding="utf-8")
            header, rows = self._legacy_read(p)
            header2, rows2, notices = sieve_tray.crowd_read_table(p)
            self.assertEqual((header, rows), (header2, rows2))
            self.assertEqual(notices, [])

    def test_cp932_csv_matches_utf8_csv(self):
        with tempfile.TemporaryDirectory() as d:
            p_u = Path(d) / "u.csv"
            p_u.write_text(_FIXTURE_CSV_TEXT, encoding="utf-8")
            p_c = Path(d) / "c.csv"
            p_c.write_bytes(_FIXTURE_CSV_TEXT.encode("cp932"))
            h_u, r_u, n_u = sieve_tray.crowd_read_table(p_u)
            h_c, r_c, n_c = sieve_tray.crowd_read_table(p_c)
            self.assertEqual((h_u, r_u), (h_c, r_c),
                             "CP932 CSV does not match the same-content "
                             "UTF-8 CSV")
            self.assertEqual(n_c, ["input encoding: cp932 (auto)"])
            self.assertEqual(n_u, [])

    def test_xlsx_matches_csv(self):
        rows = _FIXTURE_ROWS
        with tempfile.TemporaryDirectory() as d:
            p_c = Path(d) / "t.csv"
            p_c.write_text(_FIXTURE_CSV_TEXT, encoding="utf-8")
            p_x = Path(d) / "t.xlsx"
            p_x.write_bytes(_xlsx_bytes(
                [("Sheet1", [_FIXTURE_HEADER] + rows)],
                _FIXTURE_XLSX_SHARED))
            h_c, r_c, _n = sieve_tray.crowd_read_table(p_c)
            h_x, r_x, n_x = sieve_tray.crowd_read_table(p_x)
            self.assertEqual((h_c, r_c), (h_x, r_x),
                             ".xlsx does not match the same-content CSV")
            # upstream policy: a single visible sheet is silent; the
            # workbook notice fires for multiple sheets or a hidden
            # sheet (pinned in TR3-T09)
            self.assertEqual(n_x, [])


class TR3_T08_CrowdFileFilterAndContainerRefusal(unittest.TestCase):
    """TR3-T08: the file dialog filter includes *.xlsx (static), and
    .xls/.xlsm reach the engine's unsupported_format refusal."""

    def test_filter_includes_xlsx(self):
        for lang in ("en", "ja"):
            filt = STRINGS[lang]["crowd_file_filter"]
            self.assertIn("*.xlsx", filt, lang + " filter lacks *.xlsx")

    def test_xls_xlsm_refused_unsupported_format(self):
        from sieve_crowd.model import InputRefused
        with tempfile.TemporaryDirectory() as d:
            for suffix in (".xls", ".xlsm"):
                p = Path(d) / ("t" + suffix)
                p.write_text(_FIXTURE_CSV_TEXT, encoding="utf-8")
                with self.assertRaises(InputRefused) as cm:
                    sieve_tray.crowd_read_table(p)
                self.assertEqual(cm.exception.code, "unsupported_format",
                                 suffix)


class TR3_T09_CrowdNoticesSurvive(unittest.TestCase):
    """TR3-T09: Crowd's stderr-equivalent notices reach the result
    details, are never lost, and never enter the table area or the
    history payload."""

    def test_cp932_notice_is_separate_from_table(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.csv"
            p.write_bytes(_FIXTURE_CSV_TEXT.encode("cp932"))
            header, rows, notices = sieve_tray.crowd_read_table(p)
            self.assertIsInstance(notices, list)
            self.assertEqual(notices, ["input encoding: cp932 (auto)"])
            # the notice never leaks into the table payload
            self.assertNotIn("input encoding", "\n".join(header))
            for row in rows:
                for cell in row:
                    self.assertNotIn("input encoding", cell)

    def test_xlsx_workbook_notices_pass_through(self):
        rows = _FIXTURE_ROWS
        shared = _FIXTURE_XLSX_SHARED
        with tempfile.TemporaryDirectory() as d:
            # two sheets, one hidden: both notice kinds must survive
            p = Path(d) / "t.xlsx"
            p.write_bytes(_xlsx_bytes(
                [("Sheet1", [_FIXTURE_HEADER] + rows),
                 ("Sheet2", rows, "hidden")], shared))
            _h, _r, notices = sieve_tray.crowd_read_table(p)
            self.assertTrue(notices, "notices list is empty")
            self.assertTrue(all(isinstance(n, str) and n for n in notices))
            self.assertTrue(any("sheet" in n.lower() for n in notices),
                            repr(notices))

    def test_notices_stay_out_of_history_and_have_label(self):
        from sieve_tray_storage import CROWD_PAYLOAD_ALLOWLIST
        self.assertNotIn("notices", CROWD_PAYLOAD_ALLOWLIST)
        self.assertNotIn("header", CROWD_PAYLOAD_ALLOWLIST)
        self.assertNotIn("rows", CROWD_PAYLOAD_ALLOWLIST)
        for lang in ("en", "ja"):
            self.assertIn("crowd_notes_label", STRINGS[lang])


class TR3_T10_CrowdRefusalCodesDisplayed(unittest.TestCase):
    """TR3-T10: Crowd's InputRefused codes surface as the code itself or
    an i18n wording (per-code, en/ja symmetric), never with values."""

    def test_all_refusal_codes_have_symmetric_wording(self):
        for code in CROWD_REFUSAL_CODES:
            key = "crowd_refusal_" + code
            for lang in ("en", "ja"):
                self.assertIn(key, STRINGS[lang],
                              key + " missing in " + lang)
            en = STRINGS["en"][key]
            ja = STRINGS["ja"][key]
            self.assertTrue(en and ja)
            self.assertNotEqual(en, ja, key + " en/ja wording identical")

    def test_refusal_message_contract(self):
        msg = sieve_tray.crowd_refusal_message("encrypted", "en")
        self.assertEqual(msg, STRINGS["en"]["crowd_refusal_encrypted"])
        msg_ja = sieve_tray.crowd_refusal_message("encrypted", "ja")
        self.assertEqual(msg_ja, STRINGS["ja"]["crowd_refusal_encrypted"])
        # unknown code falls through to the code itself
        self.assertEqual(sieve_tray.crowd_refusal_message("weird", "en"),
                         "weird")
        self.assertEqual(sieve_tray.crowd_refusal_message("weird", "ja"),
                         "weird")
        # no values are interpolated: the wording has no format slots
        for lang in ("en", "ja"):
            for code in CROWD_REFUSAL_CODES:
                self.assertNotIn("%", STRINGS[lang]["crowd_refusal_" + code],
                                 "format slot in " + lang + "/" + code)


class TR3_T11_CrowdHistoryAllowlistHolds(unittest.TestCase):
    """TR3-T11: the allowlist still never stores table data; no new
    output items crept in with 0.9.0; old history rows load."""

    FORBIDDEN = {"header", "rows", "report_json", "io", "ok",
                 "before_alone", "after_alone", "k_requested",
                 "config_path", "notices"}

    def test_allowlist_excludes_table_data_and_notices(self):
        from sieve_tray_storage import CROWD_PAYLOAD_ALLOWLIST
        self.assertEqual(CROWD_PAYLOAD_ALLOWLIST & self.FORBIDDEN, set())

    def test_090_output_items_all_known(self):
        # 0.9.0 left report.py and inspect.py unchanged (measured):
        # the summary keys the GUI reads are the same set as 0.8.2. The
        # allowlist therefore needs no new entries.
        summary_keys = {
            "input_path", "output_path", "records_in", "records_out",
            "suppressed", "k_requested", "k_achieved", "max_risk",
            "avg_risk", "before_alone", "after_alone", "status", "reason",
            "header", "rows", "report_text", "report_json", "io", "ok",
        }
        from sieve_tray_storage import CROWD_PAYLOAD_ALLOWLIST
        for key in CROWD_PAYLOAD_ALLOWLIST:
            self.assertIn(key, summary_keys, "unexpected allowlist key: "
                          + key)
        # old history rows still load (same storage contract)
        from sieve_tray_storage import Storage
        with tempfile.TemporaryDirectory() as d:
            st = Storage(Path(d) / "history.db")
            st.save_crowd_run({
                "input_path": "old.csv", "records_in": 3, "records_out": 3,
                "suppressed": 0, "k_achieved": 2, "status": "anonymized",
                "report_text": "Records: 3 in, 3 out (0 suppressed, 0.0%)",
                "header": ["secret"], "rows": [["x"]],
            })
            rec = st.load_crowd_runs(limit=5)[0]
            self.assertEqual(rec["input_path"], "old.csv")
            self.assertNotIn("header", rec)
            self.assertNotIn("rows", rec)


class TR3_T12_TrayOwnReadsCharacterCode(unittest.TestCase):
    """TR3-T12: Tray's own .py/.txt/.md reads apply the series-wide
    character-code policy: BOM UTF-8 / UTF-8 / CP932 give the same
    result for the same content; anything else is an unobserved
    'refused' with detail 'unsupported_encoding'; no replacement
    characters; UTF-16 BOMs are refused too."""

    NOTE = "このメモは第一版である。修正は金曜日に行う。\n似た文は第二版にある。\n"

    def _tree(self):
        return {
            "in/g1/a.py": PY_A,
            "in/g1/b.py": PY_A.replace("[1, 2, 3]", "[1, 2, 4]"),
            "in/g1/note.txt": self.NOTE,
            "in/g1/note_b.txt": self.NOTE.replace("第一版", "第二版"),
            "in/g2/doc.md": "# Memo\n\nunrelated body text\n",
        }

    def test_cp932_text_matches_utf8_results(self):
        with tempfile.TemporaryDirectory() as d1, \
                tempfile.TemporaryDirectory() as d2:
            root_u = Path(d1)
            root_c = Path(d2)
            _write_tree_text(root_u, self._tree())
            self._cp932_variant(root_c)
            r_u = self._scan_prepared(root_u)
            r_c = self._scan_prepared(root_c)
            pairs_u = [p for p in r_u.text_pairs if "note" in p["a"]
                       and "note" in p["b"]]
            pairs_c = [p for p in r_c.text_pairs if "note" in p["a"]
                       and "note" in p["b"]]
            self.assertTrue(pairs_u, "UTF-8 pair missing (base sanity)")
            self.assertTrue(pairs_c,
                            "CP932 text did not produce the same pair")
            self.assertEqual(len(pairs_u), len(pairs_c))
            self.assertEqual(pairs_u[0]["mask"], pairs_c[0]["mask"],
                             "CP932 text and its UTF-8 twin disagree")
            self.assertEqual(pairs_u[0]["signal"], pairs_c[0]["signal"])

    def _cp932_variant(self, root: Path):
        tree = self._tree()
        for rel, content in tree.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if rel == "in/g1/note_b.txt":
                p.write_bytes(content.encode("cp932"))
            elif rel.startswith("in/g1/a.py") or rel == "in/g1/b.py":
                p.write_bytes(content.encode("cp932"))
            else:
                p.write_text(content, encoding="utf-8")

    def _scan_prepared(self, root: Path):
        old = os.getcwd()
        os.chdir(root)
        try:
            return run_scan(Path("in"))
        finally:
            os.chdir(old)

    def test_unsupported_encoding_is_refused(self):
        tree = self._tree()
        tree["in/g2/latin1.py"] = "x = 'caf\xe9'\n"  # Latin-1 only
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel, content in tree.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                if rel == "in/g2/latin1.py":
                    p.write_bytes(content.encode("latin-1"))
                elif rel == "in/g1/note_b.txt":
                    p.write_bytes(content.encode("cp932"))
                else:
                    p.write_text(content, encoding="utf-8")
            result = self._scan_prepared(root)
            refused = [e for e in result.unobserved
                       if e["reason"] == "refused"]
            self.assertTrue(refused,
                            "no refused entry for the Latin-1 file")
            entry = [e for e in refused if "latin1" in e["file"]][0]
            self.assertEqual(entry["detail"], "unsupported_encoding")
            self.assertEqual(entry["engine"], "scope")

    def test_no_replacement_char_leaks(self):
        tree = self._tree()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel, content in tree.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                if rel in ("in/g1/a.py", "in/g1/b.py"):
                    p.write_bytes(content.encode("cp932"))
                elif rel == "in/g1/note_b.txt":
                    p.write_bytes(content.encode("cp932"))
                else:
                    p.write_text(content, encoding="utf-8")
            result = self._scan_prepared(root)
            blob = json.dumps(result.to_dict(), ensure_ascii=False,
                              sort_keys=True)
            self.assertNotIn("\ufffd", blob,
                             "a replacement character leaked into results")
            self.assertNotIn("\u25a1", blob)

    def test_utf16_bom_refused(self):
        tree = self._tree()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel, content in tree.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                if rel == "in/g1/note_b.txt":
                    p.write_bytes(content.encode("utf-16"))  # BOM + UTF-16
                elif rel in ("in/g1/a.py", "in/g1/b.py"):
                    p.write_bytes(content.encode("cp932"))
                else:
                    p.write_text(content, encoding="utf-8")
            result = self._scan_prepared(root)
            refused = [e for e in result.unobserved
                       if e["reason"] == "refused"]
            entry = [e for e in refused if "note_b" in e["file"]]
            self.assertTrue(entry, "UTF-16 BOM file was not refused")
            self.assertEqual(entry[0]["detail"], "unsupported_encoding")


class TR3_T13_EngineSkippedFlowsToUnobserved(unittest.TestCase):
    """TR3-T13: Scope's skipped entries and scores:null pairs flow into
    the unobserved list; engines without the keys keep the v1.2.0
    behavior."""

    ANALYSIS_SKIPPED = {
        "skipped": [
            {"path": "g1/deep.py", "reason": "parse_failed"},
            {"path": "g1/empty.py", "reason": "not_applicable"},
        ],
        "pair_results": {
            ("g1/a.py", "g1/b.py"): {
                "mask": "0000",
                "h_states": {"H1": 0, "H2": 0, "H3": 0, "H4": 0},
                "scores": None,
            },
        },
    }

    def test_scope_skipped_flows_to_unobserved(self):
        pairs, excluded, skipped = sieve_tray._scope_pairs_from_analysis(
            self.ANALYSIS_SKIPPED)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["scores"], {})
        files = [e["file"] for e in skipped]
        self.assertIn("g1/deep.py", files)
        reasons = {e["file"]: e["reason"] for e in skipped}
        self.assertEqual(reasons["g1/deep.py"], "parse_failed")
        self.assertEqual(reasons["g1/empty.py"], "not_applicable")

    def test_scores_null_pair_is_safe(self):
        # must not raise TypeError: dict(None)
        pairs, _excluded, _skipped = (
            sieve_tray._scope_pairs_from_analysis(self.ANALYSIS_SKIPPED))
        self.assertIsInstance(pairs[0]["scores"], dict)

    def test_missing_keys_keep_v120_behavior(self):
        analysis = {
            "pair_results": {
                ("g1/a.py", "g1/b.py"): {
                    "mask": "0100",
                    "h_states": {"H1": 0, "H2": 1, "H3": 0, "H4": 0},
                    "scores": {"coverage": 0.5},
                },
            },
            # no 'skipped' key at all (scope 1.3.0)
        }
        pairs, excluded, skipped = sieve_tray._scope_pairs_from_analysis(
            analysis)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["scores"], {"coverage": 0.5})
        self.assertEqual(excluded, 0)
        self.assertEqual(skipped, [])

    def test_referee_without_skipped_key_is_unchanged(self):
        # referee 1.5.0's batch_evaluate returns results without any
        # skipped payload; compare_text must behave exactly as v1.2.0.
        from types import SimpleNamespace
        import sieve_tray as core

        fake = SimpleNamespace(
            item_id="g1/a.txt", matched_peer_id="g2/b.txt", mask="1000",
            pattern_name="paraphrase", reason="rephrased",
            evaluation_signal=SimpleNamespace(value="RED"),
            structural_density=0.5, max_structure_similarity=0.9,
            max_content_similarity=0.8, coverage=0.7,
        )
        original = sys.modules.get("sieve_referee")
        try:
            class _Mod:
                @staticmethod
                def batch_evaluate(text_map):
                    return [fake]
            sys.modules["sieve_referee"] = _Mod
            pairs = core.compare_text({"g1/a.txt": "x", "g2/b.txt": "y"})
        finally:
            if original is not None:
                sys.modules["sieve_referee"] = original
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["a"], "g1/a.txt")
        self.assertEqual(pairs[0]["mask"], "1000")


class TR3_T14_UnobservedMergeDedupesByPath(unittest.TestCase):
    """TR3-T14: Tray's own classification and an engine's skipped entry
    pointing at the same path count once; the engine's reason wins."""

    def test_merge_dedupe_and_engine_priority(self):
        existing = [
            {"file": "in/g1/a.py", "engine": "scope",
             "reason": "not_applicable", "detail": None},
            {"file": "in/g1/b.py", "engine": "scope",
             "reason": "parse_failed", "detail": None},
        ]
        incoming = [
            {"file": "in/g1/a.py", "engine": "scope",
             "reason": "parse_failed", "detail": None},
        ]
        merged = sieve_tray._merge_unobserved(existing, incoming)
        a_entries = [e for e in merged if e["file"] == "in/g1/a.py"]
        self.assertEqual(len(a_entries), 1,
                         "path counted twice: " + repr(merged))
        self.assertEqual(a_entries[0]["reason"], "parse_failed",
                         "engine reason did not win")
        # untouched entries survive
        self.assertTrue(any(e["file"] == "in/g1/b.py" for e in merged))


class TR3_T15_OutOfVocabReasonDropsToParseFailed(unittest.TestCase):
    """TR3-T15: an out-of-vocabulary engine reason falls to
    parse_failed; the original string never surfaces; the vocabulary
    stays the fixed 8 kinds."""

    def test_out_of_vocab_and_vocab_still_8(self):
        analysis = {
            "skipped": [
                {"path": "g1/odd.py", "reason": "weird_reason"},
            ],
            "pair_results": {},
        }
        _pairs, _excluded, skipped = (
            sieve_tray._scope_pairs_from_analysis(analysis))
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["reason"], "parse_failed")
        blob = json.dumps(skipped)
        self.assertNotIn("weird_reason", blob,
                         "the out-of-vocab string leaked")
        self.assertEqual(
            UNOBSERVED_REASONS,
            {"refused", "parse_failed", "unreadable", "too_large",
             "symlink_skipped", "engine_unavailable", "not_applicable",
             "empty_input"})


class TR3_T16_NewI18nKeysSymmetric(unittest.TestCase):
    """TR3-T16: the new i18n keys exist in both en and ja with matching
    structure; no hardcoded strings were added to the GUI code paths."""

    NEW_KEYS = ["crowd_notes_label"] + [
        "crowd_refusal_" + c for c in CROWD_REFUSAL_CODES]

    def test_new_keys_exist_in_both_languages(self):
        for key in self.NEW_KEYS:
            for lang in ("en", "ja"):
                self.assertIn(key, STRINGS[lang],
                              key + " missing in " + lang)
                value = STRINGS[lang][key]
                self.assertIsInstance(value, str)
                self.assertTrue(value.strip())

    def test_no_format_slot_mismatch(self):
        # keys without parameters must have none in either language
        for key in self.NEW_KEYS:
            en = STRINGS["en"][key]
            ja = STRINGS["ja"][key]
            self.assertEqual(en.count("{"), ja.count("{"),
                             key + " placeholder count differs")


class TR3_T17_ReadmeEnJaAligned(unittest.TestCase):
    """TR3-T17: README.md and README.ja.md share the same heading
    structure and the same version; no limitations-listing section was
    added (static check)."""

    def test_headings_and_version_align(self):
        en = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        ja = (REPO_ROOT / "README.ja.md").read_text(encoding="utf-8")
        en_h1 = re.search(r"^# (.+)$", en, re.M).group(1)
        ja_h1 = re.search(r"^# (.+)$", ja, re.M).group(1)
        self.assertIn("v1.4.0", en_h1, "en H1 is not v1.4.0: " + en_h1)
        self.assertIn("v1.4.0", ja_h1, "ja H1 is not v1.4.0: " + ja_h1)
        en_h2 = re.findall(r"^## (.+)$", en, re.M)
        ja_h2 = re.findall(r"^## (.+)$", ja, re.M)
        self.assertEqual(len(en_h2), len(ja_h2),
                         "## heading counts differ: %d vs %d"
                         % (len(en_h2), len(ja_h2)))
        # the pre-existing Known Limitations section stays as it is:
        # not removed, not extended (design doc §3.6 - a reader-facing
        # list of limits is not grown for this release)
        limit_en = [h for h in en_h2
                    if "limitation" in h.lower()]
        limit_ja = [h for h in ja_h2 if "制限" in h]
        self.assertEqual(len(limit_en), 1,
                         "en limitations sections: %r" % limit_en)
        self.assertEqual(len(limit_ja), 1,
                         "ja limitations sections: %r" % limit_ja)


class TR3_T18_DependencyFloorsStayPublished(unittest.TestCase):
    """TR3-T18: the floors reference published versions only; the
    Pillow floor matches TR3-T06's measurement."""

    def test_dependency_floors(self):
        import tomllib
        with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
            proj = tomllib.load(fh)["project"]
        # v2.1.0 (M2, request §3.13): the floors are the published
        # engines (scope 1.5.0 / referee 1.6.0 on PyPI at the raise).
        self.assertEqual(
            proj["dependencies"],
            ["sieve-lens>=0.22.0", "sieve-scope>=1.5.0",
             "sieve-referee>=1.6.0"])
        gui = proj["optional-dependencies"]["gui"]
        self.assertIn("Pillow>=10.0", gui)


class TR3_T19_Version140(unittest.TestCase):
    """TR3-T19: __version__ and pyproject agree on 2.1.0 and the
    CHANGELOG carries a [2.1.0] section (pin refreshed for the M2
    Cohort lane; the floors are the published scope 1.5.0 /
    referee 1.6.0)."""

    def test_version_is_140(self):
        self.assertEqual(sieve_tray.__version__, "2.1.0")

    def test_changelog_has_140(self):
        text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [2.1.0]", text)
