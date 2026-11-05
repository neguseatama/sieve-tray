"""Derived keep-vs-qi relations for ``plan``: does one column nearly determine the other?

For every (keep column X, qi column Q) pair — evaluated in both directions —
``plan`` reports when one column is a near-perfect proxy for the other:

* ``reveals_qi``    X is kept verbatim in the output; if X nearly determines the
  raw qi value, generalizing Q does not hide it (the attacker reads Q off X).
* ``implied_by_qi`` the qi value nearly determines the kept value, so the
  published crowd still pins X down.

Every evaluated direction lands in exactly one of four classes:

* ``unchecked``  fewer than ``MIN_SUPPORT`` compared records: too little data.
* ``trivial``    a constant column on either side (the relation carries no
  information), or every source value unique (``s - m == 0``): plain
  uniqueness, not a derived relation.
* ``flagged``    ``s >= 50`` and ``s - m > 0`` and ``100*v <= s`` and
  ``10*v <= s - m``: the violations v (records the source value does not pin
  down to one target value) are at most 1% of the records and at most 10% of
  the excess ``s - m``.
* ``clear``      checked and honest: too many violations to warn about.

The numbers are code constants on purpose (a standard, not a knob):
``MIN_SUPPORT = 50``, ``PAIR_LIMIT = 400`` pairs per plan, and the two ratio
tests 1/100 and 1/10.  Pairs beyond ``PAIR_LIMIT`` are skipped and counted in
``skipped_pairs``; the invariant

    unchecked + trivial + flagged + clear == 2 * (pairs - skipped_pairs)

holds for every input, because each evaluated pair contributes exactly two
class results, one per direction.  Both directions come out of a single
cross-tabulation (O(records) per pair).

Values are compared with the engine's own ``_norm`` (NFC + surrounding-space
strip) — the same grouping a run will use.  Empty cells are excluded from the
support.  Findings carry column names and aggregate numbers only — no cell
value is ever returned (the same sentinel rule as every other report).
"""
from __future__ import annotations

from typing import Mapping, Sequence

from .engine import _norm

MIN_SUPPORT = 50   # pairs with fewer compared records are unchecked
PAIR_LIMIT = 400   # keep x qi pairs evaluated per plan; the tail is skipped

RELATIONS = ("reveals_qi", "implied_by_qi")   # fixed order of the directions


def _classify(s: int, m: int, v: int, target_distinct: int) -> str:
    """One direction: m source groups over s compared records, v of them not
    pinned to a single target value by their source value."""
    if s < MIN_SUPPORT:
        return "unchecked"
    if m == 1 or target_distinct == 1:    # a constant column: no information
        return "trivial"
    if s == m:                            # s - m == 0: unique source values
        return "trivial"
    if 100 * v <= s and 10 * v <= s - m:
        return "flagged"
    return "clear"


def analyze(header: Sequence[str], rows: Sequence[Sequence[str]],
            roles: Mapping[str, str]) -> tuple[list[dict], dict]:
    """Cross every keep column with every qi column, both directions.

    ``roles`` maps column name -> declared role value (``keep``/``qi``/...).
    Returns ``(warnings, summary)``: ``warnings`` is the list of flagged
    directions for ``findings.warnings`` (code ``derived``, in table order,
    ``reveals_qi`` before ``implied_by_qi`` per pair) and ``summary`` is the
    ``derived_summary`` object for the findings JSON.
    """
    pos = {h: i for i, h in enumerate(header)}
    keep = [h for h in header if roles.get(h) == "keep"]
    qis = [h for h in header if roles.get(h) == "qi"]
    pairs = [(x, q) for x in keep for q in qis if x != q]
    skipped = max(0, len(pairs) - PAIR_LIMIT)
    classes = {"unchecked": 0, "trivial": 0, "flagged": 0, "clear": 0}
    warnings: list[dict] = []

    for x, q in pairs[:PAIR_LIMIT]:
        ix, iq = pos[x], pos[q]
        cross: dict[tuple[str, str], int] = {}
        for r in rows:
            xv, qv = _norm(r[ix]), _norm(r[iq])
            if xv == "" or qv == "":          # empty cells are not compared
                continue
            key = (xv, qv)
            cross[key] = cross.get(key, 0) + 1
        # one cross-tabulation, both directions
        gx: dict[str, int] = {}      # x value -> records
        gmax_x: dict[str, int] = {}  # x value -> largest q count inside the group
        gq: dict[str, int] = {}
        gmax_q: dict[str, int] = {}
        for (xv, qv), c in cross.items():
            gx[xv] = gx.get(xv, 0) + c
            if c > gmax_x.get(xv, 0):
                gmax_x[xv] = c
            gq[qv] = gq.get(qv, 0) + c
            if c > gmax_q.get(qv, 0):
                gmax_q[qv] = c
        s = sum(gx.values())
        stats = {
            "reveals_qi": (len(gx), s - sum(gmax_x.values()), len(gq)),
            "implied_by_qi": (len(gq), s - sum(gmax_q.values()), len(gx)),
        }
        for relation in RELATIONS:
            m, v, target_distinct = stats[relation]
            verdict = _classify(s, m, v, target_distinct)
            classes[verdict] += 1
            if verdict == "flagged":
                warnings.append({"code": "derived", "column": x,
                                 "declared_role": "keep", "qi_column": q,
                                 "relation": relation, "support": s,
                                 "violations": v})

    summary = {"pairs": len(pairs), "skipped_pairs": skipped,
               "unchecked": classes["unchecked"], "trivial": classes["trivial"],
               "flagged": classes["flagged"], "clear": classes["clear"]}
    return warnings, summary
