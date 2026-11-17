"""Canon 2.3.0 (request 2026-11-15): the metadata clean, the text and
JSON / CSV normalization, and the table diff.

Everything in this module rides the existing receipt frame of
sieve_tray (the shared `_gate_*` helpers are imported lazily to keep
the import acyclic) and the deterministic-zip rules of Seal.  No new
external dependency: JPEG / PNG / Office byte structures are handled
with the standard library only (request §2-3: `clean` does not depend
on Pillow and does not import it).

Vocabulary rules (request §3.6-3 and the shared header of sieve_tray):
the verify words stay closed; the new words this module uses are the
ones the request mandates - the 8 observation categories, the 3
in-content kinds, the 5 mojibake signs, the 5 table states,
`encoding_unknown`, `json_duplicate_key`, `json_invalid_number`,
`json_number_unsafe`, `csv_ragged_rows` - plus the existing closed
reasons (`parse_failed`, `unreadable`, `not_applicable`, ...).
"""
import codecs
import csv
import hashlib
import html
import io
import json
import re
import unicodedata
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# the closed vocabularies (request §3.1-10, §3.1-11, §3.2-2, §3.5-3)

CN_META_CATEGORIES = (
    "author", "time", "software", "location", "device",
    "title_subject", "thumbnail", "custom")

CN_IN_CONTENT = ("comment", "tracked_change", "hidden_part")

CN_MOJIBAKE_SIGNS = (
    "replacement_char", "c1_controls", "nul_bytes",
    "utf8_invalid", "mixed_newlines")

CN_TABLE_STATES = ("same", "changed", "removed", "added", "duplicate_key")

# §3.2-3: the fixed candidate order for the strictly-readable codecs.
# No codec that decodes everything (latin-1) - the list only reports
# codecs that can read the bytes strictly.
CN_CANDIDATE_ORDER = (
    "utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be",
    "cp932", "euc-jp")

# §3.2: the text extensions a folder walk offers to normalize.  A
# single named file is always processed (the user named it); the
# folder walk filters by this closed set and reports the rest with the
# existing not_applicable word.
CN_TEXT_EXTS = frozenset(
    {".txt", ".md", ".csv", ".json", ".log", ".xml", ".yaml", ".yml"})

CN_CLEAN_EXTS = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png",
                 ".docx": "office", ".xlsx": "office", ".pptx": "office"}

# §3.1-8: the Office output zip rides the pack rules; the constants
# are pinned against sieve_tray._SEAL_ZIP_* by tests/test_canon_common.py.
_CN_ZIP_STAMP = (1980, 1, 1, 0, 0, 0)
_CN_ZIP_FILE_ATTR = 0o100644 << 16
_CN_ZIP_DIR_ATTR = (0o040755 << 16) | 0x10

CN_RECEIPT_VERSION = 1

# the BOM table, longest first (the UTF-32 BOMs start with the UTF-16
# LE/BE BOM bytes, so the 4-byte kinds must win)
_CN_BOMS = (
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


# ---------------------------------------------------------------------------
# the deterministic zip (the pack rules; request §3.1-8)

def _cn_write_deterministic_zip(path: Path, members) -> None:
    """Write a deterministic zip: entries sorted by the UTF-8 bytes of
    the archive name, the fixed 1980 stamp, create_system 3, the fixed
    external attributes, ZIP_STORED.  `members` is a list of
    (arcname, data) tuples."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for arcname, data in sorted(
                members, key=lambda m: str(m[0]).encode("utf-8")):
            name = str(arcname)
            zi = zipfile.ZipInfo(name, date_time=_CN_ZIP_STAMP)
            zi.create_system = 3
            if name.endswith("/"):
                zi.external_attr = _CN_ZIP_DIR_ATTR
            else:
                zi.external_attr = _CN_ZIP_FILE_ATTR
            zi.compress_type = zipfile.ZIP_STORED
            zf.writestr(zi, data)


# ---------------------------------------------------------------------------
# the text observation (request §3.2-1, §3.2-2)

def _cn_detect_bom(data: bytes):
    for bom, kind in _CN_BOMS:
        if data.startswith(bom):
            return kind, data[len(bom):]
    return None, data


def _cn_newline_counts(text: str) -> dict:
    crlf = text.count("\r\n")
    cr = text.count("\r") - crlf
    lf = text.count("\n") - crlf
    kinds = sum(1 for n in (lf, crlf, cr) if n > 0)
    return {"lf": lf, "crlf": crlf, "cr": cr,
            "mixed": 1 if kinds > 1 else 0}


def _cn_strict_decode(data: bytes, codec: str):
    try:
        return data.decode(codec)
    except (UnicodeDecodeError, LookupError, ValueError):
        return None


def _cn_strict_candidates(data: bytes):
    """The strictly-readable candidates in the fixed order (§3.2-3)."""
    out = []
    for codec in CN_CANDIDATE_ORDER:
        if codec == "utf-8":
            continue          # the UTF-8 case is the known first branch
        if _cn_strict_decode(data, codec) is not None:
            out.append(codec)
    return out


def _cn_observe_text(data: bytes) -> dict:
    """The always-on observation of one text file (§3.2-1).  The
    UTF-8 validity question applies only when the file claims to be
    UTF-8 (no BOM or a UTF-8 BOM); with a UTF-16/32 BOM the answer is
    null and the utf8_invalid sign stays 0 (the context is not broken
    UTF-8).  Newlines and NUL are counted in the decoded text when a
    strict decode exists, else on the raw bytes."""
    bom, body = _cn_detect_bom(data)
    utf8_valid = None
    if bom is None:
        utf8_valid = _cn_strict_decode(data, "utf-8") is not None
    elif bom == "utf-8":
        utf8_valid = True
    # the decode context for the decoded-level signs: BOM codec, then
    # strict UTF-8, then the first strictly-readable candidate
    text = None
    resolved = None
    if bom is not None:
        text = _cn_strict_decode(body, bom)
        resolved = bom if text is not None else None
    if text is None and bom is None and utf8_valid:
        text = body.decode("utf-8")
        resolved = "utf-8"
    if text is None and bom is None:
        for codec in CN_CANDIDATE_ORDER:
            if codec == "utf-8":
                continue
            text = _cn_strict_decode(data, codec)
            if text is not None:
                resolved = codec
                break
    if text is not None:
        nl = _cn_newline_counts(text)
        nul = text.count("\x00")
        repl = text.count("\ufffd")
        c1 = sum(1 for ch in text if 0x80 <= ord(ch) <= 0x9f)
    else:
        nl = _cn_newline_counts_bytes(data)
        nul = data.count(b"\x00")
        repl = 0
        c1 = 0
    utf8_invalid = 1 if (bom is None and utf8_valid is False) else 0
    return {
        "bom": bom,
        "encoding_resolved": resolved,
        "utf8_valid": utf8_valid,
        "newlines": {"lf": nl["lf"], "crlf": nl["crlf"], "cr": nl["cr"]},
        "nul_bytes": nul,
        "signs": {
            "replacement_char": repl,
            "c1_controls": c1,
            "nul_bytes": nul,
            "utf8_invalid": utf8_invalid,
            "mixed_newlines": nl["mixed"],
        },
    }


def _cn_newline_counts_bytes(data: bytes) -> dict:
    crlf = data.count(b"\r\n")
    cr = data.count(b"\r") - crlf
    lf = data.count(b"\n") - crlf
    kinds = sum(1 for n in (lf, crlf, cr) if n > 0)
    return {"lf": lf, "crlf": crlf, "cr": cr,
            "mixed": 1 if kinds > 1 else 0}


def _cn_convert_text(text: str, newline: str = "lf",
                     nfc: bool = False) -> str:
    """§3.2-5: UTF-8 / LF (or CRLF) / exactly one trailing newline.
    A non-empty text that does not end with the newline unit gets one;
    existing blank lines stay (they are content, and the file already
    ends with the newline)."""
    if nfc:
        text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    unit = "\r\n" if newline == "crlf" else "\n"
    if newline == "crlf":
        text = text.replace("\n", "\r\n")
    if text and not text.endswith(unit):
        text += unit
    return text


class CNCSVError(ValueError):
    """The CSV refusals (§3.4): the reason carries the existing
    parse_failed word (a quoting structure the strict reader cannot
    take)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _cn_csv_normalize_text(text: str, delimiter: str = ",",
                           newline: str = "lf",
                           sort_by=()):
    """§3.4: returns (normalized_text, info).  The quoting is minimal
    (only a delimiter, a quote or a newline forces it), the quotes
    inside are doubled, the cell values are untouched, a blank line
    stays a blank line, and the ragged rows are counted - never fixed
    (§3.4-3).  `sort_by` names columns of the header; the rows sort
    by the UTF-8 bytes of the named values, stable, missing cells as
    empty (§3.4-4)."""
    if len(delimiter) != 1:
        raise ValueError("csv: --delimiter must be one character")
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""),
                               delimiter=delimiter, strict=True))
    except csv.Error as e:
        raise CNCSVError("parse_failed") from e
    info = {"ragged_rows": 0, "columns": len(rows[0]) if rows else 0}
    header_len = info["columns"]
    # the header (row 0) rides first, untouched and unsorted (§3.4-2)
    header = rows[0] if rows else None
    body = []
    for row in rows[1:]:
        if row == []:
            body.append([])
            continue
        if len(row) != header_len:
            info["ragged_rows"] += 1
        body.append(row)
    if sort_by:
        idx = [header.index(name) for name in sort_by]

        def key(row):
            return tuple((row[i].encode("utf-8")
                          if i < len(row) else b"") for i in idx)
        body = sorted(body, key=key)     # the stable sort
    out_rows = ([header] if header is not None else []) + body
    term = "\r\n" if newline == "crlf" else "\n"
    buf = io.StringIO(newline="")
    w = csv.writer(buf, delimiter=delimiter, lineterminator=term,
                   quoting=csv.QUOTE_MINIMAL, doublequote=True)
    w.writerows(out_rows)
    return buf.getvalue(), info


