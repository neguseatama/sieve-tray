from __future__ import annotations

import enum


class ConfigError(ValueError):
    """The configuration is invalid. Messages name columns, never cell values."""


class InputError(ValueError):
    """The input file cannot be read as a table."""


# The closed set of refusal codes (v0.9.0).  An error message carries the
# code only -- never cell values, file content or paths (design 2-5/2-6).
REFUSAL_CODES = frozenset({
    "not_regular_file",      # FIFO, device, directory, ...
    "file_too_large",        # beyond max_file_bytes
    "too_many_entries",      # zip entries beyond max_entries
    "part_too_large",        # one expanded part beyond max_part_bytes
    "total_too_large",       # expanded parts, summed, beyond max_total_bytes
    "too_many_elements",     # '<' bytes per XML part beyond max_elements
    "doctype_not_allowed",   # <!DOCTYPE or <!ENTITY in an XML part
    "unsupported_encoding",  # neither UTF-8 nor CP932 (auto), or a non-UTF-8
                             # XML declaration / UTF-16 BOM inside a part
    "duplicate_part",        # same (case-insensitive) part name twice
    "encrypted",             # encrypted flag on a part we would read
    "malformed_xml",         # a read part is not well-formed
    "main_part_missing",     # xl/workbook.xml absent
    "unsupported_namespace", # a spreadsheetml part outside the transitional
                             # namespace (e.g. Strict OOXML)
    "unsupported_format",    # .xls/.xlsm/other containers, unconvertible
                             # date serials
})


class InputRefused(InputError):
    """The input is refused (fail-closed, v0.9.0).

    Exits 1, writes nothing, and the message is the code only.  It is an
    InputError subclass so existing handling keeps working, but the CLI
    catches it first: refusals are I/O (exit 1), ordinary input errors
    stay usage (exit 2).
    """

    def __init__(self, code: str):
        if code not in REFUSAL_CODES:
            raise ValueError(f"unknown refusal code: {code!r}")
        super().__init__(code)
        self.code = code


class Role(enum.Enum):
    ID = "id"                # direct identifier: removed or pseudonymized
    QI = "qi"                # quasi-identifier: generalized until the crowd is big enough
    SENSITIVE = "sensitive"  # kept as is; its diversity inside every crowd can be required
    KEEP = "keep"            # kept as is, outside the crowd model
    DROP = "drop"            # removed
