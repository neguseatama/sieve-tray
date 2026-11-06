"""Safe .xlsx reading for Sieve Crowd (v0.9.0, standard library only).

The reading style follows Sieve Lens (same symbol names, no import): a
closed set of refusal codes carried by ``InputRefused`` (the message is
the code only -- never a part name, a cell value or a path), hard limits
on the file, the zip entry count, one expanded part, the expanded total
and the XML element count, DOCTYPE/ENTITY refusal (so entity expansion
never runs at all), per-part encryption and case-insensitive duplicate
checks, and the transitional spreadsheetml namespace accepted by URI
only (a renamed prefix with the standard URI reads fine, Strict OOXML is
refused).  Sheets are streamed row by row through XMLPullParser, so a
big sheet is never materialised as XML and the expansion budget is
counted while reading, not after.

Cell rules (design 3.3): strings from shared/inline/rich parts (furigana
``<rPh>`` is never a value), numbers as the raw text in the file,
booleans and error literals as their text, formulas from the cached
value (a missing cache is counted on stderr, values are never echoed),
date-styled serials converted to ISO (1900 and 1904 books), everything
else refused or empty exactly where the same CSV would be.

The limits are reading policy, not judgment: an input beyond a limit is
refused with a code instead of being read unbounded.  The defaults are
Lens's values (design 4-7; Crowd had no file-level limits before).
"""
from __future__ import annotations

import dataclasses
import datetime
import io
import os
import posixpath
import re
import stat
import zipfile
import zlib
from xml.etree import ElementTree as ET

from .model import InputError, InputRefused

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_CHUNK = 65536          # streamed part reads, like Lens
_DOCTYPE_WINDOW = 16    # a "<!DOCTYPE"/"<!ENTITY" never spans more

# builtin number-format ids that render a calendar date (14-17, 22 and the
# east-asian date families 27-36 / 50-58); pure-time formats (18-21, 45-47)
# are not dates, so their cells keep the raw serial text
BUILTIN_DATE_IDS = frozenset({14, 15, 16, 17, 22, 27, 28, 29, 30, 31, 32,
                              33, 34, 35, 36, 50, 51, 52, 53, 54, 55, 56,
                              57, 58})

_SERIAL_MAX_1900 = 2958465       # 9999-12-31 in the 1900 system
_DAYS_1900_PHANTOM = 60          # the Lotus leap-year day; unconvertible


@dataclasses.dataclass
class ReadLimits:
    """Reading policy (Lens-aligned; every value must be a positive int)."""

    max_file_bytes: int = 64 * 1024 * 1024    # whole input file
    max_entries: int = 10_000                 # zip entry count
    max_part_bytes: int = 32 * 1024 * 1024    # one expanded part
    max_total_bytes: int = 128 * 1024 * 1024  # expanded parts, summed
    max_elements: int = 1_000_000             # '<' bytes per XML part

    def __post_init__(self):
        for name in ("max_file_bytes", "max_entries", "max_part_bytes",
                     "max_total_bytes", "max_elements"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) \
                    or value <= 0:
                raise ValueError(
                    f"ReadLimits.{name} must be a positive integer, "
                    f"got {value!r}")


_XML_DECL_ENCODING_RE = re.compile(
    rb"^\xef\xbb\xbf?<\?xml\s[^>]*?encoding\s*=\s*[\"']([^\"']+)[\"']")


def _check_decl_and_doctype_head(head: bytes) -> None:
    """UTF-16/BOM and declared-encoding checks on the head of a part."""
    if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raise InputRefused("unsupported_encoding")
    m = _XML_DECL_ENCODING_RE.match(head)
    if m:
        declared = m.group(1).decode("ascii", "replace").strip().lower()
        if declared not in ("utf-8", "utf8"):
            raise InputRefused("unsupported_encoding")


def _check_static(data: bytes, limits: ReadLimits) -> None:
    """Static checks on a bounded XML part, before parsing (Lens style)."""
    _check_decl_and_doctype_head(data)
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise InputRefused("doctype_not_allowed")
    if data.count(b"<") > limits.max_elements:
        raise InputRefused("too_many_elements")