# ---------------------------------------------------------------------------
# the JSON normalization (request §3.3) - the pretty style and the JCS
# style (RFC 8785, pinned against the Appendix B vectors in §2-5)

class CNJsonError(ValueError):
    """The JSON refusals (§3.3): `reason` is one of the mandated words
    (json_duplicate_key / json_invalid_number / json_number_unsafe)
    or the existing parse_failed word (a lone surrogate, an
    unserializable value)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _cn_json_pairs(pairs):
    seen = set()
    for k, _v in pairs:
        if k in seen:
            raise CNJsonError("json_duplicate_key")
        seen.add(k)
    return dict(pairs)


def _cn_parse_constant(_name):
    raise CNJsonError("json_invalid_number")


def _cn_json_loads(text: str):
    return json.loads(text, object_pairs_hook=_cn_json_pairs,
                      parse_constant=_cn_parse_constant,
                      parse_int=int, parse_float=float)


def _cn_json_pretty(text: str) -> str:
    """§3.3-2: indent 2, the keys in the Unicode codepoint order,
    ensure_ascii false, one trailing newline, the array order
    untouched, the numbers keep their value (big integers stay
    exact)."""
    obj = _cn_json_loads(text)
    return json.dumps(obj, ensure_ascii=False, indent=2,
                      sort_keys=True) + "\n"


def _cn_es_number(v) -> str:
    """The ECMAScript Number::toString(10) form (RFC 8785 §3.2.2.3),
    pinned against the Appendix B vectors by CN-T14.  The shortest
    roundtrip digits come from repr(); the ES presentation rules are
    applied on top (the fixed/exponential switch at 10^-6 / 10^21)."""
    if isinstance(v, int):
        if abs(v) > 2 ** 53:
            raise CNJsonError("json_number_unsafe")
        return str(v)
    if v != v or v in (float("inf"), float("-inf")):
        raise CNJsonError("json_invalid_number")
    if v == 0:
        return "0"          # also minus zero (Appendix B row 8000..)
    sign = "-" if v < 0 else ""
    s = repr(abs(v))        # the shortest roundtrip digits
    if "e" in s:
        mant, _sep, exp_s = s.partition("e")
        exp = int(exp_s)
    else:
        mant, exp = s, 0
    if "." in mant:
        ip, fp = mant.split(".")
    else:
        ip, fp = mant, ""
    if fp == "0":           # repr's integral marker, not a digit
        fp = ""
    ip2 = ip.lstrip("0")
    if ip2:
        digits = ip2 + fp
        n = len(ip2) + exp
    else:
        f2 = fp.lstrip("0")
        digits = f2
        n = exp - (len(fp) - len(f2))
    k = len(digits)
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        ee = n - 1
        body = (digits[0] + ("." + digits[1:] if k > 1 else "")
                + "e" + ("+" if ee >= 0 else "-") + str(abs(ee)))
    return sign + body


_CN_JCS_SHORT = {'"': '\\"', "\\": "\\\\", "\b": "\\b",
                 "\f": "\\f", "\n": "\\n", "\r": "\\r",
                 "\t": "\\t"}


def _cn_jcs_str(s: str) -> str:
    """The minimal string escaping (RFC §3.2.2.2): the JSON specials
    and the lowercase \\uhhhh for the ASCII control range only."""
    out = ['"']
    for ch in s:
        esc = _CN_JCS_SHORT.get(ch)
        if esc is not None:
            out.append(esc)
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _cn_jcs_serialize(obj) -> str:
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, str):
        try:
            obj.encode("utf-8")
        except UnicodeEncodeError:
            raise CNJsonError("parse_failed")   # lone surrogates end it
        return _cn_jcs_str(obj)
    if isinstance(obj, (int, float)):
        return _cn_es_number(obj)
    if isinstance(obj, list):
        return "[" + ",".join(_cn_jcs_serialize(x) for x in obj) + "]"
    if isinstance(obj, dict):
        keys = sorted(obj.keys(),
                      key=lambda s: s.encode("utf-16-be",
                                             "surrogatepass"))
        return "{" + ",".join(_cn_jcs_str(k) + ":" +
                              _cn_jcs_serialize(obj[k])
                              for k in keys) + "}"
    raise CNJsonError("parse_failed")


def _cn_json_jcs(text: str) -> str:
    """§3.3-3: the RFC 8785 canonical form.  The canonical form has no
    trailing newline - the bytes are the form itself (the text-level
    trailing-newline rule does not ride the jcs style; recorded in the
    stage log)."""
    obj = _cn_json_loads(text)
    return _cn_jcs_serialize(obj)


# ---------------------------------------------------------------------------
# stage 11: the self-checks ride the gate/cohort/Seal contract (0/1/2).
# The known small inputs are assembled at run time and compared against
# the published known values.

def normalize_self_check(progress=None) -> dict:
    raise NotImplementedError("stage 11")


def clean_self_check(progress=None) -> dict:
    raise NotImplementedError("stage 11")


def table_diff_self_check(progress=None) -> dict:
    raise NotImplementedError("stage 11")


# ---------------------------------------------------------------------------
# the shared decode resolution (§3.2-3): the BOM codec, the strict
# UTF-8, then the named codec - never a guess.  The normalize command
# and the table-diff reader use the same rules.

def _cn_decode_text(data: bytes, from_encoding=None):
    """Returns (text, reason, candidates): a None text is a refusal
    with the reason word and the strictly-readable candidates."""
    bom, body = _cn_detect_bom(data)
    if bom is not None:
        text = _cn_strict_decode(body, bom)
        if text is None:
            return None, "parse_failed", None
        return text, None, None
    if _cn_strict_decode(data, "utf-8") is not None:
        return data.decode("utf-8"), None, None
    if from_encoding:
        text = _cn_strict_decode(data, from_encoding)
        if text is None:
            return None, "parse_failed", None
        return text, None, None
    return None, "encoding_unknown", _cn_strict_candidates(data)


# ---------------------------------------------------------------------------
# the normalize run (request §3.2)

def _cn_sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def run_normalize(input_path, output_dir, *, from_encoding=None,
                  newline="lf", nfc=False, check=False, text_only=False,
                  style="pretty", delimiter=",", sort_by=(),
                  progress=None) -> dict:
    """The `normalize` command (§3.2).  Observes every text file,
    converts it to UTF-8 / LF (or CRLF) / one trailing newline, and
    writes the copies under handoff/ with the original relative names.
    A file with no BOM and invalid UTF-8 is refused with
    encoding_unknown (and the strictly-readable candidates) unless
    --from-encoding names the codec; a byte sequence the named codec
    cannot read is refused with the existing parse_failed word - no
    replacement, no output copy.  --check writes the receipt only."""
    from sieve_tray import __version__, _gate_digest, _gate_norm_json, \
        _gate_write_atomic
    tell = progress or (lambda _m: None)
    src = Path(input_path)
    out = Path(output_dir)
    if not src.exists():
        raise ValueError("normalize: %s does not exist" % src)
    if newline not in ("lf", "crlf"):
        raise ValueError("normalize: --newline must be lf or crlf")
    if len(delimiter) != 1:
        raise ValueError("normalize: --delimiter must be one character")

    items = []
    if src.is_dir():
        from sieve_tray import _seal_manifest_scan
        scanned, _skipped = _seal_manifest_scan(src)
        for it in scanned:
            rel = it.get("path")
            suffix = Path(rel).suffix.lower() if rel else ""
            if suffix not in CN_TEXT_EXTS:
                items.append({"path": rel, "status": "not_applicable",
                              "reason": None,
                              "input_sha256": it["sha256"],
                              "output_sha256": None})
                continue
            data = Path(it["_abs"]).read_bytes()
            item, out_bytes = _cn_normalize_one(
                rel, data, from_encoding, newline, nfc, check,
                text_only, style, delimiter=delimiter, sort_by=sort_by)
            if item["status"] == "produced":
                copy = out / "handoff" / rel
                copy.parent.mkdir(parents=True, exist_ok=True)
                copy.write_bytes(out_bytes)
                tell("Normalize: %s -> %s" % (rel, copy))
            items.append(item)
    else:
        rel = src.name
        data = src.read_bytes()
        item, out_bytes = _cn_normalize_one(
            rel, data, from_encoding, newline, nfc, check,
            text_only, style, delimiter=delimiter, sort_by=sort_by)
        if item["status"] == "produced":
            copy = out / "handoff" / rel
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(out_bytes)
            tell("Normalize: %s -> %s" % (rel, copy))
        items.append(item)

    produced = sum(1 for it in items if it["status"] == "produced")
    refused = sum(1 for it in items if it["status"] == "refused")
    observed = sum(1 for it in items if it["status"] == "observed")
    not_app = sum(1 for it in items if it["status"] == "not_applicable")
    receipt = {
        "receipt_version": CN_RECEIPT_VERSION,
        "kind": "sieve-normalize",
        "tool": {"name": "sieve-tray", "version": __version__},
        "engines": {},
        "settings": {
            "input": str(src),
            "from_encoding": from_encoding,
            "newline": newline,
            "nfc": bool(nfc),
            "check": bool(check),
            "text_only": bool(text_only),
            "style": style,
            "delimiter": delimiter,
            "sort_by": list(sort_by),
        },
        "items": items,
        "summary": {
            "files": len(items),
            "produced": produced,
            "refused": refused,
            "observed": observed,
            "not_applicable": not_app,
        },
    }
    receipt["digest"] = _gate_digest(receipt)
    _gate_write_atomic(out / "handoff" / "normalize-receipt.json",
                       _gate_norm_json(receipt).encode("utf-8"))
    tell("Normalize: receipt %s"
         % (out / "handoff" / "normalize-receipt.json"))
    return receipt


def _cn_normalize_one(rel, data, from_encoding, newline, nfc, check,
                      text_only, style, delimiter=",", sort_by=()):
    """Normalize one file: returns (item, out_bytes_or_None)."""
    obs = _cn_observe_text(data)
    item = {
        "path": rel,
        "status": None,
        "reason": None,
        "candidates": None,
        "input_sha256": _cn_sha(data),
        "output_sha256": None,
        "observation": obs,
    }
    text, reason, candidates = _cn_decode_text(data, from_encoding)
    if text is None:
        item["status"] = "refused"
        item["reason"] = reason
        item["candidates"] = candidates
        return item, None

    suffix = Path(rel).suffix.lower()
    out_bytes = None
    if not text_only and suffix == ".json":
        try:
            if style == "jcs":
                out_bytes = _cn_json_jcs(text).encode("utf-8")
            else:
                text = _cn_json_pretty(text)
        except CNJsonError as e:
            item["status"] = "refused"
            item["reason"] = e.reason
            return item, None
    elif not text_only and suffix == ".csv":
        try:
            text, csv_info = _cn_csv_normalize_text(
                text, delimiter=delimiter, newline=newline,
                sort_by=sort_by)
        except CNCSVError as e:
            item["status"] = "refused"
            item["reason"] = e.reason
            return item, None
        item["csv"] = csv_info
    if out_bytes is None:
        converted = _cn_convert_text(text, newline=newline, nfc=nfc)
        out_bytes = converted.encode("utf-8")
    if check:
        item["status"] = "observed"
        return item, None
    item["status"] = "produced"
    item["output_sha256"] = _cn_sha(out_bytes)
    item["output_bytes"] = len(out_bytes)
    return item, out_bytes

# ---------------------------------------------------------------------------
# the table diff (request §3.5)

class CNTableRefusal(ValueError):
    """A whole-run refusal of the table diff: the side (a/b), the
    closed reason word and the strictly-readable candidates."""

    def __init__(self, reason, candidates=None, side=None):
        self.reason = reason
        self.candidates = candidates
        self.side = side
        super().__init__(reason)


def _cn_read_csv_side(path, from_encoding, delimiter):
    """Read one side with the §3.2 / §3.4 rules: the decode resolution,
    then the CSV normalization (the LF form) whose bytes give the
    normalized checksum.  Returns (rows, normalized_sha256)."""
    data = Path(path).read_bytes()
    text, reason, candidates = _cn_decode_text(data, from_encoding)
    if text is None:
        raise CNTableRefusal(reason, candidates,
                             side=Path(path).name)
    normalized, _info = _cn_csv_normalize_text(text, delimiter=delimiter)
    norm_sha = _cn_sha(normalized.encode("utf-8"))
    try:
        rows = list(csv.reader(io.StringIO(normalized, newline=""),
                               delimiter=delimiter, strict=True))
    except csv.Error as e:
        raise CNTableRefusal("parse_failed",
                             side=Path(path).name) from e
    return rows, norm_sha


def run_table_diff(path_a, path_b, key_columns, output_dir, *,
                   from_encoding_a=None, from_encoding_b=None,
                   delimiter=",", progress=None) -> dict:
    """The `table-diff` command (§3.5).  Two CSVs are read with the
    shared rules, keyed by the named columns, and every key lands in
    one of the closed 5 states.  The receipt carries the counts, the
    column-difference counts and the normalized checksums only - the
    values, the key values and the column names stay in local/
    (§3.5-5).  A missing key column refuses (exit 2, §3.5-6)."""
    from sieve_tray import __version__, _gate_digest, _gate_norm_json, \
        _gate_write_atomic
    tell = progress or (lambda _m: None)
    a_path = Path(path_a)
    b_path = Path(path_b)
    out = Path(output_dir)
    if not a_path.is_file():
        raise ValueError("table-diff: %s is not a file" % a_path)
    if not b_path.is_file():
        raise ValueError("table-diff: %s is not a file" % b_path)
    if len(delimiter) != 1:
        raise ValueError("table-diff: --delimiter must be one character")
    if not key_columns:
        raise ValueError("table-diff: --key needs at least one column")
    rows_a, sha_a = _cn_read_csv_side(a_path, from_encoding_a, delimiter)
    rows_b, sha_b = _cn_read_csv_side(b_path, from_encoding_b, delimiter)
    if not rows_a or not rows_b:
        raise ValueError("table-diff: an input has no header row")
    header_a, body_a = rows_a[0], rows_a[1:]
    header_b, body_b = rows_b[0], rows_b[1:]
    idx_a, idx_b = [], []
    for name in key_columns:
        if name not in header_a:
            raise ValueError("table-diff: the key column %r is not in "
                             "%s" % (name, a_path.name))
        if name not in header_b:
            raise ValueError("table-diff: the key column %r is not in "
                             "%s" % (name, b_path.name))
        idx_a.append(header_a.index(name))
        idx_b.append(header_b.index(name))
    common_idx = [(header_a.index(n), header_b.index(n))
                  for n in header_a if n in header_b]
    a_only = [n for n in header_a if n not in header_b]
    b_only = [n for n in header_b if n not in header_a]

    def keyof(row, idx):
        return tuple((row[i] if i < len(row) else "") for i in idx)

    def cell(row, i):
        return row[i] if i < len(row) else ""

    from collections import Counter
    count_a = Counter(keyof(r, idx_a) for r in body_a if r)
    count_b = Counter(keyof(r, idx_b) for r in body_b if r)
    dup = {k for k, c in count_a.items() if c > 1}
    dup |= {k for k, c in count_b.items() if c > 1}
    map_a = {}
    for r in body_a:
        if not r:
            continue
        k = keyof(r, idx_a)
        if k in dup:
            continue
        map_a[k] = r
    same = changed = added = 0
    local_rows = []
    for r in body_b:
        if not r:
            continue
        k = keyof(r, idx_b)
        if k in dup:
            continue
        if k in map_a:
            ra = map_a.pop(k)
            diffs = [(header_a[ci], cell(ra, ci), cell(r, cb))
                     for ci, cb in common_idx
                     if cell(ra, ci) != cell(r, cb)]
            if diffs:
                changed += 1
                local_rows.append(("changed", k, diffs))
            else:
                same += 1
        else:
            added += 1
            local_rows.append(("added", k, []))
    removed = len(map_a)
    for k, r in map_a.items():
        local_rows.append(("removed", k, []))
    receipt = {
        "receipt_version": CN_RECEIPT_VERSION,
        "kind": "sieve-table-diff",
        "tool": {"name": "sieve-tray", "version": __version__},
        "engines": {},
        "settings": {
            "a": str(a_path),
            "b": str(b_path),
            # §3.5-5: the column names never enter handoff/ - the key
            # columns ride as the indices, in A's column order
            "key_columns": list(idx_a),
            "delimiter": delimiter,
            "from_encoding_a": from_encoding_a,
            "from_encoding_b": from_encoding_b,
        },
        "items": [],
        "summary": {
            "rows_same": same,
            "rows_changed": changed,
            "rows_removed": removed,
            "rows_added": added,
            "duplicate_keys": len(dup),
            "columns_common": len(common_idx),
            "columns_a_only": len(a_only),
            "columns_b_only": len(b_only),
            "a_normalized_sha256": sha_a,
            "b_normalized_sha256": sha_b,
        },
    }
    # the local report: the row-level states, the changed columns with
    # the names and both values (§3.5-5) - written before the receipt
    # (the receipt stays LAST, the existing rule)
    lines = ["<!doctype html><html><head><meta charset=\"utf-8\">"
             "<title>table-diff report</title></head><body>",
             "<h1>table-diff report</h1>",
             "<p>A: %s</p><p>B: %s</p>"
             % (html.escape(str(a_path)), html.escape(str(b_path))),
             "<p>key columns: %s</p>"
             % html.escape(", ".join(str(k) for k in key_columns))]
    if a_only or b_only:
        lines.append("<p>columns only in A: %s</p>"
                     % html.escape(", ".join(a_only) or "(none)"))
        lines.append("<p>columns only in B: %s</p>"
                     % html.escape(", ".join(b_only) or "(none)"))
    lines.append("<table border=\"1\"><tr><th>state</th>"
                 "<th>key</th><th>changed column</th>"
                 "<th>value in A</th><th>value in B</th></tr>")
    for state, k, diffs in local_rows:
        key_txt = html.escape(" | ".join(k))
        if diffs:
            for name, va, vb in diffs:
                lines.append("<tr><td>%s</td><td>%s</td><td>%s</td>"
                             "<td>%s</td><td>%s</td></tr>"
                             % (state, key_txt, html.escape(name),
                                html.escape(va), html.escape(vb)))
        else:
            lines.append("<tr><td>%s</td><td>%s</td><td></td>"
                         "<td></td><td></td></tr>" % (state, key_txt))
    lines.append("</table></body></html>")
    local = out / "local" / "table-diff-report.html"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text("\n".join(lines), encoding="utf-8")
    tell("TableDiff: report %s" % local)
    receipt["digest"] = _gate_digest(receipt)
    _gate_write_atomic(out / "handoff" / "table-diff-receipt.json",
                       _gate_norm_json(receipt).encode("utf-8"))
    tell("TableDiff: receipt %s"
         % (out / "handoff" / "table-diff-receipt.json"))
    return receipt



# ---------------------------------------------------------------------------
# the metadata clean (request §3.1) - JPEG / PNG / Office, stdlib only
# (no PIL: the byte structures are handled directly, §2-3)

import struct as _struct


def _cn_zero_categories():
    return {c: 0 for c in CN_META_CATEGORIES}


# --- PNG ---------------------------------------------------------------

_CN_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_CN_PNG_KEEP = frozenset({
    "IHDR", "PLTE", "IDAT", "IEND",                    # the mandatory ones
    "tRNS", "gAMA", "cHRM", "sRGB", "iCCP", "sBIT",    # the display ones
    "bKGD", "pHYs"})


def _cn_png_chunks(data: bytes):
    """Parse the PNG chunk list; every CRC is re-checked (a mismatch
    is a broken file -> parse_failed)."""
    import zlib as _zlib
    if not data.startswith(_CN_PNG_SIG):
        raise ValueError("not a PNG")
    pos = 8
    chunks = []
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        ctype = data[pos + 4:pos + 8]
        end = pos + 8 + length
        payload = data[pos + 8:end]
        crc = data[end:end + 4]
        if len(payload) != length or len(crc) != 4:
            raise ValueError("PNG: truncated chunk")
        if _zlib.crc32(data[pos + 4:end]) != int.from_bytes(crc, "big"):
            raise ValueError("PNG: CRC mismatch")
        chunks.append((ctype.decode("latin-1"), payload))
        if ctype == b"IEND":
            return chunks
        pos = end + 4
    raise ValueError("PNG: no IEND")


def _cn_png_chunk_bytes(ctype: bytes, payload: bytes) -> bytes:
    import zlib as _zlib
    return (len(payload).to_bytes(4, "big") + ctype + payload
            + _zlib.crc32(ctype + payload).to_bytes(4, "big"))


_CN_PNG_KEYWORD_CATEGORIES = {
    "author": "author",
    "software": "software",
    "creation time": "time",
    "date created": "time",
    "description": "title_subject",
    "comment": "title_subject",
    "title": "title_subject",
    "subject": "title_subject",
    "keywords": "title_subject",
}


def _cn_png_observe(data: bytes):
    """The metadata observation of a PNG (§3.1-9/§3.1-10): the counts
    per category plus the removed-value samples for the local report."""
    counts = _cn_zero_categories()
    values = []
    for ctype, payload in _cn_png_chunks(data):
        if ctype == "tEXt":
            kw, _sep, text = payload.partition(b"\x00")
            cat = _CN_PNG_KEYWORD_CATEGORIES.get(
                kw.decode("latin-1").strip().lower(), "custom")
            counts[cat] += 1
            values.append((cat, text.decode("latin-1")))
        elif ctype == "iTXt":
            kw, _sep, rest = payload.partition(b"\x00")
            cat = _CN_PNG_KEYWORD_CATEGORIES.get(
                kw.decode("latin-1").strip().lower(), "custom")
            counts[cat] += 1
            values.append((cat, kw.decode("latin-1")))
        elif ctype == "zTXt":
            kw, _sep, _rest = payload.partition(b"\x00")
            cat = _CN_PNG_KEYWORD_CATEGORIES.get(
                kw.decode("latin-1").strip().lower(), "custom")
            counts[cat] += 1
            values.append((cat, kw.decode("latin-1")))
        elif ctype == "tIME":
            counts["time"] += 1
            values.append(("time", payload.hex()))
        elif ctype == "eXIf":
            ec, ev = _cn_exif_categories(payload[2:] if payload[:1] in
                                         (b"I", b"M") else payload)
            for c in CN_META_CATEGORIES:
                counts[c] += ec[c]
            values.extend(ev)
    return counts, values


def _cn_png_clean(data: bytes):
    """§3.1-4/§3.1-5: the text chunks, the eXIf, the tIME and every
    ancillary chunk outside the keep list go; the mandatory and the
    display chunks stay (the critical unknown chunks stay too - they
    may be needed to decode).  The rebuilt chunks carry fresh CRCs."""
    removed = []
    kept_core = []
    out = [_CN_PNG_SIG]
    for ctype, payload in _cn_png_chunks(data):
        ancillary = ctype[0].islower()
        if ctype in _CN_PNG_KEEP:
            chunk = _cn_png_chunk_bytes(ctype.encode("latin-1"), payload)
            out.append(chunk)
            if ctype in ("IHDR", "PLTE", "IDAT", "IEND"):
                kept_core.append(chunk)
            continue
        if ctype in ("tEXt", "iTXt", "zTXt", "eXIf", "tIME") or ancillary:
            removed.append((ctype, payload))
            continue
        # an unknown critical chunk: keep (decode safety)
        chunk = _cn_png_chunk_bytes(ctype.encode("latin-1"), payload)
        out.append(chunk)
        if ctype in ("IHDR", "PLTE", "IDAT", "IEND"):
            kept_core.append(chunk)
    return (b"".join(out), removed,
            _cn_sha(b"".join(kept_core)))


# --- EXIF (shared by the JPEG APP1 and the PNG eXIf) -------------------

_CN_EXIF_TAG_CATEGORIES = {
    0x013A: "author",          # Artist
    0x8298: "author",          # Copyright
    0x9C9B: "author",          # XPAuthor
    0x0132: "time",            # DateTime
    0x9003: "time",            # DateTimeOriginal
    0x9004: "time",            # DateTimeDigitized
    0x0131: "software",        # Software
    0x010F: "device",          # Make
    0x0110: "device",          # Model
    0xA431: "device",          # BodySerialNumber
    0xA433: "device",          # LensMake
    0xA434: "device",          # LensModel
    0xA435: "device",          # LensSerialNumber
    0x010E: "title_subject",   # ImageDescription
    0x9C9C: "title_subject",   # XPComment
    0x9C9D: "title_subject",   # XPKeywords
    0x9C9E: "title_subject",   # XPSubject
    0x9C9F: "title_subject",   # XPTitle
}


def _cn_tiff_entries(payload: bytes, off: int):
    # the byteorder for int.from_bytes is "little"/"big" (struct's "<"
    # form is not accepted there)
    bo = "little" if payload[0:2] == b"II" else "big"
    n = int.from_bytes(payload[off:off + 2], bo)
    entries = []
    for i in range(n):
        e = off + 2 + 12 * i
        tag = int.from_bytes(payload[e:e + 2], bo)
        typ = int.from_bytes(payload[e + 2:e + 4], bo)
        cnt = int.from_bytes(payload[e + 4:e + 8], bo)
        vf = payload[e + 8:e + 12]
        entries.append((tag, typ, cnt, vf))
    nxt_off = off + 2 + 12 * n
    nxt = int.from_bytes(payload[nxt_off:nxt_off + 4], bo) \
        if nxt_off + 4 <= len(payload) else 0
    return entries, nxt, bo


def _cn_tiff_value(payload: bytes, bo: str, typ: int, cnt: int, vf):
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4,
             10: 8, 11: 4, 12: 8}
    total = sizes.get(typ, 1) * cnt
    if total <= 4:
        raw = vf[:total]
    else:
        off = int.from_bytes(vf, bo)
        raw = payload[off:off + total]
    return raw


def _cn_exif_categories(tiff: bytes):
    """The category counts of one EXIF TIFF blob (no Exif\\0\\0
    prefix): IFD0 + the EXIF sub-IFD + the GPS sub-IFD + IFD1."""
    counts = _cn_zero_categories()
    values = []
    orientation = None
    try:
        if len(tiff) < 8 or tiff[0:2] not in (b"II", b"MM"):
            counts["custom"] += 1
            return counts, values, orientation
        ifd0_off = int.from_bytes(tiff[4:8],
                                  "little" if tiff[0:2] == b"II"
                                  else "big")
        entries, nxt, bo = _cn_tiff_entries(tiff, ifd0_off)
        sub_exif = sub_gps = None
        for tag, typ, cnt, vf in entries:
            if tag == 0x0112:
                raw = _cn_tiff_value(tiff, bo, typ, cnt, vf)
                if len(raw) >= 2:
                    orientation = int.from_bytes(raw[:2], bo)
                continue          # the orientation is display, no count
            if tag == 0x8769:
                sub_exif = int.from_bytes(_cn_tiff_value(
                    tiff, bo, typ, cnt, vf), bo)
                continue
            if tag == 0x8825:
                sub_gps = int.from_bytes(_cn_tiff_value(
                    tiff, bo, typ, cnt, vf), bo)
                continue
            cat = _CN_EXIF_TAG_CATEGORIES.get(tag, "custom")
            counts[cat] += 1
            if cat == "author" and tag == 0x013A:
                raw = _cn_tiff_value(tiff, bo, typ, cnt, vf)
                values.append(("author", raw.decode("latin-1")))
        if sub_exif:
            s_entries, _n2, s_bo = _cn_tiff_entries(tiff, sub_exif)
            for tag, typ, cnt, vf in s_entries:
                if tag == 0x0112:
                    raw = _cn_tiff_value(tiff, s_bo, typ, cnt, vf)
                    if len(raw) >= 2 and orientation is None:
                        orientation = int.from_bytes(raw[:2], s_bo)
                    continue
                cat = _CN_EXIF_TAG_CATEGORIES.get(tag, "custom")
                counts[cat] += 1
                if cat == "author" and tag == 0x013A:
                    raw = _cn_tiff_value(tiff, s_bo, typ, cnt, vf)
                    values.append(("author", raw.decode("latin-1")))
        if sub_gps:
            g_entries, _n3, g_bo = _cn_tiff_entries(tiff, sub_gps)
            for tag, _typ, _cnt, _vf in g_entries:
                if tag == 0x0007:
                    counts["time"] += 1
                else:
                    counts["location"] += 1
        if nxt:
            i_entries, _n4, i_bo = _cn_tiff_entries(tiff, nxt)
            thumb_off = thumb_len = None
            for tag, typ, cnt, vf in i_entries:
                if tag == 0x0201:
                    thumb_off = int.from_bytes(
                        _cn_tiff_value(tiff, i_bo, typ, cnt, vf), i_bo)
                elif tag == 0x0202:
                    thumb_len = int.from_bytes(
                        _cn_tiff_value(tiff, i_bo, typ, cnt, vf), i_bo)
            if thumb_off is not None:
                counts["thumbnail"] += 1
                if thumb_len:
                    blob = tiff[thumb_off:thumb_off + thumb_len]
                    values.append(("thumbnail",
                                   blob.decode("latin-1")))
    except (IndexError, ValueError, _struct.error):
        counts["custom"] += 1
    return counts, values, orientation


def _cn_exif_orientation(app1_payload: bytes):
    """The Orientation of one JPEG APP1 payload (Exif\\0\\0 + TIFF),
    or None."""
    tiff = app1_payload[6:]
    _c, _v, orientation = _cn_exif_categories(tiff)
    return orientation


def _cn_minimal_exif(orientation: int) -> bytes:
    """§3.1-3: the orientation-only minimal EXIF (the display keeps
    its rotation; nothing else rides along)."""
    return (b"Exif\x00\x00" + b"II" + b"\x2a\x00" + b"\x08\x00\x00\x00"
            + b"\x01\x00" + b"\x12\x01" + b"\x03\x00" + b"\x01\x00\x00\x00"
            + _struct.pack("<H", orientation) + b"\x00\x00"
            + b"\x00\x00\x00\x00")


# --- XMP (the APP1 non-EXIF form) --------------------------------------

_CN_XMP_PATTERNS = (
    ("author", re.compile(r"<(dc:creator|xmpRights:Owner|photoshop:Author)"
                          r"[\s/>]")),
    ("time", re.compile(r"<(xmp:CreateDate|xmp:ModifyDate|xmp:MetadataDate"
                        r"|photoshop:DateCreated|exif:DateTimeOriginal)"
                        r"[\s/>]")),
    ("software", re.compile(r"<(xmp:CreatorTool|photoshop:Source)[\s/>]")),
    ("location", re.compile(r"<(photoshop:City|photoshop:State"
                            r"|photoshop:Country|exif:GPSLatitude)[\s/>]")),
    ("device", re.compile(r"<(tiff:Make|tiff:Model)[\s/>]")),
    ("title_subject",
     re.compile(r"<(dc:title|dc:description|dc:subject"
                r"|photoshop:Headline|photoshop:Caption)[\s/>]")),
)
_CN_XMP_ANY_ELEMENT = re.compile(r"<([A-Za-z0-9_-]+:)?[A-Za-z0-9_-]+[\s/>]")


def _cn_xmp_categories(xml_text: str):
    counts = _cn_zero_categories()
    mapped = 0
    for cat, pattern in _CN_XMP_PATTERNS:
        n = len(pattern.findall(xml_text))
        counts[cat] += n
        mapped += n
    counts["custom"] += max(0, len(_CN_XMP_ANY_ELEMENT.findall(xml_text))
                            - mapped)
    return counts


# --- IPTC (the APP13 8BIM form) ----------------------------------------

_CN_IPTC_CATEGORIES = {
    (1, 0x32): "author",         # By-line
    (1, 0x74): "author",         # CopyrightNotice
    (1, 0x05): "title_subject",  # ObjectName
    (1, 0x19): "title_subject",  # Keywords
    (2, 0x78): "title_subject",  # Caption
    (1, 0x37): "location",       # Location
    (2, 0x37): "time",           # DateCreated
}


def _cn_iptc_categories(payload: bytes):
    counts = _cn_zero_categories()
    values = []
    data = payload
    pos = 0
    while True:
        pos = data.find(b"8BIM", pos)
        if pos < 0:
            break
        pos += 4
        if pos + 2 > len(data):
            break
        pos += 2                        # the resource id
        nlen = data[pos]
        pos += 1 + nlen
        if (1 + nlen) % 2:
            pos += 1                    # the name is padded to even
        if pos + 4 > len(data):
            break
        size = int.from_bytes(data[pos:pos + 4], "big")
        pos += 4
        body = data[pos:pos + size]
        pos += size + (size % 2)
        if size == 0 or len(body) != size:
            continue
        q = 0
        while q + 5 <= len(body):
            if body[q] != 0x1C:
                break
            rec = body[q + 1]
            ds = body[q + 2]
            ln = int.from_bytes(body[q + 3:q + 5], "big")
            val = body[q + 5:q + 5 + ln]
            cat = _CN_IPTC_CATEGORIES.get((rec, ds), "custom")
            counts[cat] += 1
            values.append((cat, val.decode("latin-1")))
            q += 5 + ln
    return counts, values


# --- JPEG --------------------------------------------------------------

_CN_JPEG_MARKER_NAMES = {0xC4: "DHT", 0xDB: "DQT", 0xDD: "DRI", 0xDA: "SOS",
                         0xFE: "COM", 0xC8: "JPG", 0xCC: "DAC", 0xDC: "DNL"}
for _m in range(0xC0, 0xD0):
    if _m not in (0xC4, 0xC8, 0xCC):
        _CN_JPEG_MARKER_NAMES[_m] = "SOF%d" % (_m - 0xC0)
for _i in range(16):
    _CN_JPEG_MARKER_NAMES[0xE0 + _i] = "APP%d" % _i
for _i in range(14):
    _CN_JPEG_MARKER_NAMES[0xF0 + _i] = "JPG%d" % _i


def _cn_seg(marker: int, payload: bytes) -> bytes:
    """One JPEG segment with its marker and the 2-byte length."""
    return (bytes([0xFF, marker])
            + (len(payload) + 2).to_bytes(2, "big") + payload)


def _cn_jpeg_segments(data: bytes):
    """Parse the JPEG segment list.  Each entry is (name, payload,
    raw); the entropy scan after SOS rides as its own SCAN entry with
    the raw bytes (FF00 stuffings and RST markers included)."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    segs = [("SOI", b"", b"\xff\xd8")]
    pos = 2
    n = len(data)
    eoi_seen = False
    while pos < n:
        if data[pos] != 0xFF:
            raise ValueError("JPEG: expected a marker at byte %d" % pos)
        while pos < n and data[pos] == 0xFF:
            pos += 1
        if pos >= n:
            raise ValueError("JPEG: truncated")
        marker = data[pos]
        pos += 1
        if marker == 0xD9:
            segs.append(("EOI", b"", b"\xff\xd9"))
            eoi_seen = True
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            segs.append(("RST", b"", data[pos - 2:pos]))
            continue
        if pos + 2 > n:
            raise ValueError("JPEG: truncated")
        seg_len = int.from_bytes(data[pos:pos + 2], "big")
        if seg_len < 2:
            raise ValueError("JPEG: bad segment length")
        payload = data[pos + 2:pos + seg_len]
        if len(payload) != seg_len - 2:
            raise ValueError("JPEG: truncated segment")
        name = _CN_JPEG_MARKER_NAMES.get(marker, "UNK%02X" % marker)
        segs.append((name, payload, data[pos - 2:pos + seg_len]))
        pos += seg_len
        if marker == 0xDA:
            q = pos
            while q < n:
                if data[q] != 0xFF:
                    q += 1
                    continue
                nxt = data[q + 1] if q + 1 < n else None
                if nxt == 0x00 or (nxt is not None
                                   and 0xD0 <= nxt <= 0xD7):
                    q += 2
                    continue
                break
            segs.append(("SCAN", b"", data[pos:q]))
            pos = q
    if not eoi_seen:
        raise ValueError("JPEG: no EOI")
    return segs


