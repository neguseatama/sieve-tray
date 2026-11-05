"""Independent measurement of an anonymized table (does not reuse the search's data structures)."""
from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Sequence

HISTOGRAM_CAP = 20   # crowd-size histograms never exceed this many entries (deterministic cut)


def _norm(v: str) -> str:
    return unicodedata.normalize("NFC", v).strip()


def _capped(pairs) -> tuple[list, bool]:
    items = sorted(pairs)
    return [list(p) for p in items[:HISTOGRAM_CAP]], len(items) > HISTOGRAM_CAP


def measure(header: Sequence[str], rows: Sequence[Sequence[str]],
            qi: Sequence[str], sensitive: Sequence[str]) -> dict:
    idx = {name: i for i, name in enumerate(header)}
    qi_idx = [idx[c] for c in qi]
    classes: dict[tuple[str, ...], list[Sequence[str]]] = {}
    for r in rows:
        classes.setdefault(tuple(_norm(r[i]) for i in qi_idx), []).append(r)
    sizes = sorted(len(v) for v in classes.values())
    n = len(rows)
    out: dict = {
        "records": n,
        "crowds": len(classes),
        "k": sizes[0] if sizes else 0,
        "smallest_crowds": sizes[:5],
        "records_in_crowd_of_1": sum(1 for s in sizes if s == 1),
        "max_risk": (1 / sizes[0]) if sizes else 0.0,
        "average_risk": (len(classes) / n) if n else 0.0,
        "diversity": {},
    }
    for c in sensitive:
        j = idx[c]
        out["diversity"][c] = min(
            (len({_norm(r[j]) for r in members}) for members in classes.values()), default=0
        )
    return out


def diagnose(header: Sequence[str], rows: Sequence[Sequence[str]],
             qi: Sequence[str], sensitive: Sequence[str], k: int, l: int) -> dict:
    """Aggregate-only trace of why rows fail k or l.  Crowd identities (the QI labels) are never
    reported, only sizes and counts, so the result is safe to put on a receipt."""
    idx = {name: i for i, name in enumerate(header)}
    qi_idx = [idx[c] for c in qi]
    keys = [tuple(_norm(r[i]) for i in qi_idx) for r in rows]
    sizes_map: Counter = Counter(keys)
    sizes = sorted(sizes_map.values())
    below = Counter(s for s in sizes if s < k)
    hist, truncated = _capped(below.items())
    shortfalls: dict[str, dict[str, int]] = {}
    for c in sensitive:
        j = idx[c]
        distinct: dict[tuple[str, ...], set[str]] = {}
        for key, r in zip(keys, rows):
            distinct.setdefault(key, set()).add(_norm(r[j]))
        bad = [(key, len(v)) for key, v in distinct.items() if len(v) < l]
        if bad:
            shortfalls[c] = {"crowds": len(bad), "records": sum(sizes_map[key] for key, _ in bad)}
    return {
        "records": len(rows),
        "crowds": len(sizes_map),
        "k_requested": k,
        "l_requested": l,
        "crowd_sizes_below_k": hist,
        "crowd_sizes_below_k_truncated": truncated,
        "records_below_k": sum(s * c for s, c in below.items()),
        "records_alone": sum(1 for s in sizes if s == 1),
        "l_shortfalls": shortfalls,
    }
