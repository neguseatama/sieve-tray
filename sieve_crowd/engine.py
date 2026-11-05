"""Orchestration: read roles -> generalize -> search -> suppress -> shuffle -> measure -> receipt."""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Optional, Sequence

from .config import Config
from .generalize import Generalizer, make_generalizer
from .measure import HISTOGRAM_CAP, diagnose, measure
from .model import ConfigError, Role
from .prng import SplitMix64
from .pseudonym import pseudonym
from .report import Report, base
from .search import Infeasible, Searcher, SearchLimitExceeded, REFINE_MAX_NODES


@dataclass(frozen=True)
class Result:
    status: str                       # "anonymized" | "refused"
    header: Optional[list[str]]
    rows: Optional[list[list[str]]]
    report: Report


def _norm(v: str) -> str:
    return unicodedata.normalize("NFC", v).strip()


def _refuse(reason: str, n_in: int, cfg: Config,
            io: Optional[tuple[str, Optional[str]]] = None,
            diagnostics: Optional[dict] = None) -> Result:
    d = base("refused", reason=reason)
    d["input"] = {"records": n_in}
    if diagnostics:
        d["diagnostics"] = diagnostics
    _add_io(d, io)
    return Result("refused", None, None, Report(d))


def _capped_hist(counter: dict) -> tuple[list, bool]:
    items = sorted(counter.items())
    return [list(p) for p in items[:HISTOGRAM_CAP]], len(items) > HISTOGRAM_CAP


