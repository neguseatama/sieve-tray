"""Orchestration: read roles -> generalize -> search -> suppress -> shuffle -> measure -> receipt."""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Sequence

from .config import Config
from .generalize import Generalizer, make_generalizer
from .measure import measure
from .model import ConfigError, Role
from .prng import SplitMix64
from .pseudonym import pseudonym
from .report import Report, base
from .search import Infeasible, Searcher, SearchLimitExceeded


@dataclass(frozen=True)
class Result:
    status: str                       # "anonymized" | "refused"
    header: Optional[list[str]]
    rows: Optional[list[list[str]]]
    report: Report


def _norm(v: str) -> str:
    return unicodedata.normalize("NFC", v).strip()


def _refuse(reason: str, n_in: int, cfg: Config,
            io: Optional[tuple[str, Optional[str]]] = None) -> Result:
    d = base("refused", reason=reason)
    d["input"] = {"records": n_in}
    _add_io(d, io)
    return Result("refused", None, None, Report(d))


def _add_io(d: dict, io: Optional[tuple[str, Optional[str]]]) -> None:
    if io:
        entry: dict = {"input_format": io[0]}
        if io[1]:
            entry["output_format"] = io[1]
        d["io"] = entry


def _check_columns(header: Sequence[str], cfg: Config) -> None:
    if len(set(header)) != len(header):
        raise ConfigError("the table has duplicate column names")
    missing = [h for h in header if h not in cfg.columns]
    if missing:
        raise ConfigError(f"column(s) without a role: {', '.join(missing)}")
    extra = [c for c in cfg.columns if c not in header]
    if extra:
        raise ConfigError(f"configuration names column(s) not in the table: {', '.join(extra)}")


