"""SQLite database for tracking bot actions, queues, leases, and quotas."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from typing import Any

from bot.utils.clock import utc_now, utc_now_iso


class BotDatabase:
    def __init__(self, db_path: str = "reddit_bot.db"):
        self.conn = sqlite3.connect(db_path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self.conn.execute("PRAGMA foreign_keys = ON")
        # WAL lets readers proceed while a writer holds the DB; needed for multi-agent
        # / UI / worker concurrency. synchronous=NORMAL is the usual pairing with WAL:
        # durable across app crashes; a power-loss window is acceptable for this DB.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                account TEXT NOT NULL,
                action TEXT NOT NULL,
                link TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 1,
                error_message TEXT,
                screenshot_path TEXT
            );

            CREATE TABLE IF NOT EXISTS account_stats (
                account TEXT NOT NULL,
                action_date TEXT NOT NULL,
                action_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (account, action_date)
            );

            CREATE INDEX IF NOT EXISTS idx_action_log_account
                ON action_log(account);
            CREATE INDEX IF NOT EXISTS idx_action_log_link
                ON action_log(account, action, link);

            CREATE TABLE IF NOT EXISTS agent_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                priority INTEGER NOT NULL DEFAULT 100,
                account TEXT NOT NULL,
                action TEXT NOT NULL,
                link TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL,
                dedupe_key TEXT,
                scheduled_for TEXT,
                locked_by TEXT,
                locked_until TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                last_error TEXT,
                result_json TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_queue_active_dedupe
                ON agent_queue(dedupe_key)
                WHERE dedupe_key IS NOT NULL
                  AND status IN ('queued', 'running');
            CREATE INDEX IF NOT EXISTS idx_agent_queue_status
                ON agent_queue(status, priority, scheduled_for, id);

            CREATE TABLE IF NOT EXISTS agent_leases (
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                acquired_by TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (resource_type, resource_id)
            );

            CREATE TABLE IF NOT EXISTS account_limits (
                account TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT '*',
                daily_action_quota INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (account, action)
            );

            CREATE TABLE IF NOT EXISTS account_action_reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                reserved_until TEXT NOT NULL,
                reservation_date TEXT NOT NULL,
                account TEXT NOT NULL,
                action TEXT NOT NULL,
                link TEXT NOT NULL DEFAULT '',
                job_id INTEGER,
                status TEXT NOT NULL DEFAULT 'reserved',
                quota INTEGER NOT NULL,
                message TEXT,
                FOREIGN KEY(job_id) REFERENCES agent_queue(id)
            );

            CREATE INDEX IF NOT EXISTS idx_account_action_reservations_quota
                ON account_action_reservations(
                    account, reservation_date, status, reserved_until
                );

            CREATE TABLE IF NOT EXISTS schedule_registry (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                source TEXT NOT NULL,
                rrule TEXT,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                account TEXT,
                profile TEXT,
                action_class TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                next_run_at TEXT,
                last_run_at TEXT,
                locked_by TEXT,
                locked_until TEXT,
                last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS chrome_profile_accounts (
                profile_name TEXT PRIMARY KEY,
                reddit_username TEXT NOT NULL UNIQUE,
                profile_path TEXT,
                debug_address TEXT,
                account_label TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );
        """)
        self._ensure_column("schedule_registry", "next_run_at", "TEXT")
        self._ensure_column("schedule_registry", "last_run_at", "TEXT")
        self._ensure_column("schedule_registry", "locked_by", "TEXT")
        self._ensure_column("schedule_registry", "locked_until", "TEXT")
        self._ensure_column("schedule_registry", "last_error", "TEXT")
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        cursor = self.conn.execute(f"PRAGMA table_info({table})")
        columns = {row["name"] for row in cursor.fetchall()}
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _now() -> datetime:
        return utc_now()

    @classmethod
    def _now_iso(cls) -> str:
        return utc_now_iso()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return dict(row)

    @staticmethod
    def _json_payload(value: Any) -> str:
        if is_dataclass(value):
            value = asdict(value)
        return json.dumps(value, sort_keys=True)

    def log_action(
        self,
        account: str,
        action: str,
        link: str,
        success: bool = True,
        error_message: str | None = None,
        screenshot_path: str | None = None,
    ) -> None:
        """Log an action to the database."""
        now = utc_now_iso()
        self.conn.execute(
            """INSERT INTO action_log
               (timestamp, account, action, link, success, error_message, screenshot_path)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (now, account, action, link, int(success), error_message, screenshot_path),
        )

        # Update daily stats
        today = date.today().isoformat()
        self.conn.execute(
            """INSERT INTO account_stats (account, action_date, action_count)
               VALUES (?, ?, 1)
               ON CONFLICT(account, action_date) DO UPDATE
               SET action_count = action_count + 1""",
            (account, today),
        )
        self.conn.commit()

    def was_action_performed(self, account: str, action: str, link: str) -> bool:
        """Check if an action was already successfully performed."""
        cursor = self.conn.execute(
            """SELECT 1 FROM action_log
               WHERE account = ? AND action = ? AND link = ? AND success = 1
               LIMIT 1""",
            (account, action, link),
        )
        return cursor.fetchone() is not None

    def get_daily_action_count(self, account: str) -> int:
        """Get the number of actions performed today by an account."""
        today = date.today().isoformat()
        cursor = self.conn.execute(
            "SELECT action_count FROM account_stats WHERE account = ? AND action_date = ?",
            (account, today),
        )
        row = cursor.fetchone()
        return row["action_count"] if row else 0

    def get_action_summary(self) -> list[dict]:
        """Get a summary of all actions grouped by account and success status."""
        cursor = self.conn.execute(
            """SELECT account, action,
                      SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as succeeded,
                      SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed
               FROM action_log
               GROUP BY account, action
               ORDER BY account, action"""
        )
        return [dict(row) for row in cursor.fetchall()]

    # ─── Agent queue ────────────────────────────────────────────

    def enqueue_action(
        self,
        account: str,
        action: str,
        payload: dict[str, Any] | Any,
        *,
        link: str = "",
        priority: int = 100,
        dedupe_key: str | None = None,
        scheduled_for: str | None = None,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        """Queue an action and return the queued or pre-existing active job."""
        now = self._now_iso()
        self.recover_stale_queue_jobs(now_iso=now)
        payload_json = self._json_payload(payload)
        if dedupe_key is None:
            dedupe_key = f"{account}:{action}:{link}:{payload_json}"

        try:
            cursor = self.conn.execute(
                """INSERT INTO agent_queue
                   (created_at, updated_at, status, priority, account, action, link,
                    payload_json, dedupe_key, scheduled_for, max_attempts)
                   VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    now,
                    now,
                    priority,
                    account,
                    action,
                    link,
                    payload_json,
                    dedupe_key,
                    scheduled_for,
                    max_attempts,
                ),
            )
            self.conn.commit()
            return self.get_queue_job(cursor.lastrowid) or {}
        except sqlite3.IntegrityError:
            cursor = self.conn.execute(
                """SELECT * FROM agent_queue
                   WHERE dedupe_key = ?
                     AND status IN ('queued', 'running')
                   ORDER BY id
                   LIMIT 1""",
                (dedupe_key,),
            )
            return self._row_to_dict(cursor.fetchone()) or {}

    def get_queue_job(self, job_id: int) -> dict[str, Any] | None:
        cursor = self.conn.execute("SELECT * FROM agent_queue WHERE id = ?", (job_id,))
        return self._row_to_dict(cursor.fetchone())

    def list_queue_jobs(
        self,
        *,
        status: str | None = None,
        account: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM agent_queue"
        params: list[Any] = []
        clauses: list[str] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if account:
            clauses.append("account = ?")
            params.append(account)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_queue_counts(self) -> dict[str, int]:
        cursor = self.conn.execute("SELECT status, COUNT(*) AS count FROM agent_queue GROUP BY status")
        return {row["status"]: row["count"] for row in cursor.fetchall()}

    def recover_stale_queue_jobs(
        self,
        *,
        now_iso: str | None = None,
    ) -> list[dict[str, Any]]:
        """Release running queue jobs whose lease expired."""
        now_iso = now_iso or self._now_iso()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.conn.execute(
                """SELECT * FROM agent_queue
                   WHERE status = 'running'
                     AND locked_until IS NOT NULL
                     AND locked_until <= ?
                   ORDER BY id ASC""",
                (now_iso,),
            )
            stale_rows = [dict(row) for row in cursor.fetchall()]
            recovered: list[dict[str, Any]] = []
            for row in stale_rows:
                exhausted = row["attempts"] >= row["max_attempts"]
                new_status = "failed" if exhausted else "queued"
                message = (
                    "Queue job lease expired before completion; max attempts exhausted."
                    if exhausted
                    else "Queue job lease expired before completion; released for retry."
                )
                self.conn.execute(
                    """UPDATE agent_queue
                       SET status = ?,
                           updated_at = ?,
                           locked_by = NULL,
                           locked_until = NULL,
                           last_error = ?
                       WHERE id = ?""",
                    (new_status, now_iso, message, row["id"]),
                )
                recovered.append(
                    {
                        "id": row["id"],
                        "previousStatus": row["status"],
                        "status": new_status,
                        "account": row["account"],
                        "action": row["action"],
                        "link": row["link"],
                        "attempts": row["attempts"],
                        "maxAttempts": row["max_attempts"],
                        "lockedBy": row["locked_by"],
                        "lockedUntil": row["locked_until"],
                        "message": message,
                    }
                )
            self.conn.commit()
            return recovered
        except Exception:
            self.conn.rollback()
            raise

    def lease_next_job(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 600,
    ) -> dict[str, Any] | None:
        """Atomically lease the next due queue job for a worker."""
        now = self._now()
        now_iso = now.isoformat()
        locked_until = (now + timedelta(seconds=lease_seconds)).isoformat()

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                """UPDATE agent_queue
                   SET status = CASE
                           WHEN attempts >= max_attempts THEN 'failed'
                           ELSE 'queued'
                       END,
                       updated_at = ?,
                       locked_by = NULL,
                       locked_until = NULL,
                       last_error = CASE
                           WHEN attempts >= max_attempts
                               THEN 'Queue job lease expired before completion; max attempts exhausted.'
                           ELSE 'Queue job lease expired before completion; released for retry.'
                       END
                   WHERE status = 'running'
                     AND locked_until IS NOT NULL
                     AND locked_until <= ?""",
                (now_iso, now_iso),
            )
            cursor = self.conn.execute(
                """SELECT * FROM agent_queue
                   WHERE status = 'queued'
                     AND (scheduled_for IS NULL OR scheduled_for <= ?)
                   ORDER BY priority ASC, id ASC
                   LIMIT 1""",
                (now_iso,),
            )
            row = cursor.fetchone()
            if row is None:
                self.conn.commit()
                return None

            self.conn.execute(
                """UPDATE agent_queue
                   SET status = 'running',
                       updated_at = ?,
                       locked_by = ?,
                       locked_until = ?,
                       attempts = attempts + 1
                   WHERE id = ?""",
                (now_iso, worker_id, locked_until, row["id"]),
            )
            self.conn.commit()
            return self.get_queue_job(row["id"])
        except Exception:
            self.conn.rollback()
            raise

    def complete_queue_job(
        self,
        job_id: int,
        *,
        success: bool,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Mark a queue job complete."""
        now = self._now_iso()
        status = "succeeded" if success else "failed"
        self.conn.execute(
            """UPDATE agent_queue
               SET status = ?,
                   updated_at = ?,
                   locked_by = NULL,
                   locked_until = NULL,
                   last_error = ?,
                   result_json = ?
               WHERE id = ?""",
            (
                status,
                now,
                error,
                self._json_payload(result or {}),
                job_id,
            ),
        )
        self.conn.commit()

    def release_queue_job(self, job_id: int, error: str) -> None:
        """Return a failed leased job to the queue when attempts remain."""
        now = self._now_iso()
        self.conn.execute(
            """UPDATE agent_queue
               SET status = CASE
                       WHEN attempts >= max_attempts THEN 'failed'
                       ELSE 'queued'
                   END,
                   updated_at = ?,
                   locked_by = NULL,
                   locked_until = NULL,
                   last_error = ?
               WHERE id = ?""",
            (now, error, job_id),
        )
        self.conn.commit()

    def retry_queue_job(self, job_id: int) -> dict[str, Any]:
        """Re-queue a terminally failed queue job for one more worker attempt."""
        now = self._now_iso()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.conn.execute("SELECT * FROM agent_queue WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            if row is None:
                self.conn.commit()
                return {
                    "id": job_id,
                    "retried": False,
                    "message": f"Queue job {job_id} was not found.",
                }

            job = dict(row)
            if job["status"] != "failed":
                self.conn.commit()
                job["retried"] = False
                job["message"] = f"Queue job {job_id} is {job['status']}; only failed jobs can be retried."
                return job

            if job.get("dedupe_key"):
                duplicate = self.conn.execute(
                    """SELECT id FROM agent_queue
                       WHERE dedupe_key = ?
                         AND status IN ('queued', 'running')
                         AND id != ?
                       LIMIT 1""",
                    (job["dedupe_key"], job_id),
                ).fetchone()
                if duplicate is not None:
                    self.conn.commit()
                    job["retried"] = False
                    job["message"] = f"An active duplicate job already exists for this request (job {duplicate['id']})."
                    return job

            max_attempts = job["max_attempts"]
            if job["attempts"] >= job["max_attempts"]:
                max_attempts = job["attempts"] + 1

            self.conn.execute(
                """UPDATE agent_queue
                   SET status = 'queued',
                       updated_at = ?,
                       locked_by = NULL,
                       locked_until = NULL,
                       last_error = NULL,
                       max_attempts = ?
                   WHERE id = ?""",
                (now, max_attempts, job_id),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        updated = self.get_queue_job(job_id) or {"id": job_id}
        updated["retried"] = True
        updated["message"] = f"Queue job {job_id} was re-queued."
        return updated

    def retry_failed_jobs(self, account: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id FROM agent_queue WHERE status = 'failed'"
        params: list[Any] = []
        if account:
            query += " AND account = ?"
            params.append(account)
        query += " ORDER BY id"
        rows = self.conn.execute(query, params).fetchall()
        return [self.retry_queue_job(row["id"]) for row in rows]

    # ─── Account limits and atomic quota reservations ────────────

    def set_account_limit(
        self,
        account: str,
        daily_action_quota: int,
        *,
        action: str = "*",
    ) -> None:
        now = self._now_iso()
        self.conn.execute(
            """INSERT INTO account_limits
               (account, action, daily_action_quota, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(account, action) DO UPDATE
               SET daily_action_quota = excluded.daily_action_quota,
                   updated_at = excluded.updated_at""",
            (account, action, daily_action_quota, now),
        )
        self.conn.commit()

    def list_account_limits(self) -> list[dict[str, Any]]:
        cursor = self.conn.execute("SELECT * FROM account_limits ORDER BY account, action")
        return [dict(row) for row in cursor.fetchall()]

    def get_account_limit(self, account: str, action: str = "*") -> int | None:
        cursor = self.conn.execute(
            """SELECT daily_action_quota FROM account_limits
               WHERE account = ? AND action IN (?, '*')
               ORDER BY CASE WHEN action = ? THEN 0 ELSE 1 END
               LIMIT 1""",
            (account, action, action),
        )
        row = cursor.fetchone()
        return row["daily_action_quota"] if row else None

    def reserve_account_action(
        self,
        account: str,
        action: str,
        link: str,
        *,
        daily_quota: int | None = None,
        job_id: int | None = None,
        ttl_seconds: int = 3600,
    ) -> tuple[bool, str, int | None]:
        """Atomically reserve one daily action slot for an account."""
        if daily_quota is None:
            daily_quota = self.get_account_limit(account, action)
        if daily_quota is None or daily_quota <= 0:
            return True, "No daily quota configured.", None

        now = self._now()
        now_iso = now.isoformat()
        today = date.today().isoformat()
        reserved_until = (now + timedelta(seconds=ttl_seconds)).isoformat()

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                """UPDATE account_action_reservations
                   SET status = 'expired',
                       updated_at = ?,
                       message = 'Reservation expired before completion.'
                   WHERE status = 'reserved'
                     AND reserved_until < ?""",
                (now_iso, now_iso),
            )

            logged_cursor = self.conn.execute(
                """SELECT action_count FROM account_stats
                   WHERE account = ? AND action_date = ?""",
                (account, today),
            )
            logged_row = logged_cursor.fetchone()
            logged_count = logged_row["action_count"] if logged_row else 0

            reserved_cursor = self.conn.execute(
                """SELECT COUNT(*) AS reserved_count
                   FROM account_action_reservations
                   WHERE account = ?
                     AND reservation_date = ?
                     AND status = 'reserved'
                     AND reserved_until >= ?""",
                (account, today, now_iso),
            )
            reserved_count = reserved_cursor.fetchone()["reserved_count"]
            if logged_count + reserved_count >= daily_quota:
                self.conn.commit()
                return (
                    False,
                    f"Daily quota ({daily_quota}) reached for {account}",
                    None,
                )

            cursor = self.conn.execute(
                """INSERT INTO account_action_reservations
                   (created_at, updated_at, reserved_until, reservation_date,
                    account, action, link, job_id, status, quota)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?)""",
                (
                    now_iso,
                    now_iso,
                    reserved_until,
                    today,
                    account,
                    action,
                    link,
                    job_id,
                    daily_quota,
                ),
            )
            self.conn.commit()
            return True, "Reserved daily quota slot.", cursor.lastrowid
        except Exception:
            self.conn.rollback()
            raise

    def finish_account_action_reservation(
        self,
        reservation_id: int | None,
        *,
        success: bool,
        message: str = "",
    ) -> None:
        if reservation_id is None:
            return
        now = self._now_iso()
        status = "succeeded" if success else "failed"
        self.conn.execute(
            """UPDATE account_action_reservations
               SET status = ?,
                   updated_at = ?,
                   message = ?
               WHERE id = ?""",
            (status, now, message, reservation_id),
        )
        self.conn.commit()

    def list_account_reservations(
        self,
        *,
        account: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM account_action_reservations"
        params: list[Any] = []
        if account:
            query += " WHERE account = ?"
            params.append(account)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_daily_action_history(
        self,
        *,
        account: str | None = None,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        days = max(1, int(days))
        end = date.today()
        start = end - timedelta(days=days - 1)
        query = """SELECT action_date, SUM(action_count) AS action_count
                   FROM account_stats
                   WHERE action_date >= ? AND action_date <= ?"""
        params: list[Any] = [start.isoformat(), end.isoformat()]
        if account:
            query += " AND account = ?"
            params.append(account)
        query += " GROUP BY action_date"
        rows = {row["action_date"]: row["action_count"] for row in self.conn.execute(query, params).fetchall()}
        return [
            {
                "action_date": (start + timedelta(days=offset)).isoformat(),
                "action_count": int(rows.get((start + timedelta(days=offset)).isoformat(), 0)),
            }
            for offset in range(days)
        ]

    def get_action_history(
        self,
        *,
        account: str | None = None,
        result: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM action_log"
        params: list[Any] = []
        clauses: list[str] = []
        if account:
            clauses.append("account = ?")
            params.append(account)
        if result == "success":
            clauses.append("success = 1")
        elif result == "fail":
            clauses.append("(success = 0 OR error_message IS NOT NULL)")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    # ─── Resource leases ────────────────────────────────────────

    def acquire_lease(
        self,
        resource_type: str,
        resource_id: str,
        owner: str,
        *,
        ttl_seconds: int = 600,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        now = self._now()
        now_iso = now.isoformat()
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.conn.execute(
                """SELECT * FROM agent_leases
                   WHERE resource_type = ? AND resource_id = ?""",
                (resource_type, resource_id),
            )
            row = cursor.fetchone()
            if row and row["expires_at"] >= now_iso and row["acquired_by"] != owner:
                self.conn.commit()
                return (
                    False,
                    f"{resource_type}:{resource_id} is leased by {row['acquired_by']} until {row['expires_at']}",
                )

            self.conn.execute(
                """INSERT INTO agent_leases
                   (resource_type, resource_id, acquired_by, acquired_at, expires_at,
                    metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(resource_type, resource_id) DO UPDATE
                   SET acquired_by = excluded.acquired_by,
                       acquired_at = excluded.acquired_at,
                       expires_at = excluded.expires_at,
                       metadata_json = excluded.metadata_json""",
                (
                    resource_type,
                    resource_id,
                    owner,
                    now_iso,
                    expires_at,
                    self._json_payload(metadata or {}),
                ),
            )
            self.conn.commit()
            return True, f"Lease acquired until {expires_at}"
        except Exception:
            self.conn.rollback()
            raise

    def release_lease(
        self,
        resource_type: str,
        resource_id: str,
        owner: str | None = None,
    ) -> bool:
        params: list[Any] = [resource_type, resource_id]
        query = "DELETE FROM agent_leases WHERE resource_type = ? AND resource_id = ?"
        if owner:
            query += " AND acquired_by = ?"
            params.append(owner)
        cursor = self.conn.execute(query, params)
        self.conn.commit()
        return cursor.rowcount > 0

    def list_leases(self, *, include_expired: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM agent_leases"
        params: list[Any] = []
        if not include_expired:
            query += " WHERE expires_at >= ?"
            params.append(self._now_iso())
        query += " ORDER BY resource_type, resource_id"
        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    # ─── Schedules ──────────────────────────────────────────────

    def register_schedule(
        self,
        schedule_id: str,
        name: str,
        *,
        source: str,
        rrule: str | None = None,
        status: str = "ACTIVE",
        account: str | None = None,
        profile: str | None = None,
        action_class: str | None = None,
        metadata: dict[str, Any] | None = None,
        next_run_at: str | None = None,
    ) -> None:
        now = self._now_iso()
        self.conn.execute(
            """INSERT INTO schedule_registry
               (id, name, source, rrule, status, account, profile, action_class,
                metadata_json, updated_at, next_run_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE
               SET name = excluded.name,
                   source = excluded.source,
                   rrule = excluded.rrule,
                   status = excluded.status,
                   account = excluded.account,
                   profile = excluded.profile,
                   action_class = excluded.action_class,
                   metadata_json = excluded.metadata_json,
                   updated_at = excluded.updated_at,
                   next_run_at = COALESCE(excluded.next_run_at, schedule_registry.next_run_at)""",
            (
                schedule_id,
                name,
                source,
                rrule,
                status,
                account,
                profile,
                action_class,
                self._json_payload(metadata or {}),
                now,
                next_run_at,
            ),
        )
        self.conn.commit()

    def list_registered_schedules(self) -> list[dict[str, Any]]:
        cursor = self.conn.execute("SELECT * FROM schedule_registry ORDER BY source, name")
        return [dict(row) for row in cursor.fetchall()]

    def lease_due_schedules(
        self,
        worker_id: str,
        *,
        now_iso: str | None = None,
        lease_seconds: int = 600,
        limit: int = 1,
        schedule_id: str | None = None,
    ) -> list[dict[str, Any]]:
        now = datetime.fromisoformat(now_iso) if now_iso else self._now()
        now_iso = now.isoformat()
        locked_until = (now + timedelta(seconds=lease_seconds)).isoformat()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            params: list[Any] = [now_iso, now_iso]
            id_filter = ""
            if schedule_id:
                id_filter = " AND id = ?"
                params.append(schedule_id)
            params.append(limit)
            cursor = self.conn.execute(
                f"""SELECT * FROM schedule_registry
                   WHERE status = 'ACTIVE'
                     AND next_run_at IS NOT NULL
                     AND next_run_at <= ?
                     AND (locked_until IS NULL OR locked_until <= ?)
                     {id_filter}
                   ORDER BY next_run_at ASC, id ASC
                   LIMIT ?""",
                params,
            )
            rows = cursor.fetchall()
            for row in rows:
                self.conn.execute(
                    """UPDATE schedule_registry
                       SET locked_by = ?,
                           locked_until = ?,
                           updated_at = ?
                       WHERE id = ?""",
                    (worker_id, locked_until, now_iso, row["id"]),
                )
            self.conn.commit()
            return [dict(row) for row in rows]
        except Exception:
            self.conn.rollback()
            raise

    def complete_schedule_run(
        self,
        schedule_id: str,
        *,
        next_run_at: str | None,
        last_run_at: str | None,
        error: str | None = None,
        deactivate: bool = False,
    ) -> None:
        now = self._now_iso()
        status_expr = "PAUSED" if deactivate else "ACTIVE"
        self.conn.execute(
            """UPDATE schedule_registry
               SET status = ?,
                   next_run_at = ?,
                   last_run_at = COALESCE(?, last_run_at),
                   locked_by = NULL,
                   locked_until = NULL,
                   last_error = ?,
                   updated_at = ?
               WHERE id = ?""",
            (status_expr, next_run_at, last_run_at, error, now, schedule_id),
        )
        self.conn.commit()

    def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        cursor = self.conn.execute(
            "SELECT * FROM schedule_registry WHERE id = ?",
            (schedule_id,),
        )
        return self._row_to_dict(cursor.fetchone())

    def set_schedule_status(self, schedule_id: str, status: str) -> dict[str, Any]:
        normalized = status.strip().upper()
        if normalized not in {"ACTIVE", "PAUSED"}:
            raise ValueError("Schedule status must be ACTIVE or PAUSED.")

        now = self._now_iso()
        cursor = self.conn.execute(
            """UPDATE schedule_registry
               SET status = ?,
                   updated_at = ?,
                   locked_by = NULL,
                   locked_until = NULL
               WHERE id = ?""",
            (normalized, now, schedule_id),
        )
        self.conn.commit()
        schedule = self.get_schedule(schedule_id) or {"id": schedule_id, "status": normalized}
        schedule["changed"] = cursor.rowcount > 0
        schedule["message"] = (
            f"Schedule {schedule_id} set to {normalized}." if cursor.rowcount > 0 else f"Schedule {schedule_id} was not found."
        )
        return schedule

    def delete_schedule(self, schedule_id: str) -> dict[str, Any]:
        existing = self.get_schedule(schedule_id)
        cursor = self.conn.execute(
            "DELETE FROM schedule_registry WHERE id = ?",
            (schedule_id,),
        )
        self.conn.commit()
        schedule = existing or {"id": schedule_id}
        schedule["deleted"] = cursor.rowcount > 0
        schedule["message"] = f"Schedule {schedule_id} deleted." if cursor.rowcount > 0 else f"Schedule {schedule_id} was not found."
        return schedule

    # ─── Chrome profile account associations ────────────────────

    @staticmethod
    def normalize_reddit_username(username: str) -> str:
        value = username.strip()
        if value.lower().startswith("u/"):
            value = value[2:]
        return value

    def associate_chrome_profile(
        self,
        profile_name: str,
        reddit_username: str,
        *,
        profile_path: str | None = None,
        debug_address: str | None = None,
        account_label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist the Reddit account that belongs to a saved Chrome profile."""
        normalized_username = self.normalize_reddit_username(reddit_username)
        resolved_label = account_label or normalized_username
        now = self._now_iso()
        self.conn.execute(
            """INSERT INTO chrome_profile_accounts
               (profile_name, reddit_username, profile_path, debug_address,
                account_label, metadata_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(profile_name) DO UPDATE
               SET reddit_username = excluded.reddit_username,
                   profile_path = excluded.profile_path,
                   debug_address = excluded.debug_address,
                   account_label = excluded.account_label,
                   metadata_json = excluded.metadata_json,
                   updated_at = excluded.updated_at""",
            (
                profile_name,
                normalized_username,
                profile_path,
                debug_address,
                resolved_label,
                self._json_payload(metadata or {}),
                now,
            ),
        )
        self.conn.commit()
        return self.get_chrome_profile_association(profile_name=profile_name) or {}

    def get_chrome_profile_association(
        self,
        *,
        profile_name: str | None = None,
        reddit_username: str | None = None,
        account_label: str | None = None,
    ) -> dict[str, Any] | None:
        clauses = []
        params: list[Any] = []
        if profile_name:
            clauses.append("profile_name = ?")
            params.append(profile_name)
        if reddit_username:
            clauses.append("reddit_username = ?")
            params.append(self.normalize_reddit_username(reddit_username))
        if account_label:
            clauses.append("account_label = ?")
            params.append(account_label)
        if not clauses:
            raise ValueError("Provide profile_name, reddit_username, or account_label.")

        cursor = self.conn.execute(
            f"""SELECT * FROM chrome_profile_accounts
                WHERE {" OR ".join(clauses)}
                ORDER BY profile_name
                LIMIT 1""",
            params,
        )
        return self._row_to_dict(cursor.fetchone())

    def list_chrome_profile_associations(self) -> list[dict[str, Any]]:
        cursor = self.conn.execute("SELECT * FROM chrome_profile_accounts ORDER BY profile_name")
        return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        self.conn.close()