_CN_JPEG_XMP_PREFIX = b"http://ns.adobe.com/xap/1.0/\x00"


def _cn_jpeg_observe(data: bytes):
    """The metadata observation of a JPEG (§3.1-9/§3.1-10)."""
    counts = _cn_zero_categories()
    values = []
    for name, payload, _raw in _cn_jpeg_segments(data):
        if name == "COM":
            counts["custom"] += 1
            values.append(("custom", payload.decode("latin-1")))
        elif name == "APP1":
            if payload.startswith(b"Exif\x00\x00"):
                ec, ev, _o = _cn_exif_categories(payload[6:])
                for c in CN_META_CATEGORIES:
                    counts[c] += ec[c]
                values.extend(ev)
            elif payload.startswith(_CN_JPEG_XMP_PREFIX):
                xml = payload[len(_CN_JPEG_XMP_PREFIX):].decode(
                    "utf-8", "replace")
                xc = _cn_xmp_categories(xml)
                for c in CN_META_CATEGORIES:
                    counts[c] += xc[c]
                values.append(("custom", xml[:120]))
            else:
                counts["custom"] += 1
                values.append(("custom", payload[:40].decode("latin-1")))
        elif name == "APP13":
            ic, iv = _cn_iptc_categories(payload)
            for c in CN_META_CATEGORIES:
                counts[c] += ic[c]
            values.extend(iv)
        elif name.startswith("APP") and name not in ("APP0", "APP2",
                                                     "APP14"):
            counts["custom"] += 1
            values.append(("custom", payload[:40].decode("latin-1")))
        elif name == "APP0" and payload.startswith(b"JFIF\x00"):
            if len(payload) >= 14 and (payload[12] or payload[13]):
                counts["thumbnail"] += 1
                values.append(("thumbnail",
                               payload[14:].decode("latin-1")))
        elif name == "APP0":
            counts["custom"] += 1
            values.append(("custom", payload[:40].decode("latin-1")))
    return counts, values


