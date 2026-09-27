from pathlib import Path

from sieve_tray import ScanResult, run_scan
from sieve_tray_storage import Storage

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
