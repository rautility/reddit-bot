"""SQLite database for tracking bot actions and preventing duplicates."""

from __future__ import annotations

import sqlite3
from datetime import datetime, date
from typing import Optional


class BotDatabase:
    def __init__(self, db_path: str = "reddit_bot.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
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
        """)
        self.conn.commit()

    def log_action(
        self,
        account: str,
        action: str,
        link: str,
        success: bool = True,
        error_message: Optional[str] = None,
        screenshot_path: Optional[str] = None,
    ) -> None:
        """Log an action to the database."""
        now = datetime.utcnow().isoformat()
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

    def close(self) -> None:
        self.conn.close()
