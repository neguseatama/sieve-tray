"""Format dispatch: detect a table format from a file extension and read/write it.

CSV, JSON and XML (all UTF-8, a BOM accepted).  Every adapter normalizes to one
string table, so the engine never sees a format.  Excel formats are deliberately
unsupported (see D12): they would need third-party readers.
"""
from __future__ import annotations

from typing import Optional

from .csvio import read_table as _read_csv, write_table as _write_csv
from .jsonio import read_json, write_json
from .model import InputError
from .xmlio import read_xml, write_xml

FORMATS = ("csv", "json", "xml")
_EXTENSIONS = {".csv": "csv", ".json": "json", ".xml": "xml"}
_SPREADSHEET = {".xlsx", ".xlsm", ".xls"}


def detect_format(extension: str) -> str:
    fmt = _EXTENSIONS.get(extension.lower())
    if fmt:
        return fmt
    if extension.lower() in _SPREADSHEET:
        raise InputError("Excel files are not supported; the supported formats are "
                         "csv, json and xml")
    raise InputError(f"unknown table format {extension!r}; the supported formats are csv, "
                     f"json and xml (choose one with --in-format / --out-format)")


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
