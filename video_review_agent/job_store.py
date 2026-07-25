"""SQLite-backed storage for service review jobs."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StoredReviewJob:
    job_id: str
    thread_id: str
    status: str
    request_payload: dict[str, Any]
    plan: dict[str, Any]
    result: dict[str, Any]
    error: str | None
    created_at: str
    updated_at: str


class SQLiteJobStore:
    """Persist job snapshots so service status survives process restarts."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_jobs (
                    job_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_review_jobs_thread_id
                ON review_jobs(thread_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_review_jobs_status
                ON review_jobs(status)
                """
            )

    def save_job(
        self,
        *,
        job_id: str,
        thread_id: str,
        status: str,
        request_payload: dict[str, Any],
        plan: dict[str, Any],
        result: dict[str, Any],
        error: str | None,
        created_at: str,
        updated_at: str,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO review_jobs (
                    job_id,
                    thread_id,
                    status,
                    request_json,
                    plan_json,
                    result_json,
                    error,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    thread_id = excluded.thread_id,
                    status = excluded.status,
                    request_json = excluded.request_json,
                    plan_json = excluded.plan_json,
                    result_json = excluded.result_json,
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (
                    job_id,
                    thread_id,
                    status,
                    json.dumps(request_payload, ensure_ascii=False),
                    json.dumps(plan, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    error,
                    created_at,
                    updated_at,
                ),
            )

    def get_job(self, job_id: str) -> StoredReviewJob | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    job_id,
                    thread_id,
                    status,
                    request_json,
                    plan_json,
                    result_json,
                    error,
                    created_at,
                    updated_at
                FROM review_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()

        if row is None:
            return None

        return StoredReviewJob(
            job_id=row["job_id"],
            thread_id=row["thread_id"],
            status=row["status"],
            request_payload=json.loads(row["request_json"] or "{}"),
            plan=json.loads(row["plan_json"] or "{}"),
            result=json.loads(row["result_json"] or "{}"),
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_jobs(self, limit: int = 50) -> list[StoredReviewJob]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    job_id,
                    thread_id,
                    status,
                    request_json,
                    plan_json,
                    result_json,
                    error,
                    created_at,
                    updated_at
                FROM review_jobs
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            StoredReviewJob(
                job_id=row["job_id"],
                thread_id=row["thread_id"],
                status=row["status"],
                request_payload=json.loads(row["request_json"] or "{}"),
                plan=json.loads(row["plan_json"] or "{}"),
                result=json.loads(row["result_json"] or "{}"),
                error=row["error"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]
