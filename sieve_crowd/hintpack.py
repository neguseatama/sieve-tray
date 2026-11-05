"""Hint packs for `inspect` and `plan`: suggest roles and check value shapes.

A pack is a JSON object (schema 1, read as ``utf-8-sig`` so spreadsheet exports
with a BOM work).  Packs are loaded **only** by ``inspect`` and ``plan``; the
``run`` command never imports this module (the import sits inside the two
command handlers, not at the top of ``cli.py``), so the anonymization path is
byte-for-byte unchanged.

The matching vocabulary is a closed set:

* ``column_names`` — exact match against the normalized column name
  (``unicodedata.normalize("NFKC", name).strip().lower()``; no token or
  substring matching).  The legacy token/substring ``hint()`` route in
  ``hints.py`` is separate and left untouched.
* ``value_shape`` — a bounded shape pattern: ``#`` one digit, ``@`` one ASCII
  letter, ``\\X`` a literal escape of ``X``, any other character is a literal.
  Only ``{m}`` and ``{m,n}`` quantifiers are allowed, and only on the preceding
  atom.  No alternation, no nesting, no backreferences — the language cannot
  describe a catastrophic-backtracking pattern.
* ``set`` / ``range`` / ``check`` (``luhn`` · ``my_number`` · ``email_shape``)
  — evaluations that return three values: **match / mismatch / cannot-check**.

Since v0.7.1 the value inputs are folded through the shared chartable
(``chartable.fold``) before matching: ``value_shape`` and the leak scan fold
with ``dashes=True`` (shape matching — the long-vowel mark and the other
folding dashes become ``-``), the value checks fold with ``dashes=False``
(v0.7.5: the luhn evaluation alone re-folds with ``dashes=True`` and strips
the dashes first, so hyphenated card numbers reach luhn — ``_luhn_digits``).
The fold is a fixed mapping, so pure-ASCII input is unchanged and the match
results stay byte-identical there; full-width digits, full-width symbols,
long-vowel dashes and invisible characters now reach the matchers (the v0.5.2
"full-width never matches" limitation is resolved).  Column names keep their
NFKC normalization (unchanged, Unicode-database dependent by design decision
of v0.5.0).

Findings carry aggregates and column names only — **no cell value ever appears**
in a finding, a warning, or a suggestion.  Candidate lists are ordered by
contract, not by load order or by the order rules appear in a pack: evidence
strength (name+value → value → name → stat), then role (id → sensitive → qi;
roles outside this list come last), then rule id ascending.  ``_suggest``
follows the first candidate of the sorted list.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional, Sequence

from .model import ConfigError

SCHEMA = 1
MAX_PACK_BYTES = 1 << 20      # 1 MiB initial ceiling (declared; raise after measurement)
MAX_RULES = 200               # initial ceiling
MAX_NAME_CHARS = 128          # column_names / id length ceiling
MAX_CELL_CHARS = 4096         # cells longer than this are skipped in the leak scan

_CHECK_KINDS = ("set", "range", "luhn", "my_number", "email_shape")
_ERA = re.compile(r"(明治|大正|昭和|平成|令和)\d{1,2}年")
# A token is a run of ASCII alphanumerics plus the characters that glue numbers
# and addresses together (- + @ . _ %).  Everything else — whitespace,
# punctuation, prose in any script — separates tokens.  Dashes stay inside a
# token so 03-1234-5678 is one token; dots stay so a@example.co.jp is one.
_TOKENS = re.compile(r"[0-9A-Za-z\-+@._%]+")
_FULLWIDTH_DIGIT = "".join(chr(c) for c in range(0xFF10, 0xFF1A))      # ０..９
_FULLWIDTH_UPPER = "".join(chr(c) for c in range(0xFF21, 0xFF3B))      # Ａ..Ｚ
_FULLWIDTH_LOWER = "".join(chr(c) for c in range(0xFF41, 0xFF5B))      # ａ..ｚ
_FULL_ALNUM = _FULLWIDTH_DIGIT + _FULLWIDTH_UPPER + _FULLWIDTH_LOWER
_HALF_DIGIT = "0123456789"
_HALF_ALPHA = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


# --------------------------------------------------------------------------- #
# value_shape
# --------------------------------------------------------------------------- #
def _compile_shape(shape: str) -> re.Pattern:
    """Compile a value_shape string into an anchored regex.

    The shape language is restricted on purpose (see module docstring); the
    compiled regex therefore cannot exhibit exponential backtracking.
    """
    atoms: list[str] = []
    i, n = 0, len(shape)
    while i < n:
        ch = shape[i]
        if ch == "\\":
            i += 1
            if i >= n:
                raise ConfigError("value_shape: '\\' must escape a character")
            atoms.append(re.escape(shape[i]))
            kind = "literal"
        elif ch == "#":
            atoms.append("[0-9]"); kind = "digit"
        elif ch == "@":
            atoms.append("[A-Za-z]"); kind = "letter"
        elif ch in "{}":
            raise ConfigError(f"value_shape: '{ch}' must follow an atom")
        else:
            atoms.append(re.escape(ch)); kind = "literal"
        i += 1
        # quantifier?
        if i < n and shape[i] == "{":
            j = shape.find("}", i)
            if j < 0:
                raise ConfigError("value_shape: unterminated '{...}'")
            body = shape[i + 1:j]
            if not re.fullmatch(r"\d+|\d+,\d+", body):
                raise ConfigError(f"value_shape: bad quantifier {{{body}}}")
            lo, _, hi = body.partition(",")
            hi = hi or lo
            if int(lo) < 0 or int(hi) < int(lo):
                raise ConfigError(f"value_shape: bad quantifier {{{body}}}")
            atoms[-1] = f"(?:{atoms[-1]}){{{body}}}"
            i = j + 1
            del kind  # quantifier consumed; not used further
    return re.compile("".join(atoms) + r"\Z")


# --------------------------------------------------------------------------- #
# checks (three-valued: "match" / "mismatch" / "cannot_check")
# --------------------------------------------------------------------------- #
def _luhn(digits: str) -> bool:
    s = 0
    for k, d in enumerate(reversed(digits)):
        x = int(d) * (2 if k % 2 else 1)
        s += x - 9 if x > 9 else x
    return s % 10 == 0


def _luhn_digits(value: str) -> str:
    """v0.7.5 (README known-limitation 6 resolved): the value checks fold with
    ``dashes=False``, so a hyphenated card number never reached luhn — it
    counted as ``cannot_check``.  The luhn evaluation alone re-folds its input
    with ``dashes=True`` and accepts it only when the result is a run of ASCII
    digits and dashes: the dash-stripped digits go to luhn.  Anything else —
    letters, spaces, no digits, non-ASCII digits — stays ``cannot_check``.
    Dashless values take the same path (the fold is idempotent and every
    printable ASCII character is invariant), so their results are unchanged."""
    from .chartable import fold   # function-level, as in scan(): run never gets here
    fv = fold(value, dashes=True)
    core = fv.replace("-", "")
    if core and core.isascii() and core.isdigit():
        return core
    return ""


def _my_number_ok(digits: str) -> bool:
    """12-digit Japanese My Number: 11 body digits + 1 check digit (residue 11)."""
    if len(digits) != 12 or not digits.isdigit():
        return False
    body, check = digits[:11], int(digits[11])
    weights = [6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    total = sum(int(d) * w for d, w in zip(body, weights))
    r = total % 11
    expected = 0 if r <= 1 else 11 - r
    return check == expected


_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\Z")


def _eval_check(check: "Check", value: str) -> str:
    kind = check.kind
    if value == "":
        return "cannot_check"
    if kind == "set":
        return "match" if value in check.values else "mismatch"
    if kind == "range":
        try:
            x = float(value)
        except ValueError:
            return "cannot_check"
        if not (x == x):          # NaN guard (should not arise from float())
            return "cannot_check"
        return "match" if check.min <= x <= check.max else "mismatch"
    if kind == "luhn":
        digits = _luhn_digits(value)   # v0.7.5: dash-folded, digits and dashes only
        if digits:
            return "match" if _luhn(digits) else "mismatch"
        return "cannot_check"
    if kind == "my_number":
        return "match" if _my_number_ok(value) else (
            "mismatch" if value.isdigit() and len(value) == 12 else "cannot_check")
    if kind == "email_shape":
        return "match" if _EMAIL.match(value) else "mismatch"
    raise ConfigError(f"unknown check kind: {kind!r}")   # validated earlier; defensive


def _token_matches(rule: "Rule", token: str) -> bool:
    """One token against a leak rule.  The plain token is tried first (emails
    keep their dots); a dashed token is also tried without its dashes, so
    formatted numbers (03-1234-5678, 4242-4242-4242-4242) reach the digit
    shapes and the digit-only checks.  Space-separated pieces are separate
    tokens and never re-combined (documented constraint)."""
    if rule.shape is not None:
        return bool(rule.shape.match(token)) or (
            "-" in token and bool(rule.shape.match(token.replace("-", ""))))
    if rule.check is not None:
        return _eval_check(rule.check, token) == "match" or (
            "-" in token and _eval_check(rule.check, token.replace("-", "")) == "match")
    return False


# --------------------------------------------------------------------------- #
# pack model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Check:
    kind: str
    values: frozenset[str] = frozenset()
    min: float = 0.0
    max: float = 0.0

    @classmethod
    def from_obj(cls, obj: Mapping[str, Any]) -> "Check":
        kind = obj.get("kind")
        if kind not in _CHECK_KINDS:
            raise ConfigError(f"check: kind must be one of {', '.join(_CHECK_KINDS)}")
        if kind == "set":
            vals = obj.get("values")
            if not isinstance(vals, list) or not vals or not all(isinstance(v, str) for v in vals):
                raise ConfigError("check set: 'values' must be a non-empty list of strings")
            return cls(kind, frozenset(vals))
        if kind == "range":
            mn, mx = obj.get("min"), obj.get("max")
            if not isinstance(mn, (int, float)) or isinstance(mn, bool) or \
               not isinstance(mx, (int, float)) or isinstance(mx, bool):
                raise ConfigError("check range: 'min' and 'max' must be numbers")
            if mn > mx:
                raise ConfigError("check range: 'min' must be <= 'max'")
            return cls(kind, min=float(mn), max=float(mx))
        return cls(kind)


@dataclass(frozen=True)
class Rule:
    id: str
    pack_id: str
    column_names: frozenset[str]
    shape: Optional[re.Pattern]
    suggest: Optional[Mapping[str, Any]]
    check: Optional[Check]
    leak: bool


@dataclass(frozen=True)
class Pack:
    id: str
    rules: tuple[Rule, ...]
    version: Optional[str] = None   # optional "version" field of the pack JSON
    sha256: str = ""                # sha256 of the loaded bytes (file or builtin constant)
    source: str = "file"            # "builtin" or "file"


def _norm_name(name: str) -> str:
    """NFKC + strip + lower-case: exact-match normalization for ``column_names``."""
    return unicodedata.normalize("NFKC", str(name)).strip().lower()


def _validate_rule(obj: Mapping[str, Any], pack_id: str) -> Rule:
    if not isinstance(obj, Mapping):
        raise ConfigError(f"pack {pack_id!r}: a rule must be an object")
    rid = obj.get("id")
    if not isinstance(rid, str) or not rid or len(rid) > MAX_NAME_CHARS:
        raise ConfigError(f"pack {pack_id!r}: every rule needs a non-empty string 'id'")
    when = obj.get("when", {})
    if not isinstance(when, Mapping):
        raise ConfigError(f"pack {pack_id!r} rule {rid!r}: 'when' must be an object")
    names = when.get("column_names")
    if names is None:
        names_set = frozenset()
    elif isinstance(names, list) and all(isinstance(x, str) and x for x in names):
        names_set = frozenset(_norm_name(x) for x in names)
    else:
        raise ConfigError(f"pack {pack_id!r} rule {rid!r}: 'column_names' must be a list of strings")
    shape_raw = when.get("value_shape")
    shape = None
    if shape_raw is not None:
        if not isinstance(shape_raw, str) or not shape_raw:
            raise ConfigError(f"pack {pack_id!r} rule {rid!r}: 'value_shape' must be a non-empty string")
        shape = _compile_shape(shape_raw)
    if not names_set and shape is None and "check" not in obj and not obj.get("leak"):
        raise ConfigError(f"pack {pack_id!r} rule {rid!r}: needs 'when', 'check', or 'leak'")
    suggest = obj.get("suggest")
    if suggest is not None:
        if not isinstance(suggest, Mapping) or "role" not in suggest:
            raise ConfigError(f"pack {pack_id!r} rule {rid!r}: 'suggest' must be an object with a 'role'")
        if not isinstance(suggest["role"], str):
            raise ConfigError(f"pack {pack_id!r} rule {rid!r}: suggest.role must be a string")
    check = None
    if "check" in obj:
        check = Check.from_obj(obj["check"])
    leak = bool(obj.get("leak", False))
    return Rule(rid, pack_id, names_set, shape, suggest, check, leak)


def _parse_pack(raw: Mapping[str, Any]) -> Pack:
    if raw.get("schema") != SCHEMA:
        raise ConfigError(f"hint pack: 'schema' must be {SCHEMA}")
    pid = raw.get("id")
    if not isinstance(pid, str) or not pid or len(pid) > MAX_NAME_CHARS:
        raise ConfigError("hint pack: needs a non-empty string 'id'")
    version = raw.get("version")
    if version is not None and (
            not isinstance(version, str) or not version or len(version) > MAX_NAME_CHARS):
        raise ConfigError(
            f"pack {pid!r}: 'version' must be a non-empty string of at most {MAX_NAME_CHARS} chars")
    rules_raw = raw.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ConfigError(f"pack {pid!r}: 'rules' must be a non-empty list")
    if len(rules_raw) > MAX_RULES:
        raise ConfigError(f"pack {pid!r}: more than {MAX_RULES} rules (ceiling)")
    seen: set[str] = set()
    rules = []
    for r in rules_raw:
        rule = _validate_rule(r, pid)
        if rule.id in seen:
            raise ConfigError(f"pack {pid!r}: duplicate rule id {rule.id!r}")
        seen.add(rule.id)
        rules.append(rule)
    return Pack(pid, tuple(rules), version)


def load_pack_bytes(data: bytes, *, source: str = "<pack>", origin: str = "file") -> Pack:
    if len(data) > MAX_PACK_BYTES:
        raise ConfigError(f"hint pack {source}: larger than {MAX_PACK_BYTES} bytes (ceiling)")
    try:
        raw = json.loads(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise ConfigError(f"hint pack {source}: not valid UTF-8") from None
    except json.JSONDecodeError as exc:
        raise ConfigError(f"hint pack {source}: not valid JSON ({exc.msg})") from None
    if not isinstance(raw, Mapping):
        raise ConfigError(f"hint pack {source}: the top level must be a JSON object")
    pack = _parse_pack(raw)
    # D: sha256 of the exact bytes loaded (a file, or the builtin string constant)
    return replace(pack, sha256=hashlib.sha256(data).hexdigest(), source=origin)


def load_packs(paths: Sequence[str], *, include_builtin: bool) -> list[Pack]:
    """Load the builtin pack (unless ``--no-builtin-hints``), then the user
    packs in the command-line order — the order findings ``packs``/``pack_info``
    and candidate lists use (ties broken in favour of the earlier pack).

    Pack ids and rule ids are unique across the whole set, builtin included:
    a duplicate raises ConfigError (exit code 2).  To replace the builtin,
    give ``--no-builtin-hints`` and then reuse its id.
    """
    packs: list[Pack] = []
    pack_owner: dict[str, str] = {}   # pack id -> what claimed it first
    rule_owner: dict[str, str] = {}   # rule id -> pack id that claimed it first
    if include_builtin:
        from .hintpack_builtin import BUILTIN_PACK_BYTES
        pack = load_pack_bytes(BUILTIN_PACK_BYTES, source="<jp-basic>", origin="builtin")
        packs.append(pack)
        pack_owner[pack.id] = "the built-in pack"
        for r in pack.rules:
            rule_owner[r.id] = "the built-in pack"
    for p in paths:
        try:
            with open(p, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            raise ConfigError(f"hint pack {p}: cannot read ({exc.strerror})") from None
        pack = load_pack_bytes(data, source=p)
        if pack.id in pack_owner:
            if pack_owner[pack.id] == "the built-in pack":
                raise ConfigError(
                    f'hint pack "{p}": pack id "{pack.id}" is already used by the built-in pack '
                    f"(use --no-builtin-hints to replace it)")
            raise ConfigError(
                f'hint pack "{p}": pack id "{pack.id}" is already used by pack "{pack_owner[pack.id]}"')
        for r in pack.rules:
            if r.id in rule_owner:
                if rule_owner[r.id] == "the built-in pack":
                    raise ConfigError(
                        f'hint pack "{p}": rule id "{r.id}" is already used by the built-in pack '
                        f"(use --no-builtin-hints to replace it)")
                raise ConfigError(
                    f'hint pack "{p}": rule id "{r.id}" is already used by pack "{rule_owner[r.id]}"')
            rule_owner[r.id] = pack.id
        pack_owner[pack.id] = pack.id
        packs.append(pack)
    return packs


# --------------------------------------------------------------------------- #
# evaluation
# --------------------------------------------------------------------------- #
def _has_fullwidth(v: str) -> bool:
    return any(c in _FULL_ALNUM for c in v)


def _has_halfwidth(v: str) -> bool:
    return any(c in _HALF_DIGIT + _HALF_ALPHA for c in v)


@dataclass
class ColumnFindings:
    candidates: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    leaks: list[dict] = field(default_factory=list)
    declared_role: Optional[str] = None   # plan only: the role the config declares


@dataclass
class Findings:
    packs: list[str]
    pack_info: list[dict]             # D: {id, version, source, sha256} per pack, load order
    columns: dict[str, ColumnFindings]
    warnings: list[dict]
    template_extras: dict[str, dict]   # col -> {"_suggest": {...}, "_candidates": [...]}
    derived_summary: Optional[dict] = None   # v0.6.0, plan only: the derived keep-vs-qi class counts
    hidden_chars_summary: Optional[dict] = None   # v0.7.1, plan only: the invisible-character scan

    def to_json(self) -> str:
        return json.dumps(self._as_obj(), ensure_ascii=False, indent=2, sort_keys=True)

    def _as_obj(self) -> dict:
        cols: dict[str, dict] = {}
        for col, cf in self.columns.items():
            if not cf.candidates and not cf.checks and not cf.leaks:
                continue
            entry: dict = {}
            if cf.declared_role is not None:
                entry["declared_role"] = cf.declared_role
            if cf.candidates:
                entry["candidates"] = cf.candidates
            if cf.checks:
                entry["checks"] = cf.checks
            if cf.leaks:
                entry["leaks"] = cf.leaks
            cols[col] = entry
        obj = {"packs": self.packs, "pack_info": self.pack_info,
               "columns": cols, "warnings": self.warnings}
        if self.derived_summary is not None:      # key addition only (v0.6.0)
            obj["derived_summary"] = self.derived_summary
        if self.hidden_chars_summary is not None:  # key addition only (v0.7.1)
            obj["hidden_chars_summary"] = self.hidden_chars_summary
        return obj

    def warning_lines(self, lang: str) -> list[str]:
        """stderr lines (v0.5.1 format).  Pack findings carry the heading; the
        derived lines (v0.6.0) and the hidden-character lines (v0.7.1) follow
        right after them without one."""
        if not self.warnings:
            return []
        ja = lang == "ja"
        head = "ヒントパックの所見:" if ja else "Hint pack findings:"
        pack_lines: list[str] = []
        derived_lines: list[str] = []
        hidden_lines: list[str] = []
        for w in self.warnings:
            code = w["code"]
            if code == "derived":
                if w["relation"] == "reveals_qi":
                    if ja:
                        derived_lines.append(
                            f"  - derived: 「{w['column']}」（宣言 {w['declared_role']}）から"
                            f"準識別子「{w['qi_column']}」がほぼ推定できます: "
                            f"支持 {w['support']} 件、違反 {w['violations']} 件")
                    else:
                        derived_lines.append(
                            f"  - derived: \"{w['column']}\" (declared {w['declared_role']}) "
                            f"reveals qi \"{w['qi_column']}\": "
                            f"support {w['support']}, violations {w['violations']}")
                else:
                    if ja:
                        derived_lines.append(
                            f"  - derived: 準識別子「{w['qi_column']}」から"
                            f"「{w['column']}」（宣言 {w['declared_role']}）がほぼ推定できます: "
                            f"支持 {w['support']} 件、違反 {w['violations']} 件")
                    else:
                        derived_lines.append(
                            f"  - derived: \"{w['column']}\" (declared {w['declared_role']}) "
                            f"is implied by qi \"{w['qi_column']}\": "
                            f"support {w['support']}, violations {w['violations']}")
            elif code == "role_mismatch":
                if ja:
                    pack_lines.append(
                        f"  - role_mismatch: 「{w['column']}」は {w['suggested']} を提案しますが、"
                        f"設定では {w['declared']} として宣言されています（根拠: {w['evidence']}）")
                else:
                    pack_lines.append(
                        f"  - role_mismatch: \"{w['column']}\" suggests {w['suggested']} "
                        f"but is declared {w['declared']} (evidence: {w['evidence']})")
            elif code == "mixed_form":
                if ja:
                    pack_lines.append(
                        f"  - mixed_form: 「{w['column']}」に全角・半角が混在する値が "
                        f"{w['mixed_values']} 件あります（NFC では別の群れになります）")
                else:
                    pack_lines.append(
                        f"  - mixed_form: \"{w['column']}\" has {w['mixed_values']} value(s) "
                        f"mixing full/half-width forms (NFC keeps them as separate crowds)")
            elif code == "japanese_era":
                if ja:
                    pack_lines.append(
                        f"  - japanese_era: 「{w['column']}」に和暦形式の値が {w['count']} 件あります"
                        f"（西暦への統一を推奨）")
                else:
                    pack_lines.append(
                        f"  - japanese_era: \"{w['column']}\" has {w['count']} value(s) in a "
                        f"Japanese-era form (prefer ISO dates)")
            elif code == "hidden_chars":
                kinds = ", ".join(w["kinds"])
                if ja:
                    tail = ("見た目が同じ値が別のグループに分かれます"
                            if w["declared_role"] == "qi"
                            else "出力にそのまま残ります")
                    hidden_lines.append(
                        f"  - hidden_chars: 「{w['column']}」（宣言 {w['declared_role']}）: "
                        f"{w['rows']} 行に不可視文字（{kinds}）が含まれています。{tail}")
                else:
                    tail = ("values that look identical form separate groups"
                            if w["declared_role"] == "qi"
                            else "they stay in the output")
                    hidden_lines.append(
                        '  - hidden_chars: "' + w["column"]
                        + f'" (declared {w["declared_role"]}): '
                        + f"{w['rows']} row(s) contain invisible characters ({kinds}); {tail}")
            elif code == "leak":
                if ja:
                    pack_lines.append(
                        f"  - leak: 「{w['column']}」（宣言 {w['declared_role']}）: "
                        f"空でない {w['checked']} 件のうち {w['count']} 件に "
                        f"{w['pack']}/{w['rule']} が含まれる可能性があります")
                else:
                    pack_lines.append(
                        f"  - leak: \"{w['column']}\" (declared {w['declared_role']}): "
                        f"{w['count']} of {w['checked']} non-empty cells may contain "
                        f"{w['pack']}/{w['rule']}")
        if pack_lines:
            return [head] + pack_lines + derived_lines + hidden_lines
        return derived_lines + hidden_lines


_EVIDENCE_ORDER = {"name+value": 0, "value": 1, "name": 2, "stat": 3}
_ROLE_ORDER = {"id": 0, "sensitive": 1, "qi": 2}   # roles not listed here sort after qi


def _candidate_key(cand: dict) -> tuple:
    """a (v0.5.2): the candidate order is a contract, not load order and not the
    order rules are written in a pack: evidence strength, then role, then rule id
    ascending (plain string comparison).  Rule ids are unique across all packs,
    so the key never ties."""
    return (_EVIDENCE_ORDER[cand["evidence"]],
            _ROLE_ORDER.get(cand["suggest"].get("role"), len(_ROLE_ORDER)),
            cand["rule"])


def scan(header: Sequence[str], rows: Sequence[Sequence[str]],
         info: Sequence[Mapping[str, Any]], packs: Sequence[Pack],
         *, cfg_roles: Optional[Mapping[str, str]] = None) -> Findings:
    """Evaluate packs against the columns.  ``info`` is ``inspect_table``'s output.

    ``cfg_roles`` maps column -> declared role value (``id``/``qi``/...); pass
    ``None`` for ``inspect`` (no config yet) to suppress ``role_mismatch``.
    Cell values are never placed in the returned findings — only aggregates,
    column names, and rule ids.  Values are folded through the shared chartable
    before matching (function-level import: the fold's table must never load
    from ``run``, which does not reach this module anyway).
    """
    from .chartable import fold

    def _make_cached(dashes: bool):
        """A fold with a distinct-value cache; call once per column (columns
        repeat their values heavily, so the cache is bounded by the column's
        own distinct values)."""
        cache: dict[str, str] = {}

        def fold_cached(v: str) -> str:
            if v.isascii():
                return v                  # exact: no key is below U+0080
            r = cache.get(v)
            if r is None:
                r = fold(v, dashes=dashes)
                cache[v] = r
            return r

        return fold_cached

    pos = {h: i for i, h in enumerate(header)}
    packs_list = [p.id for p in packs]
    cols: dict[str, ColumnFindings] = {h: ColumnFindings() for h in header}
    extras: dict[str, dict] = {}
    warnings: list[dict] = []

    for c in info:
        name = c["name"]
        idx = pos[name]
        values = [r[idx] for r in rows]
        nonempty = [v for v in values if v != ""]
        norm_name = _norm_name(name)
        cf = cols[name]

        # Leak-scan scoping (B): plan scans only the columns whose declared role
        # is keep/sensitive/qi — id/drop are never scanned.  Inspect has no roles
        # and scans every column.  Nothing but counts is recorded.
        leak_target = cfg_roles is None or cfg_roles.get(name) in ("keep", "sensitive", "qi")
        if leak_target and cfg_roles is not None:
            cf.declared_role = cfg_roles.get(name)
        # a plain-digit cell is its own single token (skips the regex scan);
        # oversized cells are skipped regardless of shape.  v0.7.1: the cell is
        # folded (dashes=True — shape matching) before tokenizing, so full-width
        # digits and long-vowel dashes form tokens too; both folds are cached
        # per column and ASCII takes the exact fast path.
        fold_shape = _make_cached(True)
        fold_check = _make_cached(False)

        def _cell_tokens(v: str):
            fv = fold_shape(v)
            if len(fv) > MAX_CELL_CHARS:
                return None
            if fv.isascii() and fv.isdigit():
                return (fv,)
            return tuple(_TOKENS.findall(fv))

        cell_tokens = [_cell_tokens(v) for v in nonempty] if leak_target else ()
        if leak_target:
            uniq_tokens = {t for tokens in cell_tokens if tokens for t in tokens}
            n_checked = sum(1 for t in cell_tokens if t is not None)
            n_skipped = len(nonempty) - n_checked

        for pack in packs:
            for rule in pack.rules:
                name_match = bool(rule.column_names) and norm_name in rule.column_names
                # The whole-column value signals feed the evidence rank, the
                # checks record and the candidates — never the leak counts
                # (the token scan below does that).  A leak rule whose name
                # does not match therefore skips the whole-column scan on this
                # column: its job here is the token scan only, and the checks
                # record keeps its v0.5.0 condition (a signal must exist).
                if name_match or not rule.leak:
                    shape_match = rule.shape is not None and any(
                        rule.shape.match(fold_shape(v)) for v in nonempty)   # type: ignore[union-attr]
                    check_match = rule.check is not None and any(
                        _eval_check(rule.check, fold_check(v)) == "match"
                        for v in nonempty)   # type: ignore[union-attr]
                else:
                    shape_match = check_match = False
                value_signal = shape_match or check_match
                # B: a leak rule is evaluated on every scanned column regardless
                # of name/value signals — prose-embedded identifiers must be
                # found in columns that neither look named nor shape-matched.
                if not (name_match or value_signal or rule.leak):
                    continue
                if name_match and value_signal:
                    evi = "name+value"
                elif value_signal:
                    evi = "value"
                else:
                    evi = "name"

                # check aggregates (three-valued; unchanged v0.5.0 condition:
                # the column must show a name or value signal for the rule)
                if rule.check is not None and (name_match or value_signal):
                    agg = {"match": 0, "mismatch": 0, "cannot_check": 0}
                    for v in values:
                        agg[_eval_check(rule.check, fold_check(v))] += 1
                    cf.checks.append({"pack": pack.id, "rule": rule.id,
                                      "kind": rule.check.kind, **agg})   # type: ignore[union-attr]

                # leak count (B): values that look like a direct identifier are
                # matched as prose tokens (see _token_matches); cells over
                # MAX_CELL_CHARS are skipped and counted as skipped.  The
                # distinct tokens are matched once per column, then the cells
                # that carry one are counted — the same counts as matching
                # cell by cell, without re-matching repeated values.  No value
                # is emitted, only the counts.  On plan a count >= 1 also adds
                # a warnings element (code leak) so the stderr line appears.
                if rule.leak and leak_target:
                    matched = {t for t in uniq_tokens if _token_matches(rule, t)}
                    count = 0
                    if matched:
                        for tokens in cell_tokens:
                            if tokens is not None and any(t in matched for t in tokens):
                                count += 1
                    if count or n_skipped:
                        cf.leaks.append({"pack": pack.id, "rule": rule.id, "count": count,
                                         "checked": n_checked, "skipped": n_skipped})
                        if count and cfg_roles is not None:
                            warnings.append({"code": "leak", "column": name,
                                             "declared_role": cf.declared_role,
                                             "pack": pack.id, "rule": rule.id,
                                             "count": count, "checked": n_checked})

                # candidate for the template (order fixed by the sort below).
                # v0.7.3 gate: a suggestion needs a name or a value signal.
                # A leak rule with neither still runs its token scan above,
                # but it must not hang a suggestion on the column — without
                # this gate every scanned column would carry a suggestion
                # from a leak rule that has one (jp-email, jp-phone,
                # jp-mynumber, jp-card since jp-basic 1.4.0).
                if rule.suggest is not None and (name_match or value_signal):
                    cf.candidates.append({"pack": pack.id, "rule": rule.id,
                                          "evidence": evi, "suggest": dict(rule.suggest)})

        # a (v0.5.2): the candidate order is a contract — evidence strength, then
        # role, then rule id — independent of load order and of the order rules
        # are written in a pack.  _suggest follows the first sorted candidate.
        if cf.candidates:
            cf.candidates.sort(key=_candidate_key)
            extras[name] = {"_suggest": dict(cf.candidates[0]["suggest"]),
                            "_candidates": list(cf.candidates)}

        # observation warnings (always emitted when scanning; value-shape only,
        # no cell values): full/half-width mixing and Japanese-era dates
        mixed = sum(1 for v in nonempty if _has_fullwidth(v) and _has_halfwidth(v))
        if mixed:
            warnings.append({"code": "mixed_form", "column": name, "mixed_values": mixed})
        era = sum(1 for v in nonempty if _ERA.search(v))
        if era:
            warnings.append({"code": "japanese_era", "column": name, "count": era})

    # role_mismatch (v0.5.1 qi, v0.7.3 id): a column suggested 'qi' (evidence
    # name+value or value) but declared keep / sensitive, or suggested 'id'
    # (evidence name+value) but declared keep / qi / sensitive.  The id side
    # divides the labour with the leak scan: a column whose name does not
    # match the rule is leak's job (value-only evidence never fires
    # role_mismatch for id), and name-only evidence alone never contradicts a
    # declaration.  id/drop declarations are never a mismatch.  One warning
    # per column — the first qualifying candidate in the sorted order (id
    # sorts before qi at equal evidence).  Inspect has no config -> skipped.
    if cfg_roles is not None:
        for name, cf in cols.items():
            declared = cfg_roles.get(name)
            if declared not in ("keep", "qi", "sensitive"):
                continue
            for cand in cf.candidates:
                role = cand["suggest"].get("role")
                evi = cand["evidence"]
                if role == "qi" and declared in ("keep", "sensitive") \
                        and evi in ("name+value", "value"):
                    warnings.append({"code": "role_mismatch", "column": name,
                                     "declared": declared, "suggested": "qi",
                                     "evidence": evi})
                    break
                if role == "id" and evi == "name+value":
                    warnings.append({"code": "role_mismatch", "column": name,
                                     "declared": declared, "suggested": "id",
                                     "evidence": evi})
                    break

    return Findings(packs_list,
                    [{"id": p.id, "version": p.version, "source": p.source, "sha256": p.sha256}
                     for p in packs],
                    cols, warnings, extras)