def _cn_jpeg_clean(data: bytes):
    """§3.1-2/§3.1-3: EXIF, XMP (APP1), IPTC (APP13), COM, the JFIF
    thumbnail and the EXIF thumbnail go; the entropy body, the frame /
    table definitions, the ICC (APP2) and the Adobe (APP14) stay.  An
    Orientation other than 1 keeps the orientation-only minimal EXIF
    (orientation_kept).  The content checksum covers the kept
    non-metadata segments (the body and the required definitions)."""
    segs = _cn_jpeg_segments(data)
    out = [b"\xff\xd8"]
    content_parts = []
    removed = []
    orientation_kept = False
    for name, payload, raw in segs:
        if name == "SOI":
            continue
        if name in ("EOI",):
            out.append(b"\xff\xd9")
            continue
        if name in ("SCAN", "RST", "SOS"):
            out.append(raw)
            content_parts.append(raw)
            continue
        if name.startswith("SOF") or name in ("DHT", "DQT", "DRI",
                                              "DNL", "JPG", "DAC"):
            out.append(raw)
            content_parts.append(raw)
            continue
        if name == "APP0":
            if payload.startswith(b"JFIF\x00") and len(payload) >= 14:
                xt, yt = payload[12], payload[13]
                if xt or yt:
                    removed.append(("thumbnail",
                                    payload[14:].decode("latin-1")))
                    payload = payload[:11] + b"\x00\x00"
                    out.append(_cn_seg(0xE0, payload))
                else:
                    out.append(raw)
            else:
                removed.append(("custom",
                                payload[:40].decode("latin-1")))
            continue
        if name == "APP1":
            if payload.startswith(b"Exif\x00\x00"):
                _c, _v, orientation = _cn_exif_categories(payload[6:])
                if orientation is not None and orientation != 1:
                    orientation_kept = True
                    out.append(_cn_seg(0xE1, _cn_minimal_exif(orientation)))
                else:
                    removed.append(("custom", "(exif)"))
                continue
            removed.append(("custom", payload[:60].decode("latin-1")))
            continue
        # the remaining APPn / COM families are metadata
        if name == "APP2" or name == "APP14":
            out.append(raw)
            continue
        removed.append((name, payload[:60].decode("latin-1")))
    return (b"".join(out), removed, _cn_sha(b"".join(content_parts)),
            orientation_kept)


