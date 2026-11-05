"""The shared character table (chartable v1) and its fixed fold.

``chartable_v1.json`` is a byte-exact replica of the Sieve Lens canonical
table: the Lens owns the standard, this copy is pinned by sha256, and
changes to the standard are made upstream on the Lens side — not by local
edits.  The fold is a FIXED mapping built from that file, with no lookups
into the Python Unicode database, so identical input folds to identical
output on every Python build.

``fold(text, dashes=False)`` applies, in this order:

1. invisible characters (all kinds) are removed;
2. twins and the fullwidth ASCII range are replaced by their ASCII twins;
3. the folding spaces (U+00A0, U+3000) become the ASCII space;
4. only with ``dashes=True``, the folding dashes (U+2010..U+2015, U+2212,
   U+30FC, U+FF70) become the ASCII hyphen-minus.

The four steps share no code point (validated at load), so one translation
pass is equivalent to running them in order.  Every mapping target is
printable ASCII, which makes the fold idempotent and leaves every printable
ASCII character invariant — pure-ASCII input therefore folds to itself and
older behavior is unchanged.

The table loads lazily, once, and its sha256 is verified against the pin
below; a missing, tampered or malformed table is a hard ChartableError —
never a silent fallback.  Loading is reachable only from inspect/plan (via
the hint pack and the hidden-character observation); ``run`` never gets here.
Pure-ASCII input takes an exact fast path: no key of the mapping is below
U+0080, so an ASCII string folds to itself without a table lookup.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Optional

CHARTABLE_SHA256 = "c5ae4757bc9d07a2dcd1507d662460c3412c932d73318e54912569608242e605"
SCHEMA = "sieve-chartable/1"
_TABLE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "chartable_v1.json")

_HEX = re.compile(r"[0-9A-F]{4,6}\Z")
_KINDS = ("bidi_control", "tag", "variation_selector", "zero_width")  # sorted


class ChartableError(Exception):
    """The shared character table is missing, tampered with, or malformed."""


def _cp(entry) -> int:
    if not isinstance(entry, str) or not _HEX.fullmatch(entry):
        raise ChartableError(f"the shared character table: bad code point {entry!r}")
    return int(entry, 16)


def _range(entry) -> tuple[int, int]:
    if (not isinstance(entry, (list, tuple)) or len(entry) != 2
            or not all(isinstance(x, str) for x in entry)):
        raise ChartableError("the shared character table: a range must be [lo, hi]")
    lo, hi = _cp(entry[0]), _cp(entry[1])
    if lo > hi:
        raise ChartableError(f"the shared character table: reversed range {entry!r}")
    return lo, hi


class ChartTable:
    """A validated table: the two fold mappings plus the invisible categories."""

    def __init__(self, base: dict[int, Optional[str]], dashes: dict[int, str],
                 categories: dict[str, frozenset[int]]):
        self._base = base
        self._with_dashes: dict[int, Optional[str]] = {**base, **dashes}
        self._categories = categories

    def fold(self, text: str, dashes: bool = False) -> str:
        if text.isascii():
            return text        # exact fast path: no key is below U+0080
        return text.translate(self._with_dashes if dashes else self._base)

    def invisible_categories(self) -> dict[str, frozenset[int]]:
        return self._categories


def load_table(raw: bytes) -> ChartTable:
    """Verify the sha256 pin on the exact bytes, parse, and build the fold."""
    digest = hashlib.sha256(raw).hexdigest()
    if digest != CHARTABLE_SHA256:
        raise ChartableError(
            f"the shared character table is not the pinned one "
            f"(sha256 {digest}, expected {CHARTABLE_SHA256})")
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise ChartableError("the shared character table: not valid UTF-8") from None
    except json.JSONDecodeError as exc:
        raise ChartableError(f"the shared character table: not valid JSON ({exc.msg})") from None
    return parse_table(data)


def parse_table(data) -> ChartTable:
    """Validate one parsed table object and build the fold (pure)."""
    if not isinstance(data, dict):
        raise ChartableError("the shared character table: the top level must be an object")
    if data.get("schema") != SCHEMA:
        raise ChartableError(f"the shared character table: 'schema' must be {SCHEMA!r}")
    if data.get("version") != 1 or isinstance(data.get("version"), bool):
        raise ChartableError("the shared character table: 'version' must be 1")
    if not isinstance(data.get("description"), str):
        raise ChartableError("the shared character table: 'description' must be a string")

    inv = data.get("invisible")
    if not isinstance(inv, dict):
        raise ChartableError("the shared character table: 'invisible' must be an object")
    categories: dict[str, frozenset[int]] = {}
    for kind in _KINDS:
        items = inv.get(kind)
        if not isinstance(items, list):
            raise ChartableError(f"the shared character table: invisible.{kind} must be a list")
        cps: set[int] = set()
        for entry in items:
            lo, hi = _range(entry) if isinstance(entry, list) else (_cp(entry),) * 2
            cps.update(range(lo, hi + 1))
        categories[kind] = frozenset(cps)

    twins = data.get("twins")
    if not isinstance(twins, dict) or not twins:
        raise ChartableError("the shared character table: 'twins' must be a non-empty object")
    fa = data.get("fullwidth_ascii")
    if not isinstance(fa, dict) or not {"base", "from", "to"} <= set(fa):
        raise ChartableError("the shared character table: 'fullwidth_ascii' must be "
                             "an object with 'base', 'from' and 'to'")
    spaces = data.get("spaces")
    if not isinstance(spaces, list):
        raise ChartableError("the shared character table: 'spaces' must be a list")
    dash_list = data.get("dashes")
    if not isinstance(dash_list, list):
        raise ChartableError("the shared character table: 'dashes' must be a list")

    base: dict[int, Optional[str]] = {}
    for kind in _KINDS:                       # 1. invisible -> removed
        for cp in categories[kind]:
            _put(base, cp, None)
    for src, dst in twins.items():            # 2. look-alike twins -> ASCII
        cp = _cp(src)
        if not isinstance(dst, str) or len(dst) != 1 or not ord(dst) <= 0x7E:
            raise ChartableError(
                f"the shared character table: twins.{src} must map to one ASCII character")
        _put(base, cp, dst)
    lo, hi = _range([fa["from"], fa["to"]])   # 2. fullwidth ASCII range
    base_cp = _cp(fa["base"])
    if base_cp + (hi - lo) > 0x7E:
        raise ChartableError("the shared character table: fullwidth_ascii leaves the "
                             "printable ASCII range")
    for cp in range(lo, hi + 1):
        _put(base, cp, chr(base_cp + (cp - lo)))
    for src in spaces:                        # 3. folding spaces -> ASCII space
        _put(base, _cp(src), " ")

    dash_map: dict[int, str] = {}
    for src in dash_list:                     # 4. folding dashes -> '-'
        cp = _cp(src)
        if cp in dash_map:
            raise ChartableError(f"the shared character table: duplicate dash {src!r}")
        dash_map[cp] = "-"
    return ChartTable(base, dash_map, categories)


def _put(mapping: dict[int, Optional[str]], cp: int, target: Optional[str]) -> None:
    if 0x20 <= cp <= 0x7E:
        raise ChartableError(
            f"the shared character table: printable ASCII U+{cp:04X} must never be a key")
    if cp in mapping:
        if mapping[cp] == target:
            return        # twins and the fullwidth range agree on the target
        raise ChartableError(
            f"the shared character table: code point U+{cp:04X} maps to two "
            f"different targets")
    if target is not None and ord(target) > 0x7E:
        raise ChartableError(
            f"the shared character table: the target of U+{cp:04X} is not ASCII")
    mapping[cp] = target


_table: Optional[ChartTable] = None


def _get() -> ChartTable:
    global _table
    if _table is None:
        try:
            with open(_TABLE_FILE, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            raise ChartableError(
                f"the shared character table is missing ({exc.strerror})") from None
        _table = load_table(raw)
    return _table


def fold(text: str, dashes: bool = False) -> str:
    """Fold one value through the shared table (see the module docstring)."""
    if text.isascii():
        return text            # exact fast path: no key is below U+0080
    return _get().fold(text, dashes)


def invisible_categories() -> dict[str, frozenset[int]]:
    """The invisible-character code points, by kind (loaded once)."""
    return _get().invisible_categories()