def _parse_bounded_xml(data: bytes):
    try:
        return ET.fromstring(data)
    except (ET.ParseError, ValueError):
        raise InputRefused("malformed_xml") from None


def _require_main_namespace(root) -> None:
    """Refuse a spreadsheetml part outside the transitional namespace.

    The namespace is judged by URI, never by prefix: a file written with
    any prefix still reads, Strict OOXML (a different URI) is refused --
    a part we would silently read as empty is an observation, not a
    success (Lens style).
    """
    tag = root.tag
    if not (isinstance(tag, str) and tag.startswith("{" + MAIN_NS + "}")):
        raise InputRefused("unsupported_namespace")


def _read_zip_part(zf, name: str, limits: ReadLimits,
                   budget: dict) -> bytes | None:
    """Read one small part under the bounds; None when absent.

    The declared size is not trusted: the decompressed read is chunked
    and stops at max_part_bytes, and every chunk counts against the
    shared total budget.
    """
    try:
        info = zf.getinfo(name)
    except KeyError:
        return None
    _check_part_info(info, limits)
    chunks: list[bytes] = []
    total = 0
    with zf.open(name) as f:
        while True:
            try:
                chunk = f.read(_CHUNK)
            except (zipfile.BadZipFile, EOFError, zlib.error, OSError):
                raise InputRefused("malformed_xml") from None
            if not chunk:
                break
            total += len(chunk)
            if total > limits.max_part_bytes:
                raise InputRefused("part_too_large")
            budget["total"] += len(chunk)
            if budget["total"] > limits.max_total_bytes:
                raise InputRefused("total_too_large")
            chunks.append(chunk)
    data = b"".join(chunks)
    _check_static(data, limits)
    return data


def _check_part_info(info, limits: ReadLimits) -> None:
    if info.flag_bits & 0x1:
        raise InputRefused("encrypted")
    if info.file_size > limits.max_part_bytes:
        raise InputRefused("part_too_large")


def _part_path(target: str) -> str:
    if target.startswith("/"):
        return target[1:]
    return posixpath.normpath(posixpath.join("xl", target))


def _col_index(ref: str) -> int:
    """'AB12' -> the 0-based column index 27 (letters only)."""
    letters = ""
    for ch in ref:
        if ch.isalpha():
            letters += ch.upper()
        else:
            break
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


# ----------------------------------------------------------------------
# workbook level
# ----------------------------------------------------------------------

def _sheet_list(workbook) -> list[tuple[str, str, bool]]:
    parent = workbook.find(f"{{{MAIN_NS}}}sheets")
    if parent is None:
        raise InputRefused("malformed_xml")
    sheets = []
    for sh in parent:
        if sh.tag != f"{{{MAIN_NS}}}sheet":
            continue
        rid = sh.get(f"{{{R_NS}}}id") or ""
        name = sh.get("name") or ""
        state = (sh.get("state") or "visible").strip().lower()
        sheets.append((name, rid, state in ("hidden", "veryhidden")))
    if not sheets:
        raise InputRefused("malformed_xml")
    return sheets


def _worksheet_targets(zf, limits, budget) -> dict:
    data = _read_zip_part(zf, "xl/_rels/workbook.xml.rels", limits, budget)
    if data is None:
        return {}
    root = _parse_bounded_xml(data)
    targets = {}
    for rel in root:
        if (rel.tag == f"{{{PKG_REL_NS}}}Relationship"
                and (rel.get("Type") or "").endswith("/worksheet")):
            targets[rel.get("Id") or ""] = rel.get("Target") or ""
    return targets


def _choose_sheet(sheets, sheet_arg):
    """-> (1-based position, rId, hidden); a bad choice is a usage error."""
    if sheet_arg is None:
        for pos, (name, rid, hidden) in enumerate(sheets, start=1):
            if not hidden:
                return pos, rid, False
        raise InputError(
            "the workbook has no visible sheet (choose one with --sheet)")
    text = str(sheet_arg)
    if re.fullmatch(r"[0-9]+", text):
        pos = int(text)
        if pos < 1 or pos > len(sheets):
            raise InputError(
                "no such sheet (give a sheet name or a 1-based index)")
        name, rid, hidden = sheets[pos - 1]
        return pos, rid, hidden
    for pos, (name, rid, hidden) in enumerate(sheets, start=1):
        if name == text:
            return pos, rid, hidden
    raise InputError("no such sheet (give a sheet name or a 1-based index)")


