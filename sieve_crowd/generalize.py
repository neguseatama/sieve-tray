"""Generalization hierarchies.

Every generalizer has levels 0..L:  0 = the value itself,  L = "*" (fully suppressed).
Each level is a *coarsening* of the previous one (two values that share a label at level j
share it at every level above).  The lattice search relies on this property, so it is
validated at construction time.
"""
from __future__ import annotations

import datetime
import math
import re
from bisect import bisect_right
from typing import Any, Mapping, Sequence

from .model import ConfigError

STAR = "*"
_INT = re.compile(r"^[+-]?\d+$")
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


class Generalizer:
    levels: int  # index of the top ("*") level

    def prepare(self, distinct_values: Sequence[str]) -> None:
        """Called once with the distinct (normalized) values of the column."""

    def label(self, value: str, level: int) -> str:
        raise NotImplementedError

    def describe(self, level: int, lang: str) -> str:
        raise NotImplementedError

    def _check(self, level: int) -> None:
        if not 0 <= level <= self.levels:
            raise ValueError(f"level {level} outside 0..{self.levels}")


class NumericGen(Generalizer):
    """Integer/decimal numbers into nested ranges: widths must be positive integers, each a multiple of the previous."""

    def __init__(self, widths: Sequence[int]) -> None:
        if not widths:
            raise ConfigError("numeric: 'widths' must not be empty")
        prev = None
        for w in widths:
            if not isinstance(w, int) or isinstance(w, bool) or w <= 0:
                raise ConfigError("numeric: widths must be positive integers")
            if prev is not None and (w <= prev or w % prev != 0):
                raise ConfigError("numeric: each width must be a larger multiple of the previous one")
            prev = w
        self.widths = tuple(widths)
        self.levels = len(self.widths) + 1
        self._int_mode = True

    def prepare(self, distinct_values: Sequence[str]) -> None:
        self._int_mode = all(v == "" or _INT.match(v) for v in distinct_values)

    def label(self, value: str, level: int) -> str:
        self._check(level)
        if level == 0:
            return value
        if level == self.levels or value == "":
            return STAR
        w = self.widths[level - 1]
        if self._int_mode:
            x = int(value)
            lo = (x // w) * w
            return f"{lo}-{lo + w - 1}"
        try:
            x = float(value)
        except ValueError:
            return STAR
        if not math.isfinite(x):
            return STAR
        lo = math.floor(x / w) * w
        return f"[{lo},{lo + w})"

    def describe(self, level: int, lang: str) -> str:
        if level == 0:
            return "exact" if lang == "en" else "そのまま"
        if level == self.levels:
            return "suppressed" if lang == "en" else "全体を隠す"
        w = self.widths[level - 1]
        return f"ranges of {w}" if lang == "en" else f"{w}刻みの範囲"


class BinsGen(Generalizer):
    """Numbers into custom, non-uniform bins: `edges` are strictly increasing interior boundaries,
    so the first and the last bin are open-ended (ages 0-19 / 20-39 / 40-64 / 65+ are edges [0, 20, 40, 65]).
    Levels: 0 the value itself · 1 the bins · 2 "*".  Labels use the edge values as given;
    integer columns use "<0", "0-19", "65+", decimal columns use "<0.5", "[0.5,20)", ">=65".
    """

    def __init__(self, edges: Sequence[Any]) -> None:
        if not edges:
            raise ConfigError("numeric: 'bins' must not be empty")
        vals = []
        for e in edges:
            if isinstance(e, bool) or not isinstance(e, (int, float)) or not math.isfinite(e):
                raise ConfigError("numeric: 'bins' must be finite numbers")
            vals.append(e)
        if any(b <= a for a, b in zip(vals, vals[1:])):
            raise ConfigError("numeric: 'bins' must be strictly increasing")
        self.edges = tuple(vals)
        self.levels = 2
        self._int_mode = True

    def prepare(self, distinct_values: Sequence[str]) -> None:
        self._int_mode = all(v == "" or _INT.match(v) for v in distinct_values)
        if self._int_mode and any(not float(e).is_integer() for e in self.edges):
            raise ConfigError("numeric: 'bins' edges must be integers when the column holds integers")

    def _fmt(self, e: Any) -> str:
        return str(int(e)) if self._int_mode else str(e)

    def label(self, value: str, level: int) -> str:
        self._check(level)
        if level == 0:
            return value
        if level == self.levels or value == "":
            return STAR
        try:
            x = int(value) if self._int_mode else float(value)
        except ValueError:
            return STAR
        if not math.isfinite(x):
            return STAR
        i = bisect_right(self.edges, x)
        if i == 0:
            return "<" + self._fmt(self.edges[0])
        if i == len(self.edges):
            return self._fmt(self.edges[-1]) + "+" if self._int_mode else ">=" + self._fmt(self.edges[-1])
        lo, hi = self.edges[i - 1], self.edges[i]
        if self._int_mode:
            return f"{self._fmt(lo)}-{int(hi) - 1}"
        return f"[{self._fmt(lo)},{self._fmt(hi)})"

    def describe(self, level: int, lang: str) -> str:
        if level == 0:
            return "exact" if lang == "en" else "そのまま"
        if level == self.levels:
            return "suppressed" if lang == "en" else "全体を隠す"
        edge_text = ", ".join(self._fmt(e) for e in self.edges)
        return f"custom bins at {edge_text}" if lang == "en" else f"カスタム区間（境界 {edge_text}）"


class DateGen(Generalizer):
    """ISO dates YYYY-MM-DD: day, month, year, decade, suppressed."""

    levels = 4

    def label(self, value: str, level: int) -> str:
        self._check(level)
        if level == 0:
            return value
        if level == self.levels:
            return STAR
        m = _DATE.match(value)
        if not m:
            return STAR
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            datetime.date(y, mo, d)
        except ValueError:
            return STAR
        if level == 1:
            return f"{y:04d}-{mo:02d}"
        if level == 2:
            return f"{y:04d}"
        return f"{y // 10 * 10:04d}s"

    def describe(self, level: int, lang: str) -> str:
        en = ("exact date", "month", "year", "decade", "suppressed")
        ja = ("そのまま", "年月", "年", "年代", "全体を隠す")
        return (en if lang == "en" else ja)[level]


class PrefixGen(Generalizer):
    """Strings such as postal codes: mask 1..length trailing characters, then suppress."""

    def __init__(self, length: int) -> None:
        if not isinstance(length, int) or isinstance(length, bool) or length < 1:
            raise ConfigError("prefix: 'length' must be a positive integer")
        self.length = length
        self.levels = length + 1

    def label(self, value: str, level: int) -> str:
        self._check(level)
        if level == 0:
            return value
        if level == self.levels:
            return STAR
        if value == "":
            return STAR
        if level >= len(value):
            return STAR * len(value)
        return value[: len(value) - level] + STAR * level

    def describe(self, level: int, lang: str) -> str:
        if level == 0:
            return "exact" if lang == "en" else "そのまま"
        if level == self.levels:
            return "suppressed" if lang == "en" else "全体を隠す"
        return f"last {level} character(s) masked" if lang == "en" else f"末尾{level}文字を隠す"


class CategoryGen(Generalizer):
    """Categories with an optional hierarchy: value -> [parent, grandparent, ...]."""

    def __init__(self, hierarchy: Mapping[str, Sequence[str]] | None = None) -> None:
        self._chains: dict[str, tuple[str, ...]] = {}
        depth = 0
        for value, chain in (hierarchy or {}).items():
            if not isinstance(chain, (list, tuple)) or not all(isinstance(c, str) for c in chain):
                raise ConfigError("category: a hierarchy entry must map a value to a list of strings")
            if STAR in chain or not chain:
                raise ConfigError("category: ancestors must be non-empty and must not be '*'")
            self._chains[value] = tuple(chain)
            depth = max(depth, len(chain))
        self.depth = depth
        self.levels = depth + 1
        # every level must coarsen the previous one
        for j in range(1, depth):
            seen: dict[str, str] = {}
            for value in self._chains:
                a, b = self._at(value, j), self._at(value, j + 1)
                if seen.setdefault(a, b) != b:
                    raise ConfigError(
                        f"category: hierarchy is inconsistent: one level-{j} group has two different parents"
                    )

    def _at(self, value: str, level: int) -> str:
        chain = self._chains[value]
        return chain[min(level, len(chain)) - 1]

    def label(self, value: str, level: int) -> str:
        self._check(level)
        if level == 0:
            return value
        if level == self.levels:
            return STAR
        if value not in self._chains:
            return STAR
        return self._at(value, level)

    def describe(self, level: int, lang: str) -> str:
        if level == 0:
            return "exact" if lang == "en" else "そのまま"
        if level == self.levels:
            return "suppressed" if lang == "en" else "全体を隠す"
        return f"hierarchy level {level}" if lang == "en" else f"階層の{level}段目"


def make_generalizer(settings: Mapping[str, Any]) -> Generalizer:
    kind = settings.get("type")
    if kind == "numeric":
        if "bins" in settings:
            if "widths" in settings:
                raise ConfigError("numeric: use 'widths' or 'bins', not both")
            return BinsGen(settings["bins"])
        return NumericGen(settings.get("widths", [5, 10, 20, 50, 100]))
    if kind == "date":
        return DateGen()
    if kind == "prefix":
        if "length" not in settings:
            raise ConfigError("prefix: 'length' is required")
        return PrefixGen(settings["length"])
    if kind == "category":
        return CategoryGen(settings.get("hierarchy"))
    if kind == "exact":
        return CategoryGen(None)
    raise ConfigError("a qi column needs 'type': numeric, date, prefix, category or exact")
