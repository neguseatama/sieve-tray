"""Command line: inspect / keygen / run.  Cell values never appear in messages or logs."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import tempfile
from typing import Optional, Sequence

from . import __version__
from .config import parse_config, parse_key
from .engine import anonymize, inspect_table
from .hints import hint
from .model import ConfigError, InputError
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
    r.add_argument("--keep-order", action="store_true", help="relaxation: do not shuffle the rows (recorded)")
    r.add_argument("--shuffle-seed", type=int, default=0)
    r.add_argument("--lang", choices=["en", "ja"], default="en")
    r.add_argument("--max-rows", type=int, default=200_000)
    r.add_argument("--max-evals", type=int, default=20_000)
    r.add_argument("--report-json", metavar="FILE")
    r.add_argument("--quiet", action="store_true")
    r.add_argument("--force", action="store_true")
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


def _cmd_inspect(a: argparse.Namespace) -> int:
    try:
        in_fmt = _resolve_format(a.input, a.in_format, dash_default="csv")
        delim = _delimiter(a.delimiter, {in_fmt})
        header, rows = read_any(_read(a.input), in_fmt, delim)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr); return EXIT_CONFIG
    except OSError as exc:
        print(f"error: cannot read the input ({exc.strerror})", file=sys.stderr); return EXIT_IO
    info = inspect_table(header, rows)
    en = a.lang == "en"
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
    if a.config_out:
        if os.path.exists(a.config_out) and not a.force:
            print("error: the config file exists (use --force)", file=sys.stderr); return EXIT_IO
        template = {"k": 5, "l": 1, "max_suppression": 0.05,
                    "columns": {c["name"]: ({"role": "?", "_hint": hints[c["name"]][1]} if hints[c["name"]][0]
                                    else {"role": "?"}) for c in info}}
        try:
            _atomic_write(a.config_out, (json.dumps(template, ensure_ascii=False, indent=2) + "\n").encode())
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
        with open(a.config, "rb") as fh:
            raw = json.loads(fh.read().decode("utf-8-sig"))
        key = parse_key(open(a.key_file, encoding="utf-8").read()) if a.key_file else None
        cfg = parse_config(raw, k=a.k, l=a.l, max_suppression=a.max_suppression,
                           shuffle=not a.keep_order, shuffle_seed=a.shuffle_seed, lang=a.lang,
                           max_rows=a.max_rows, max_evals=a.max_evals, key=key)
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    a = _parser().parse_args(argv)
    return {"inspect": _cmd_inspect, "keygen": _cmd_keygen, "run": _cmd_run}[a.cmd](a)