def _read_shared_strings(zf, limits, budget) -> list[str] | None:
    data = _read_zip_part(zf, "xl/sharedStrings.xml", limits, budget)
    if data is None:
        return None
    root = _parse_bounded_xml(data)
    _require_main_namespace(root)
    return [_si_text(si) for si in root
            if si.tag == f"{{{MAIN_NS}}}si"]


def _si_text(si) -> str:
    """Concatenate the visible text runs; <rPh> furigana is never a value."""
    parts: list[str] = []

    def collect(node) -> None:
        for child in node:
            tag = child.tag
            if tag == f"{{{MAIN_NS}}}rPh":
                continue                       # the reading, not the value
            if tag == f"{{{MAIN_NS}}}t":
                parts.append(child.text or "")
            elif tag == f"{{{MAIN_NS}}}r":
                collect(child)
            # rPr, phoneticPr, ... carry no text

    collect(si)
    return "".join(parts)


def _read_styles(zf, limits, budget):
    """-> (custom numFmt codes by id, numFmtId per cellXf)."""
    data = _read_zip_part(zf, "xl/styles.xml", limits, budget)
    if data is None:
        return {}, []
    root = _parse_bounded_xml(data)
    _require_main_namespace(root)
    custom: dict[int, str] = {}
    for nf in root.iter(f"{{{MAIN_NS}}}numFmt"):
        try:
            nid = int(nf.get("numFmtId") or "")
        except ValueError:
            continue
        custom[nid] = nf.get("formatCode") or ""
    xfs: list[int] = []
    cellxfs = root.find(f"{{{MAIN_NS}}}cellXfs")
    if cellxfs is not None:
        for xf in cellxfs:
            try:
                xfs.append(int(xf.get("numFmtId") or "0"))
            except ValueError:
                xfs.append(0)
    return custom, xfs


def _code_is_date(code: str) -> bool:
    """A custom format is a date when y/m/d sit outside the literals.

    Quoted sections, backslash escapes and bracketed prefixes (locale,
    colour, conditions) carry no format letters.  A lone ``m`` next to
    ``h``/``s`` is minutes, not a month, so time-only formats stay raw.
    """
    cleaned = re.sub(r"\[[^\]]*\]", "", code)
    cleaned = re.sub(r'"[^"]*"', "", cleaned)
    cleaned = re.sub(r"\\.", "", cleaned)
    if "y" in cleaned or "d" in cleaned:
        return True
    return "m" in cleaned and "h" not in cleaned and "s" not in cleaned


def _style_is_date(styles, style: int) -> bool:
    custom, xfs = styles
    if style < 0 or style >= len(xfs):
        return False
    nid = xfs[style]
    if nid in BUILTIN_DATE_IDS:
        return True
    code = custom.get(nid)
    return bool(code) and _code_is_date(code)


def _serial_to_iso(raw: str, date1904: bool) -> str:
    """A date-styled serial -> ISO; anything unconvertible is refused."""
    try:
        value = float(raw)
        days = int(value)
    except (ValueError, OverflowError):
        raise InputRefused("unsupported_format") from None
    frac = value - days
    if date1904:
        if value < 0:
            raise InputRefused("unsupported_format")
        base = datetime.datetime(1904, 1, 1)
    else:
        if value < 1 or days > _SERIAL_MAX_1900:
            raise InputRefused("unsupported_format")
        if days == _DAYS_1900_PHANTOM:
            # 1900-02-29 does not exist; the same rule as every converter
            raise InputRefused("unsupported_format")
        base = (datetime.datetime(1899, 12, 31) if days <= 59
                else datetime.datetime(1899, 12, 30))
        # 1899-12-31 + days holds for serials <= 59; from 61 on the phantom
        # day is already skipped by the 1899-12-30 base (61 -> 1900-03-01)
    seconds = round(frac * 86400)
    if seconds >= 86400:
        seconds -= 86400
        days += 1
    try:
        stamp = base + datetime.timedelta(days=days, seconds=seconds)
    except (OverflowError, OSError):
        raise InputRefused("unsupported_format") from None
    if stamp.year > 9999:
        raise InputRefused("unsupported_format")
    if seconds or frac:
        return stamp.strftime("%Y-%m-%d %H:%M:%S")
    return stamp.strftime("%Y-%m-%d")


