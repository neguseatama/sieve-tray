from __future__ import annotations

import enum


class ConfigError(ValueError):
    """The configuration is invalid. Messages name columns, never cell values."""


class InputError(ValueError):
    """The input file cannot be read as a table."""


class Role(enum.Enum):
    ID = "id"                # direct identifier: removed or pseudonymized
    QI = "qi"                # quasi-identifier: generalized until the crowd is big enough
    SENSITIVE = "sensitive"  # kept as is; its diversity inside every crowd can be required
    KEEP = "keep"            # kept as is, outside the crowd model
    DROP = "drop"            # removed
