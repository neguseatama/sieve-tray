"""audit: observe the table as it is — integers only, no judgment.

``audit`` answers "what does this table look like right now": it generalizes
nothing, transforms nothing and refuses nothing.  Where ``run`` reports what a
table became, ``audit`` reports what a table is, in counts and floored
per-mille values — every number is an integer produced by integer division, so
the same table yields byte-identical output on every platform and every Python.

Three observations:

* A  equivalence classes on the QI tuple — count, smallest, unique rows, rows
  below k, per-mille, and rows per fixed size bucket.
* B  per QI column — distinct values (empty cells excluded), rows whose value
  is unique in that column, and rows_below_k recomputed with that column
  dropped (which column is carrying the grouping).
* C  repeated subjects (only with ``--subject``) — k-anonymity speaks about
  rows, but a person can sit in several of them.  audit counts the people:
  rows per subject, subjects per class, and ``rows_overstated`` — classes that
  look safe on rows (size >= k) but hold fewer than k distinct people.

Alignment with the existing engine (no new rules):

* values are compared with the engine's own ``_norm`` (NFC + surrounding-space
  strip) — the same grouping a run would use;
* classes are built exactly like ``measure``/``diagnose`` at level 0: every
  row takes part, an empty QI value acts as the empty value, and the
  ``missing_value_policy`` is *not* applied (suppressing rows would be a
  transformation, not an observation).  These are the same numbers ``plan``
  reports as ``before`` — same names, same numbers;
* the observation is canonical: the QI columns are reported in sorted order,
  so neither the row order nor the column order of the input changes a byte;
* an empty subject cannot be told apart from another empty subject, so every
  empty-subject row is treated as a person of its own (one row, one person) —
  in every C item, consistently;
* the per-mille values are ``1000 * count // n`` (floored integer division,
  ``0`` for ``n = 0``); no float is ever computed.

No cell value ever leaves the table — subject values included.  Column names
and aggregates only (the same sentinel rule as every other report).
"""
from __future__ import annotations

from collections import Counter
from typing import Optional, Sequence

from . import __version__
from .config import Config
from .engine import _check_columns, _norm
from .model import ConfigError, Role

SCHEMA = 1                          # the audit findings schema (bumped on breaking changes)

SIZE_BUCKETS = ("1", "2", "3", "4", "5-9", "10-49", "50+")     # class size -> rows
SUBJECT_BUCKETS = ("1", "2", "3-4", "5-9", "10+")              # rows per subject -> subjects


def _size_bucket(size: int) -> str:
    if size <= 4:
        return str(size)
    if size < 10:
        return "5-9"
    if size < 50:
        return "10-49"
    return "50+"


def _subject_bucket(rows: int) -> str:
    if rows == 1:
        return "1"
    if rows == 2:
        return "2"
    if rows < 5:
        return "3-4"
    if rows < 10:
        return "5-9"
    return "10+"


def validate_subject(cfg: Config, subject: Optional[str]) -> None:
    """The subject column must be configured and must not be qi or sensitive.

    A qi column as subject would break the observation (the classes would be
    built on the person column itself); a sensitive column would echo its
    values through the class accounting.  ``id`` / ``keep`` / ``drop`` are
    fine — the id column is the typical subject.  The message names the
    column, never a cell value.
    """
    if subject is None:
        return
    spec = cfg.columns.get(subject)
    if spec is None:
        raise ConfigError(f'the subject column "{subject}" is not declared in the configuration')
    if spec.role is Role.QI or spec.role is Role.SENSITIVE:
        raise ConfigError(f'the subject column must not have the role qi or sensitive ("{subject}")')