# --- Office ------------------------------------------------------------

_CN_EMPTY_CORE_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
    'package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:dcterms="http://purl.org/dc/terms/" '
    'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>')

_CN_EMPTY_APP_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/'
    'officeDocument/2006/extended-properties" xmlns:vt="http://'
    'schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"/>')

_CN_EMPTY_CUSTOM_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/'
    'officeDocument/2006/custom-properties" xmlns:vt="http://'
    'schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"/>')

_CN_XML_COUNTS = {
    "docProps/core.xml": (
        ("author", re.compile(r"<dc:creator[\s/>]")),
        ("author", re.compile(r"<cp:lastModifiedBy[\s/>]")),
        ("time", re.compile(r"<dcterms:created[\s/>]")),
        ("time", re.compile(r"<dcterms:modified[\s/>]")),
        ("title_subject", re.compile(r"<dc:title[\s/>]")),
        ("title_subject", re.compile(r"<dc:subject[\s/>]")),
        ("title_subject", re.compile(r"<cp:keywords[\s/>]")),
        ("title_subject", re.compile(r"<dc:description[\s/>]")),
    ),
    "docProps/app.xml": (
        ("author", re.compile(r"<Company[\s/>]")),
        ("author", re.compile(r"<Manager[\s/>]")),
        ("software", re.compile(r"<Application[\s/>]")),
        ("software", re.compile(r"<AppVersion[\s/>]")),
    ),
}


