"""Lattice search for the least generalization that gives every crowd >= k members.

Nodes are vectors of generalization levels, one per quasi-identifier.  A node is *acceptable*
when the records in too-small crowds (size < k, or fewer than l distinct sensitive values) are
at most the suppression budget.  Acceptability is monotone (generalizing further never hurts),
so the minimal total height is found by binary search over heights.
"""
from __future__ import annotations

import itertools
import math
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterator, Sequence


class Infeasible(Exception):
    """No generalization (not even suppressing every quasi-identifier) satisfies k and l."""


class SearchLimitExceeded(Exception):
    """More node evaluations than allowed."""


REFINE_MAX_NODES = 200_000   # refinement enumerates the lattice; skipped above this size


@dataclass(frozen=True)
class SearchResult:
    levels: tuple[int, ...]
    suppressed: tuple[int, ...]   # row indices to drop
    evaluations: int
    truncated: bool = False       # the refinement stopped at the evaluation limit


def nodes_at(height: int, tops: Sequence[int]) -> Iterator[tuple[int, ...]]:
    m = len(tops)
    suffix = [0] * (m + 1)
    for i in range(m - 1, -1, -1):
        suffix[i] = suffix[i + 1] + tops[i]

    def rec(i: int, rem: int) -> Iterator[tuple[int, ...]]:
        if i == m - 1:
            if 0 <= rem <= tops[i]:
                yield (rem,)
            return
        for v in range(max(0, rem - suffix[i + 1]), min(tops[i], rem) + 1):
            for tail in rec(i + 1, rem - v):
                yield (v,) + tail

    yield from rec(0, height)


class Searcher:
    def __init__(self, codes: Sequence[Sequence[list[int]]], cards: Sequence[Sequence[int]],
                 sens: Sequence[list[int]], n: int, k: int, l: int, budget: int, max_evals: int) -> None:
        self.codes, self.cards, self.sens = codes, cards, sens
        self.n, self.k, self.l, self.budget, self.max_evals = n, k, l, budget, max_evals
        self.tops = tuple(len(c) - 1 for c in codes)
        self.evals = 0
        self._cache: dict[tuple[int, ...], int] = {}

    def keys(self, vec: Sequence[int]) -> list[int]:
        acc = list(self.codes[0][vec[0]])
        for i in range(1, len(vec)):
            c, ci = self.codes[i][vec[i]], self.cards[i][vec[i]]
            acc = [a * ci + b for a, b in zip(acc, c)]
        return acc

    def _bad_classes(self, keys: list[int]) -> tuple[Counter, set[int]]:
        sizes = Counter(keys)
        bad = {key for key, c in sizes.items() if c < self.k}
        if self.l > 1:
            for s in self.sens:
                distinct = Counter(key for key, _ in set(zip(keys, s)))
                bad |= {key for key, d in distinct.items() if d < self.l}
        return sizes, bad

    def suppressed_count(self, vec: tuple[int, ...]) -> int:
        if vec in self._cache:
            return self._cache[vec]
        self.evals += 1
        if self.evals > self.max_evals:
            raise SearchLimitExceeded()
        sizes, bad = self._bad_classes(self.keys(vec))
        self._cache[vec] = sum(sizes[key] for key in bad)
        return self._cache[vec]

    def acceptable(self, vec: tuple[int, ...]) -> bool:
        return self.suppressed_count(vec) <= self.budget

    def exists(self, height: int) -> bool:
        return any(self.acceptable(v) for v in nodes_at(height, self.tops))

    def loss(self, vec: Sequence[int]) -> Fraction:
        return sum((Fraction(v, t) for v, t in zip(vec, self.tops)), Fraction(0))

    def weight(self, vec: Sequence[int]) -> int:
        """Integer form of the normalized loss: loss(vec) * lcm(tops)."""
        return sum(v * (self._lcm // t) for v, t in zip(vec, self.tops))

    def run(self) -> SearchResult:
        """Objective (lexicographic): least normalized generalization loss, then fewest suppressed
        records, then the smallest level vector.

        Phase 1 finds the least total height h* by binary search (nothing below h* is acceptable)
        and its best node.  Phase 2 looks at every other node of height >= h* whose loss does not
        exceed that node's loss, so the result is the optimum unless the evaluation limit is hit.
        """
        self._lcm = math.lcm(*self.tops)
        top_height = sum(self.tops)
        if not self.exists(top_height):
            raise Infeasible()
        lo, hi = 0, top_height
        while lo < hi:
            mid = (lo + hi) // 2
            if self.exists(mid):
                hi = mid
            else:
                lo = mid + 1
        candidates = [v for v in nodes_at(lo, self.tops) if self.acceptable(v)]
        best = min(candidates, key=lambda v: (self.weight(v), self.suppressed_count(v), v))
        truncated = False
        lattice = math.prod(t + 1 for t in self.tops)
        if lattice <= REFINE_MAX_NODES:
            w_best = self.weight(best)
            region = sorted(
                (v for v in itertools.product(*[range(t + 1) for t in self.tops])
                 if sum(v) >= lo and self.weight(v) <= w_best),
                key=lambda v: (self.weight(v), v),
            )
            try:
                for v in region:
                    if self.weight(v) > self.weight(best):
                        break
                    if self.acceptable(v) and (self.weight(v), self.suppressed_count(v), v) < (
                            self.weight(best), self.suppressed_count(best), best):
                        best = v
            except SearchLimitExceeded:
                truncated = True
        keys = self.keys(best)
        _sizes, bad = self._bad_classes(keys)
        dropped = tuple(i for i, key in enumerate(keys) if key in bad)
        return SearchResult(best, dropped, self.evals, truncated)
