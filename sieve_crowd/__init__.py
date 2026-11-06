"""Sieve Crowd: make every record one of a crowd, and measure it.

Deterministic, offline, zero-dependency k-anonymity (with optional l-diversity)
for CSV, JSON and XML tables.
"""

__version__ = "0.9.0"

from .config import Config, parse_config, parse_key  # noqa: E402
from .engine import Result, anonymize, inspect_table, plan_table  # noqa: E402
from .model import ConfigError, InputError, Role  # noqa: E402

__all__ = [
    "__version__", "anonymize", "inspect_table", "plan_table", "Result", "Config", "parse_config",
    "parse_key", "ConfigError", "InputError", "Role",
]