def _suppression_diagnostics(searcher: Searcher, levels: tuple[int, ...], qi_cols: list[str],
                             sens_cols: list[str], sens_codes: list[list[int]],
                             dropped: tuple[int, ...]) -> dict:
    """Why rows were dropped, in aggregates only: sizes and violation counts, never crowd labels."""
    keys = searcher.keys(levels)
    sizes = Counter(keys)
    dropped_keys = {keys[i] for i in dropped}
    hist, truncated = _capped_hist(Counter(sizes[key] for key in dropped_keys))
    bk_c = bk_r = bl_c = bl_r = 0
    columns: dict[str, dict[str, int]] = {}
    for key in dropped_keys:
        s = sizes[key]
        if s < searcher.k:
            bk_c += 1
            bk_r += s
            continue
        bl_c += 1
        bl_r += s
        for name, sc in zip(sens_cols, sens_codes):
            if len({sc[i] for i, kx in enumerate(keys) if kx == key}) < searcher.l:
                e = columns.setdefault(name, {"crowds": 0, "records": 0})
                e["crowds"] += 1
                e["records"] += s
    rescued: dict[str, int] = {}
    for j, c in enumerate(qi_cols):
        if levels[j] >= searcher.tops[j]:
            continue
        vec = levels[:j] + (levels[j] + 1,) + levels[j + 1:]
        keys2 = searcher.keys(vec)
        _sizes2, bad2 = searcher._bad_classes(keys2)
        rescued[c] = sum(1 for i in dropped if keys2[i] not in bad2)
    out = {
        "budget": searcher.budget,
        "dropped_crowds": len(dropped_keys), "dropped_records": len(dropped),
        "crowd_sizes": hist, "crowd_sizes_truncated": truncated,
        "reasons": {"below_k": {"crowds": bk_c, "records": bk_r},
                    "below_l": {"crowds": bl_c, "records": bl_r, "columns": columns}},
    }
    if rescued:
        out["one_level_further"] = rescued
    return out


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

    # --- missing-value policy ----------------------------------------------------------
    # "star" (default): a missing QI value takes part like any value and generalizes to "*"
    # from level 1.  "suppress": records with an empty QI value are removed before the search
    # and consume the suppression budget; they refuse the run when they alone exceed it.
    budget = min(n - 1, int(math.floor(cfg.max_suppression * n)))
    missing: list[int] = []
    work = rows
    if cfg.missing_value_policy == "suppress":
        missing = [i for i, r in enumerate(rows) if any(_norm(r[pos[c]]) == "" for c in qi_cols)]
        if len(missing) > budget:
            return _refuse("missing_exceeds_budget", n, cfg, io,
                           {"records": n, "missing": len(missing), "budget": budget})
        budget -= len(missing)
        if missing:
            gone = set(missing)
            work = [r for i, r in enumerate(rows) if i not in gone]

    # --- generalization tables ---------------------------------------------------------
    gens: list[Generalizer] = []
    values: list[list[str]] = []
    codes: list[list[list[int]]] = []
    cards: list[list[int]] = []
    for c in qi_cols:
        col = [_norm(r[pos[c]]) for r in work]
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
        sens_codes.append([ids2.setdefault(_norm(r[pos[c]]), len(ids2)) for r in work])

    # --- search ------------------------------------------------------------------------
    searcher = Searcher(codes, cards, sens_codes, len(work), cfg.k, cfg.l, budget, cfg.max_evals)
    try:
        found = searcher.run()
    except Infeasible:
        sens_distinct = {c: len({_norm(r[pos[c]]) for r in rows}) for c in sens_cols}
        return _refuse("infeasible", n, cfg, io,
                       {"records": n, "k_requested": cfg.k, "l_requested": cfg.l,
                        "sensitive_distinct": sens_distinct})
    except SearchLimitExceeded:
        return _refuse("resource_limit_search", n, cfg, io,
                       {"lattice_nodes": math.prod(t + 1 for t in searcher.tops),
                        "tops": list(searcher.tops), "evaluations": searcher.evals,
                        "max_evals": cfg.max_evals})

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
    for ri, r in enumerate(work):
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
        diag = diagnose(out_header, out_rows, qi_cols, sens_cols, cfg.k, cfg.l)
        diag["levels"] = list(found.levels)
        return _refuse("verification_failed", n, cfg, io, diag)

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
    d["settings"] = {"k": cfg.k, "l": cfg.l, "max_suppression": cfg.max_suppression,
                     "missing_value_policy": cfg.missing_value_policy}
    d["result"] = {"records_out": len(out_rows),
                   "suppressed": len(missing) + len(dropped),
                   "suppression_rate": (len(missing) + len(dropped)) / n,
                   "missing_suppressed": len(missing)}
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
    if dropped:
        d["diagnostics"] = {"suppression": _suppression_diagnostics(
            searcher, found.levels, qi_cols, sens_cols, sens_codes, dropped)}
    d["verification"] = "passed"
    _add_io(d, io)
    return Result("anonymized", out_header, out_rows, Report(d))


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def plan_table(header: Sequence[str], rows: Sequence[Sequence[str]], cfg: Config) -> dict:
    """Pre-flight profile of a run: the exact search-space size, the suppression budget and the
    level-0 crowd statistics, with warnings.  No search is run; no cell values are reported."""
    header = list(header)
    _check_columns(header, cfg)
    n = len(rows)
    pos = {name: i for i, name in enumerate(header)}
    qi_cols = [h for h in header if cfg.columns[h].role is Role.QI]
    sens_cols = [h for h in header if cfg.columns[h].role is Role.SENSITIVE]

    tops = [make_generalizer(cfg.columns[c].gen or {}).levels for c in qi_cols]
    nodes = math.prod(t + 1 for t in tops) if tops else 1
    budget = max(0, min(n - 1, int(math.floor(cfg.max_suppression * n))))

    before = measure(header, rows, qi_cols, [])
    diag = diagnose(header, rows, qi_cols, sens_cols, cfg.k, cfg.l)
    sens_distinct = {c: len({_norm(r[pos[c]]) for r in rows}) for c in sens_cols}

    warnings: list[dict] = []

    def warn(code: str, **params) -> None:
        warnings.append({"code": code, "params": params})

    if n > cfg.max_rows:
        warn("rows_over_limit", records=n, max_rows=cfg.max_rows)
    if n < cfg.k:
        warn("k_unreachable", records=n, k=cfg.k)
    for c, v in sens_distinct.items():
        if v < cfg.l:
            warn("l_unreachable", column=c, distinct=v, l=cfg.l)
    if budget == 0 and diag["records_below_k"] > 0:
        warn("budget_zero", records=diag["records_below_k"])
    missing = sum(1 for r in rows if any(_norm(r[pos[c]]) == "" for c in qi_cols))
    if cfg.missing_value_policy == "suppress" and missing > budget:
        warn("missing_over_budget", records=missing, budget=budget)
    if nodes > REFINE_MAX_NODES:
        warn("lattice_large", nodes=nodes, cap=REFINE_MAX_NODES)
    if nodes > cfg.max_evals:
        warn("evals_tight", nodes=nodes, max_evals=cfg.max_evals)
    if n and before["records_in_crowd_of_1"] / n >= 0.5:
        warn("many_singletons", records=before["records_in_crowd_of_1"],
             ratio=round(before["records_in_crowd_of_1"] / n, 4))

    d = base("plan")
    d["input"] = {"records": n, "columns": len(header)}
    d["settings"] = {"k": cfg.k, "l": cfg.l, "max_suppression": cfg.max_suppression,
                     "max_rows": cfg.max_rows, "max_evals": cfg.max_evals}
    d["columns"] = inspect_table(header, rows)
    d["lattice"] = {"quasi_identifiers": qi_cols, "tops": tops, "max_height": sum(tops),
                    "nodes": nodes, "refinement_cap": REFINE_MAX_NODES,
                    "refinement_skipped": nodes > REFINE_MAX_NODES,
                    "worst_case_evaluations": nodes}
    d["budget"] = {"records": budget, "max_suppression": cfg.max_suppression}
    d["missing"] = {"policy": cfg.missing_value_policy, "records": missing}
    d["before"] = {"crowds": before["crowds"], "smallest_crowd": before["k"],
                   "records_alone": before["records_in_crowd_of_1"],
                   "records_alone_ratio": (before["records_in_crowd_of_1"] / n) if n else 0.0,
                   "max_risk": before["max_risk"], "average_risk": before["average_risk"],
                   "records_below_k": diag["records_below_k"]}
    d["sensitive"] = {"columns": sens_cols, "distinct": sens_distinct}
    d["warnings"] = warnings
    return d


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
