"""JSON adapter: an array of records, or an explicit ``{"header": ..., "rows": ...}`` object.

Every cell arrives as JSON and leaves as a string, so the rest of the pipeline stays
format-blind.  Strict by design: nested values, duplicate keys and the non-standard
``NaN``/``Infinity`` literals are rejected instead of being guessed away.
"""
from __future__ import annotations

import json
import math
from typing import Any

from .model import InputError

_CELL_RULES = ("a cell must be a string, a number, a boolean or null "
               "(nested objects and arrays are not cells)")
_TOP_SHAPE = ("expected an array of records ([{...}, ...]) or an object with exactly "
              "'header' and 'rows'")


def _reject_constant(name: str) -> Any:
    raise InputError(f"{name} is not valid JSON here (RFC 8259)")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise InputError(f"duplicate key {key!r} in the JSON input")
        seen.add(key)
    return dict(pairs)


def _load(data: bytes) -> Any:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("the input is not valid UTF-8") from None
    try:
        return json.loads(text, parse_constant=_reject_constant,
                          object_pairs_hook=_object_without_duplicates)
    except json.JSONDecodeError as exc:
        raise InputError(f"the input is not valid JSON ({exc})") from None


def _cell(value: Any, where: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):                       # before int: bool is an int subtype
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):                  # e.g. 1e400 overflows to inf
            raise InputError(f"{where}: the number is out of range")
        return repr(value)                            # shortest text that round-trips
    raise InputError(f"{where}: {_CELL_RULES}")


def read_json(data: bytes) -> tuple[list[str], list[list[str]]]:
    doc = _load(data)
    if isinstance(doc, list):                          # records form
        if not doc:
            raise InputError("the input has no header row")
        if not all(isinstance(rec, dict) for rec in doc):
            raise InputError("every record must be a JSON object ({...})")
        header = list(doc[0])
        if not header:
            raise InputError("the input has no header row")
        wanted = set(header)
        rows = []
        for i, rec in enumerate(doc, start=1):
            keys = set(rec)
            if keys != wanted:
                missing = ", ".join(sorted(wanted - keys)) or "-"
                extra = ", ".join(sorted(keys - wanted)) or "-"
                raise InputError(f"record {i} does not have the columns of record 1 "
                                 f"(missing: {missing}; unexpected: {extra})")
            rows.append([_cell(rec[h], f"record {i}") for h in header])
        return header, rows
    if isinstance(doc, dict):                          # explicit form
        if set(doc) != {"header", "rows"}:
            raise InputError(_TOP_SHAPE)
        header_raw, body = doc["header"], doc["rows"]
        if (not isinstance(header_raw, list) or not header_raw
                or not all(isinstance(h, str) for h in header_raw)):
            raise InputError("'header' must be a non-empty array of column names")
        if not isinstance(body, list):
            raise InputError("'rows' must be an array of arrays")
        header = list(header_raw)
        rows = []
        for i, row in enumerate(body, start=1):
            if not isinstance(row, list) or len(row) != len(header):
                width = len(row) if isinstance(row, list) else "wrong"
                raise InputError(f"row {i} has {width} fields, the header has {len(header)}")
            rows.append([_cell(v, f"row {i}") for v in row])
        return header, rows
    raise InputError(_TOP_SHAPE)


def write_json(header: list[str], rows: list[list[str]]) -> bytes:
    """Array of records, 2-space indented; an empty cell stays "" (never null)."""
    records = [dict(zip(header, row)) for row in rows]
    return (json.dumps(records, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
