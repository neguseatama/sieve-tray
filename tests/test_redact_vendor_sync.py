"""Vendored sieve_redact.py must byte-match the pinned upstream release.

The pin below is refreshed only when the vendored copy is intentionally
re-vendored from the published Sieve Redact repository. CI re-checks the
vendored copy against the upstream repository on every push, so silent
drift between the two fails the build and a human reviews the diff
(intentional update vs missed sync).
"""

import hashlib
import pathlib

VENDORED = pathlib.Path(__file__).resolve().parent.parent / "sieve_redact.py"
PINNED_SHA256 = "7c4bf9160c5333f9a2b42ce82520317b2d1860bd4d9f1b9d52be827427dd1621"


def test_vendored_module_matches_pin():
    assert VENDORED.exists(), "vendored sieve_redact.py is missing"
    actual = hashlib.sha256(VENDORED.read_bytes()).hexdigest()
    assert actual == PINNED_SHA256, (
        "vendored sieve_redact.py differs from the pinned upstream copy\n"
        "  pinned : " + PINNED_SHA256 + "\n"
        "  actual : " + actual + "\n"
        "If the upstream update is intentional, re-vendor the file and "
        "refresh the pin; otherwise restore the pinned copy."
    )
