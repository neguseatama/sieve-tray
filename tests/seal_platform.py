"""Shared platform helpers for the Seal test files (the CI #90 fix
round, 2026-11-15).

The Seal tests measure names a disk may refuse to hold: Windows'
forbidden / reserved device names, a case-fold pair on the
case-insensitive defaults of Windows and macOS, an NFC/NFD pair on a
folding or normalizing filesystem, and names that are not valid
UTF-8.  The rule of this round: such names are tested twice - once
through the pure functions with the name list (runs on all three
OSes) and once on disk, where the test first ASKS THE DISK and skips
the lane it cannot hold.

can_create_names() is that ask.  It writes every name into a probe
folder and accepts only when every name comes back as its own entry:
a case-folding or normalizing volume silently merges a pair into one
entry, a reserved device name (CON.txt) writes to the device instead
of the folder, a forbidden character raises, and an invalid-UTF-8
name may raise - all four must read as "no", so the entry-by-entry
comparison is against the exact names asked for.
"""
import os
import shutil

from pathlib import Path


def can_create_names(root: Path, names) -> bool:
    """True only when this disk holds every name as its own entry.

    ``root`` is the folder the probe folder is created UNDER (pass the
    tmp_path root, never the tree under test - the probe must not
    pollute a tree that is about to be measured)."""
    probe = root / "_seal_name_probe"
    try:
        probe.mkdir(exist_ok=True)
        try:
            for n in names:
                (probe / n).write_bytes(b"")
        except (OSError, ValueError):
            return False
        seen = os.listdir(probe)
        return set(seen) == set(names)
    except (OSError, ValueError):
        return False
    finally:
        shutil.rmtree(probe, ignore_errors=True)
