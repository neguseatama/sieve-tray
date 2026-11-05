"""Invisible-character observation for ``plan``: count, never change.

Every cell of every column — the rows ``plan`` already reads, so the plan's
own ``max_rows`` guard stays the only cap — is scanned for characters from
the shared chartable's ``invisible`` categories.  Per column the scan records:

* ``rows``   how many rows of the column contain at least one invisible char
* ``chars``  the total number of invisible characters
* ``kinds``  which of the four kinds were seen (sorted names)

One warning per column is emitted when the column's declared role is
``keep``, ``qi`` or ``sensitive`` and ``rows`` is positive; warnings are in
column-name sort order.  ``id`` and ``drop`` columns are counted in the
summary only: their values never reach the output verbatim (pseudonymized or
dropped), so there is nothing for the operator to act on.

This is an observation, not a change: no cell is rewritten, ``run`` never
reaches this module, and the findings carry counts and kind names only — no
cell value and no code point ever leaves this module (the same sentinel rule
as every other report).
"""
from __future__ import annotations

import re
from typing import Mapping, Sequence

_KINDS = ("bidi_control", "tag", "variation_selector", "zero_width")  # sorted

_WARN_ROLES = ("keep", "qi", "sensitive")


def _span(lo: int, hi: int) -> str:
    if lo == hi:
        return re.escape(chr(lo))
    if hi == lo + 1:
        return re.escape(chr(lo)) + re.escape(chr(hi))
    return re.escape(chr(lo)) + "-" + re.escape(chr(hi))


def _pattern(categories: dict[str, frozenset[int]]) -> "re.Pattern[str]":
    """One compiled character class covering every invisible code point."""
    cps = sorted(set().union(*categories.values()))
    parts: list[str] = []
    start = prev = None
    for cp in cps:
        if prev is None or cp != prev + 1:
            if start is not None:
                parts.append(_span(start, prev))
            start = cp
        prev = cp
    if start is not None:
        parts.append(_span(start, prev))
    return re.compile("[" + "".join(parts) + "]")


def analyze(header: Sequence[str], rows: Sequence[Sequence[str]],
            roles: Mapping[str, str]) -> tuple[list[dict], dict]:
    """Scan every cell of every column.

    ``roles`` maps column name -> declared role value (``keep``/``qi``/...).
    Returns ``(warnings, summary)`` for ``findings.warnings`` (code
    ``hidden_chars``, column-name sort order) and the findings JSON's
    ``hidden_chars_summary`` object.
    """
    from .chartable import invisible_categories   # lazy: run never loads the table

    cats = invisible_categories()
    kind_of: dict[int, str] = {}
    for kind in _KINDS:
        for cp in cats[kind]:
            kind_of[cp] = kind
    pat = _pattern(cats)

    pos = {h: i for i, h in enumerate(header)}
    warnings: list[dict] = []
    flagged = 0
    for name in sorted(pos):
        idx = pos[name]
        rows_with = 0
        chars = 0
        kinds: set[str] = set()
        for r in rows:
            cell = r[idx]
            if cell.isascii():
                continue                     # every invisible char is non-ASCII
            hits = pat.findall(cell)
            if not hits:
                continue
            rows_with += 1
            chars += len(hits)
            kinds.update(kind_of[ord(ch)] for ch in hits)
        if rows_with and roles.get(name) in _WARN_ROLES:
            flagged += 1
            warnings.append({"code": "hidden_chars", "column": name,
                             "declared_role": roles.get(name),
                             "rows": rows_with, "chars": chars,
                             "kinds": sorted(kinds)})
    return warnings, {"columns_checked": len(pos), "columns_flagged": flagged}
