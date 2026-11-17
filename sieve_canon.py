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
    # the decode resolution (§3.2-3): BOM codec, strict UTF-8, then
    # the named codec - never a guess
    bom = obs["bom"]
    body = _cn_detect_bom(data)[1]
    text = None
    if bom is not None:
        text = _cn_strict_decode(body, bom)
        if text is None:
            item["status"] = "refused"
            item["reason"] = "parse_failed"
            return item, None
    elif obs["utf8_valid"]:
        text = data.decode("utf-8")
    elif from_encoding:
        text = _cn_strict_decode(data, from_encoding)
        if text is None:
            item["status"] = "refused"
            item["reason"] = "parse_failed"
            return item, None
    else:
        item["status"] = "refused"
        item["reason"] = "encoding_unknown"
        item["candidates"] = _cn_strict_candidates(data)
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