# ----------------------------------------------------------------------
# sheet level (streamed)
# ----------------------------------------------------------------------

def _row_values(row, shared, styles, date1904, missing) -> list[str]:
    values: dict[int, str] = {}
    last = -1
    for cell in row:
        if cell.tag != f"{{{MAIN_NS}}}c":
            continue
        ref = cell.get("r")
        if ref and ref[0].isalpha():
            index = _col_index(ref)
        else:
            index = last + 1
        last = index
        values[index] = _cell_value(cell, shared, styles, date1904, missing)
    if not values:
        return []
    width = max(values) + 1
    return [values.get(i, "") for i in range(width)]


def _cell_value(cell, shared, styles, date1904, missing) -> str:
    kind = cell.get("t", "n")
    v_el = cell.find(f"{{{MAIN_NS}}}v")
    if kind == "inlineStr":
        is_el = cell.find(f"{{{MAIN_NS}}}is")
        if is_el is None:
            return ""
        return _si_text(is_el)
    if kind == "s":
        if v_el is None or v_el.text is None:
            return ""
        try:
            index = int(v_el.text)
        except ValueError:
            raise InputRefused("malformed_xml") from None
        if shared is None or index < 0 or index >= len(shared):
            raise InputRefused("malformed_xml")
        return shared[index]
    if kind == "b":
        flag = (v_el.text or "").strip() if v_el is not None else ""
        return "TRUE" if flag in ("1", "true") else "FALSE"
    if kind == "e":
        return (v_el.text or "") if v_el is not None else ""
    # numbers (kind "n" or absent) and formula results (kind "str")
    if v_el is None or v_el.text is None or v_el.text == "":
        if cell.find(f"{{{MAIN_NS}}}f") is not None:
            missing[0] += 1              # no cached value; counted, unnamed
            return ""
        return ""
    raw = v_el.text
    if kind == "str":
        return raw
    style = cell.get("s") or "0"
    try:
        style_index = int(style)
    except ValueError:
        style_index = 0
    if _style_is_date(styles, style_index):
        return _serial_to_iso(raw, date1904)
    return raw                            # the file's own numeric text


def _read_sheet(zf, part: str, limits: ReadLimits, budget: dict,
                shared, styles, date1904):
    """Stream one sheet part row by row; -> (grid, missing-cache count).

    The grid keeps blank rows as [] (a blank CSV line) and rows of empty
    cells as ["", ...]; the table rules (trailing margins, header width)
    are applied by :func:`_table_from_grid`, the same rules csvio's
    parser applies to CSV text.
    """
    try:
        info = zf.getinfo(part)
    except KeyError:
        raise InputRefused("malformed_xml") from None
    _check_part_info(info, limits)
    parser = ET.XMLPullParser(events=("start", "end"))
    root_checked = False
    grid: list[list[str]] = []
    missing = [0]
    elements = 0
    fed = 0
    tail = b""
    with zf.open(part) as stream:
        while True:
            try:
                chunk = stream.read(_CHUNK)
            except (zipfile.BadZipFile, EOFError, zlib.error, OSError):
                raise InputRefused("malformed_xml") from None
            done = not chunk
            if chunk:
                window = tail + chunk
                if b"<!DOCTYPE" in window or b"<!ENTITY" in window:
                    raise InputRefused("doctype_not_allowed")
                if fed == 0:
                    _check_decl_and_doctype_head(chunk)
                fed += len(chunk)
                if fed > limits.max_part_bytes:
                    raise InputRefused("part_too_large")
                budget["total"] += len(chunk)
                if budget["total"] > limits.max_total_bytes:
                    raise InputRefused("total_too_large")
                elements += chunk.count(b"<")
                if elements > limits.max_elements:
                    raise InputRefused("too_many_elements")
                tail = chunk[-_DOCTYPE_WINDOW:]
                try:
                    parser.feed(chunk)
                except ET.ParseError:
                    raise InputRefused("malformed_xml") from None
            for event, elem in parser.read_events():
                if event == "start":
                    if not root_checked:
                        root_checked = True
                        _require_main_namespace(elem)
                elif elem.tag == f"{{{MAIN_NS}}}row":
                    grid.append(_row_values(elem, shared, styles, date1904,
                                            missing))
                    elem.clear()
            if done:
                break
    try:
        parser.close()
    except ET.ParseError:
        raise InputRefused("malformed_xml") from None
    return grid, missing[0]


