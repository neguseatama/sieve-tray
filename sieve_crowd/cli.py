"""Command line: inspect / keygen / run.  Cell values never appear in messages or logs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile
from typing import Mapping, Optional, Sequence

from . import __version__
from .config import parse_config, parse_key
from .engine import anonymize, inspect_table, plan_table
from .hints import hint
from .model import ConfigError, InputError
from .report import Report
from .tableio import FORMATS, detect_format, read_any, write_any

EXIT_OK, EXIT_IO, EXIT_CONFIG, EXIT_REFUSED = 0, 1, 2, 3


def _atomic_write(path: str, data: bytes, private: bool = False) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".sieve-crowd-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        if private:
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sieve-crowd",
                                description="Make every record one of a crowd of at least k, and measure it.")
    p.add_argument("--version", action="version", version=f"sieve-crowd {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("inspect", help="describe the columns of a table (csv, json or xml) and write a config template")
    i.add_argument("input")
    i.add_argument("--delimiter", help="CSV only")
    i.add_argument("--in-format", choices=FORMATS,
                   help="force the input format (default: from the file extension)")
    i.add_argument("--lang", choices=["en", "ja"], default="en")
    i.add_argument("--config-out", metavar="FILE", help="write a template with role '?' for every column")
    i.add_argument("--force", action="store_true")
    i.add_argument("--hint-pack", metavar="FILE", action="append",
                   help="load a hint pack (inspect/plan only; may be given more than once)")
    i.add_argument("--no-builtin-hints", action="store_true",
                   help="exclude the built-in jp-basic pack (load --hint-pack files only)")
    i.add_argument("--findings-json", metavar="FILE",
                   help="write the hint-pack findings (aggregates only, never cell values) as JSON")

    k = sub.add_parser("keygen", help="create a key for pseudonyms")
    k.add_argument("-o", "--output", required=True)
    k.add_argument("--force", action="store_true")

    r = sub.add_parser("run", help="anonymize a table (csv, json or xml)")
    r.add_argument("input")
    r.add_argument("-c", "--config", required=True)
    r.add_argument("-o", "--output")
    r.add_argument("--dry-run", action="store_true", help="measure only; write no table")
    r.add_argument("--delimiter", help="CSV only")
    r.add_argument("--in-format", choices=FORMATS,
                   help="force the input format (default: from the file extension)")
    r.add_argument("--out-format", choices=FORMATS,
                   help="force the output format (default: from the output extension)")
    r.add_argument("--key-file")
    r.add_argument("--k", type=int)
    r.add_argument("--l", type=int)
    r.add_argument("--max-suppression", type=float)
    r.add_argument("--missing-value-policy", choices=["star", "suppress"],
                   help="what to do with records whose QI value is empty: generalize it to '*' "
                        "(star, default) or drop the record against the suppression budget (suppress)")
    r.add_argument("--keep-order", action="store_true", help="relaxation: do not shuffle the rows (recorded)")
    r.add_argument("--shuffle-seed", type=int, default=0)
    r.add_argument("--lang", choices=["en", "ja"], default="en")
    r.add_argument("--max-rows", type=int, default=200_000)
    r.add_argument("--max-evals", type=int, default=20_000)
    r.add_argument("--report-json", metavar="FILE")
    r.add_argument("--quiet", action="store_true")
    r.add_argument("--force", action="store_true")

    pl = sub.add_parser("plan", help="estimate the search before running: lattice size, suppression budget, "
                                     "level-0 crowds and warnings (no table, no search)")
    pl.add_argument("input")
    pl.add_argument("-c", "--config", required=True)
    pl.add_argument("--delimiter", help="CSV only")
    pl.add_argument("--in-format", choices=FORMATS,
                    help="force the input format (default: from the file extension)")
    pl.add_argument("--lang", choices=["en", "ja"], default="en")
    pl.add_argument("--k", type=int)
    pl.add_argument("--l", type=int)
    pl.add_argument("--max-suppression", type=float)
    pl.add_argument("--missing-value-policy", choices=["star", "suppress"])
    pl.add_argument("--max-rows", type=int, default=200_000)
    pl.add_argument("--max-evals", type=int, default=20_000)
    pl.add_argument("--key-file")
    pl.add_argument("--report-json", metavar="FILE")
    pl.add_argument("--quiet", action="store_true")
    pl.add_argument("--hint-pack", metavar="FILE", action="append",
                    help="load a hint pack (inspect/plan only; may be given more than once)")
    pl.add_argument("--no-builtin-hints", action="store_true",
                    help="exclude the built-in jp-basic pack (load --hint-pack files only)")
    pl.add_argument("--no-derived", action="store_true",
                    help="skip the derived keep-vs-qi relation report (on by default)")
    pl.add_argument("--no-hidden-chars", action="store_true",
                    help="skip the invisible-character observation (on by default)")
    pl.add_argument("--findings-json", metavar="FILE",
                    help="write the hint-pack and derived findings (aggregates only, "
                         "never cell values) as JSON")

    au = sub.add_parser("audit", help="observe the table as it is: classes, per-QI columns and "
                                      "repeated subjects (integers only; nothing searched or written)")
    au.add_argument("input")
    au.add_argument("-c", "--config", required=True)
    au.add_argument("--subject", metavar="COLUMN",
                    help="the column that says who is who (name, customer id, ...); repeats "
                         "are observed on it. A configured column with a role other than "
                         "qi/sensitive is required")
    au.add_argument("--delimiter", help="CSV only")
    au.add_argument("--in-format", choices=FORMATS,
                    help="force the input format (default: from the file extension)")
    au.add_argument("--lang", choices=["en", "ja"], default="en")
    au.add_argument("--max-rows", type=int, default=200_000)
    au.add_argument("--max-evals", type=int, default=20_000)
    au.add_argument("--findings-json", metavar="FILE",
                    help="write the audit observation (aggregates only, never cell values) as JSON")
    au.add_argument("--quiet", action="store_true")

    sc = sub.add_parser("scan", help="write one static HTML page that shows how the table "
                                     "looks right now (roles, groups, observations; nothing "
                                     "searched, no cell values)")
    sc.add_argument("input")
    sc.add_argument("-c", "--config",
                    help="use the declared roles as they are (scan = plan + audit); "
                         "without it the roles are provisional, from the hint packs")
    sc.add_argument("--hint-pack", metavar="FILE", action="append",
                    help="load a hint pack (may be given more than once)")
    sc.add_argument("--no-builtin-hints", action="store_true",
                    help="exclude the built-in jp-basic pack (load --hint-pack files only)")
    sc.add_argument("--no-hidden-chars", action="store_true",
                    help="skip the invisible-character observation (on by default)")
    sc.add_argument("--subject", metavar="COLUMN",
                    help="the column that says who is who (name, customer id, ...); "
                         "repeats are observed on it")
    sc.add_argument("--k", type=int,
                    help="k for the provisional roles (without -c; default 5); with -c "
                         "it overrides the configured k like on plan")
    sc.add_argument("--max-rows", type=int, default=200_000,
                    help="read every row; the report notes when the table is larger "
                         "(default: %(default)s)")
    sc.add_argument("--no-derived", action="store_true",
                    help="skip the derived keep-vs-qi relation report (on by default)")
    sc.add_argument("--lang", choices=["en", "ja"], default="en")
    sc.add_argument("-o", "--output", help="the HTML file (default: INPUT with the last "
                                           "extension replaced by .scan.html; '-' is stdout)")
    return p


def _read(path: str) -> bytes:
    if path == "-":
        return sys.stdin.buffer.read()
    with open(path, "rb") as fh:
        return fh.read()


def _resolve_format(path: str, explicit: Optional[str], *, dash_default: str) -> str:
    if explicit:
        return explicit
    if path == "-":
        return dash_default
    return detect_format(os.path.splitext(path)[1])


def _delimiter(given: Optional[str], sides: set[str]) -> Optional[str]:
    if given is None:
        return None
    if sides - {"csv"}:
        raise InputError("--delimiter applies to csv only (the table is json/xml)")
    return given


def _packs_line(pack_info: Sequence[Mapping], en: bool) -> str:
    """D (v0.5.1): one leading line naming the loaded packs (recommended)."""
    parts = []
    for p in pack_info:
        if en:
            src = "builtin" if p["source"] == "builtin" else "file"
        else:
            src = "内蔵" if p["source"] == "builtin" else "ファイル"
        parts.append(f"{p['id']} ({src})")
    return ("hint packs: " if en else "ヒントパック: ") + ", ".join(parts)


def _cmd_inspect(a: argparse.Namespace) -> int:
    try:
        in_fmt = _resolve_format(a.input, a.in_format, dash_default="csv")
        delim = _delimiter(a.delimiter, {in_fmt})
        header, rows = read_any(_read(a.input), in_fmt, delim)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    except OSError as exc:
        print(f"error: cannot read the input ({exc.strerror})", file=sys.stderr); return EXIT_IO
    packs = _hint_packs(a)
    if isinstance(packs, int):
        return packs
    info = inspect_table(header, rows)
    en = a.lang == "en"
    findings = None
    if packs:
        from .hintpack import scan as _scan
        findings = _scan(header, rows, info, packs, cfg_roles=None)
    if findings:
        print(_packs_line(findings.pack_info, en))
    print(f"records: {len(rows)}" if en else f"レコード数: {len(rows)}")
    hints = {}
    for c in info:
        role, text_en, text_ja = hint(c["name"], c, len(rows))
        hints[c["name"]] = (role, text_en if en else text_ja)
        shown = f"  {c['name']}: {c['distinct']} distinct, {c['empty']} empty, {c['unique_ratio']:.0%} unique values, looks like {c['shape']}" \
            if en else f"  {c['name']}: 異なる値 {c['distinct']}、空 {c['empty']}、一意な値 {c['unique_ratio']:.0%}、形は {c['shape']}"
        print(shown)
        if role:
            print(f"      -> {hints[c['name']][1]}")
        if findings and c["name"] in findings.template_extras:
            for cand in findings.template_extras[c["name"]]["_candidates"]:
                summ = _suggest_summary(cand["suggest"])
                if en:
                    print(f"      * hint-pack {cand['pack']}/{cand['rule']}: suggests {summ} (evidence: {cand['evidence']})")
                else:
                    print(f"      * ヒントパック {cand['pack']}/{cand['rule']}: {summ} を提案（根拠: {cand['evidence']}）")
        if findings:                                    # B: inspect leak line (candidate format)
            for lk in findings.columns[c["name"]].leaks:
                if lk["count"]:
                    if en:
                        print(f"      * leak: {lk['count']} of {lk['checked']} non-empty cells "
                              f"may contain {lk['pack']}/{lk['rule']}")
                    else:
                        print(f"      * 漏洩の可能性: 空でない {lk['checked']} 件のうち "
                              f"{lk['count']} 件に {lk['pack']}/{lk['rule']} が含まれる可能性があります")
    if findings:
        for line in findings.warning_lines(a.lang):
            print(line, file=sys.stderr)
    if a.config_out:
        if os.path.exists(a.config_out) and not a.force:
            print("error: the config file exists (use --force)", file=sys.stderr); return EXIT_IO
        extras = findings.template_extras if findings else {}
        columns = {}
        for c in info:
            nm = c["name"]
            col = {"role": "?", "_hint": hints[nm][1]} if hints[nm][0] else {"role": "?"}
            if nm in extras:
                col["_suggest"] = extras[nm]["_suggest"]
                col["_candidates"] = extras[nm]["_candidates"]
            columns[nm] = col
        template = {"k": 5, "l": 1, "max_suppression": 0.05, "columns": columns}
        try:
            _atomic_write(a.config_out, (json.dumps(template, ensure_ascii=False, indent=2) + "\n").encode())
        except OSError as exc:
            print(f"error: cannot write ({exc.strerror})", file=sys.stderr); return EXIT_IO
    if findings and a.findings_json:
        try:
            _atomic_write(a.findings_json, (findings.to_json() + "\n").encode("utf-8"))
        except OSError as exc:
            print(f"error: cannot write ({exc.strerror})", file=sys.stderr); return EXIT_IO
    return EXIT_OK


def _cmd_keygen(a: argparse.Namespace) -> int:
    if os.path.exists(a.output) and not a.force:
        print("error: the key file exists (use --force)", file=sys.stderr); return EXIT_IO
    try:
        _atomic_write(a.output, (secrets.token_hex(32) + "\n").encode(), private=True)
    except OSError as exc:
        print(f"error: cannot write ({exc.strerror})", file=sys.stderr); return EXIT_IO
    return EXIT_OK


def _load_config(a: argparse.Namespace):
    with open(a.config, "rb") as fh:
        raw = json.loads(fh.read().decode("utf-8-sig"))
    key_file = getattr(a, "key_file", None)
    key = parse_key(open(key_file, encoding="utf-8").read()) if key_file else None
    # audit's parser carries no k/l/max-suppression overrides: the config file
    # is the single source there.  getattr keeps that optional (None overrides
    # are ignored by parse_config); run/plan are unaffected.
    return parse_config(raw, k=getattr(a, "k", None), l=getattr(a, "l", None),
                        max_suppression=getattr(a, "max_suppression", None),
                        missing_value_policy=getattr(a, "missing_value_policy", None),
                        shuffle=not getattr(a, "keep_order", False),
                        shuffle_seed=getattr(a, "shuffle_seed", 0), lang=a.lang,
                        max_rows=a.max_rows, max_evals=a.max_evals, key=key)


def _hint_packs(a: argparse.Namespace):
    """Load hint packs for inspect/plan, or an exit code on failure.

    Since v0.5.1 the builtin jp-basic pack is loaded by default (A);
    ``--no-builtin-hints`` excludes it.  With no user pack and the builtin
    excluded, nothing is loaded and the inspect/plan output stays byte-identical
    to v0.4.0 (TEMPLATE_SHA route).  The import of :mod:`sieve_crowd.hintpack`
    lives here, not at the top of the module, so ``run`` never pulls it into
    its import closure.
    """
    paths = getattr(a, "hint_pack", None) or []
    include_builtin = not getattr(a, "no_builtin_hints", False)
    if not paths and not include_builtin:
        return []
    try:
        from .hintpack import load_packs
        return load_packs(paths, include_builtin=include_builtin)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG


def _suggest_summary(s: Mapping) -> str:
    parts = [f"role={s['role']}"]
    if "type" in s:
        parts.append(f"type={s['type']}")
    if "length" in s:
        parts.append(f"length={s['length']}")
    if "widths" in s:
        parts.append(f"widths={s['widths']}")
    if "hierarchy" in s:
        parts.append(f"hierarchy={len(s['hierarchy'])} entries")
    return ", ".join(parts)


def _cmd_run(a: argparse.Namespace) -> int:
    if not a.dry_run and not a.output:
        print("error: give -o/--output or --dry-run", file=sys.stderr); return EXIT_CONFIG
    if a.output and a.input != "-" and os.path.realpath(a.output) == os.path.realpath(a.input):
        print("error: the output must not be the input file", file=sys.stderr); return EXIT_CONFIG
    if a.output and os.path.exists(a.output) and not a.force:
        print("error: output exists (use --force to replace it)", file=sys.stderr); return EXIT_IO
    try:
        in_fmt = _resolve_format(a.input, a.in_format, dash_default="csv")
        out_fmt = _resolve_format(a.output, a.out_format, dash_default="csv") if a.output else None
        delim = _delimiter(a.delimiter, {in_fmt} | (set() if out_fmt is None else {out_fmt}))
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    try:
        cfg = _load_config(a)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("error: the configuration is not valid JSON", file=sys.stderr); return EXIT_CONFIG
    except OSError as exc:
        print(f"error: cannot read the configuration or key ({exc.strerror})", file=sys.stderr); return EXIT_IO
    try:
        header, rows = read_any(_read(a.input), in_fmt, delim)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    except OSError as exc:
        print(f"error: cannot read the input ({exc.strerror})", file=sys.stderr); return EXIT_IO
    try:
        result = anonymize(header, rows, cfg, io=(in_fmt, out_fmt))
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    if not a.quiet:
        print(result.report.text(cfg.lang), file=sys.stderr)
    try:
        if a.report_json:
            _atomic_write(a.report_json, (result.report.to_json() + "\n").encode("utf-8"))
        if result.status == "refused":
            return EXIT_REFUSED
        if not a.dry_run:
            data = write_any(result.header, result.rows, out_fmt, delim)
            if a.output == "-":
                sys.stdout.buffer.write(data); sys.stdout.buffer.flush()
            else:
                _atomic_write(a.output, data)
    except OSError as exc:
        print(f"error: cannot write ({exc.strerror})", file=sys.stderr); return EXIT_IO
    return EXIT_OK


def _cmd_plan(a: argparse.Namespace) -> int:
    try:
        in_fmt = _resolve_format(a.input, a.in_format, dash_default="csv")
        delim = _delimiter(a.delimiter, {in_fmt})
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    try:
        cfg = _load_config(a)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("error: the configuration is not valid JSON", file=sys.stderr); return EXIT_CONFIG
    except OSError as exc:
        print(f"error: cannot read the configuration or key ({exc.strerror})", file=sys.stderr); return EXIT_IO
    try:
        header, rows = read_any(_read(a.input), in_fmt, delim)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    except OSError as exc:
        print(f"error: cannot read the input ({exc.strerror})", file=sys.stderr); return EXIT_IO
    packs = _hint_packs(a)
    if isinstance(packs, int):
        return packs
    try:
        report = Report(plan_table(header, rows, cfg))
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    roles = {n: spec.role.value for n, spec in cfg.columns.items()}
    findings = None
    if packs:
        from .hintpack import scan as _scan
        findings = _scan(header, rows, report.data["columns"], packs, cfg_roles=roles)
    if not a.no_derived:
        # v0.6.0: the derived keep-vs-qi report runs on plan with or without
        # packs (function-level import: run never pulls this module in).
        from .derived import analyze as _analyze
        derived_warnings, derived_summary = _analyze(header, rows, roles)
        if findings is None:
            from .hintpack import Findings
            findings = Findings([], [], {}, [], {})
        findings.warnings.extend(derived_warnings)
        findings.derived_summary = derived_summary
    if not a.no_hidden_chars:
        # v0.7.1: the invisible-character observation runs on plan with or
        # without packs (function-level import: run never pulls this module in).
        from .hidden_chars import analyze as _hidden_analyze
        hidden_warnings, hidden_summary = _hidden_analyze(header, rows, roles)
        if findings is None:
            from .hintpack import Findings
            findings = Findings([], [], {}, [], {})
        findings.warnings.extend(hidden_warnings)
        findings.hidden_chars_summary = hidden_summary
    if not a.quiet:
        if findings and findings.pack_info:
            print(_packs_line(findings.pack_info, cfg.lang == "ja"), file=sys.stderr)
        print(report.text(cfg.lang), file=sys.stderr)
        if findings:
            for line in findings.warning_lines(cfg.lang):
                print(line, file=sys.stderr)
    if findings and a.findings_json:
        try:
            _atomic_write(a.findings_json, (findings.to_json() + "\n").encode("utf-8"))
        except OSError as exc:
            print(f"error: cannot write ({exc.strerror})", file=sys.stderr); return EXIT_IO
    try:
        if a.report_json:
            _atomic_write(a.report_json, (report.to_json() + "\n").encode("utf-8"))
    except OSError as exc:
        print(f"error: cannot write ({exc.strerror})", file=sys.stderr); return EXIT_IO
    return EXIT_OK


def _cmd_audit(a: argparse.Namespace) -> int:
    try:
        in_fmt = _resolve_format(a.input, a.in_format, dash_default="csv")
        delim = _delimiter(a.delimiter, {in_fmt})
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    try:
        cfg = _load_config(a)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("error: the configuration is not valid JSON", file=sys.stderr); return EXIT_CONFIG
    except OSError as exc:
        print(f"error: cannot read the configuration or key ({exc.strerror})", file=sys.stderr); return EXIT_IO
    try:
        header, rows = read_any(_read(a.input), in_fmt, delim)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    except OSError as exc:
        print(f"error: cannot read the input ({exc.strerror})", file=sys.stderr); return EXIT_IO
    # v0.7.0: audit is imported here only - run/plan/inspect never pull it in.
    from .audit import audit_table, report_text, validate_subject
    try:
        validate_subject(cfg, a.subject)
        result = audit_table(header, rows, cfg, subject=a.subject)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    if not a.quiet:
        print(report_text(result, cfg.lang, max_rows=cfg.max_rows), file=sys.stderr)
    if a.findings_json:
        try:
            _atomic_write(a.findings_json,
                          (json.dumps({"audit": result}, ensure_ascii=False, indent=2,
                                      sort_keys=True) + "\n").encode("utf-8"))
        except OSError as exc:
            print(f"error: cannot write ({exc.strerror})", file=sys.stderr); return EXIT_IO
    return EXIT_OK


def _cmd_scan(a: argparse.Namespace) -> int:
    """One static HTML page: how the table looks right now (v0.8.0).

    The imports live here, function level, like every other optional module:
    run/plan/inspect/audit never pull :mod:`sieve_crowd.scan` in.  Exit codes:
    0 ok (also when no quasi-identifier candidate was found) - 1 I/O -
    2 usage (stdin without -o), same-path refusal, configuration or pack
    errors, invalid input.
    """
    if a.input == "-" and not a.output:
        print("error: give -o/--output when the input is standard input",
              file=sys.stderr)
        return EXIT_CONFIG
    if a.k is not None and a.k < 2:
        print("error: k must be an integer >= 2", file=sys.stderr)
        return EXIT_CONFIG
    if a.output and a.output != "-":
        real_out = os.path.realpath(a.output)
        clash = ((a.input != "-" and real_out == os.path.realpath(a.input))
                 or (a.config and real_out == os.path.realpath(a.config)))
        if clash:
            print("error: the output must not be the input file or the configuration file",
                  file=sys.stderr)
            return EXIT_CONFIG                    # nothing is written
    try:
        in_fmt = _resolve_format(a.input, None, dash_default="csv")
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    try:
        data = _read(a.input)
    except OSError as exc:
        print(f"error: cannot read the input ({exc.strerror})", file=sys.stderr)
        return EXIT_IO
    try:
        header, rows = read_any(data, in_fmt, None)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    packs = _hint_packs(a)
    if isinstance(packs, int):
        return packs
    try:
        if a.config:
            try:
                with open(a.config, "rb") as fh:
                    raw = json.loads(fh.read().decode("utf-8-sig"))
            except OSError as exc:
                print(f"error: cannot read the configuration ({exc.strerror})",
                      file=sys.stderr)
                return EXIT_IO
            cfg = parse_config(raw, k=a.k, lang=a.lang, max_rows=a.max_rows)
            obs_roles = {name: spec.role.value for name, spec in cfg.columns.items()}
            provisional, unassigned, k = False, frozenset(), cfg.k
        else:
            cfg, obs_roles = None, None
            provisional = True
            unassigned = frozenset()
            k = a.k if a.k is not None else 5
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("error: the configuration is not valid JSON", file=sys.stderr)
        return EXIT_CONFIG
    info = inspect_table(header, rows)
    findings = None
    if packs:
        from .hintpack import scan as _hint_scan
        findings = _hint_scan(header, rows, info, packs,
                              cfg_roles=None if provisional else obs_roles)
    if provisional:
        # the provisional roles: the first candidate's suggestion (v0.5.2
        # order), unassigned columns provisionally keep so the derived and
        # hidden-character observations can still look at them
        role_map: dict = {}
        for h in header:
            extra = findings.template_extras.get(h) if findings is not None else None
            r = extra["_suggest"].get("role") if extra else None
            role_map[h] = r if r in ("id", "qi", "sensitive", "keep", "drop") else None
        unassigned = frozenset(h for h in header if role_map[h] is None)
        obs_roles = {h: (role_map[h] or "keep") for h in header}
        if any(role_map[h] == "qi" for h in header):
            cols = {}
            for h in header:
                r = role_map[h]
                cols[h] = ({"role": "qi", "type": "exact"} if r == "qi" else
                           {"role": "id"} if r == "id" else
                           {"role": "sensitive"} if r == "sensitive" else
                           {"role": "drop"} if r == "drop" else {"role": "keep"})
            try:
                cfg = parse_config({"k": k, "columns": cols},
                                   lang=a.lang, max_rows=a.max_rows)
            except ConfigError as exc:
                print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
        # else: no qi candidate -> cfg stays None, the audit sections stay out
    derived_result = None
    if cfg is not None and not a.no_derived:
        from .derived import analyze as _derived_analyze
        derived_result = _derived_analyze(header, rows, obs_roles)
    hidden_result = None
    if not a.no_hidden_chars:
        from .hidden_chars import analyze as _hidden_analyze
        hidden_result = _hidden_analyze(header, rows, obs_roles)
    audit_result = None
    if cfg is not None:
        from .audit import audit_table, validate_subject
        try:
            validate_subject(cfg, a.subject)
            audit_result = audit_table(header, rows, cfg, subject=a.subject)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    from .scan import page
    html = page(header, rows, cfg=cfg, k=k, roles=obs_roles, provisional=provisional,
                unassigned=unassigned, findings=findings, derived=derived_result,
                hidden=hidden_result, audit=audit_result, subject=a.subject,
                lang=a.lang,
                input_name=None if a.input == "-" else os.path.basename(a.input),
                input_sha256=hashlib.sha256(data).hexdigest(),
                config_name=os.path.basename(a.config) if a.config else None)
    payload = html.encode("utf-8")
    try:
        if a.output == "-":
            sys.stdout.buffer.write(payload); sys.stdout.buffer.flush()
            dest = "（標準出力）" if a.lang == "ja" else "(standard output)"
        else:
            dest = a.output or os.path.splitext(a.input)[0] + ".scan.html"
            _atomic_write(dest, payload)
    except OSError as exc:
        print(f"error: cannot write ({exc.strerror})", file=sys.stderr)
        return EXIT_IO
    w = ((len(findings.warnings) if findings is not None else 0)
         + (len(derived_result[0]) if derived_result is not None else 0)
         + (len(hidden_result[0]) if hidden_result is not None else 0))
    if a.lang == "ja":
        print(f"scan: {dest} に書きました（{len(rows)} 行、{len(header)} 列、所見 {w} 件）",
              file=sys.stderr)
    else:
        print(f"scan: wrote {dest} ({len(rows)} rows, {len(header)} columns, "
              f"{w} findings)", file=sys.stderr)
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    a = _parser().parse_args(argv)
    return {"inspect": _cmd_inspect, "keygen": _cmd_keygen, "run": _cmd_run,
            "plan": _cmd_plan, "audit": _cmd_audit, "scan": _cmd_scan}[a.cmd](a)
