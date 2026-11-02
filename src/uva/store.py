"""本机 SQLite：Job 队列、审计事件、去重桶、IMS 幂等。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from uva.contract import Job, utc_now
from uva.settings import Settings, load_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  media_path TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL,
  claimed_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id);

CREATE TABLE IF NOT EXISTS results (
  job_id TEXT PRIMARY KEY,
  run_id TEXT,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  run_id TEXT,
  job_id TEXT,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, id);

CREATE TABLE IF NOT EXISTS dedup (
  bucket TEXT PRIMARY KEY,
  last_ts REAL NOT NULL,
  last_job_id TEXT,
  last_alert_type TEXT
);

CREATE TABLE IF NOT EXISTS ims_pushes (
  idempotency_key TEXT PRIMARY KEY,
  run_id TEXT,
  job_id TEXT,
  status TEXT NOT NULL,
  response_json TEXT,
  created_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def enqueue(self, job: Job) -> Job:
        payload = job.dumps()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO jobs
            (job_id, run_id, source_type, media_path, captured_at, payload_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.run_id,
                job.source_type,
                job.media_path,
                job.captured_at,
                payload,
                job.status,
                job.created_at,
            ),
        )
        self._conn.commit()
        return job

    def claim_next(self) -> Job | None:
        cur = self._conn.execute(
            "SELECT * FROM jobs WHERE status IN ('queued', 'ims_retry') ORDER BY created_at LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return None
        now = utc_now()
        cur = self._conn.execute(
            "UPDATE jobs SET status='running', claimed_at=? WHERE job_id=? AND status IN ('queued', 'ims_retry')",
            (now, row["job_id"]),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            return None
        job = Job.from_json(row["payload_json"])
        job.status = "running"
        return job

    def set_status(self, job_id: str, status: str) -> None:
        self._conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))
        self._conn.commit()

    def requeue_stuck(self, statuses: tuple[str, ...] = ("running",)) -> int:
        placeholders = ",".join("?" * len(statuses))
        cur = self._conn.execute(
            f"UPDATE jobs SET status='queued' WHERE status IN ({placeholders})",
            statuses,
        )
        self._conn.commit()
        return cur.rowcount

    def save_result(self, job_id: str, run_id: str | None, result: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO results (job_id, run_id, result_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (job_id, run_id, json.dumps(result, ensure_ascii=False), utc_now()),
        )
        self._conn.commit()

    def add_event(self, kind: str, *, run_id: str | None = None, job_id: str | None = None, payload: dict[str, Any] | None = None) -> None:
        self._conn.execute(
            "INSERT INTO events (ts, run_id, job_id, kind, payload_json) VALUES (?, ?, ?, ?, ?)",
            (utc_now(), run_id, job_id, kind, json.dumps(payload or {}, ensure_ascii=False)),
        )
        self._conn.commit()

    def get_dedup(self, bucket: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM dedup WHERE bucket=?", (bucket,)).fetchone()
        return dict(row) if row else None

    def touch_dedup(self, bucket: str, ts: float, job_id: str, alert_type: str | None) -> None:
        self._conn.execute(
            """
            INSERT INTO dedup (bucket, last_ts, last_job_id, last_alert_type)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(bucket) DO UPDATE SET
              last_ts=excluded.last_ts,
              last_job_id=excluded.last_job_id,
              last_alert_type=excluded.last_alert_type
            """,
            (bucket, ts, job_id, alert_type),
        )
        self._conn.commit()

    def has_ims_key(self, key: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM ims_pushes WHERE idempotency_key=? AND status='ok'",
            (key,),
        ).fetchone()
        return row is not None

    def save_ims_push(self, key: str, run_id: str | None, job_id: str | None, status: str, response: Any) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO ims_pushes
            (idempotency_key, run_id, job_id, status, response_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (key, run_id, job_id, status, json.dumps(response, ensure_ascii=False, default=str), utc_now()),
        )
        self._conn.commit()

    def list_recent_ims_pushes(self, limit: int = 5) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT created_at, status, run_id, job_id, idempotency_key
            FROM ims_pushes
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_jobs(self, run_id: str) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM jobs WHERE run_id=?", (run_id,)).fetchone()
        return int(row[0]) if row else 0

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT run_id,
                   MIN(created_at) AS started_at,
                   COUNT(*) AS job_count,
                   SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done_count,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count
            FROM jobs
            GROUP BY run_id
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_jobs(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT job_id, source_type, status, captured_at, media_path FROM jobs WHERE run_id=? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_audit_rows(self, run_id: str | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT j.job_id, j.run_id, j.source_type, j.status, j.captured_at, j.created_at,
                   j.media_path, j.payload_json, r.result_json
            FROM jobs j
            LEFT JOIN results r ON r.job_id = j.job_id
        """
        params: list[Any] = []
        if run_id:
            sql += " WHERE j.run_id=?"
            params.append(run_id)
        sql += " ORDER BY j.created_at"
        out = []
        for row in self._conn.execute(sql, params).fetchall():
            item = dict(row)
            payload = item.pop("payload_json")
            result_json = item.pop("result_json")
            try:
                item["job"] = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                item["job"] = {}
            try:
                item["result"] = json.loads(result_json) if result_json else None
            except json.JSONDecodeError:
                item["result"] = None
            out.append(item)
        return out

    def list_events(self, run_id: str, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, ts, job_id, kind, payload_json FROM events WHERE run_id=? ORDER BY id LIMIT ?",
            (run_id, limit),
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["payload"] = json.loads(item.pop("payload_json"))
            except json.JSONDecodeError:
                item["payload"] = item.pop("payload_json")
            out.append(item)
        return out

    def get_result(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT result_json FROM results WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return json.loads(row["result_json"])

    def get_job(self, job_id: str) -> Job | None:
        row = self._conn.execute(
            "SELECT payload_json, status FROM jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        job = Job.from_json(row["payload_json"])
        job.status = row["status"]
        return job

    def purge_all(self) -> dict[str, int]:
        """删除队列、识别结果、审计事件、去重与 IMS/飞流幂等记录（测试重置用）。"""
        counts: dict[str, int] = {}
        for table in ("events", "results", "ims_pushes", "dedup", "jobs"):
            row = self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            counts[table] = int(row["n"]) if row else 0
            self._conn.execute(f"DELETE FROM {table}")
        self._conn.commit()
        self._conn.execute("VACUUM")
        self._conn.commit()
        return counts


def open_store(settings: Settings | None = None) -> Store:
    settings = settings or load_settings()
    return Store(settings.db_path)
