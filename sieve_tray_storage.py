"""
sieve_tray_storage.py - local history & settings persistence.

Deliberately kept independent of Qt so it can be unit tested without
a GUI, and depends only on sqlite3 (stdlib) + ScanResult's
to_dict()/from_dict() from sieve_tray.py.

Data lives in a single file: ~/.sieve_tray/history.db
"""

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from sieve_tray import ScanResult, classify_observation

DEFAULT_DB_PATH = Path.home() / ".sieve_tray" / "history.db"


def _posix_path_str(p) -> str:
    """Canonical POSIX-slash form of a path string (cohort-m2, run #84).

    The sanitize history rows are pinned cross-OS ('/b/in', never a
    backslash form): WindowsPath's str() carries backslashes, so every
    path entering the history is normalized at the storage boundary -
    the same canonical form the report molds use (sieve_tray._posix).
    Identity on POSIX."""
    return str(p).replace(os.sep, "/")


# v1.1.0 (design doc §3.7): the crowd payload is stored as an allowlist, not a
# denylist. Measured basis (v1.0.0): the receipt never contains cell values
# (sieve_crowd/report.py), and the fields below are exactly those the GUI
# history table and the report display. Table data (header / rows), report_json,
# io, ok, before/after_alone, k_requested and config_path are not displayed
# anywhere and stay out of the payload.
CROWD_PAYLOAD_ALLOWLIST = frozenset({
    "input_path", "output_path",
    "records_in", "records_out", "suppressed",
    "k_achieved", "max_risk", "avg_risk",
    "status", "reason",
    "report_text",
})

# v1.1.0: one-time settings flag for the payload scrub migration (§3.7 (2)).
_CROWD_SCRUB_FLAG = "crowd_payload_scrub_v1_1_0"

