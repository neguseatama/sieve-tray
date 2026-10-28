"""
sieve_tray_storage.py - local history & settings persistence.

Deliberately kept independent of Qt so it can be unit tested without
a GUI, and depends only on sqlite3 (stdlib) + ScanResult's
to_dict()/from_dict() from sieve_tray.py.

Data lives in a single file: ~/.sieve_tray/history.db
"""

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from sieve_tray import ScanResult

DEFAULT_DB_PATH = Path.home() / ".sieve_tray" / "history.db"

DEFAULT_SETTINGS = {
    "export_dir": str(Path.home()),
    "history_retention": "50",
    "language": "en",
    # v0.8.0: optional override path for the quantifier audit lane's
    # modifier-vocab file. Empty string = use the bundled default
    # (DEFAULT_MODIFIER_VOCAB_PATH in sieve_tray.py).
    "audit_modifier_vocab_path": "",
}


@dataclass
class RunSummary:
    id: int
    timestamp: str
    input_dir: str
    groups_count: int
    doc_count: int
    flagged_doc_count: int
    pair_count: int
    text_pair_count: int = 0
    audit_count: int = 0  # v0.8.0: quantifier audit flagged sentences


class Storage:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    input_dir TEXT NOT NULL,
                    groups_count INTEGER NOT NULL,
                    doc_count INTEGER NOT NULL,
                    flagged_doc_count INTEGER NOT NULL,
                    pair_count INTEGER NOT NULL,
                    result_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sanitizations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    input_dir TEXT NOT NULL,
                    config_path TEXT NOT NULL,
                    out_root TEXT NOT NULL,
                    n_files INTEGER NOT NULL,
                    ok_count INTEGER NOT NULL,
                    masked_total INTEGER NOT NULL,
                    integrity_bad_count INTEGER NOT NULL,
                    skipped INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            # Migration for DBs created before Sieve-Referee support
            # (Phase 4): add the text_pair_count column if it's missing.
            # A fresh CREATE TABLE above already lacks it too, so this
            # single ALTER covers both old and brand-new databases.
            cols = [row[1] for row in
                    conn.execute("PRAGMA table_info(runs)").fetchall()]
            if "text_pair_count" not in cols:
                conn.execute(
                    "ALTER TABLE runs ADD COLUMN "
                    "text_pair_count INTEGER NOT NULL DEFAULT 0"
                )
            # v0.8.0: audit_count column for the quantifier audit lane.
            # Same forward-compatible ALTER pattern as text_pair_count.
            if "audit_count" not in cols:
                conn.execute(
                    "ALTER TABLE runs ADD COLUMN "
                    "audit_count INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crowd_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    records_in INTEGER NOT NULL,
                    records_out INTEGER,
                    suppressed INTEGER,
                    k_requested INTEGER,
                    k_achieved INTEGER,
                    max_risk REAL,
                    avg_risk REAL,
                    before_alone INTEGER,
                    after_alone INTEGER,
                    payload_json TEXT NOT NULL
                )
                """
            )

    # ------------------------------------------------------------------
    # settings
    # ------------------------------------------------------------------

    def get_setting(self, key: str) -> str:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        if row is not None:
            return row[0]
        return DEFAULT_SETTINGS.get(key, "")

    def set_setting(self, key: str, value: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ------------------------------------------------------------------
    # runs (history)
    # ------------------------------------------------------------------

    def save_run(self, input_dir: Path, result: ScanResult) -> int:
        flagged = sum(1 for r in result.doc_results if r.get("flagged"))
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO runs "
                "(timestamp, input_dir, groups_count, doc_count, "
                " flagged_doc_count, pair_count, text_pair_count, "
                " audit_count, result_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    str(input_dir),
                    len(result.groups),
                    len(result.doc_results),
                    flagged,
                    len(result.code_pairs),
                    len(result.text_pairs),
                    len(result.audit_results),
                    json.dumps(result.to_dict()),
                ),
            )
            run_id = cur.lastrowid
        self.prune_history()
        return run_id

    def list_runs(self, limit: int = 200) -> List[RunSummary]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, timestamp, input_dir, groups_count, doc_count, "
                "flagged_doc_count, pair_count, text_pair_count, audit_count "
                "FROM runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [RunSummary(*row) for row in rows]

    def load_run(self, run_id: int) -> Optional[ScanResult]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT result_json FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return ScanResult.from_dict(json.loads(row[0]))

    def delete_run(self, run_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))

    def save_sanitization(self, summary: dict, input_dir,
                          config_path, out_root) -> int:
        """Persist one sanitize run; returns the row id."""
        from datetime import datetime
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO sanitizations (timestamp, input_dir,"
                " config_path, out_root, n_files, ok_count, masked_total,"
                " integrity_bad_count, skipped) VALUES (?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"),
                 str(input_dir), str(config_path), str(out_root),
                 summary.get("n_files", 0), summary.get("ok_count", 0),
                 summary.get("masked_total", 0),
                 summary.get("integrity_bad_count", 0),
                 1 if summary.get("skipped") else 0))
            row_id = cur.lastrowid
        self.prune_history()
        return row_id

    def load_sanitizations(self, limit: int = 20) -> list:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, timestamp, input_dir, config_path, out_root,"
                " n_files, ok_count, masked_total, integrity_bad_count,"
                " skipped FROM sanitizations"
                " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "timestamp": r[1], "input_dir": r[2],
                 "config_path": r[3], "out_root": r[4], "n_files": r[5],
                 "ok_count": r[6], "masked_total": r[7],
                 "integrity_bad_count": r[8], "skipped": bool(r[9])}
                for r in rows]

    def prune_history(self) -> None:
        """Keep only the newest N runs, where N = history_retention setting.

        Called automatically after every save_run(), and can also be
        called after the user changes the retention setting so the
        effect is immediate rather than waiting for the next scan.
        """
        try:
            retention = int(self.get_setting("history_retention"))
        except ValueError:
            retention = int(DEFAULT_SETTINGS["history_retention"])
        if retention <= 0:
            return
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "DELETE FROM runs WHERE id NOT IN "
                "(SELECT id FROM runs ORDER BY id DESC LIMIT ?)",
                (retention,),
            )
            conn.execute(
                "DELETE FROM sanitizations WHERE id NOT IN "
                "(SELECT id FROM sanitizations ORDER BY id DESC LIMIT ?)",
                (retention,),
            )

    def clear_runs(self) -> int:
        """Delete all scan history rows; returns the number of rows deleted.

        v0.9.0: exposed for the GUI's 'Clear history' button on the
        History tab. Does not touch the sanitizations table.
        """
        with closing(self._connect()) as conn, conn:
            cur = conn.execute("DELETE FROM runs")
            return cur.rowcount

    def clear_sanitizations(self) -> int:
        """Delete all sanitize history rows; returns the number of rows
        deleted.

        v0.9.0: exposed for the GUI's 'Clear history' button on the
        Sanitize History tab. Does not touch the runs table.
        """
        with closing(self._connect()) as conn, conn:
            cur = conn.execute("DELETE FROM sanitizations")
            return cur.rowcount

    def save_crowd_run(self, summary: dict) -> int:
        """Persist one crowd run summary dict; returns the row id.

        summary is the flat dict returned by the crowd wrappers in
        sieve_tray.py. Scalar metrics go into queryable columns and
        the whole dict into payload_json, mirroring the runs table's
        result_json pattern. Auto-prunes with the history_retention
        setting, like save_run() does.
        """
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO crowd_runs (timestamp, status, reason,"
                " records_in, records_out, suppressed, k_requested,"
                " k_achieved, max_risk, avg_risk, before_alone,"
                " after_alone, payload_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 str(summary.get("status", "")),
                 summary.get("reason"),
                 int(summary.get("records_in") or 0),
                 summary.get("records_out"),
                 summary.get("suppressed"),
                 summary.get("k_requested"),
                 summary.get("k_achieved"),
                 summary.get("max_risk"),
                 summary.get("avg_risk"),
                 summary.get("before_alone"),
                 summary.get("after_alone"),
                 json.dumps(summary, ensure_ascii=False, sort_keys=True)))
            row_id = cur.lastrowid
        self.prune_crowd_runs()
        return row_id

    def load_crowd_runs(self, limit: int = 20) -> list:
        """Return stored crowd run dicts, newest first.

        Each record is the original summary dict with id and timestamp
        injected, so the GUI can render the receipt straight from it.
        """
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, timestamp, payload_json FROM crowd_runs"
                " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        records = []
        for row_id, timestamp, payload in rows:
            record = json.loads(payload)
            record["id"] = row_id
            record["timestamp"] = timestamp
            records.append(record)
        return records

    def prune_crowd_runs(self, keep: Optional[int] = None) -> int:
        """Keep only the newest keep rows; returns the deleted count.

        keep defaults to the history_retention setting, matching
        prune_history(); keep <= 0 disables pruning and returns 0.
        """
        if keep is None:
            try:
                keep = int(self.get_setting("history_retention"))
            except ValueError:
                keep = int(DEFAULT_SETTINGS["history_retention"])
        if keep <= 0:
            return 0
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "DELETE FROM crowd_runs WHERE id NOT IN "
                "(SELECT id FROM crowd_runs ORDER BY id DESC LIMIT ?)",
                (keep,))
            return cur.rowcount