def _table_from_grid(grid: list[list[str]]):
    """csvio's table rules over the streamed grid (design 3.3)."""
    while grid and all(v == "" for v in grid[-1]):
        grid.pop()                        # the empty bottom margin
    body = [r for r in grid[1:] if r != []]   # blank rows, like csvio
    if not grid or not grid[0]:
        raise InputError("the input has no header row")
    header = grid[0]
    if any(v != "" for v in header):
        width = len(header)
        while width > 0 and header[width - 1] == "":
            width -= 1                    # the empty right margin
        header = header[:width]
    else:
        width = len(header)               # an all-empty header: as csvio
    rows = []
    for i, r in enumerate(body, start=2):
        if len(r) > width:
            raise InputError(
                f"row {i} has {len(r)} fields, the header has {width}")
        rows.append(r + [""] * (width - len(r)))
    return header, rows


# ----------------------------------------------------------------------
# entry point
# ----------------------------------------------------------------------

def read_workbook(data: bytes, *, sheet: str | None = None,
                  limits: ReadLimits | None = None,
                  path: str | None = None):
    """Read an .xlsx byte string; -> (header, rows, stderr notices)."""
    limits = limits if limits is not None else ReadLimits()
    if path is not None and path != "-":
        st = os.stat(path)
        if not stat.S_ISREG(st.st_mode):
            raise InputRefused("not_regular_file")
    if len(data) > limits.max_file_bytes:
        raise InputRefused("file_too_large")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, EOFError):
        raise InputRefused("unsupported_format") from None
    with zf:
        infos = zf.infolist()
        if len(infos) > limits.max_entries:
            raise InputRefused("too_many_entries")
        seen = set()
        for info in infos:
            lowered = info.filename.lower()
            if lowered in seen:
                raise InputRefused("duplicate_part")
            seen.add(lowered)
        budget = {"total": 0}
        workbook_bytes = _read_zip_part(zf, "xl/workbook.xml", limits,
                                        budget)
        if workbook_bytes is None:
            raise InputRefused("main_part_missing")
        workbook = _parse_bounded_xml(workbook_bytes)
        _require_main_namespace(workbook)
        date1904 = (workbook.find(f"{{{MAIN_NS}}}workbookPr") is not None
                    and (workbook.find(f"{{{MAIN_NS}}}workbookPr")
                         .get("date1904") or "").strip()
                        in ("1", "true"))
        sheets = _sheet_list(workbook)
        targets = _worksheet_targets(zf, limits, budget)
        position, rid, hidden = _choose_sheet(sheets, sheet)
        target = targets.get(rid)
        if not target:
            raise InputRefused("malformed_xml")
        part = _part_path(target)
        shared = _read_shared_strings(zf, limits, budget)
        styles = _read_styles(zf, limits, budget)
        grid, missing = _read_sheet(zf, part, limits, budget, shared,
                                    styles, date1904)
    header, rows = _table_from_grid(grid)
    notices = []
    count = len(sheets)
    line = (f"input workbook: {count} "
            f"{'sheet' if count == 1 else 'sheets'}, using sheet {position}")
    if hidden:
        line += " (hidden)"
    if count > 1 or hidden:
        notices.append(line)
    if missing:
        notices.append(f"input workbook: {missing} formula cells have "
                       f"no cached value")
    return header, rows, notices