def _cn_office_open(data: bytes):
    zf = zipfile.ZipFile(io.BytesIO(data))
    # a broken structure surfaces as ValueError (parse_failed)
    bad = zf.testzip()
    if bad is not None:
        raise ValueError("Office: bad member %s" % bad)
    return zf


def _cn_office_members(data: bytes):
    zf = _cn_office_open(data)
    return [(info.filename.replace("\\", "/"), zf.read(info))
            for info in zf.infolist()]


def _cn_office_observe(members):
    """The metadata observation of an Office package (§3.1-10) plus
    the in_content counts (§3.1-11: comment / tracked_change /
    hidden_part - counted, never removed)."""
    counts = _cn_zero_categories()
    values = []
    in_content = {k: 0 for k in CN_IN_CONTENT}
    for name, payload in members:
        text = None
        if name in _CN_XML_COUNTS:
            text = payload.decode("utf-8", "replace")
            for cat, pattern in _CN_XML_COUNTS[name]:
                counts[cat] += len(pattern.findall(text))
            if name == "docProps/core.xml":
                for m in re.findall(r"<dc:creator>(.*?)</dc:creator>",
                                    text):
                    values.append(("author", m))
                for m in re.findall(
                        r"<cp:lastModifiedBy>(.*?)</cp:lastModifiedBy>",
                        text):
                    values.append(("author", m))
        elif name == "docProps/custom.xml":
            text = payload.decode("utf-8", "replace")
            counts["custom"] += len(re.findall(r"<property[\s/>]", text))
        elif name.startswith("docProps/thumbnail") and payload:
            counts["thumbnail"] += 1
            values.append(("thumbnail", name))
        elif name == "word/comments.xml":
            in_content["comment"] += len(
                re.findall(rb"<w:comment[\s/>]", payload))
        elif name.startswith("xl/comments"):
            in_content["comment"] += len(
                re.findall(rb"<comment[\s/>]", payload))
        elif name == "word/document.xml":
            in_content["tracked_change"] += len(
                re.findall(rb"<w:ins[\s/>]", payload))
            in_content["tracked_change"] += len(
                re.findall(rb"<w:del[\s/>]", payload))
        elif name == "xl/workbook.xml":
            in_content["hidden_part"] += len(
                re.findall(rb"<sheet[^>]*state=\"hidden\"", payload))
        elif (name.startswith("ppt/slides/slide")
                and name.endswith(".xml")):
            if b'show="0"' in payload:
                in_content["hidden_part"] += 1
    return counts, values, in_content


