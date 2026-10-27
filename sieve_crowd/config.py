"""Configuration: which column plays which role, and how much to protect."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .generalize import make_generalizer
from .model import ConfigError, Role

_TOP_KEYS = {"k", "l", "max_suppression", "columns"}
_COL_KEYS = {"role", "action", "type", "widths", "length", "hierarchy"}
_HEX = re.compile(r"^[0-9a-fA-F]{32,}$")


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    role: Role
    action: str = "drop"                    # role id: "drop" | "pseudonymize"
    gen: Optional[Mapping[str, Any]] = None  # role qi: generalizer settings


@dataclass(frozen=True)
class Config:
    columns: Mapping[str, ColumnSpec]
    k: int = 5
    l: int = 1
    max_suppression: float = 0.05
    shuffle: bool = True            # keep-order is a relaxation, recorded in the report
    shuffle_seed: int = 0
    lang: str = "en"
    max_rows: int = 200_000
    max_evals: int = 20_000
    key: Optional[bytes] = None

    def names(self, role: Role) -> list[str]:
        return [n for n, c in self.columns.items() if c.role is role]


def parse_key(text: str) -> bytes:
    t = text.strip()
    if not _HEX.match(t):
        raise ConfigError("the key must be at least 32 hexadecimal characters (see 'sieve-crowd keygen')")
    return bytes.fromhex(t if len(t) % 2 == 0 else t[:-1])


def parse_config(obj: Mapping[str, Any], **overrides: Any) -> Config:
    if not isinstance(obj, Mapping):
        raise ConfigError("the configuration must be a JSON object")
    obj = {k: v for k, v in obj.items() if not str(k).startswith("_")}
    unknown = set(obj) - _TOP_KEYS
    if unknown:
        raise ConfigError(f"unknown configuration key(s): {', '.join(sorted(unknown))}")
    cols_raw = obj.get("columns")
    if not isinstance(cols_raw, Mapping) or not cols_raw:
        raise ConfigError("'columns' must list every column of the table with a role")

    columns: dict[str, ColumnSpec] = {}
    for name, spec in cols_raw.items():
        if not isinstance(spec, Mapping):
            raise ConfigError(f"column {name!r}: expected an object")
        spec = {k: v for k, v in spec.items() if not str(k).startswith("_")}
        extra = set(spec) - _COL_KEYS
        if extra:
            raise ConfigError(f"column {name!r}: unknown key(s): {', '.join(sorted(extra))}")
        role_text = spec.get("role")
        if role_text == "?" or role_text is None:
            raise ConfigError(f"column {name!r} has no role yet (choose id, qi, sensitive, keep or drop)")
        try:
            role = Role(role_text)
        except ValueError:
            raise ConfigError(f"column {name!r}: unknown role {role_text!r}") from None
        action, gen = "drop", None
        if role is Role.ID:
            action = spec.get("action", "drop")
            if action not in ("drop", "pseudonymize"):
                raise ConfigError(f"column {name!r}: action must be 'drop' or 'pseudonymize'")
        if role is Role.QI:
            gen = {k: v for k, v in spec.items() if k not in ("role", "action")}
            make_generalizer(gen)  # validate now
        columns[name] = ColumnSpec(name, role, action, gen)

    def pick(key: str, default: Any) -> Any:
        v = overrides.get(key)
        return obj.get(key, default) if v is None else v

    k = pick("k", 5)
    l = pick("l", 1)
    ms = pick("max_suppression", 0.05)
    if not isinstance(k, int) or isinstance(k, bool) or k < 2:
        raise ConfigError("k must be an integer >= 2")
    if not isinstance(l, int) or isinstance(l, bool) or l < 1:
        raise ConfigError("l must be an integer >= 1")
    if not isinstance(ms, (int, float)) or isinstance(ms, bool) or not 0 <= ms < 1:
        raise ConfigError("max_suppression must be a number in [0, 1)")

    cfg = Config(
        columns=columns, k=k, l=l, max_suppression=float(ms),
        shuffle=overrides.get("shuffle", True),
        shuffle_seed=overrides.get("shuffle_seed", 0),
        lang=overrides.get("lang", "en"),
        max_rows=overrides.get("max_rows", 200_000),
        max_evals=overrides.get("max_evals", 20_000),
        key=overrides.get("key"),
    )
    if not cfg.names(Role.QI):
        raise ConfigError("at least one column needs the role 'qi' (what an outsider could already know)")
    if cfg.l > 1 and not cfg.names(Role.SENSITIVE):
        raise ConfigError("l > 1 needs at least one column with the role 'sensitive'")
    if cfg.lang not in ("en", "ja"):
        raise ConfigError("lang must be 'en' or 'ja'")
    if any(c.role is Role.ID and c.action == "pseudonymize" for c in columns.values()) and cfg.key is None:
        raise ConfigError("pseudonymize needs a key (create one with 'sieve-crowd keygen')")
    for field, value in (("max_rows", cfg.max_rows), ("max_evals", cfg.max_evals)):
        if not isinstance(value, int) or value < 1:
            raise ConfigError(f"{field} must be a positive integer")
    return cfg
