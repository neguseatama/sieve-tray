"""Independent measurement of an anonymized table (does not reuse the search's data structures)."""
from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Sequence


def _norm(v: str) -> str:
    return unicodedata.normalize("NFC", v).strip()


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