def _cn_office_clean(data: bytes):
    """§3.1-6/§3.1-7/§3.1-8: the docProps parts are replaced with the
    empty valid shapes (nothing is dropped - the content-type and the
    relationships stay untouched), the thumbnail part becomes empty,
    every other member rides byte-identically, and the output zip is
    the deterministic pack form."""
    members = _cn_office_members(data)
    removed = []
    out_members = []
    content_members = []
    for name, payload in members:
        if name == "docProps/core.xml":
            removed.append(("author", _cn_office_first(payload,
                                                       r"<dc:creator>"
                                                       r"(.*?)</dc:creator>")))
            out_members.append((name, _CN_EMPTY_CORE_XML.encode("utf-8")))
            continue
        if name == "docProps/app.xml":
            removed.append(("software", _cn_office_first(
                payload, r"<Application>(.*?)</Application>")))
            out_members.append((name, _CN_EMPTY_APP_XML.encode("utf-8")))
            continue
        if name == "docProps/custom.xml":
            removed.append(("custom", "(custom properties)"))
            out_members.append((name,
                                _CN_EMPTY_CUSTOM_XML.encode("utf-8")))
            continue
        if name.startswith("docProps/thumbnail"):
            if payload:
                removed.append(("thumbnail", name))
            out_members.append((name, b""))
            continue
        out_members.append((name, payload))
        if not name.startswith("docProps/"):
            content_members.append((name, payload))
    content_members.sort(key=lambda m: m[0].encode("utf-8"))
    digest = _cn_sha(b"".join(
        n.encode("utf-8") + b"\x00" + p for n, p in content_members))
    return out_members, removed, digest