# v2.1.0 (M2 Cohort, request §3.7): the cohort_runs allowlist - the same
# discipline as gate_runs.  Counts, the receipt digest and the engine
# versions only; no paths, file names, bodies or fragments are ever
# stored.  The flagged pairs are listed inside the receipt (kept by the
# caller), never here.
COHORT_RUN_ALLOWLIST = frozenset({
    "run_id", "ts_utc", "items", "compared", "not_compared",
    "pairs_flagged", "removed_total", "receipt_digest", "engines",
})

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
            # v2.0.0 (M1 Gate): a dedicated Gate history table with its
            # own allowlist - counts, receipt digest, engine versions.
            # No paths, file names, bodies or fragments are ever stored
            # here (request doc §3.6); existing tables stay untouched.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gate_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    items_total INTEGER NOT NULL,
                    produced INTEGER NOT NULL,
                    np_needs_settings INTEGER NOT NULL,
                    np_unobserved INTEGER NOT NULL,
                    np_not_applicable INTEGER NOT NULL,
                    np_engine_unavailable INTEGER NOT NULL,
                    np_engine_refused INTEGER NOT NULL,
                    np_write_failed INTEGER NOT NULL,
                    status_flagged INTEGER NOT NULL,
                    status_clean INTEGER NOT NULL,
                    status_unobserved INTEGER NOT NULL,
                    receipt_digest TEXT NOT NULL,
                    engines_version TEXT NOT NULL
                )
                """
            )
            # v2.1.0 (M2 Cohort): a dedicated Cohort history table with
            # its own allowlist (COHORT_RUN_ALLOWLIST) - counts, the
            # receipt digest and the engine versions.  No paths, bodies
            # or fragments (request doc §3.7); existing tables stay
            # untouched.  Optional counts stay nullable so partial
            # records can never break the insert.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cohort_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    items INTEGER,
                    compared INTEGER,
                    not_compared INTEGER,
                    pairs_flagged INTEGER,
                    removed_total INTEGER,
                    receipt_digest TEXT,
                    engines TEXT
                )
                """
            )
            # v1.1.0 (design doc §3.7 (2)): scrub legacy crowd payloads once.
            # Never breaks history: a failure leaves the flag unset and the
            # scrub is retried on the next start. load_crowd_runs sanitizes
            # on read regardless ((1)), so old records are safe either way.
            try:
                self._scrub_crowd_payloads(conn)
            except Exception:
                pass

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
        result = ScanResult.from_dict(json.loads(row[0]))
        # v1.1.0 (design doc §3.5): records saved before the third state carry
        # no status keys - derive them on read. Undeterminable records
        # become unobserved/parse_failed, never silently clean.
        for d in result.doc_results:
            if "status" not in d:
                status, reason, detail = classify_observation(d)
                d["status"] = status
                d["unobserved_reason"] = reason
                d["unobserved_detail"] = detail
        return result

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
                 _posix_path_str(input_dir), _posix_path_str(config_path),
                 _posix_path_str(out_root),
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
                 json.dumps(self._allowlisted(summary),
                            ensure_ascii=False, sort_keys=True)))
            row_id = cur.lastrowid
        self.prune_crowd_runs()
        return row_id

    @staticmethod
    def _allowlisted(summary: dict) -> dict:
        """v1.1.0: keep only the allowlisted keys of a crowd summary."""
        return {k: v for k, v in summary.items()
                if k in CROWD_PAYLOAD_ALLOWLIST}

    # ------------------------------------------------------------------
    # v2.0.0 (M1 Gate): the gate_runs allowlist table
    # ------------------------------------------------------------------

    def record_gate_run(self, run_id: str, created_at: str, items_total: int,
                        produced: int, np_needs_settings: int,
                        np_unobserved: int, np_not_applicable: int,
                        np_engine_unavailable: int, np_engine_refused: int,
                        np_write_failed: int, status_flagged: int,
                        status_clean: int, status_unobserved: int,
                        receipt_digest: str, engines_version: str) -> int:
        """Persist one Gate run's allowlisted summary; returns the row id.

        The columns are exactly the allowlist of request doc §3.6 -
        counts, the receipt digest and the engine versions. Paths,
        file names, bodies and fragments are structurally absent.
        """
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO gate_runs (run_id, created_at, items_total,"
                " produced, np_needs_settings, np_unobserved,"
                " np_not_applicable, np_engine_unavailable,"
                " np_engine_refused, np_write_failed, status_flagged,"
                " status_clean, status_unobserved, receipt_digest,"
                " engines_version)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(run_id), str(created_at), int(items_total),
                 int(produced), int(np_needs_settings), int(np_unobserved),
                 int(np_not_applicable), int(np_engine_unavailable),
                 int(np_engine_refused), int(np_write_failed),
                 int(status_flagged), int(status_clean),
                 int(status_unobserved), str(receipt_digest),
                 str(engines_version)))
            row_id = cur.lastrowid
        return row_id

    def load_gate_runs(self, limit: int = 20) -> list:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, run_id, created_at, items_total, produced,"
                " np_needs_settings, np_unobserved, np_not_applicable,"
                " np_engine_unavailable, np_engine_refused,"
                " np_write_failed, status_flagged, status_clean,"
                " status_unobserved, receipt_digest, engines_version"
                " FROM gate_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        keys = ["id", "run_id", "created_at", "items_total", "produced",
                "np_needs_settings", "np_unobserved", "np_not_applicable",
                "np_engine_unavailable", "np_engine_refused",
                "np_write_failed", "status_flagged", "status_clean",
                "status_unobserved", "receipt_digest", "engines_version"]
        return [dict(zip(keys, row)) for row in rows]

    # ------------------------------------------------------------------
    # v2.1.0 (M2 Cohort): the cohort_runs allowlist table
    # ------------------------------------------------------------------

    def record_cohort_run(self, record: dict) -> int:
        """Persist one Cohort run's allowlisted summary; returns the row
        id.  Only COHORT_RUN_ALLOWLIST keys are read - any other key of
        the record dict is structurally dropped, so paths, bodies and
        fragments can never reach the table."""
        rec = {k: record.get(k) for k in sorted(COHORT_RUN_ALLOWLIST)}
        for k in ("items", "compared", "not_compared", "pairs_flagged",
                  "removed_total"):
            if rec[k] is not None:
                rec[k] = int(rec[k])
        for k in ("run_id", "ts_utc", "receipt_digest", "engines"):
            if rec[k] is not None:
                rec[k] = str(rec[k])
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO cohort_runs (run_id, ts_utc, items,"
                " compared, not_compared, pairs_flagged, removed_total,"
                " receipt_digest, engines)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (rec["run_id"], rec["ts_utc"], rec["items"],
                 rec["compared"], rec["not_compared"],
                 rec["pairs_flagged"], rec["removed_total"],
                 rec["receipt_digest"], rec["engines"]))
            row_id = cur.lastrowid
        return row_id

    def load_cohort_runs(self, limit: int = 20) -> list:
        """Return stored Cohort run dicts, newest first.  The keys are
        exactly the allowlist (no row id), so the caller sees only what
        the §3.7 discipline allows."""
        keys = ["run_id", "ts_utc", "items", "compared", "not_compared",
                "pairs_flagged", "removed_total", "receipt_digest",
                "engines"]
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT run_id, ts_utc, items, compared, not_compared,"
                " pairs_flagged, removed_total, receipt_digest, engines"
                " FROM cohort_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(zip(keys, row)) for row in rows]

    def _scrub_crowd_payloads(self, conn) -> None:
        """v1.1.0 (design doc §3.7 (2)): remove non-allowlisted keys from every
        stored crowd payload, once. Idempotent: the settings flag marks
        completion and the second run changes nothing. VACUUM keeps the
        removed table data from lingering in free pages. Runs inside the
        caller's connection; a failure propagates to the caller's guard
        so the flag stays unset and the scrub is retried later.
        """
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (_CROWD_SCRUB_FLAG,)).fetchone()
        if row is not None and row[0] == "done":
            return
        rows = conn.execute(
            "SELECT id, payload_json FROM crowd_runs").fetchall()
        changed = False
        for row_id, payload in rows:
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            scrubbed = {k: v for k, v in data.items()
                        if k in CROWD_PAYLOAD_ALLOWLIST}
            if scrubbed != data:
                conn.execute(
                    "UPDATE crowd_runs SET payload_json = ? WHERE id = ?",
                    (json.dumps(scrubbed, ensure_ascii=False, sort_keys=True),
                     row_id))
                changed = True
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, 'done')"
            " ON CONFLICT(key) DO UPDATE SET value = 'done'",
            (_CROWD_SCRUB_FLAG,))
        conn.commit()
        if changed:
            conn.execute("VACUUM")
            conn.commit()

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
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            # v1.1.0 (design doc §3.7 (1)): sanitize on read - records written
            # before the allowlist never resurface their table data.
            record = {k: v for k, v in data.items()
                      if k in CROWD_PAYLOAD_ALLOWLIST}
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
