"""Format dispatch: detect a table format from a file extension and read/write it.

CSV, JSON and XML (all UTF-8 until v0.8.2; CSV gained the series-wide
character-code policy in v0.9.0), and .xlsx since v0.9.0 (read-only,
through the safe reader).  Every adapter normalizes to one string table,
so the engine never sees a format.  .xls and .xlsm stay refused (D12):
they would need third-party readers.
"""
from __future__ import annotations

from typing import Optional

from .csvio import read_table as _read_csv, write_table as _write_csv
from .jsonio import read_json, write_json
from .model import InputError, InputRefused
from .xmlio import read_xml, write_xml

FORMATS = ("csv", "json", "xml")
IN_FORMATS = FORMATS + ("xlsx",)
_EXTENSIONS = {".csv": "csv", ".json": "json", ".xml": "xml",
               ".xlsx": "xlsx"}
_SPREADSHEET = {".xls", ".xlsm"}


def detect_format(extension: str) -> str:
    fmt = _EXTENSIONS.get(extension.lower())
    if fmt:
        return fmt
    if extension.lower() in _SPREADSHEET:
        raise InputRefused("unsupported_format")
    raise InputError(f"unknown table format {extension!r}; the supported formats are csv, "
                     f"json, xml and xlsx (choose one with --in-format / --out-format)")


def read_any(data: bytes, fmt: str,
             delimiter: Optional[str] = None) -> tuple[list[str], list[list[str]]]:
    if fmt == "csv":
        return _read_csv(data, delimiter or ",")
    if fmt == "json":
        return read_json(data)
    if fmt == "xml":
        return read_xml(data)
    raise InputError(f"unknown table format {fmt!r}")


def write_any(header: list[str], rows: list[list[str]], fmt: str,
              delimiter: Optional[str] = None) -> bytes:
    if fmt == "csv":
        return _write_csv(header, rows, delimiter or ",")
    if fmt == "json":
        return write_json(header, rows)
    if fmt == "xml":
        return write_xml(header, rows)
    raise InputError(f"unknown table format {fmt!r}")
