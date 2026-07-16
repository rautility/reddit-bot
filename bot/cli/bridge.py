"""Bridge helpers: agentctl invocation, identity, profile preflight, DB access."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

from bot import agentctl
from bot.agentctl import (
    DEFAULT_PROFILE_NAME,
    EXECUTOR_LOG_PATH,
    REPO_ROOT,
)
from bot.config import BotConfig
from bot.control.errors import CliError
from bot.database import BotDatabase
from bot.utils.input_parser import VALID_ACTIONS, parse_links_file

DEFAULT_ACTIONS_DIR = REPO_ROOT / ".agent-actions"
ERROR_KEYWORDS = ("error", "failed", "exception", "traceback")
# Re-export for callers that previously imported DEFAULT_REDDIT_USER from bridge.
# Runtime defaults come from chrome_profile_accounts / REDDIT_BOT_DEFAULT_USER.
DEFAULT_REDDIT_USER = None

def _global_agentctl_args(args: argparse.Namespace) -> list[str]:
    control_args: list[str] = []
    if getattr(args, "config", None):
        control_args.extend(["--config", args.config])
    if getattr(args, "db_path", None):
        control_args.extend(["--db-path", args.db_path])
    return control_args


def _agentctl_payload(args: argparse.Namespace, command: list[str]) -> dict[str, Any]:
    stdout = io.StringIO()
    control_args = [*_global_agentctl_args(args), *command]
    try:
        with contextlib.redirect_stdout(stdout):
            exit_code = agentctl.main(control_args)
    except SystemExit as exc:
        code = exc.code if exc.code is not None else 0
        if code:
            raise CliError(str(code)) from exc
        exit_code = 0
    raw = stdout.getvalue().strip()
    # agentctl prints structured JSON even for validation failures (exit 2), so
    # parse first and let the caller inspect it. Only raise when there is no
    # machine-readable payload to hand back.
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            if exit_code:
                raise CliError(f"agentctl exited with status {exit_code}: {raw}") from exc
            raise CliError(f"agentctl returned non-JSON output: {raw}") from exc
    if exit_code:
        raise CliError(f"agentctl exited with status {exit_code}")
    return {}


def _load_config(args: argparse.Namespace) -> BotConfig:
    config = BotConfig.from_yaml(args.config) if getattr(args, "config", None) else BotConfig()
    config.merge_env_vars()
    if getattr(args, "db_path", None):
        config.db_path = args.db_path
    return config


def _open_db(args: argparse.Namespace) -> BotDatabase:
    return BotDatabase(_load_config(args).db_path)


def _identity_args(args: argparse.Namespace) -> list[str]:
    """CLI identity flags for agentctl. Empty means agentctl applies DB/env defaults."""
    if getattr(args, "account_label", None):
        return ["--account-label", args.account_label]
    if getattr(args, "profile_name", None):
        return ["--profile-name", args.profile_name]
    if getattr(args, "reddit_user", None):
        return ["--reddit-user", args.reddit_user]
    return []


def _debug_host_port(debug_address: str) -> tuple[str, str]:
    address = debug_address.replace("http://", "").replace("https://", "").rstrip("/")
    if ":" not in address:
        return address, ""
    return address.rsplit(":", 1)


def _open_profile_for_identity(identity: dict[str, Any], debug_address: str) -> dict[str, Any]:
    """Open the saved Chrome profile through the project diagnostic helper."""
    host, port = _debug_host_port(debug_address)
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "reddit_healer_debug.py"),
        "open-profile",
        "--profile-name",
        identity.get("profileName") or DEFAULT_PROFILE_NAME,
        "--debug-address",
        debug_address,
    ]
    if identity.get("profilePath"):
        command.extend(["--profile-dir", identity["profilePath"]])
    if host:
        command.extend(["--host", host])
    if port:
        command.extend(["--port", port])

    try:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returnCode": None,
            "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
            "stderr": "Timed out while opening Chrome profile.",
        }
    return {
        "command": command,
        "returnCode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _profile_preflight(args: argparse.Namespace) -> dict[str, Any]:
    """Resolve and validate the Chrome profile before dispatching a live worker."""
    if getattr(args, "no_profile_preflight", False):
        return {"checked": False, "reason": "Disabled by --no-profile-preflight."}

    identity = _agentctl_payload(args, ["profiles", "resolve", *_identity_args(args)])
    debug_address = identity.get("debugAddress")
    payload: dict[str, Any] = {
        "checked": bool(debug_address),
        "resolvedIdentity": identity,
        "debugAddress": debug_address,
    }
    if not debug_address:
        payload["reason"] = "Resolved identity has no Chrome debug address."
        return payload

    probe = agentctl.probe_debug_address(debug_address)
    payload["probe"] = probe
    if probe.get("ok"):
        return payload

    if getattr(args, "no_open_profile", False):
        detail = probe.get("error") or "debugger unreachable"
        if probe.get("hint"):
            detail = f"{detail} ({probe['hint']})"
        raise CliError(f"Chrome profile preflight failed and --no-open-profile was set: {detail}")

    open_result = _open_profile_for_identity(identity, debug_address)
    payload["openedProfile"] = open_result
    if open_result.get("returnCode") != 0:
        raise CliError(
            "Unable to open saved Chrome profile: "
            f"{open_result.get('stderr') or open_result.get('stdout') or open_result.get('returnCode')}"
        )

    for _ in range(12):
        time.sleep(0.5)
        probe = agentctl.probe_debug_address(debug_address, timeout=1.0)
        payload["probe"] = probe
        if probe.get("ok"):
            return payload

    detail = probe.get("error") or "probe failed"
    if probe.get("hint"):
        detail = f"{detail} ({probe['hint']})"
    raise CliError(f"Chrome profile opened, but DevTools is still unreachable at {debug_address}: {detail}")


def _schedule_identity_args(args: argparse.Namespace) -> list[str]:
    """Identity flags for schedules register. Empty → agentctl may leave account blank.

    For live schedule registration without explicit flags, resolve the sole
    association / env default so the schedule binds to an account.
    """
    if getattr(args, "account_label", None):
        return ["--account", args.account_label]
    if getattr(args, "profile_name", None):
        return ["--profile-name", args.profile_name]
    if getattr(args, "reddit_user", None):
        return ["--reddit-user", args.reddit_user]
    # Best-effort default identity so schedule add still binds an account when
    # a single association (or REDDIT_BOT_DEFAULT_USER) is available.
    try:
        from bot.control.profiles import resolve_profile_identity

        db = _open_db(args)
        try:
            identity = resolve_profile_identity(db)
        finally:
            db.close()
    except SystemExit:
        return []
    if identity.get("profileName"):
        return ["--profile-name", identity["profileName"]]
    if identity.get("redditUsername"):
        return ["--reddit-user", identity["redditUsername"]]
    if identity.get("accountLabel"):
        return ["--account", identity["accountLabel"]]
    return []


def _repo_codex_automations(payload: dict[str, Any], *, include_all: bool = False) -> list[dict[str, Any]]:
    automations = payload.get("codexAutomations", [])
    if include_all:
        return automations
    repo = str(REPO_ROOT)
    return [item for item in automations if repo in [str(path) for path in item.get("cwds", [])]]


def _action_line(args: argparse.Namespace) -> str:
    link = args.link or getattr(args, "query", "")
    if not link or not args.action:
        raise CliError("Provide --link/--query and --action, or provide --links.")
    if args.action not in VALID_ACTIONS:
        valid = ", ".join(sorted(VALID_ACTIONS))
        raise CliError(f"Unsupported action '{args.action}'. Valid actions: {valid}.")
    fields = [link, args.action]
    if args.comment:
        fields.append(args.comment.replace("\n", " "))
    return "|".join(fields) + "\n"


def _resolve_links_file(args: argparse.Namespace, schedule_id: str) -> Path:
    if args.links:
        path = Path(args.links).expanduser().resolve()
        if not path.exists():
            raise CliError(f"Links file does not exist: {path}")
        parse_links_file(str(path))
        return path

    actions_dir = Path(args.actions_dir).expanduser().resolve()
    actions_dir.mkdir(parents=True, exist_ok=True)
    path = actions_dir / f"{schedule_id}.txt"
    path.write_text(_action_line(args), encoding="utf-8")
    return path


def _job_outcome(args: argparse.Namespace, job_id: int) -> dict[str, Any]:
    """Read a single queue job by id and return its status plus parsed result."""
    db = _open_db(args)
    try:
        job = db.get_queue_job(job_id)
    finally:
        db.close()
    if not job:
        return {"id": job_id, "found": False}
    result = None
    if job.get("result_json"):
        try:
            result = json.loads(job["result_json"])
        except json.JSONDecodeError:
            result = {"raw": job["result_json"]}
    return {
        "id": job.get("id"),
        "found": True,
        "status": job.get("status"),
        "account": job.get("account"),
        "action": job.get("action"),
        "link": job.get("link"),
        "attempts": job.get("attempts"),
        "maxAttempts": job.get("max_attempts"),
        "lastError": job.get("last_error"),
        "result": result,
    }


def _collect_errors_from_db(*, limit: int, db_path: str) -> dict[str, Any]:
    db = BotDatabase(db_path)
    try:
        queue_errors = db.list_queue_jobs(status="failed", limit=limit)
        schedule_errors = [item for item in db.list_registered_schedules() if item.get("last_error")][:limit]
        cursor = db.conn.execute(
            """SELECT id, timestamp, account, action, link, error_message, screenshot_path
               FROM action_log
               WHERE success = 0 OR error_message IS NOT NULL
               ORDER BY id DESC
               LIMIT ?""",
            (limit,),
        )
        action_errors = [dict(row) for row in cursor.fetchall()]
    finally:
        db.close()
    return {
        "queueErrors": queue_errors,
        "scheduleErrors": schedule_errors,
        "actionErrors": action_errors,
    }


def _tail_executor_errors(limit: int) -> list[str]:
    if not EXECUTOR_LOG_PATH.exists():
        return []
    lines: deque[str] = deque(maxlen=limit)
    try:
        with EXECUTOR_LOG_PATH.open("r", encoding="utf-8", errors="replace") as file_obj:
            for line in file_obj:
                stripped = line.rstrip()
                if any(keyword in stripped.lower() for keyword in ERROR_KEYWORDS):
                    lines.append(stripped)
    except OSError as exc:
        return [f"Unable to read executor log: {exc}"]
    return list(lines)