def anonymize(header: Sequence[str], rows: Sequence[Sequence[str]], cfg: Config,
              *, io: Optional[tuple[str, Optional[str]]] = None) -> Result:
    """io, when given, is (input_format, output_format or None) and is recorded in the receipt."""
    header = list(header)
    _check_columns(header, cfg)
    n = len(rows)
    if n == 0:
        return _refuse("no_records", n, cfg, io)
    if n > cfg.max_rows:
        return _refuse("resource_limit_rows", n, cfg, io)

    pos = {name: i for i, name in enumerate(header)}
    qi_cols = [h for h in header if cfg.columns[h].role is Role.QI]
    sens_cols = [h for h in header if cfg.columns[h].role is Role.SENSITIVE]

    # --- generalization tables ---------------------------------------------------------
    gens: list[Generalizer] = []
    values: list[list[str]] = []
    codes: list[list[list[int]]] = []
    cards: list[list[int]] = []
    for c in qi_cols:
        col = [_norm(r[pos[c]]) for r in rows]
        distinct = list(dict.fromkeys(col))
        g = make_generalizer(cfg.columns[c].gen or {})
        g.prepare(distinct)
        per_level, per_card = [], []
        for lvl in range(g.levels + 1):
            ids: dict[str, int] = {}
            of_value = {v: ids.setdefault(g.label(v, lvl), len(ids)) for v in distinct}
            per_level.append([of_value[v] for v in col])
            per_card.append(len(ids))
        gens.append(g); values.append(col); codes.append(per_level); cards.append(per_card)

    sens_codes: list[list[int]] = []
    for c in sens_cols:
        ids2: dict[str, int] = {}
        sens_codes.append([ids2.setdefault(_norm(r[pos[c]]), len(ids2)) for r in rows])

    # --- search ------------------------------------------------------------------------
    budget = min(n - 1, int(math.floor(cfg.max_suppression * n)))
    searcher = Searcher(codes, cards, sens_codes, n, cfg.k, cfg.l, budget, cfg.max_evals)
    try:
        found = searcher.run()
    except Infeasible:
        return _refuse("infeasible", n, cfg, io)
    except SearchLimitExceeded:
        return _refuse("resource_limit_search", n, cfg, io)

    # --- build the output table --------------------------------------------------------
    dropped = set(found.suppressed)
    chosen = dict(zip(qi_cols, found.levels))
    qi_labels = {}
    for c, g, col in zip(qi_cols, gens, values):
        lvl = chosen[c]
        qi_labels[c] = {v: g.label(v, lvl) for v in dict.fromkeys(col)}
    qi_index = {c: i for i, c in enumerate(qi_cols)}

    out_header = [h for h in header
                  if cfg.columns[h].role not in (Role.DROP,)
                  and not (cfg.columns[h].role is Role.ID and cfg.columns[h].action == "drop")]
    out_rows: list[list[str]] = []
    for ri, r in enumerate(rows):
        if ri in dropped:
            continue
        out = []
        for h in out_header:
            spec = cfg.columns[h]
            if spec.role is Role.QI:
                out.append(qi_labels[h][values[qi_index[h]][ri]])
            elif spec.role is Role.ID:
                out.append(pseudonym(cfg.key, h, r[pos[h]]))
            else:
                out.append(r[pos[h]])
        out_rows.append(out)

    if cfg.shuffle:
        SplitMix64(cfg.shuffle_seed).shuffle(out_rows)

    # --- verify on the output itself ---------------------------------------------------
    m = measure(out_header, out_rows, qi_cols, sens_cols)
    if m["k"] < cfg.k or any(v < cfg.l for v in m["diversity"].values()) or m["records"] == 0:
        return _refuse("verification_failed", n, cfg, io)

    # --- receipt -----------------------------------------------------------------------
    before = measure(header, rows, qi_cols, [])
    tops = searcher.tops
    out_pos = {h: i for i, h in enumerate(out_header)}
    cols_report = []
    for h in header:
        spec = cfg.columns[h]
        entry = {"name": h, "role": spec.role.value}
        if spec.role is Role.ID:
            entry["action"] = spec.action
        elif spec.role is Role.QI:
            g, lvl = gens[qi_index[h]], chosen[h]
            entry.update(level=lvl, top_level=g.levels,
                         description_en=g.describe(lvl, "en"), description_ja=g.describe(lvl, "ja"))
        elif spec.role is Role.KEEP:
            col_vals = [r[out_pos[h]] for r in out_rows]
            entry["unique_ratio"] = round(len(set(col_vals)) / len(col_vals), 4) if col_vals else 0.0
        cols_report.append(entry)

    d = base("anonymized")
    d["input"] = {"records": n, "columns": len(header)}
    d["settings"] = {"k": cfg.k, "l": cfg.l, "max_suppression": cfg.max_suppression}
    d["result"] = {"records_out": len(out_rows), "suppressed": len(dropped),
                   "suppression_rate": len(dropped) / n}
    d["privacy"] = {
        "quasi_identifiers": qi_cols,
        "k_requested": cfg.k, "k_achieved": m["k"], "crowds": m["crowds"],
        "smallest_crowds": m["smallest_crowds"], "records_alone_in_crowd": m["records_in_crowd_of_1"],
        "max_risk": m["max_risk"], "average_risk": m["average_risk"],
        "l_requested": cfg.l, "diversity": m["diversity"],
        "before": {"records_alone": before["records_in_crowd_of_1"],
                   "records_alone_ratio": before["records_in_crowd_of_1"] / n,
                   "smallest_crowd": before["k"]},
    }
    d["information_loss"] = {"height": sum(found.levels), "max_height": sum(tops),
                             "precision_loss": float(searcher.loss(found.levels) / len(tops))}
    d["columns"] = cols_report
    d["order"] = {"shuffled": cfg.shuffle, "seed": cfg.shuffle_seed if cfg.shuffle else None}
    d["relaxations"] = [] if cfg.shuffle else ["keep_order"]
    d["search"] = {"evaluations": found.evaluations, "refinement_truncated": found.truncated}
    d["verification"] = "passed"
    _add_io(d, io)
    return Result("anonymized", out_header, out_rows, Report(d))


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def inspect_table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[dict]:
    """Observations per column (no roles are guessed)."""
    n = len(rows)
    out = []
    for i, h in enumerate(header):
        col = [r[i].strip() for r in rows]
        nonempty = [v for v in col if v != ""]
        if nonempty and all(re.match(r"^[+-]?\d+$", v) for v in nonempty):
            shape = "integer"
        elif nonempty and all(_DATE.match(v) for v in nonempty):
            shape = "date"
        else:
            shape = "text"
        out.append({"name": h, "distinct": len(set(col)), "empty": len(col) - len(nonempty),
                    "unique_ratio": round(len(set(col)) / n, 4) if n else 0.0, "shape": shape})
    return out
