from __future__ import annotations

import csv
import io

from .model import InputError


def read_table_text(text: str, delimiter: str = ",") -> tuple[list[str], list[list[str]]]:
    """Decoded CSV text with a header row (the syntax layer; v0.9.0).

    The character-code layer lives in :mod:`sieve_crowd.tabular`; this
    function is the v0.8.2 parsing behaviour unchanged, so the same text
    yields the very same table, errors and exit codes.
    """
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    except csv.Error as exc:
        raise InputError(f"the input is not valid CSV ({exc})") from None
    if not rows or not rows[0]:
        raise InputError("the input has no header row")
    header, body = rows[0], rows[1:]
    body = [r for r in body if r != []]  # blank lines
    for i, r in enumerate(body, start=2):
        if len(r) != len(header):
            raise InputError(f"row {i} has {len(r)} fields, the header has {len(header)}")
    return header, body


def read_table(data: bytes, delimiter: str = ",") -> tuple[list[str], list[list[str]]]:
    """UTF-8 (BOM allowed) CSV with a header row.

    Kept as the strict-UTF-8 byte entry; the CLI reads through
    :mod:`sieve_crowd.tabular` since v0.9.0.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("the input is not valid UTF-8") from None
    return read_table_text(text, delimiter)


def write_table(header: list[str], rows: list[list[str]], delimiter: str = ",") -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")