def audit_table(header: Sequence[str], rows: Sequence[Sequence[str]], cfg: Config,
                subject: Optional[str] = None) -> dict:
    """Observe the table and return the ``audit`` object (the findings JSON body).

    Pure observation: the table is only read, nothing is generalized, nothing
    is suppressed, nothing is judged.
    """
    header = list(header)
    _check_columns(header, cfg)
    n = len(rows)
    k = cfg.k
    pos = {name: i for i, name in enumerate(header)}
    qi_cols = [h for h in header if cfg.columns[h].role is Role.QI]
    qi_idx = [pos[c] for c in qi_cols]

    # --- A: equivalence classes at level 0 (all rows, empty values included) ---------
    keys = [tuple(_norm(r[i]) for i in qi_idx) for r in rows]
    sizes_map: Counter = Counter(keys)
    class_sizes = list(sizes_map.values())
    unique_rows = sum(1 for s in class_sizes if s == 1)
    rows_below_k = sum(s for s in class_sizes if s < k)
    classes = {
        "count": len(sizes_map),
        "min_size": min(class_sizes) if class_sizes else 0,
        "unique_rows": unique_rows,
        "rows_below_k": rows_below_k,
        "unique_permille": (1000 * unique_rows // n) if n else 0,
        "below_k_permille": (1000 * rows_below_k // n) if n else 0,
        "size_buckets": {b: 0 for b in SIZE_BUCKETS},   # rows per bucket, keys always present
    }
    for s in class_sizes:
        classes["size_buckets"][_size_bucket(s)] += s

    # --- B: per QI column, in canonical (sorted) order --------------------------------
    # Dropping one column rebuilds the classes on the remaining QI tuple
    # (O(n) per column).  With a single QI column this yields one class of
    # size n, so rows_below_k_without is n when n < k, else 0.
    qi_columns = []
    for p, c in sorted(enumerate(qi_cols), key=lambda t: t[1]):
        col = [_norm(r[pos[c]]) for r in rows]
        freq: Counter = Counter(v for v in col if v != "")
        without = [key[:p] + key[p + 1:] for key in keys]
        qi_columns.append({
            "column": c,
            "distinct": len(freq),
            "unique_rows": sum(1 for v in col if v != "" and freq[v] == 1),
            "rows_below_k_without": sum(s for s in Counter(without).values() if s < k),
        })

    # --- C: repeated subjects (only with --subject) ------------------------------------
    subj: Optional[dict] = None
    warnings: list[dict] = []
    if rows_below_k:
        warnings.append({"code": "small_classes", "rows": rows_below_k})
    if subject is not None:
        j = pos[subject]
        vals = [_norm(r[j]) for r in rows]
        missing = sum(1 for v in vals if v == "")
        freq: Counter = Counter(v for v in vals if v != "")
        repeated = [c for c in freq.values() if c >= 2]
        buckets = {b: 0 for b in SUBJECT_BUCKETS}       # subjects per bucket
        for c in freq.values():
            buckets[_subject_bucket(c)] += 1
        if missing:
            buckets["1"] += missing                     # each empty row is its own subject
        acc: dict = {}
        for key, v in zip(keys, vals):
            e = acc.setdefault(key, [set(), 0])         # distinct values, empty rows
            if v == "":
                e[1] += 1
            else:
                e[0].add(v)
        distinct = {key: len(s) + e for key, (s, e) in acc.items()}
        subj = {
            "column": subject,
            "rows_with_subject": n - missing,
            "rows_missing_subject": missing,
            "subjects": len(freq) + missing,
            "repeated_subjects": len(repeated),
            "rows_in_repeated_subjects": sum(repeated),
            "max_rows_per_subject": max(freq.values()) if freq else (1 if missing else 0),
            "rows_per_subject_buckets": buckets,
            "class_subjects": {
                "min_distinct": min(distinct.values()) if distinct else 0,
                "rows_below_k": sum(sizes_map[key] for key, d in distinct.items() if d < k),
                "rows_overstated": sum(sizes_map[key] for key, d in distinct.items()
                                       if d < k and sizes_map[key] >= k),
            },
        }
        if subj["class_subjects"]["rows_overstated"]:
            warnings.append({"code": "subject_overstated",
                             "rows": subj["class_subjects"]["rows_overstated"]})

    return {
        "schema": SCHEMA,
        "rows": n,
        "k": k,
        "qi": sorted(qi_cols),
        "classes": classes,
        "qi_columns": qi_columns,
        "subject": subj,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# human report (stderr, like plan); every number is an integer
# --------------------------------------------------------------------------- #

_W = {
    "en": {
        "status": "audit (observation only; nothing is generalized, searched or written)",
        "records": "Records: {n}, k = {k}, qi: {cols}",
        "classes": ("Equivalence classes on the QI tuple: count {count}, smallest {min}, "
                    "unique rows {unique}, rows below k {below}"),
        "permille": "  per mille (floor): unique {up}, below k {bp}",
        "sizes": "  rows by class size: ",
        "cols_head": "QI columns:",
        "col": "  {c}: distinct {d}, unique rows {u}, rows below k without it {w}",
        "subject": ('Subject "{c}": rows with {with_}, missing {missing}, subjects {subjects}, '
                    "repeated {repeated}, rows in repeated {in_repeated}, max {max_rows}"),
        "per_subject": "  rows per subject: ",
        "class_subjects": ("  distinct subjects per class: min {min}, rows below k {below}, "
                           "rows overstated {over}"),
        "warnings": "Warnings:",
        "no_warnings": "Warnings: none",
        "rows_over_limit": ("  - rows_over_limit: {n} record(s) exceed the limit {max_rows}; "
                            "the observation reads all of them"),
        "small_classes": "  - small_classes: {r} row(s) sit in classes smaller than k={k}",
        "subject_overstated": ('  - subject_overstated: {r} row(s) sit in classes of size >= k, '
                               'but with fewer than k distinct subjects (column "{c}")'),
    },
    "ja": {
        "status": "監査（観測のみ。一般化も探索も書き込みもしません）",
        "records": "レコード: {n} 件、k = {k}、準識別子: {cols}",
        "classes": "同値類（準識別子の組）: {count} 個、最小 {min}、一独りの行 {unique} 件、k 未満 {below} 件",
        "permille": "  千分率（切り捨て）: 一独り {up}、k 未満 {bp}",
        "sizes": "  サイズ別の行数: ",
        "cols_head": "準識別子の列:",
        "col": "  {c}: 異なる値 {d}、一独りの行 {u}、この列を外すと k 未満 {w} 件",
        "subject": "対象「{c}」: あり {with_} 件、空 {missing} 件、対象 {subjects} 人、"
                   "繰り返し {repeated} 人、その行 {in_repeated} 件、最大 {max_rows} 行",
        "per_subject": "  対象ごとの行数: ",
        "class_subjects": "  同値類ごとの異なる対象数: 最小 {min}、k 未満の行 {below} 件、行の上で過大な行 {over} 件",
        "warnings": "警告:",
        "no_warnings": "警告: なし",
        "rows_over_limit": "  - rows_over_limit: {n} 件が上限 {max_rows} 件を超えています。観測はすべての行を読みます",
        "small_classes": "  - small_classes: {r} 行が、サイズ k={k} 未満のグループに属しています",
        "subject_overstated": "  - subject_overstated: {r} 行は、サイズは k 以上ですが、"
                              "異なる対象（列「{c}」）が k 人に届かないグループに属しています",
    },
}


def _bucket_line(head: str, buckets: dict) -> str:
    return head + ", ".join(f"{b}:{buckets[b]}" for b in buckets)


def report_text(audit: dict, lang: str, max_rows: int = 0) -> str:
    """The stderr report (plan carries its text to stderr too).  Integers only."""
    m = _W[lang]
    c = audit["classes"]
    lines = [f"Sieve Crowd {__version__}",
             ("Status: " if lang == "en" else "状態: ") + m["status"],
             m["records"].format(n=audit["rows"], k=audit["k"], cols=", ".join(audit["qi"])),
             m["classes"].format(count=c["count"], min=c["min_size"],
                                 unique=c["unique_rows"], below=c["rows_below_k"]),
             m["permille"].format(up=c["unique_permille"], bp=c["below_k_permille"]),
             _bucket_line(m["sizes"], c["size_buckets"]),
             m["cols_head"]]
    for col in audit["qi_columns"]:
        lines.append(m["col"].format(c=col["column"], d=col["distinct"],
                                     u=col["unique_rows"], w=col["rows_below_k_without"]))
    s = audit["subject"]
    if s is not None:
        cs = s["class_subjects"]
        lines.append(m["subject"].format(c=s["column"], with_=s["rows_with_subject"],
                                         missing=s["rows_missing_subject"],
                                         subjects=s["subjects"],
                                         repeated=s["repeated_subjects"],
                                         in_repeated=s["rows_in_repeated_subjects"],
                                         max_rows=s["max_rows_per_subject"]))
        lines.append(_bucket_line(m["per_subject"], s["rows_per_subject_buckets"]))
        lines.append(m["class_subjects"].format(min=cs["min_distinct"],
                                                below=cs["rows_below_k"],
                                                over=cs["rows_overstated"]))
    warn = []
    if max_rows and audit["rows"] > max_rows:
        warn.append(m["rows_over_limit"].format(n=audit["rows"], max_rows=max_rows))
    for w in audit["warnings"]:
        if w["code"] == "small_classes":
            warn.append(m["small_classes"].format(r=w["rows"], k=audit["k"]))
        else:
            warn.append(m["subject_overstated"].format(r=w["rows"], c=s["column"]))
    if warn:
        lines.append(m["warnings"])
        lines.extend(warn)
    else:
        lines.append(m["no_warnings"])
    return "\n".join(lines)
