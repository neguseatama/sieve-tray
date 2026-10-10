from pathlib import Path

from sieve_tray import ScanResult, run_scan
from sieve_tray_storage import Storage
import unittest

FIXTURES = Path(__file__).parent / "fixtures"


def make_storage(tmp_path) -> Storage:
    return Storage(db_path=tmp_path / "history.db")


def test_settings_roundtrip(tmp_path):
    storage = make_storage(tmp_path)
    assert storage.get_setting("export_dir") == str(Path.home())  # default
    storage.set_setting("export_dir", "/tmp/example")
    assert storage.get_setting("export_dir") == "/tmp/example"

    # overwrite works (ON CONFLICT ... DO UPDATE)
    storage.set_setting("export_dir", "/tmp/other")
    assert storage.get_setting("export_dir") == "/tmp/other"


def test_save_and_load_run_roundtrip(tmp_path):
    storage = make_storage(tmp_path)
    result = run_scan(FIXTURES)

    run_id = storage.save_run(FIXTURES, result)
    assert isinstance(run_id, int)

    runs = storage.list_runs()
    assert len(runs) == 1
    assert runs[0].id == run_id
    assert runs[0].input_dir == str(FIXTURES)
    assert runs[0].doc_count == len(result.doc_results)
    assert runs[0].pair_count == len(result.code_pairs)

    loaded = storage.load_run(run_id)
    assert isinstance(loaded, ScanResult)
    assert loaded.doc_results == result.doc_results
    assert loaded.code_pairs == result.code_pairs
    assert [name for name, _ in loaded.groups] == [name for name, _ in result.groups]


def test_load_missing_run_returns_none(tmp_path):
    storage = make_storage(tmp_path)
    assert storage.load_run(999) is None


def test_delete_run(tmp_path):
    storage = make_storage(tmp_path)
    result = run_scan(FIXTURES)
    run_id = storage.save_run(FIXTURES, result)

    storage.delete_run(run_id)
    assert storage.load_run(run_id) is None
    assert storage.list_runs() == []


def test_history_retention_prunes_oldest(tmp_path):
    storage = make_storage(tmp_path)
    storage.set_setting("history_retention", "2")
    result = run_scan(FIXTURES)

    id1 = storage.save_run(FIXTURES, result)
    id2 = storage.save_run(FIXTURES, result)
    id3 = storage.save_run(FIXTURES, result)

    remaining_ids = {r.id for r in storage.list_runs()}
    assert remaining_ids == {id2, id3}
    assert id1 not in remaining_ids


def test_history_retention_zero_means_unlimited(tmp_path):
    storage = make_storage(tmp_path)
    storage.set_setting("history_retention", "0")
    result = run_scan(FIXTURES)

    for _ in range(5):
        storage.save_run(FIXTURES, result)

    assert len(storage.list_runs()) == 5


class TestSanitizations(unittest.TestCase):
    """Sanitize run history: save / load / prune (separate table,
    ScanResult schema untouched)."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from sieve_tray_storage import Storage
        tmp = tempfile.TemporaryDirectory()
        self._tmp = tmp
        self.storage = Storage(Path(tmp.name) / "history.db")
        self.addCleanup(tmp.cleanup)

    def test_save_and_load_sanitization(self):
        summary = {"n_files": 5, "ok_count": 4, "masked_total": 7,
                   "integrity_bad_count": 1, "failed": [],
                   "skipped": False}
        from pathlib import Path
        sid = self.storage.save_sanitization(
            summary, Path("/data/submissions"),
            Path("/data/rules.cfg"), Path("/export/submissions_sanitized"))
        rows = self.storage.load_sanitizations(limit=10)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["n_files"], 5)
        self.assertEqual(row["ok_count"], 4)
        self.assertEqual(row["masked_total"], 7)
        self.assertEqual(row["integrity_bad_count"], 1)
        self.assertFalse(row["skipped"])
        self.assertEqual(row["input_dir"], "/data/submissions")
        self.assertEqual(row["out_root"], "/export/submissions_sanitized")

    def test_load_empty(self):
        rows = self.storage.load_sanitizations(limit=10)
        self.assertEqual(rows, [])

    def test_load_limit_orders_newest_first(self):
        from pathlib import Path
        for i in range(3):
            self.storage.save_sanitization(
                {"n_files": i, "ok_count": 0, "masked_total": 0,
                 "integrity_bad_count": 0, "failed": [], "skipped": False},
                Path("/d%d" % i), Path("/r.cfg"), Path("/o%d" % i))
        rows = self.storage.load_sanitizations(limit=2)
        self.assertEqual(len(rows), 2)

    def test_prune_sanitizations(self):
        from pathlib import Path
        self.storage.set_setting("history_retention", "2")
        for i in range(4):
            self.storage.save_sanitization(
                {"n_files": 0, "ok_count": 0, "masked_total": 0,
                 "integrity_bad_count": 0, "failed": [], "skipped": False},
                Path("/d%d" % i), Path("/r.cfg"), Path("/o%d" % i))
        # retention 2: only the newest 2 sanitizations remain
        self.storage.prune_history()
        rows = self.storage.load_sanitizations(limit=10)
        self.assertLessEqual(len(rows), 2)
