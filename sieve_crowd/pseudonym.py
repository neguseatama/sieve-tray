"""Keyed pseudonyms: HMAC-SHA256(key, column NUL value), 80 bits, base32.

Same key => same pseudonym (records stay linkable across releases made with that key).
Without the key the mapping cannot be recomputed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import unicodedata


def pseudonym(key: bytes, column: str, value: str) -> str:
    if value == "":
        return ""
    msg = (column + "\0" + unicodedata.normalize("NFC", value).strip()).encode("utf-8")
    digest = hmac.new(key, msg, hashlib.sha256).digest()[:10]
    return "p-" + base64.b32encode(digest).decode("ascii").lower()
