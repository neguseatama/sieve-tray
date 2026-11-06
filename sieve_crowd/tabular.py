"""The input layer: character codes for CSV, one entry for every format.

Every subcommand reads its table through :func:`read_input` since v0.9.0.
The CLI resolves the format (from the extension or ``--in-format``), reads
the raw bytes and hands them over; this module owns the character-code
policy and dispatches to the CSV/JSON/XML readers or the safe .xlsx reader.

Character-code policy (design 3.1, the series-wide policy):

    ``auto`` tries, in order, and takes the first candidate that holds:

    1. the file starts with a UTF-8 BOM -> ``utf-8-sig``
    2. the whole file decodes as strict UTF-8 -> ``utf-8``
    3. the whole file decodes as strict CP932 (Windows-31J) -> ``cp932``
    4. none of them -> refused (``unsupported_encoding``, exit 1)

    UTF-16 / UTF-32 BOMs are refused outright.  ``errors="replace"`` and
    ``"ignore"`` are never used: one bad byte sinks the candidate.  When
    CP932 is adopted, one stderr notice line is printed (by the CLI, from
    the notices returned here); the notice never reaches result files,
    receipts or the scan HTML, so no pin moves.  ``--encoding`` pins the
    codec (no auto fall-through); ``auto`` is the default.

The layer imports the standard library and sibling stdlib-only modules
only (T101).  xlsx_reader is imported lazily, so reading a CSV never
pulls the xlsx machinery into the import closure (T103).
"""
from __future__ import annotations

from .csvio import read_table_text
from .jsonio import read_json
from .model import InputError, InputRefused
from .xmlio import read_xml

ENCODINGS = ("auto", "utf-8", "utf-8-sig", "cp932")

_NOTICE_CP932_AUTO = "input encoding: cp932 (auto)"
_NOTICE_CP932_SPEC = "input encoding: cp932 (specified)"

_UTF16_32_BOMS = (b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff",
                  b"\xff\xfe\x00\x00")


def decode_csv(data: bytes, encoding: str = "auto") -> tuple[str, list[str]]:
    """Resolve the character code and decode strictly.

    Returns the text and the stderr notices (empty for the UTF-8 family).
    Raises ``InputRefused("unsupported_encoding")`` when nothing holds.
    """
    if encoding not in ENCODINGS:
        raise InputError(f"unknown encoding {encoding!r}")
    if encoding == "auto":
        if data[:4] in _UTF16_32_BOMS or data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            raise InputRefused("unsupported_encoding")
        if data.startswith(b"\xef\xbb\xbf"):
            try:
                return data.decode("utf-8-sig"), []
            except UnicodeDecodeError:
                pass
        try:
            return data.decode("utf-8"), []
        except UnicodeDecodeError:
            pass
        try:
            data.decode("cp932")
        except UnicodeDecodeError:
            raise InputRefused("unsupported_encoding") from None
        return data.decode("cp932"), [_NOTICE_CP932_AUTO]
    if encoding == "cp932":
        try:
            data.decode("cp932")
        except UnicodeDecodeError:
            raise InputRefused("unsupported_encoding") from None
        return data.decode("cp932"), [_NOTICE_CP932_SPEC]
    try:
        return data.decode(encoding), []
    except UnicodeDecodeError:
        raise InputRefused("unsupported_encoding") from None


def read_input(data: bytes, fmt: str, *, delimiter: str | None = None,
               encoding: str | None = None, sheet: str | None = None,
               path: str | None = None,
               ) -> tuple[list[str], list[list[str]], list[str]]:
    """Read a table of the given format; returns (header, rows, notices).

    ``notices`` are one-line stderr observations the CLI prints after the
    read (encoding adoption, sheet selection, missing formula caches).
    JSON/XML stay UTF-8 by specification; their readers are unchanged.
    """
    if fmt == "csv":
        text, notices = decode_csv(data, encoding if encoding else "auto")
        header, rows = read_table_text(text, delimiter or ",")
        return header, rows, notices
    if fmt == "xlsx":
        from . import xlsx_reader     # lazy: a csv read never pulls it in
        header, rows, notices = xlsx_reader.read_workbook(
            data, sheet=sheet, path=path)
        return header, rows, notices
    if fmt == "json":
        header, rows = read_json(data)
        return header, rows, []
    if fmt == "xml":
        header, rows = read_xml(data)
        return header, rows, []
    raise InputError(f"unknown table format {fmt!r}")
