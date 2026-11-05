"""crowd_runs history persistence on the Storage class.

save_crowd_run stores one crowd summary dict (the flat dict returned
by the crowd wrappers in sieve_tray.py): scalar metrics as queryable
columns and the full dict as JSON, mirroring the runs table's
result_json pattern. load_crowd_runs returns the stored dicts newest
first with id and timestamp injected. prune_crowd_runs keeps only the
newest rows, returns how many were deleted, and defaults to the
history_retention setting.
"""

import sqlite3

from sieve_tray_storage import Storage


def make_storage(tmp_path) -> Storage:
    return Storage(db_path=tmp_path / "history.db")


def make_summary(**top):
    summary = {
        "ok": True,
        "status": "anonymized",
        "reason": None,
        "header": ["age", "city"],
        "rows": [["30", "Osaka"], ["40", "Kyoto"], ["40", "Kyoto"],
                 ["25", "Nara"]],
        "report_text": "Sieve Crowd report",
        "report_json": '{"status": "anonymized"}',
        "records_in": 5,
        "records_out": 4,
        "suppressed": 1,
        "k_requested": 2,
        "k_achieved": 2,
        "max_risk": 0.5,
        "avg_risk": 0.25,
        "before_alone": 1,
        "after_alone": 0,
        "io": {"input_format": "csv", "output_format": "csv"},
        "input_path": "/tmp/in.csv",
        "output_path": "/tmp/out.csv",
    }
    summary.update(top)
    return summary


def make_refused_summary(**top):
    summary = {
        "ok": False,
        "status": "refused",
        "reason": "infeasible",
        "header": None,
        "rows": None,
        "report_text": "Sieve Crowd receipt: refused",
        "report_json": '{"status": "refused"}',
        "records_in": 3,
        "records_out": None,
        "suppressed": None,
        "k_requested": 5,
        "k_achieved": None,
        "max_risk": None,
        "avg_risk": None,
        "before_alone": 0,
        "after_alone": None,
        "io": {"input_format": "csv", "output_format": None},
        "input_path": "/tmp/in.csv",
        "output_path": None,
    }
    summary.update(top)
    return summary


def test_crowd_save_and_load_roundtrip_preserves_summary(tmp_path):
    storage = make_storage(tmp_path)
    summary = make_summary()
    refused = make_refused_summary()
    ok_id = storage.save_crowd_run(summary)
    refused_id = storage.save_crowd_run(refused)
    assert isinstance(ok_id, int) and isinstance(refused_id, int)

    runs = storage.load_crowd_runs()
    assert len(runs) == 2
    newest, older = runs[0], runs[1]
    assert newest["id"] == refused_id and older["id"] == ok_id
    assert newest["timestamp"].endswith("+00:00")
    assert older["timestamp"].endswith("+00:00")
    # v1.1.0 (TR-T14, design doc §3.7): the payload is an allowlist - the
    # display/report fields survive, the non-display keys (header/rows and
    # the rest) are no longer stored. Changed from the v1.0.0 full-dict
    # roundtrip because keeping table data out of history.db is the
    # purpose of item B.
    from sieve_tray_storage import CROWD_PAYLOAD_ALLOWLIST
    for key in CROWD_PAYLOAD_ALLOWLIST:
        assert newest[key] == refused.get(key)
        assert older[key] == summary.get(key)
    assert "header" not in newest and "rows" not in newest
    assert "header" not in older and "rows" not in older

    conn = sqlite3.connect(tmp_path / "history.db")
    try:
        row = conn.execute(
            "SELECT status, reason, records_in, records_out, suppressed,"
            " k_requested, k_achieved, max_risk, avg_risk, before_alone,"
            " after_alone FROM crowd_runs WHERE id = ?", (refused_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row == ("refused", "infeasible", 3, None, None, 5, None,
                   None, None, 0, None)


def test_crowd_load_runs_orders_newest_first_and_respects_limit(tmp_path):
    storage = make_storage(tmp_path)
    for n in range(1, 6):
        storage.save_crowd_run(make_summary(records_in=n, records_out=n - 1))
    runs = storage.load_crowd_runs()
    assert [r["id"] for r in runs] == [5, 4, 3, 2, 1]
    assert [r["records_in"] for r in runs] == [5, 4, 3, 2, 1]
    assert [r["records_in"] for r in storage.load_crowd_runs(limit=3)] == [5, 4, 3]


def test_crowd_prune_runs_keeps_newest_and_reports_deleted(tmp_path):
    storage = make_storage(tmp_path)
    for n in range(1, 6):
        storage.save_crowd_run(make_summary(records_in=n))
    assert storage.prune_crowd_runs(keep=2) == 3
    assert [r["records_in"] for r in storage.load_crowd_runs()] == [5, 4]
    assert storage.prune_crowd_runs(keep=2) == 0

    storage.set_setting("history_retention", "1")
    storage.save_crowd_run(make_refused_summary(records_in=9))
    assert [r["records_in"] for r in storage.load_crowd_runs()] == [9]


def test_crowd_fresh_storage_starts_empty_and_holds_refused_only_row(tmp_path):
    storage = make_storage(tmp_path)
    assert storage.load_crowd_runs() == []
    assert storage.prune_crowd_runs(keep=5) == 0
    storage.save_crowd_run(make_refused_summary())
    runs = storage.load_crowd_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "refused"
    assert runs[0]["records_out"] is None
    # v1.1.0 (TR-T14): after_alone is not a display/report field and is no
    # longer part of the stored payload.
    assert "after_alone" not in runs[0]
