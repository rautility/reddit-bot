"""Localhost-only web dashboard API and static file server."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import mimetypes
import re
import sys
import uuid
from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from bot import agentctl, tool_cli
from bot.action_schema import describe_actions, validate_action_fields
from bot.control.schedules import parse_dtstart as _parse_dtstart
from bot.control.schedules import parse_rrule_text as _parse_rrule_text
from bot.control.schedules import slugify
from bot.database import BotDatabase
from bot.utils.clock import utc_now

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATIC_DIR = REPO_ROOT / "web"
DEFAULT_ACTIONS_DIR = REPO_ROOT / ".agent-actions"
POST_ACTION_FIELDS = (
    "link",
    "comment",
    "title",
    "subreddit",
    "body",
    "flair",
    "recipient",
    "message",
    "query",
)
WEEKDAY_LABELS = {
    "MO": "Mon",
    "TU": "Tue",
    "WE": "Wed",
    "TH": "Thu",
    "FR": "Fri",
    "SA": "Sat",
    "SU": "Sun",
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return value


def human_cadence(rrule_text: str) -> str:
    parts = _parse_rrule_text(rrule_text)
    freq = parts.get("FREQ", "").upper()
    hour = parts.get("BYHOUR")
    minute = parts.get("BYMINUTE")
    if parts.get("COUNT") == "1":
        dtstart = _parse_dtstart(parts.get("DTSTART", ""))
        if dtstart:
            return f"One-time on {dtstart.strftime('%Y-%m-%d at %H:%M')}"
        return "One-time"
    if freq == "DAILY" and hour is not None:
        return f"Daily at {int(hour):02d}:{int(minute or 0):02d}"
    if freq == "WEEKLY":
        days = [WEEKDAY_LABELS.get(day, day) for day in parts.get("BYDAY", "").split(",") if day]
        day_text = ", ".join(days) if days else "scheduled days"
        if hour is not None:
            return f"Weekly on {day_text} at {int(hour):02d}:{int(minute or 0):02d}"
        return f"Weekly on {day_text}"
    return rrule_text or "No cadence"


def _identity_args(identity: dict[str, Any], *, schedule: bool = False) -> list[str]:
    if identity.get("account_label"):
        return ["--account" if schedule else "--account-label", str(identity["account_label"])]
    if identity.get("profile_name"):
        return ["--profile-name", str(identity["profile_name"])]
    if identity.get("reddit_user"):
        return ["--reddit-user", str(identity["reddit_user"])]
    return []


def _run_cli(
    main_func: Callable[[list[str]], int],
    argv: list[str],
) -> tuple[int, Any, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main_func(argv)
    except SystemExit as exc:
        exit_code = int(exc.code or 0) if isinstance(exc.code, int) else 1
    raw = stdout.getvalue().strip()
    if not raw:
        return exit_code, {}, stderr.getvalue().strip()
    try:
        return exit_code, json.loads(raw), stderr.getvalue().strip()
    except json.JSONDecodeError:
        return exit_code, {"raw": raw}, stderr.getvalue().strip()


def _build_schedule_rule(timing: dict[str, Any]) -> tuple[str, str]:
    mode = str(timing.get("mode") or "now")
    if mode == "once":
        raw_at = str(timing.get("at") or "").strip()
        if not raw_at:
            raise ValueError("One-time tasks require timing.at.")
        at = datetime.fromisoformat(raw_at.replace("Z", "+00:00")).replace(tzinfo=None)
        return f"DTSTART:{at.strftime('%Y%m%dT%H%M%S')}\nRRULE:FREQ=DAILY;COUNT=1", at.isoformat()
    if mode == "daily":
        daily_at = str(timing.get("dailyAt") or timing.get("time") or "").strip()
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", daily_at)
        if not match:
            raise ValueError("Daily tasks require timing.dailyAt as HH:MM.")
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            raise ValueError("Daily time must be a valid HH:MM value.")
        return f"FREQ=DAILY;BYHOUR={hour};BYMINUTE={minute}", str(timing.get("nextRunAt") or "")
    if mode == "weekly":
        weekdays = [str(day).upper() for day in (timing.get("weekdays") or []) if str(day).upper() in WEEKDAY_LABELS]
        if not weekdays:
            raise ValueError("Weekly tasks require at least one weekday.")
        raw_time = str(timing.get("time") or "").strip()
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", raw_time)
        if not match:
            raise ValueError("Weekly tasks require timing.time as HH:MM.")
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            raise ValueError("Weekly time must be a valid HH:MM value.")
        return (
            f"FREQ=WEEKLY;BYDAY={','.join(weekdays)};BYHOUR={hour};BYMINUTE={minute}",
            str(timing.get("nextRunAt") or ""),
        )
    if mode == "rrule":
        rrule = str(timing.get("rrule") or "").strip()
        if not rrule:
            raise ValueError("Advanced RRULE tasks require timing.rrule.")
        return rrule, str(timing.get("nextRunAt") or "")
    raise ValueError(f"Unsupported timing mode for scheduled task: {mode}")


class RedditUIHandler(BaseHTTPRequestHandler):
    db_path = "reddit_bot.db"
    static_dir = DEFAULT_STATIC_DIR
    actions_dir = DEFAULT_ACTIONS_DIR

    server_version = "reddit-bot-ui/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        super().log_message(format, *args)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api_get(parsed.path, parse_qs(parsed.query))
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        if not parsed.path.startswith("/api/"):
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found."})
            return
        try:
            body = self._read_json_body()
            self._handle_api_post(parsed.path, parse_qs(parsed.query), body)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def _open_db(self) -> BotDatabase:
        return BotDatabase(str(self.db_path))

    def _agentctl(self, command: list[str]) -> dict[str, Any]:
        exit_code, payload, stderr = _run_cli(
            agentctl.main,
            ["--db-path", str(self.db_path), *command],
        )
        return {
            "ok": exit_code == 0,
            "exitCode": exit_code,
            "data": payload,
            "error": None
            if exit_code == 0
            else (stderr or (payload.get("error") if isinstance(payload, dict) else None) or "Command failed."),
        }

    def _tool(self, command: list[str]) -> dict[str, Any]:
        exit_code, payload, stderr = _run_cli(
            tool_cli.main,
            ["--db-path", str(self.db_path), "--json", *command],
        )
        ok = exit_code == 0 and (not isinstance(payload, dict) or payload.get("ok", True) is not False)
        return {
            "ok": ok,
            "exitCode": exit_code,
            "data": payload,
            "error": None if ok else (stderr or (payload.get("error") if isinstance(payload, dict) else None) or "Command failed."),
        }

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, default=_jsonable).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be valid JSON.") from exc
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    def _account(self, query: dict[str, list[str]]) -> str | None:
        value = (query.get("account") or [""])[0]
        if not value or value == "all":
            return None
        return value

    def _int_query(
        self,
        query: dict[str, list[str]],
        name: str,
        default: int,
        *,
        maximum: int = 500,
    ) -> int:
        raw = (query.get(name) or [str(default)])[0]
        try:
            return max(1, min(maximum, int(raw)))
        except ValueError:
            return default

    def _handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        account = self._account(query)
        if path == "/api/profiles":
            self._send_json(HTTPStatus.OK, self._agentctl(["profiles", "list"]))
            return
        if path == "/api/overview":
            self._send_json(HTTPStatus.OK, {"ok": True, "data": self._overview(account)})
            return
        if path == "/api/schedules":
            self._send_json(HTTPStatus.OK, {"ok": True, "data": self._schedules(account)})
            return
        if path == "/api/queue":
            status = (query.get("status") or [""])[0] or None
            limit = self._int_query(query, "limit", 100)
            db = self._open_db()
            try:
                data = {
                    "jobs": db.list_queue_jobs(status=status, account=account, limit=limit),
                    "queueCounts": self._queue_counts(db, account),
                }
            finally:
                db.close()
            self._send_json(HTTPStatus.OK, {"ok": True, "data": data})
            return
        if path == "/api/history":
            result = (query.get("result") or [""])[0] or None
            limit = self._int_query(query, "limit", 100)
            db = self._open_db()
            try:
                data = {"history": db.get_action_history(account=account, result=result, limit=limit)}
            finally:
                db.close()
            self._send_json(HTTPStatus.OK, {"ok": True, "data": data})
            return
        if path == "/api/daily":
            days = self._int_query(query, "days", 30, maximum=120)
            self._send_json(HTTPStatus.OK, {"ok": True, "data": self._daily(account, days)})
            return
        if path == "/api/errors":
            limit = self._int_query(query, "limit", 50)
            self._send_json(HTTPStatus.OK, {"ok": True, "data": self._errors(account, limit)})
            return
        if path == "/api/capabilities":
            self._send_json(HTTPStatus.OK, {"ok": True, "data": describe_actions()})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown API endpoint."})

    def _handle_api_post(
        self,
        path: str,
        query: dict[str, list[str]],
        body: dict[str, Any],
    ) -> None:
        retry_match = re.fullmatch(r"/api/queue/(\d+)/retry", path)
        if retry_match:
            payload = self._agentctl(["queue", "retry", "--id", retry_match.group(1)])
            self._send_json(HTTPStatus.OK, payload)
            return
        schedule_match = re.fullmatch(r"/api/schedules/([^/]+)/(pause|resume|delete)", path)
        if schedule_match:
            schedule_id = unquote(schedule_match.group(1))
            action = schedule_match.group(2)
            if action == "delete":
                payload = self._agentctl(["schedules", "delete", "--id", schedule_id])
            else:
                status = "PAUSED" if action == "pause" else "ACTIVE"
                payload = self._agentctl(["schedules", "set-status", "--id", schedule_id, "--status", status])
            self._send_json(HTTPStatus.OK, payload)
            return
        if path == "/api/tasks":
            self._send_json(HTTPStatus.OK, self._create_task(body))
            return
        if path == "/api/queue/retry-failed":
            command = ["queue", "retry", "--all"]
            account = self._account(query)
            if account:
                command.extend(["--account", account])
            self._send_json(HTTPStatus.OK, self._agentctl(command))
            return
        if path == "/api/schedules/run-due":
            command = ["schedules", "run-due", "--run-worker"]
            if body.get("limit"):
                command.extend(["--limit", str(int(body["limit"]))])
            self._send_json(HTTPStatus.OK, self._agentctl(command))
            return
        if path == "/api/limits":
            account = str(body.get("account") or "").strip()
            quota = body.get("daily_action_quota")
            if not account or quota is None:
                raise ValueError("Limits require account and daily_action_quota.")
            payload = self._agentctl(
                [
                    "limits",
                    "set",
                    "--account",
                    account,
                    "--action",
                    str(body.get("action") or "*"),
                    "--daily-action-quota",
                    str(int(quota)),
                ]
            )
            self._send_json(HTTPStatus.OK, payload)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown API endpoint."})

    def _create_task(self, body: dict[str, Any]) -> dict[str, Any]:
        action = str(body.get("action") or "").strip()
        raw_fields = body.get("fields") if isinstance(body.get("fields"), dict) else {}
        fields = {field: raw_fields.get(field) for field in POST_ACTION_FIELDS if raw_fields.get(field) not in (None, "")}
        if action == "human_search" and fields.get("query") and not fields.get("link"):
            fields["link"] = fields["query"]
        field_errors = validate_action_fields(action, fields)
        if field_errors:
            return {
                "ok": False,
                "data": {"fieldErrors": field_errors},
                "error": "Action payload is missing required fields.",
            }

        identity = body.get("identity") or {}
        timing = body.get("timing") or {"mode": "now"}
        mode = str(timing.get("mode") or "now")
        if mode == "now":
            command = ["do", "--action", action]
            for field in POST_ACTION_FIELDS:
                if field in fields:
                    command.extend([f"--{field.replace('_', '-')}", str(fields[field])])
            command.extend(_identity_args(identity))
            return self._tool(command)

        rrule, next_run_at = _build_schedule_rule(timing)
        timestamp = utc_now().strftime("%Y%m%dT%H%M%S")
        name = str(body.get("name") or f"{action} task {timestamp}")
        schedule_id = str(body.get("id") or f"reddit-ui-{slugify(name, max_length=64)}-{timestamp}")
        self.actions_dir.mkdir(parents=True, exist_ok=True)
        action_file = self.actions_dir / f"{schedule_id}-{uuid.uuid4().hex[:8]}.json"
        scheduled_fields = {key: value for key, value in fields.items() if key != "query"}
        action_file.write_text(
            json.dumps([{"action": action, **scheduled_fields}], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        command = [
            "schedules",
            "register",
            "--id",
            schedule_id,
            "--name",
            name,
            "--source",
            "web-ui",
            "--rrule",
            rrule,
            "--status",
            str(body.get("status") or "ACTIVE"),
            "--action-class",
            "live",
            "--links",
            str(action_file),
            *_identity_args(identity, schedule=True),
        ]
        if next_run_at:
            command.extend(["--next-run-at", next_run_at])
        if body.get("noEnsureExecutor"):
            command.append("--no-ensure-executor")
        payload = self._agentctl(command)
        payload.setdefault("data", {})
        if isinstance(payload["data"], dict):
            payload["data"]["actionFile"] = str(action_file)
        return payload

    def _overview(self, account: str | None) -> dict[str, Any]:
        db = self._open_db()
        try:
            today = utc_now().date().isoformat()
            queue_counts = self._queue_counts(db, account)
            if account:
                action_count = db.get_daily_action_count(account)
                quota = db.get_account_limit(account)
            else:
                row = db.conn.execute(
                    "SELECT COALESCE(SUM(action_count), 0) AS count FROM account_stats WHERE action_date = ?",
                    (today,),
                ).fetchone()
                action_count = int(row["count"] or 0)
                quota = sum(int(limit["daily_action_quota"]) for limit in db.list_account_limits() if limit.get("action") == "*") or None
            schedules = [schedule for schedule in db.list_registered_schedules() if (not account or schedule.get("account") == account)]
            active_next = sorted(
                [schedule for schedule in schedules if schedule.get("status") == "ACTIVE" and schedule.get("next_run_at")],
                key=lambda schedule: schedule["next_run_at"],
            )
            recent_error_count = self._recent_error_count(db, account)
        finally:
            db.close()
        return {
            "queueCounts": queue_counts,
            "today": {
                "action_date": today,
                "action_count": action_count,
                "daily_action_quota": quota,
            },
            "nextSchedule": active_next[0] if active_next else None,
            "executor": agentctl.executor_status(),
            "recentErrorCount": recent_error_count,
        }

    def _schedules(self, account: str | None) -> dict[str, Any]:
        db = self._open_db()
        try:
            schedules = [
                {**schedule, "humanCadence": human_cadence(schedule.get("rrule") or "")}
                for schedule in db.list_registered_schedules()
                if not account or schedule.get("account") == account
            ]
        finally:
            db.close()
        return {"registeredSchedules": schedules}

    def _daily(self, account: str | None, days: int) -> dict[str, Any]:
        db = self._open_db()
        try:
            history = db.get_daily_action_history(account=account, days=days)
            if account:
                quota = db.get_account_limit(account)
                accounts = [account]
            else:
                accounts = sorted({row["account"] for row in db.conn.execute("SELECT DISTINCT account FROM account_stats")})
                quota = sum(int(limit["daily_action_quota"]) for limit in db.list_account_limits() if limit.get("action") == "*") or None
            today_count = history[-1]["action_count"] if history else 0
        finally:
            db.close()
        return {
            "history": history,
            "daily_action_quota": quota,
            "today_action_count": today_count,
            "accounts": accounts,
        }

    def _errors(self, account: str | None, limit: int) -> dict[str, Any]:
        db = self._open_db()
        try:
            queue_errors = db.list_queue_jobs(status="failed", account=account, limit=limit)
            schedule_errors = [
                schedule
                for schedule in db.list_registered_schedules()
                if schedule.get("last_error") and (not account or schedule.get("account") == account)
            ][:limit]
            action_errors = db.get_action_history(account=account, result="fail", limit=limit)
        finally:
            db.close()
        return {
            "queueErrors": queue_errors,
            "scheduleErrors": schedule_errors,
            "actionErrors": action_errors,
            "executorLogErrors": tool_cli._tail_executor_errors(limit),  # noqa: SLF001
        }

    def _queue_counts(self, db: BotDatabase, account: str | None) -> dict[str, int]:
        query = "SELECT status, COUNT(*) AS count FROM agent_queue"
        params: list[Any] = []
        if account:
            query += " WHERE account = ?"
            params.append(account)
        query += " GROUP BY status"
        cursor = db.conn.execute(query, params)
        return {row["status"]: row["count"] for row in cursor.fetchall()}

    def _recent_error_count(self, db: BotDatabase, account: str | None) -> int:
        params: list[Any] = []
        queue_query = "SELECT COUNT(*) AS count FROM agent_queue WHERE status = 'failed'"
        if account:
            queue_query += " AND account = ?"
            params.append(account)
        queue_count = db.conn.execute(queue_query, params).fetchone()["count"]
        schedule_params: list[Any] = []
        schedule_query = "SELECT COUNT(*) AS count FROM schedule_registry WHERE last_error IS NOT NULL"
        if account:
            schedule_query += " AND account = ?"
            schedule_params.append(account)
        schedule_count = db.conn.execute(schedule_query, schedule_params).fetchone()["count"]
        action_params: list[Any] = []
        action_query = "SELECT COUNT(*) AS count FROM action_log WHERE (success = 0 OR error_message IS NOT NULL)"
        if account:
            action_query += " AND account = ?"
            action_params.append(account)
        action_count = db.conn.execute(action_query, action_params).fetchone()["count"]
        return int(queue_count or 0) + int(schedule_count or 0) + int(action_count or 0)

    def _serve_static(self, path: str) -> None:
        target = self.static_dir / "index.html" if path in {"", "/"} else self.static_dir / path.lstrip("/")
        target = target.resolve()
        static_root = self.static_dir.resolve()
        if not str(target).startswith(str(static_root)) or not target.exists() or target.is_dir():
            target = static_root / "index.html"
        try:
            body = target.read_bytes()
        except OSError:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Static file not found."})
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_handler(
    *,
    db_path: str,
    static_dir: Path = DEFAULT_STATIC_DIR,
    actions_dir: Path = DEFAULT_ACTIONS_DIR,
    quiet: bool = False,
) -> type[RedditUIHandler]:
    class ConfiguredRedditUIHandler(RedditUIHandler):
        pass

    ConfiguredRedditUIHandler.db_path = str(db_path)
    ConfiguredRedditUIHandler.static_dir = Path(static_dir)
    ConfiguredRedditUIHandler.actions_dir = Path(actions_dir)
    ConfiguredRedditUIHandler.quiet = quiet
    return ConfiguredRedditUIHandler


def create_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: str = "reddit_bot.db",
    static_dir: Path = DEFAULT_STATIC_DIR,
    actions_dir: Path = DEFAULT_ACTIONS_DIR,
    quiet: bool = False,
) -> ThreadingHTTPServer:
    handler = make_handler(
        db_path=db_path,
        static_dir=static_dir,
        actions_dir=actions_dir,
        quiet=quiet,
    )
    server = ThreadingHTTPServer((host, port), handler)
    server.quiet = quiet  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local reddit-bot web dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db-path", default="reddit_bot.db")
    parser.add_argument("--static-dir", default=str(DEFAULT_STATIC_DIR))
    parser.add_argument("--actions-dir", default=str(DEFAULT_ACTIONS_DIR))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("The UI is localhost-only. Use 127.0.0.1, localhost, or ::1.")

    server = create_server(
        host=args.host,
        port=args.port,
        db_path=args.db_path,
        static_dir=Path(args.static_dir),
        actions_dir=Path(args.actions_dir),
        quiet=args.quiet,
    )
    url_host = "127.0.0.1" if args.host == "localhost" else args.host
    print(f"reddit-bot UI listening on http://{url_host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping reddit-bot UI.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
