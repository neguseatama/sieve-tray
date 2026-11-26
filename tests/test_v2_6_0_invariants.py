"""Tray 2.6.0 - the invariants (CK-T11).

No test measures wall-clock durations or their ratios: the suite has
no timing comparisons at all (measured on the 2.5.1 tree - the only
``time`` users are two poll deadlines that wait for a thread or a
dialog to finish, with no threshold or ratio), and the new lanes keep
it that way.  A wall-clock comparison would re-introduce the
environment-jitter failures the engine releases had to fix.
"""
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent

# the two known poll deadlines (thread / dialog liveness waits) - the
# only places allowed to read the clock
POLL_FILES = ("test_sanitize_thread_affinity.py", "test_cohort_m2_gui.py")


def test_ck_t11_no_timing_comparisons_in_tests():
    """CK-T11: no performance-clock imports anywhere, and clock reads
    only in the two known poll-deadline files."""
    clock_names = re.compile(r"\b(perf_counter|timeit|monotonic)\b")
    me = Path(__file__).name
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == me:
            continue  # this watcher carries the words in its pattern
        text = path.read_text(encoding="utf-8")
        assert not clock_names.search(text), (
            path.name, "uses a performance clock")
        if "import time" in text or re.search(r"\btime\.\w+", text):
            assert path.name in POLL_FILES, (
                path.name, "reads the clock outside the poll deadlines")


def test_ck_t11_poll_deadlines_carry_no_threshold():
    """CK-T11: the poll deadlines wait for a condition, they never
    compare a measured duration against a threshold or a ratio."""
    for name in POLL_FILES:
        text = (TESTS / name).read_text(encoding="utf-8")
        assert "deadline = time.time()" in text, name
        assert not re.search(r"\bperf_counter\b", text), name