def _cn_office_first(payload: bytes, pattern: str):
    m = re.search(pattern, payload.decode("utf-8", "replace"))
    return m.group(1) if m else ""


def _cn_office_content_sha(members):
    picked = [(n, p) for n, p in members
              if not n.startswith("docProps/")]
    picked.sort(key=lambda m: m[0].encode("utf-8"))
    return _cn_sha(b"".join(
        n.encode("utf-8") + b"\x00" + p for n, p in picked))


# --- the clean run (request §3.1) --------------------------------------

def _cn_png_content_sha(data: bytes) -> str:
    kept = []
    for ctype, payload in _cn_png_chunks(data):
        if ctype in ("IHDR", "PLTE", "IDAT", "IEND"):
            kept.append(_cn_png_chunk_bytes(ctype.encode("latin-1"),
                                            payload))
    return _cn_sha(b"".join(kept))


def _cn_jpeg_content_sha(data: bytes) -> str:
    kept = []
    for name, _payload, raw in _cn_jpeg_segments(data):
        if name in ("SCAN", "RST", "SOS") or name.startswith("SOF") \
                or name in ("DHT", "DQT", "DRI", "DNL", "JPG", "DAC"):
            kept.append(raw)
    return _cn_sha(b"".join(kept))


def run_clean(input_path, output_dir, *, no_paths=False,
              progress=None) -> dict:
    """The `clean` command (§3.1).  JPEG / PNG / Office packages are
    stripped of their metadata into handoff/ copies (the original file
    is never written); the same observation runs again on the outputs
    (§3.1-9).  Everything else is recorded with the existing closed
    words and stays out of the output.  The removed values go only to
    the local report (§3.1-14)."""
    from sieve_tray import (__version__, _gate_digest, _gate_norm_json,
                            _gate_write_atomic, _seal_manifest_scan)
    tell = progress or (lambda _m: None)
    src = Path(input_path)
    out = Path(output_dir)
    if not src.exists():
        raise ValueError("clean: %s does not exist" % src)
    include_paths = not no_paths
    entries = []
    if src.is_dir():
        scanned, _skipped = _seal_manifest_scan(src)
        for i, it in enumerate(scanned, start=1):
            entries.append((it.get("path"), Path(it["_abs"]), i))
    else:
        entries.append((src.name, src, 1))

    items = []
    report_parts = []
    cleaned = refused = not_app = orientation_count = 0
    for rel, path, index in entries:
        suffix = path.suffix.lower()
        fmt = CN_CLEAN_EXTS.get(suffix)
        if fmt is None:
            fmt_label = "pdf" if suffix == ".pdf" else "other"
        else:
            fmt_label = fmt
        item = {"path": rel if include_paths else None,
                "status": None,
                "reason": None,
                "format": fmt_label,
                "input_sha256": None,
                "output_sha256": None,
                "output_bytes": None,
                "content_checksum_match": None,
                "in_content": None,
                "categories_before": None,
                "categories_after": None}
        if not include_paths:
            item["index"] = index
        try:
            data = path.read_bytes()
        except OSError:
            item["status"] = "refused"
            item["reason"] = "unreadable"
            items.append(item)
            refused += 1
            continue
        item["input_sha256"] = _cn_sha(data)
        if fmt is None:
            item["status"] = "not_applicable"
            items.append(item)
            not_app += 1
            continue
        try:
            if fmt == "png":
                before, removed = _cn_png_observe(data)
                out_bytes, _r2, out_content = _cn_png_clean(data)
                after, _av = _cn_png_observe(out_bytes)
                in_content = {k: 0 for k in CN_IN_CONTENT}
                orientation_kept = None
                content_match = (_cn_png_content_sha(data) == out_content)
            elif fmt == "jpeg":
                before, removed = _cn_jpeg_observe(data)
                out_bytes, _r2, out_content, o_kept = \
                    _cn_jpeg_clean(data)
                after, _av = _cn_jpeg_observe(out_bytes)
                in_content = {k: 0 for k in CN_IN_CONTENT}
                orientation_kept = bool(o_kept)
                content_match = (_cn_jpeg_content_sha(data)
                                 == out_content)
            else:
                members = _cn_office_members(data)
                before, removed, in_content = _cn_office_observe(members)
                out_members, _r2, out_content = \
                    _cn_office_clean(data)
                after, _av, in_after = _cn_office_observe(out_members)
                # the emptied docProps count nothing; the in_content
                # numbers are the input ones (the content is unchanged)
                orientation_kept = None
                content_match = (
                    _cn_office_content_sha(members)
                    == _cn_office_content_sha(out_members))
                out_bytes = b"".join([])
                import io as _io
                buf = _io.BytesIO()
                _cn_write_zip_stream(buf, out_members)
                out_bytes = buf.getvalue()
        except (ValueError, zipfile.BadZipFile):
            item["status"] = "refused"
            item["reason"] = "parse_failed"
            items.append(item)
            refused += 1
            continue
        item["status"] = "cleaned"
        item["categories_before"] = before
        item["categories_after"] = after
        item["in_content"] = in_content
        item["content_checksum_match"] = bool(content_match)
        item["output_sha256"] = _cn_sha(out_bytes)
        item["output_bytes"] = len(out_bytes)
        if fmt == "jpeg":
            item["orientation_kept"] = orientation_kept
        cleaned += 1
        if orientation_kept:
            orientation_count += 1
        if removed:
            rows = ""
            for cat, val in removed:
                if isinstance(val, bytes):
                    val = val.decode("latin-1", "replace")
                rows += ("<tr><td>%s</td><td>%s</td></tr>"
                         % (html.escape(cat),
                            html.escape((val or "")[:200])))
            report_parts.append(
                "<h2>%s (%s)</h2><table border=\"1\">"
                "<tr><th>category</th><th>removed value</th></tr>%s"
                "</table>" % (html.escape(rel or "item %d" % index),
                              fmt, rows))
        # the copy goes to handoff/ under the original name (or the
        # index form with --no-paths)
        copy_name = rel if include_paths else \
            "%04d%s" % (index, path.suffix.lower())
        copy = out / "handoff" / copy_name
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(out_bytes)
        tell("Clean: %s -> %s" % (rel, copy))
        items.append(item)

    receipt = {
        "receipt_version": CN_RECEIPT_VERSION,
        "kind": "sieve-clean",
        "tool": {"name": "sieve-tray", "version": __version__},
        "engines": {},
        "settings": {
            "input": str(src),
            "no_paths": bool(no_paths),
        },
        "items": items,
        "summary": {
            "files": len(items),
            "cleaned": cleaned,
            "refused": refused,
            "not_applicable": not_app,
            "orientation_kept": orientation_count,
        },
    }
    # the local report (the removed values live here, never in
    # handoff/ - §3.1-14); the receipt stays LAST
    local = out / "local" / "clean-report.html"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>clean report</title></head><body>"
        "<h1>clean report</h1><p>input: %s</p>%s"
        "</body></html>" % (html.escape(str(src)),
                            "\n".join(report_parts)),
        encoding="utf-8")
    tell("Clean: report %s" % local)
    receipt["digest"] = _gate_digest(receipt)
    _gate_write_atomic(out / "handoff" / "clean-receipt.json",
                       _gate_norm_json(receipt).encode("utf-8"))
    tell("Clean: receipt %s" % (out / "handoff" / "clean-receipt.json"))
    return receipt


def _cn_write_zip_stream(buf, members):
    """The deterministic zip bytes (the pack rules) into an open
    stream."""
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for arcname, data in sorted(
                members, key=lambda m: str(m[0]).encode("utf-8")):
            name = str(arcname)
            zi = zipfile.ZipInfo(name, date_time=_CN_ZIP_STAMP)
            zi.create_system = 3
            if name.endswith("/"):
                zi.external_attr = _CN_ZIP_DIR_ATTR
            else:
                zi.external_attr = _CN_ZIP_FILE_ATTR
            zi.compress_type = zipfile.ZIP_STORED
            zf.writestr(zi, data)
