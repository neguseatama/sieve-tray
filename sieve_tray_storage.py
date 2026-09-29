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
                " flagged_doc_count, pair_count, text_pair_count, result_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    str(input_dir),
                    len(result.groups),
                    len(result.doc_results),
                    flagged,
                    len(result.code_pairs),
                    len(result.text_pairs),
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
                "flagged_doc_count, pair_count, text_pair_count FROM runs "
                "ORDER BY id DESC LIMIT ?",
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
