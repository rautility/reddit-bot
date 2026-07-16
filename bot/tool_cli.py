"""Human-friendly operations CLI for the Reddit bot control plane."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import time
from collections import deque
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bot import agentctl
from bot.action_schema import (
    ACTION_SCHEMA,
    FIELD_GLOSSARY,
    SCHEMA_VERSION,
    URL_CONTRACT,
    describe_actions,
    validate_action_fields,
)
from bot.agentctl import (
    DEFAULT_DEBUG_ADDRESS,
    DEFAULT_PROFILE_NAME,
    EXECUTOR_LOG_PATH,
    REPO_ROOT,
)
from bot.config import BotConfig
from bot.control import doctor as doctor_control
from bot.control import schedules as schedule_control
from bot.control.errors import CliError
from bot.control.resolve import resolve_reddit_url
from bot.database import BotDatabase
from bot.utils.clock import utc_now
from bot.utils.input_parser import VALID_ACTIONS, parse_links_file

DEFAULT_REDDIT_USER = "u/Particular-Arm2102"
DEFAULT_ACTIONS_DIR = REPO_ROOT / ".agent-actions"
ERROR_KEYWORDS = ("error", "failed", "exception", "traceback")
# Transport fields an agent can pass inline to `do`, mirroring ActionEntry.
INLINE_ACTION_FIELDS = (
    "link",
    "comment",
    "title",
    "subreddit",
    "body",
    "flair",
    "recipient",
    "message",
)
QUERY_ACTIONS = {name for name, spec in ACTION_SCHEMA.items() if spec.get("link_kind") == "query"}

WEEKDAYS = schedule_control.WEEKDAYS
_normalize_weekdays = schedule_control.normalize_weekdays
_parse_at = schedule_control.parse_at
_parse_time = schedule_control.parse_time
_schedule_rule = schedule_control.schedule_rule
_slugify = schedule_control.slugify


def _envelope(command: str, *, data: Any = None, ok: bool = True, error: Any = None) -> dict[str, Any]:
    """Wrap a command result in the stable, versioned response contract."""
    return {
        "ok": ok,
        "schemaVersion": SCHEMA_VERSION,
        "command": command,
        "data": data if data is not None else {},
        "error": error,
    }


def _truncate(value: Any, width: int = 54) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", "\\n")
    if len(text) <= width:
        return text
    return text[: max(0, width - 3)] + "..."


def _print_table(headers: list[str], rows: Iterable[Iterable[Any]]) -> None:
    rendered_rows = [[_truncate(cell) for cell in row] for row in rows]
    if not rendered_rows:
        print("(none)")
        return
    widths = [max(len(str(header)), *(len(row[index]) for row in rendered_rows)) for index, header in enumerate(headers)]
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rendered_rows:
        print("  ".join(row[index].ljust(widths[index]) for index in range(len(headers))))


def _print_kv(items: Iterable[tuple[str, Any]]) -> None:
    pairs = [(label, "" if value is None else str(value)) for label, value in items]
    width = max((len(label) for label, _ in pairs), default=0)
    for label, value in pairs:
        print(f"{label.ljust(width)}  {value}")


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


def _json_or_table(args: argparse.Namespace, payload: dict[str, Any], printer) -> int:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        printer(payload)
    return 0


def _identity_args(args: argparse.Namespace) -> list[str]:
    if getattr(args, "account_label", None):
        return ["--account-label", args.account_label]
    if getattr(args, "profile_name", None):
        return ["--profile-name", args.profile_name]
    reddit_user = getattr(args, "reddit_user", None) or DEFAULT_REDDIT_USER
    return ["--reddit-user", reddit_user]


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
    if getattr(args, "account_label", None):
        return ["--account", args.account_label]
    if getattr(args, "profile_name", None):
        return ["--profile-name", args.profile_name]
    reddit_user = getattr(args, "reddit_user", None) or DEFAULT_REDDIT_USER
    return ["--reddit-user", reddit_user]


def _repo_codex_automations(payload: dict[str, Any], *, include_all: bool = False) -> list[dict[str, Any]]:
    automations = payload.get("codexAutomations", [])
    if include_all:
        return automations
    repo = str(REPO_ROOT)
    return [item for item in automations if repo in [str(path) for path in item.get("cwds", [])]]


def _print_overview(payload: dict[str, Any]) -> None:
    print("Reddit Bot Overview")
    queue_counts = payload.get("queueCounts", {})
    executor = payload.get("executor", {})
    _print_kv(
        [
            ("cwd", payload.get("cwd")),
            ("db", payload.get("dbPath")),
            (
                "queue",
                ", ".join(f"{key}={value}" for key, value in sorted(queue_counts.items())) or "empty",
            ),
            (
                "executor",
                f"{executor.get('method', '')} running={executor.get('running')} available={executor.get('available')}",
            ),
            ("executor log", executor.get("logPath")),
            ("default debug", payload.get("defaultChromeDebugAddress")),
        ]
    )

    print("\nProject schedules")
    schedules = sorted(
        payload.get("registeredSchedules", []),
        key=lambda item: (
            item.get("next_run_at") is None,
            item.get("next_run_at") or "",
            item.get("id") or "",
        ),
    )[:8]
    _print_table(
        ["id", "status", "next", "last", "account", "error"],
        [
            [
                item.get("id"),
                item.get("status"),
                item.get("next_run_at"),
                item.get("last_run_at"),
                item.get("account"),
                item.get("last_error"),
            ]
            for item in schedules
        ],
    )

    print("\nSaved profiles")
    _print_table(
        ["profile", "account", "debug", "default"],
        [
            [
                item.get("profileName"),
                item.get("redditUsername") or item.get("accountLabel"),
                item.get("configuredDebugAddress") or item.get("suggestedDebugAddress"),
                "yes" if item.get("isDefault") else "",
            ]
            for item in payload.get("savedChromeProfiles", [])
        ],
    )

    print("\nActive leases")
    _print_table(
        ["type", "resource", "by", "expires"],
        [
            [
                item.get("resource_type"),
                item.get("resource_id"),
                item.get("acquired_by"),
                item.get("expires_at"),
            ]
            for item in payload.get("activeLeases", [])
        ],
    )

    errors = _collect_errors_from_db(limit=5, db_path=payload.get("dbPath") or "reddit_bot.db")
    print("\nRecent errors")
    _print_error_summary(errors, include_logs=False)


def command_overview(args: argparse.Namespace) -> int:
    payload = _agentctl_payload(args, ["status"])
    return _json_or_table(args, payload, _print_overview)


def _print_doctor(payload: dict[str, Any]) -> None:
    data = payload.get("data") or {}
    print(doctor_control.format_checks_table(data))


def command_doctor(args: argparse.Namespace) -> int:
    """Read-only health checks: DB, profiles, debugger, queue, executor, etc.

    Exit code is non-zero only for hard local misconfiguration (DB open
    failure). Soft failures leave exit 0 so agents can parse JSON — see
    ``data.summary.exitPolicy``.
    """
    config = _load_config(args)
    report = doctor_control.run_doctor(
        db_path=config.db_path,
        debug_address=getattr(args, "debug_address", None) or None,
        reddit_user=getattr(args, "reddit_user", None) or None,
        profile_name=getattr(args, "profile_name", None) or None,
        account_label=getattr(args, "account_label", None) or None,
    )
    # Envelope ok tracks hard failures only; per-check and summary.ok carry soft fails.
    hard_failed = (report.get("summary") or {}).get("hardFailed") or []
    payload = _envelope(
        "doctor",
        ok=not hard_failed,
        data=report,
        error=None if not hard_failed else f"Hard diagnostic failures: {', '.join(hard_failed)}",
    )
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_doctor(payload)
    return doctor_control.process_exit_code(report)


def _print_schedule_list(payload: dict[str, Any], *, limit: int, include_all_codex: bool) -> None:
    schedules = payload.get("registeredSchedules", [])[:limit]
    print("Project schedules")
    _print_table(
        ["id", "status", "next", "last", "account", "profile", "class", "error"],
        [
            [
                item.get("id"),
                item.get("status"),
                item.get("next_run_at"),
                item.get("last_run_at"),
                item.get("account"),
                item.get("profile"),
                item.get("action_class"),
                item.get("last_error"),
            ]
            for item in schedules
        ],
    )

    automations = _repo_codex_automations(payload, include_all=include_all_codex)
    print("\nCodex automations")
    _print_table(
        ["id", "status", "rrule", "path"],
        [
            [
                item.get("id"),
                item.get("status"),
                item.get("rrule"),
                item.get("path"),
            ]
            for item in automations[:limit]
        ],
    )


def command_schedule_list(args: argparse.Namespace) -> int:
    command = ["schedules", "list"]
    if args.include_crontab:
        command.append("--include-crontab")
    payload = _agentctl_payload(args, command)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_schedule_list(payload, limit=args.limit, include_all_codex=args.all_codex)
    return 0


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


def _print_schedule_add(payload: dict[str, Any]) -> None:
    print("Schedule registered")
    _print_kv(
        [
            ("id", payload.get("registered")),
            ("links", payload.get("linksPath")),
            ("identity", (payload.get("resolvedIdentity") or {}).get("accountLabel")),
            ("executor ensured", (payload.get("executor") or {}).get("ensured")),
            ("executor error", (payload.get("executor") or {}).get("error")),
            ("executor hint", (payload.get("executor") or {}).get("hint")),
        ]
    )
    schedules = [item for item in payload.get("schedules", []) if item.get("id") == payload.get("registered")]
    if schedules:
        print("\nRegistered row")
        _print_table(
            ["id", "status", "next", "account", "profile", "rrule"],
            [
                [
                    item.get("id"),
                    item.get("status"),
                    item.get("next_run_at"),
                    item.get("account"),
                    item.get("profile"),
                    item.get("rrule"),
                ]
                for item in schedules
            ],
        )


def command_schedule_add(args: argparse.Namespace) -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    default_name = f"{args.action or 'Reddit'} task {timestamp}"
    name = args.name or default_name
    schedule_id = args.id or f"reddit-bot-{_slugify(name)}-{timestamp}"
    rrule, next_run_at = _schedule_rule(args)
    links_path = _resolve_links_file(args, schedule_id)

    command = [
        "schedules",
        "register",
        "--id",
        schedule_id,
        "--name",
        name,
        "--source",
        args.source,
        "--rrule",
        rrule,
        "--status",
        args.status,
        "--action-class",
        args.action_class,
        "--links",
        str(links_path),
        *_schedule_identity_args(args),
    ]
    if next_run_at:
        command.extend(["--next-run-at", next_run_at])
    if args.no_ensure_executor:
        command.append("--no-ensure-executor")
    payload = _agentctl_payload(args, command)
    payload["linksPath"] = str(links_path)
    return _json_or_table(args, payload, _print_schedule_add)


def _print_run_due(payload: dict[str, Any]) -> None:
    print("Due schedule run")
    _print_kv(
        [
            ("worker", payload.get("workerId")),
            ("due schedules", payload.get("dueSchedules")),
            ("runnable jobs", len(payload.get("runnableJobIds", []))),
            ("stale recovered", len(payload.get("recoveredStaleJobs", []))),
            ("worker processed", (payload.get("worker") or {}).get("processed")),
            ("worker idle", (payload.get("worker") or {}).get("idle")),
        ]
    )
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        print("\nDiagnostics")
        _print_table(
            ["code", "message"],
            [[item.get("code"), item.get("message")] for item in diagnostics],
        )
    print("\nProcessed")
    _print_table(
        ["id", "submitted", "queued", "next", "error"],
        [
            [
                item.get("id"),
                item.get("submitted"),
                ",".join(str(job_id) for job_id in item.get("queuedJobIds", [])),
                item.get("nextRunAt"),
                item.get("error"),
            ]
            for item in payload.get("processed", [])
        ],
    )


def command_schedule_run_due(args: argparse.Namespace) -> int:
    command = [
        "schedules",
        "run-due",
        "--limit",
        str(args.limit),
        "--priority",
        str(args.priority),
    ]
    if args.now:
        command.extend(["--now", args.now])
    if args.run_worker:
        command.append("--run-worker")
    if args.verbose:
        command.append("--verbose")
    payload = _agentctl_payload(args, command)
    return _json_or_table(args, payload, _print_run_due)


def _print_schedule_change(payload: dict[str, Any]) -> None:
    schedule = payload.get("schedule") or {}
    _print_kv(
        [
            ("id", schedule.get("id")),
            ("changed", payload.get("changed", payload.get("deleted"))),
            ("status", schedule.get("status")),
            ("message", schedule.get("message")),
        ]
    )


def command_schedule_pause(args: argparse.Namespace) -> int:
    payload = _agentctl_payload(
        args,
        ["schedules", "set-status", "--id", args.id, "--status", "PAUSED"],
    )
    return _json_or_table(args, payload, _print_schedule_change)


def command_schedule_resume(args: argparse.Namespace) -> int:
    payload = _agentctl_payload(
        args,
        ["schedules", "set-status", "--id", args.id, "--status", "ACTIVE"],
    )
    return _json_or_table(args, payload, _print_schedule_change)


def command_schedule_delete(args: argparse.Namespace) -> int:
    payload = _agentctl_payload(args, ["schedules", "delete", "--id", args.id])
    return _json_or_table(args, payload, _print_schedule_change)


def _print_queue(payload: dict[str, Any]) -> None:
    counts = payload.get("queueCounts", {})
    print("Queue")
    print(", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "empty")
    _print_table(
        ["id", "status", "account", "action", "link", "scheduled", "attempts", "error"],
        [
            [
                item.get("id"),
                item.get("status"),
                item.get("account"),
                item.get("action"),
                item.get("link"),
                item.get("scheduled_for"),
                f"{item.get('attempts')}/{item.get('max_attempts')}",
                item.get("last_error"),
            ]
            for item in payload.get("jobs", [])
        ],
    )


def command_queue_list(args: argparse.Namespace) -> int:
    command = ["queue", "list", "--limit", str(args.limit)]
    if args.status:
        command.extend(["--status", args.status])
    if args.account:
        command.extend(["--account", args.account])
    payload = _agentctl_payload(args, command)
    return _json_or_table(args, payload, _print_queue)


def _print_queue_add(payload: dict[str, Any]) -> None:
    print("Queue submission")
    _print_kv(
        [
            ("submitted", payload.get("submitted")),
            ("identity", (payload.get("resolvedIdentity") or {}).get("accountLabel")),
        ]
    )
    _print_table(
        ["id", "status", "account", "action", "link", "scheduled"],
        [
            [
                item.get("id"),
                item.get("status"),
                item.get("account"),
                item.get("action"),
                item.get("link"),
                item.get("scheduled_for"),
            ]
            for item in payload.get("jobs", [])
        ],
    )


def command_queue_add(args: argparse.Namespace) -> int:
    command = [
        "queue",
        "submit",
        *_identity_args(args),
        "--links",
        args.links,
        "--priority",
        str(args.priority),
        "--max-attempts",
        str(args.max_attempts),
    ]
    if args.scheduled_for:
        command.extend(["--scheduled-for", args.scheduled_for])
    payload = _agentctl_payload(args, command)
    if args.run_worker:
        payload["worker"] = _agentctl_payload(
            args,
            ["queue", "worker", "--once", "--max-jobs", str(payload.get("submitted", 1))],
        )
    return _json_or_table(args, payload, _print_queue_add)


def _print_worker(payload: dict[str, Any]) -> None:
    print("Queue worker")
    _print_kv(
        [
            ("worker", payload.get("workerId")),
            ("processed", payload.get("processed")),
            ("idle", payload.get("idle")),
        ]
    )


def command_queue_run_once(args: argparse.Namespace) -> int:
    command = ["queue", "worker", "--once", "--max-jobs", str(args.max_jobs)]
    if args.verbose:
        command.append("--verbose")
    payload = _agentctl_payload(args, command)
    return _json_or_table(args, payload, _print_worker)


def _print_queue_recover_stale(payload: dict[str, Any]) -> None:
    print("Stale queue recovery")
    _print_kv(
        [
            ("recovered", payload.get("recovered")),
            (
                "queue",
                ", ".join(f"{k}={v}" for k, v in sorted((payload.get("queueCounts") or {}).items())),
            ),
        ]
    )
    _print_table(
        ["id", "status", "action", "link", "attempts", "message"],
        [
            [
                item.get("id"),
                item.get("status"),
                item.get("action"),
                item.get("link"),
                f"{item.get('attempts')}/{item.get('maxAttempts')}",
                item.get("message"),
            ]
            for item in payload.get("jobs", [])
        ],
    )


def command_queue_recover_stale(args: argparse.Namespace) -> int:
    command = ["queue", "recover-stale"]
    if args.now:
        command.extend(["--now", args.now])
    payload = _agentctl_payload(args, command)
    return _json_or_table(args, payload, _print_queue_recover_stale)


def _print_queue_retry(payload: dict[str, Any]) -> None:
    print("Queue retry")
    _print_kv([("retried", payload.get("count", 0))])
    _print_table(
        ["id", "retried", "status", "account", "action", "attempts", "message"],
        [
            [
                item.get("id"),
                "yes" if item.get("retried") else "no",
                item.get("status"),
                item.get("account"),
                item.get("action"),
                f"{item.get('attempts')}/{item.get('max_attempts')}",
                item.get("message"),
            ]
            for item in payload.get("retried", [])
        ],
    )


def command_queue_retry(args: argparse.Namespace) -> int:
    command = ["queue", "retry"]
    if args.id is not None:
        command.extend(["--id", str(args.id)])
    else:
        command.append("--all")
    if getattr(args, "account", None):
        command.extend(["--account", args.account])
    payload = _agentctl_payload(args, command)
    return _json_or_table(args, payload, _print_queue_retry)


def _print_executor(payload: dict[str, Any]) -> None:
    print("Executor")
    _print_kv(
        [
            ("method", payload.get("method")),
            ("available", payload.get("available")),
            ("running", payload.get("running")),
            ("ensured", payload.get("ensured")),
            ("started", payload.get("started")),
            ("label", payload.get("label")),
            ("plist", payload.get("plistPath")),
            ("pid path", payload.get("pidPath")),
            ("log", payload.get("logPath")),
            ("error", payload.get("error")),
        ]
    )


def command_executor(args: argparse.Namespace) -> int:
    command = ["executor", args.executor_action]
    if args.executor_action == "ensure":
        command.extend(["--executor-interval", str(args.executor_interval)])
        command.extend(["--start-interval", str(args.start_interval)])
        if args.allow_pid_fallback:
            command.append("--allow-pid-fallback")
    payload = _agentctl_payload(args, command)
    return _json_or_table(args, payload, _print_executor)


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


def _print_error_summary(payload: dict[str, Any], *, include_logs: bool = True) -> None:
    print("Queue failures")
    _print_table(
        ["id", "updated", "account", "action", "link", "attempts", "error"],
        [
            [
                item.get("id"),
                item.get("updated_at"),
                item.get("account"),
                item.get("action"),
                item.get("link"),
                f"{item.get('attempts')}/{item.get('max_attempts')}",
                item.get("last_error"),
            ]
            for item in payload.get("queueErrors", [])
        ],
    )

    print("\nSchedule errors")
    _print_table(
        ["id", "updated", "next", "account", "error"],
        [
            [
                item.get("id"),
                item.get("updated_at"),
                item.get("next_run_at"),
                item.get("account"),
                item.get("last_error"),
            ]
            for item in payload.get("scheduleErrors", [])
        ],
    )

    print("\nAction log errors")
    _print_table(
        ["id", "time", "account", "action", "link", "error", "screenshot"],
        [
            [
                item.get("id"),
                item.get("timestamp"),
                item.get("account"),
                item.get("action"),
                item.get("link"),
                item.get("error_message"),
                item.get("screenshot_path"),
            ]
            for item in payload.get("actionErrors", [])
        ],
    )

    if include_logs:
        print("\nExecutor log error lines")
        log_lines = payload.get("executorLogErrors", [])
        if not log_lines:
            print("(none)")
        else:
            for line in log_lines:
                print(_truncate(line, 120))


def command_errors(args: argparse.Namespace) -> int:
    config = _load_config(args)
    payload = _collect_errors_from_db(limit=args.limit, db_path=config.db_path)
    payload["executorLogErrors"] = _tail_executor_errors(args.limit)
    return _json_or_table(
        args,
        payload,
        lambda data: _print_error_summary(data, include_logs=True),
    )


def _print_profiles(payload: dict[str, Any]) -> None:
    print("Profiles")
    _print_table(
        ["profile", "account", "reddit", "debug", "path"],
        [
            [
                item.get("profileName"),
                item.get("accountLabel"),
                item.get("redditUsername"),
                item.get("configuredDebugAddress") or item.get("suggestedDebugAddress"),
                item.get("profilePath"),
            ]
            for item in payload.get("profiles", [])
        ],
    )


def command_profiles(args: argparse.Namespace) -> int:
    payload = _agentctl_payload(args, ["profiles", "list"])
    return _json_or_table(args, payload, _print_profiles)


def _print_limits(payload: dict[str, Any]) -> None:
    print("Account limits")
    _print_table(
        ["account", "action", "quota", "updated"],
        [
            [
                item.get("account"),
                item.get("action"),
                item.get("daily_action_quota"),
                item.get("updated_at"),
            ]
            for item in payload.get("accountLimits", [])
        ],
    )
    print("\nActive reservations")
    _print_table(
        ["id", "account", "action", "status", "until", "message"],
        [
            [
                item.get("id"),
                item.get("account"),
                item.get("action"),
                item.get("status"),
                item.get("reserved_until"),
                item.get("message"),
            ]
            for item in payload.get("activeReservations", [])
        ],
    )


def command_limits_list(args: argparse.Namespace) -> int:
    payload = _agentctl_payload(args, ["limits", "list", "--limit", str(args.limit)])
    return _json_or_table(args, payload, _print_limits)


def command_limits_set(args: argparse.Namespace) -> int:
    command = [
        "limits",
        "set",
        "--account",
        args.account,
        "--action",
        args.action,
        "--daily-action-quota",
        str(args.daily_action_quota),
    ]
    payload = _agentctl_payload(args, command)
    return _json_or_table(args, payload, _print_limits)


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


def _print_capabilities(payload: dict[str, Any]) -> None:
    data = payload.get("data", {})
    if data.get("action"):
        spec = data.get("spec", {})
        print(f"Reddit action: {data.get('action')}")
        _print_kv(
            [
                ("summary", spec.get("summary")),
                ("required", ", ".join(spec.get("required", [])) or "-"),
                ("optional", ", ".join(spec.get("optional", [])) or "-"),
                ("link kind", spec.get("link_kind")),
                ("notes", spec.get("notes")),
            ]
        )
        return

    print(f"Reddit action capabilities (schema {data.get('schemaVersion')})")
    print("\nActions")
    _print_table(
        ["action", "required", "optional", "link", "summary"],
        [
            [
                name,
                ", ".join(spec.get("required", [])) or "-",
                ", ".join(spec.get("optional", [])) or "-",
                spec.get("link_kind", "-"),
                spec.get("summary", ""),
            ]
            for name, spec in sorted(data.get("actions", {}).items())
        ],
    )
    contract = data.get("urlContract", {})
    print("\nURL contract")
    _print_kv(
        [
            ("canonical", contract.get("canonicalFormat")),
            ("post actions", ", ".join(contract.get("postActions", []))),
            ("rejects", contract.get("rejects")),
        ]
    )
    defaults = data.get("defaults", {})
    print("\nDefaults")
    _print_kv(
        [
            ("reddit user", defaults.get("redditUser")),
            ("profile name", defaults.get("profileName")),
            ("debug address", defaults.get("debugAddress")),
            ("identity flags", ", ".join(defaults.get("identityOptions", []))),
        ]
    )
    limits = data.get("accountLimits", [])
    if limits:
        print("\nCurrent quotas")
        _print_table(
            ["account", "action", "quota"],
            [[i.get("account"), i.get("action"), i.get("daily_action_quota")] for i in limits],
        )
    print("\nResolve share shortlinks (rejected by queue submit by default):")
    print("  reddit-tool resolve-url --link <share_or_post_url>")
    print("\nRun one action end to end:")
    print("  reddit-tool do --action upvote --link <post_url>")
    print("  reddit-tool search-upvote --query <search_query>")


def _print_resolve_url(payload: dict[str, Any]) -> None:
    data = payload.get("data", {})
    print("Resolve URL" + ("" if payload.get("ok") else " (failed)"))
    _print_kv(
        [
            ("ok", payload.get("ok")),
            ("input", data.get("input")),
            ("output", data.get("output")),
            ("resolved", data.get("resolved")),
            ("kind", data.get("kind")),
        ]
    )
    if payload.get("error"):
        print(f"\nerror: {payload['error']}")


def command_resolve_url(args: argparse.Namespace) -> int:
    """Convert a Reddit share shortlink to a canonical /comments/ URL."""
    try:
        data = resolve_reddit_url(
            args.link,
            timeout=float(getattr(args, "timeout", 15.0) or 15.0),
        )
    except CliError as exc:
        payload = _envelope(
            "resolve-url",
            ok=False,
            error=str(exc),
            data={
                "input": (args.link or "").strip(),
                "output": None,
                "resolved": False,
                "kind": None,
            },
        )
        _json_or_table(args, payload, _print_resolve_url)
        return 2

    payload = _envelope("resolve-url", data=data)
    return _json_or_table(args, payload, _print_resolve_url)


def command_capabilities(args: argparse.Namespace) -> int:
    from bot.agentctl import DEFAULT_PROFILE_NAME

    data = describe_actions()
    command_name = getattr(args, "command_name", None) or "capabilities"
    data["defaults"] = {
        "redditUser": DEFAULT_REDDIT_USER,
        "profileName": DEFAULT_PROFILE_NAME,
        "debugAddress": DEFAULT_DEBUG_ADDRESS,
        "identityOptions": ["--reddit-user", "--profile-name", "--account-label"],
    }
    data["howToRun"] = {
        "oneShot": "reddit-tool do --action <action> --link <url> [field flags]",
        "resolveShareUrl": "reddit-tool resolve-url --link <share_or_post_url>",
        "searchUpvote": "reddit-tool search-upvote --query <search query>",
        "externalSearchUpvote": ("reddit-tool external-search-upvote --query <search query> [--subreddit <name>] --json"),
        "queueOnly": "reddit-tool queue add --links <file>",
        "schedule": "reddit-tool schedule add --action <action> --link <url> --at <iso>",
        "scheduleSearchUpvote": ("reddit-tool schedule add --action search_upvote --query <search query> --at <iso>"),
    }
    try:
        db = _open_db(args)
        try:
            data["accountLimits"] = db.list_account_limits()
        finally:
            db.close()
    except Exception:
        data["accountLimits"] = []

    action_name = getattr(args, "action_name", None)
    if action_name:
        spec = data["actions"].get(action_name)
        if spec is None:
            payload = _envelope(
                command_name,
                ok=False,
                error=(f"Unknown action '{action_name}'. Valid actions: " + ", ".join(sorted(data["actions"])) + "."),
                data={"action": action_name},
            )
            _json_or_table(args, payload, _print_capabilities)
            return 2
        data = {
            "schemaVersion": SCHEMA_VERSION,
            "action": action_name,
            "spec": spec,
            "fieldGlossary": FIELD_GLOSSARY,
            "urlContract": URL_CONTRACT,
            "defaults": data["defaults"],
        }

    payload = _envelope(command_name, data=data)
    return _json_or_table(args, payload, _print_capabilities)


def _print_do(payload: dict[str, Any]) -> None:
    data = payload.get("data", {})
    print("Reddit action" + ("" if payload.get("ok") else " (failed)"))
    _print_kv(
        [
            ("ok", payload.get("ok")),
            ("action", data.get("action")),
            ("submitted", data.get("submitted")),
            ("ran worker", data.get("ranWorker")),
            ("action file", data.get("actionFile")),
        ]
    )
    preflight = data.get("profilePreflight")
    if preflight:
        probe = preflight.get("probe") or {}
        print("\nProfile preflight")
        _print_kv(
            [
                ("checked", preflight.get("checked")),
                ("debug", preflight.get("debugAddress")),
                ("probe ok", probe.get("ok")),
                ("probe error", probe.get("error")),
                ("probe hint", probe.get("hint")),
                ("opened", bool(preflight.get("openedProfile"))),
            ]
        )
    if payload.get("error"):
        print(f"\nerror: {payload['error']}")
        for item in data.get("fieldErrors", []):
            print(f"  - {item.get('field')}: {item.get('error')}")
        for item in data.get("linkErrors", []):
            print(f"  - line {item.get('line')}: {item.get('error')}")
    results = data.get("results", [])
    if results:
        print("\nOutcome")
        _print_table(
            ["job", "status", "action", "link", "error"],
            [[r.get("id"), r.get("status"), r.get("action"), r.get("link"), r.get("lastError")] for r in results],
        )


def command_do(args: argparse.Namespace) -> int:
    provided = {field: getattr(args, field) for field in INLINE_ACTION_FIELDS if getattr(args, field, None)}
    if args.action in QUERY_ACTIONS and getattr(args, "query", None) and "link" not in provided:
        provided["link"] = args.query

    field_errors = validate_action_fields(args.action, provided)
    if field_errors:
        payload = _envelope(
            "do",
            ok=False,
            error="Action payload is missing required fields.",
            data={"action": args.action, "submitted": 0, "fieldErrors": field_errors},
        )
        _json_or_table(args, payload, _print_do)
        return 2

    preflight = None
    if not args.no_run:
        try:
            preflight = _profile_preflight(args)
        except CliError as exc:
            payload = _envelope(
                "do",
                ok=False,
                error=str(exc),
                data={
                    "action": args.action,
                    "submitted": 0,
                    "profilePreflight": {"checked": True, "error": str(exc)},
                },
            )
            _json_or_table(args, payload, _print_do)
            return 2

    actions_dir = Path(args.actions_dir).expanduser().resolve()
    actions_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    action_file = actions_dir / f"do-{args.action}-{timestamp}.txt"
    entry = {"action": args.action, **provided}
    action_file.write_text(json.dumps([entry], indent=2), encoding="utf-8")

    try:
        submit = _agentctl_payload(
            args,
            ["queue", "submit", *_identity_args(args), "--links", str(action_file)],
        )
    except CliError as exc:
        payload = _envelope(
            "do",
            ok=False,
            error=str(exc),
            data={"action": args.action, "submitted": 0, "actionFile": str(action_file)},
        )
        _json_or_table(args, payload, _print_do)
        return 2

    if submit.get("linkErrors"):
        payload = _envelope(
            "do",
            ok=False,
            error="Links file contains unsupported Reddit URL formats.",
            data={
                "action": args.action,
                "submitted": 0,
                "actionFile": str(action_file),
                "linkErrors": submit.get("linkErrors", []),
            },
        )
        _json_or_table(args, payload, _print_do)
        return 2

    submitted = submit.get("submitted", 0)
    if not submitted:
        payload = _envelope(
            "do",
            ok=False,
            error=submit.get("error") or "Nothing was queued.",
            data={"action": args.action, "submitted": 0, "actionFile": str(action_file)},
        )
        _json_or_table(args, payload, _print_do)
        return 2
    job_ids = [job.get("id") for job in submit.get("jobs", []) if job.get("id") is not None]
    data: dict[str, Any] = {
        "action": args.action,
        "submitted": submitted,
        "actionFile": str(action_file),
        "resolvedIdentity": submit.get("resolvedIdentity"),
        "jobIds": job_ids,
        "ranWorker": False,
    }
    if preflight is not None:
        data["profilePreflight"] = preflight

    ok = True
    if not args.no_run and submitted:
        worker = _agentctl_payload(args, ["queue", "worker", "--once", "--max-jobs", str(submitted)])
        data["ranWorker"] = True
        data["worker"] = worker
        data["results"] = [_job_outcome(args, job_id) for job_id in job_ids]
        ok = all(r.get("status") == "succeeded" for r in data["results"]) if data["results"] else False

    payload = _envelope("do", ok=ok, data=data, error=None if ok else "One or more actions did not complete.")
    exit_code = _json_or_table(args, payload, _print_do)
    return exit_code if ok else 1


def command_search_upvote(args: argparse.Namespace) -> int:
    args.action = "search_upvote"
    if getattr(args, "query", None) and not getattr(args, "link", None):
        args.link = args.query
    return command_do(args)


def _terminal_job_status(status: str | None) -> bool:
    return status in {"succeeded", "failed"}


def _selected_result_link(job: dict[str, Any]) -> str | None:
    result = job.get("result") or {}
    results = result.get("results") if isinstance(result, dict) else None
    if not results:
        return None
    first = results[0] if isinstance(results[0], dict) else {}
    return first.get("link")


def _is_post_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and parsed.netloc.endswith("reddit.com") and "/comments/" in parsed.path


def _queue_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _external_schedule_window(at: str, window_seconds: int) -> tuple[datetime, datetime, str]:
    parsed = _parse_at(at)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    window_seconds = max(1, window_seconds)
    bucket = int(parsed.timestamp()) // window_seconds * window_seconds
    start = datetime.fromtimestamp(bucket)
    end = datetime.fromtimestamp(bucket + window_seconds)
    return start, end, start.strftime("%Y%m%dT%H%M%S")


def _external_search_schedule_id(
    query: str,
    identity: dict[str, Any] | None,
    at: str,
    window_seconds: int,
) -> str:
    account = (identity or {}).get("accountLabel") or (identity or {}).get("redditUsername") or "default"
    _, _, bucket = _external_schedule_window(at, window_seconds)
    return f"external-search-upvote-{_slugify(query)}-{_slugify(str(account))}-{bucket}"


def _find_matching_search_upvote_job(
    args: argparse.Namespace,
    *,
    account: str,
    query: str,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any] | None:
    if not account:
        return None
    db = _open_db(args)
    try:
        jobs = db.list_queue_jobs(limit=200)
    finally:
        db.close()
    for job in jobs:
        if job.get("account") != account:
            continue
        if job.get("action") != "search_upvote" or job.get("link") != query:
            continue
        created_at = _queue_timestamp(job.get("created_at"))
        if created_at is None or not (window_start <= created_at < window_end):
            continue
        return _job_outcome(args, int(job["id"]))
    return None


def _previous_selected_result_link(args: argparse.Namespace, job: dict[str, Any]) -> str | None:
    db = _open_db(args)
    try:
        jobs = db.list_queue_jobs(status="succeeded", limit=200)
    finally:
        db.close()
    for candidate in jobs:
        if candidate.get("id") == job.get("id"):
            continue
        if candidate.get("account") != job.get("account"):
            continue
        if candidate.get("action") != job.get("action"):
            continue
        if candidate.get("link") != job.get("link"):
            continue
        outcome = _job_outcome(args, int(candidate["id"]))
        selected = _selected_result_link(outcome)
        if _is_post_url(selected):
            return selected
    return None


def _selected_post_url_from_outcomes(
    args: argparse.Namespace,
    outcomes: list[dict[str, Any]],
) -> str | None:
    fallback: str | None = None
    for item in outcomes:
        selected = _selected_result_link(item)
        if _is_post_url(selected):
            return selected
        if selected and fallback is None:
            fallback = selected
        previous = _previous_selected_result_link(args, item)
        if previous:
            return previous
    return fallback


def _selection_details_from_outcomes(
    outcomes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Pull the structured search_upvote diagnostics (attempts/skip trace) out of
    the first job result that carries them, for the normalized envelope."""
    for item in outcomes:
        result = item.get("result") or {}
        results = result.get("results") if isinstance(result, dict) else None
        if not results or not isinstance(results[0], dict):
            continue
        details = results[0].get("details")
        if isinstance(details, dict) and details.get("attempts"):
            return details
    return None


def _poll_job_outcomes(
    args: argparse.Namespace,
    job_ids: list[int],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    outcomes = [_job_outcome(args, job_id) for job_id in job_ids]
    while outcomes and not all(_terminal_job_status(item.get("status")) for item in outcomes):
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_interval_seconds)
        outcomes = [_job_outcome(args, job_id) for job_id in job_ids]
    return outcomes


def _print_external_search_upvote(payload: dict[str, Any]) -> None:
    data = payload.get("data", {})
    print("External search-upvote" + ("" if payload.get("ok") else " (failed)"))
    _print_kv(
        [
            ("ok", payload.get("ok")),
            ("query", data.get("query")),
            ("schedule registered", data.get("scheduleIdRegistered") or data.get("scheduleId")),
            ("schedule processed", data.get("scheduleIdProcessed")),
            ("links", data.get("linksPath")),
            ("jobs", ",".join(str(job_id) for job_id in data.get("jobIds", []))),
            ("selected post", data.get("selectedPostUrl")),
            ("mutation", data.get("mutationStatus")),
            ("error", payload.get("error")),
        ]
    )
    diagnostics = data.get("diagnostics") or []
    if diagnostics:
        print("\nDiagnostics")
        _print_table(
            ["code", "message"],
            [[item.get("code"), item.get("message")] for item in diagnostics],
        )
    results = data.get("jobResults") or []
    if results:
        print("\nJobs")
        _print_table(
            ["id", "status", "action", "link", "error"],
            [
                [
                    item.get("id"),
                    item.get("status"),
                    item.get("action"),
                    item.get("link"),
                    item.get("lastError"),
                ]
                for item in results
            ],
        )
    selection = data.get("selectionDetails") or {}
    attempts = selection.get("attempts") if isinstance(selection, dict) else None
    if attempts:
        print("\nSelection attempts")
        _print_table(
            ["#", "outcome", "reason", "ageDays", "tries", "url"],
            [
                [
                    a.get("index"),
                    a.get("outcome"),
                    a.get("reason"),
                    a.get("ageDays"),
                    a.get("voteAttempts"),
                    a.get("url"),
                ]
                for a in attempts
            ],
        )


def command_external_search_upvote(args: argparse.Namespace) -> int:
    """Register and optionally execute a one-shot search_upvote schedule."""
    if not args.query.strip():
        payload = _envelope(
            "external-search-upvote",
            ok=False,
            error="Provide a non-empty --query.",
            data={"query": args.query},
        )
        _json_or_table(args, payload, _print_external_search_upvote)
        return 2

    at = args.at or utc_now().replace(microsecond=0).isoformat()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    data: dict[str, Any] = {
        "query": args.query,
        "scheduleId": None,
        "scheduleIdRegistered": None,
        "scheduleIdProcessed": None,
        "scheduleIdsProcessed": [],
        "linksPath": None,
        "scheduledFor": at,
        "diagnostics": [],
        "jobIds": [],
        "jobResults": [],
        "selectedPostUrl": None,
        "selectionDetails": None,
        "mutationStatus": "not_run",
        "idempotency": {"reusedExistingJob": False},
    }

    preflight = None
    resolved_identity = None
    if not args.no_run_due and not args.no_profile_preflight:
        try:
            preflight = _profile_preflight(args)
            resolved_identity = preflight.get("resolvedIdentity")
            data["profilePreflight"] = preflight
        except CliError as exc:
            data["mutationStatus"] = "blocked_before_registration"
            data["diagnostics"].append(
                {
                    "code": "profile_preflight_failed",
                    "message": str(exc),
                }
            )
            payload = _envelope(
                "external-search-upvote",
                ok=False,
                error=str(exc),
                data=data,
            )
            _json_or_table(args, payload, _print_external_search_upvote)
            return 2

    if resolved_identity is None:
        try:
            resolved_identity = _agentctl_payload(args, ["profiles", "resolve", *_identity_args(args)])
        except CliError:
            resolved_identity = {}

    schedule_id = args.id or _external_search_schedule_id(
        args.query,
        resolved_identity,
        at,
        args.dedupe_window_seconds,
    )
    data["scheduleId"] = schedule_id
    data["scheduleIdRegistered"] = schedule_id
    data["resolvedIdentity"] = resolved_identity

    if not args.id and not args.no_run_due:
        window_start, window_end, window_bucket = _external_schedule_window(
            at,
            args.dedupe_window_seconds,
        )
        data["idempotency"]["windowStart"] = window_start.isoformat()
        data["idempotency"]["windowEnd"] = window_end.isoformat()
        data["idempotency"]["windowBucket"] = window_bucket
        existing = _find_matching_search_upvote_job(
            args,
            account=(resolved_identity or {}).get("accountLabel") or "",
            query=args.query,
            window_start=window_start,
            window_end=window_end,
        )
        if existing and existing.get("status") == "succeeded":
            data["idempotency"]["reusedExistingJob"] = True
            data["jobIds"] = [existing["id"]]
            data["jobResults"] = [existing]
            data["selectedPostUrl"] = _selected_post_url_from_outcomes(args, [existing])
            data["selectionDetails"] = _selection_details_from_outcomes([existing])
            data["mutationStatus"] = "succeeded"
            payload = _envelope("external-search-upvote", data=data)
            return _json_or_table(args, payload, _print_external_search_upvote)

    subreddit = (getattr(args, "subreddit", "") or "").strip().strip("/")
    if subreddit.lower().startswith("r/"):
        subreddit = subreddit[2:]
    data["subreddit"] = subreddit or None

    actions_dir = Path(args.actions_dir).expanduser().resolve()
    actions_dir.mkdir(parents=True, exist_ok=True)
    links_path = actions_dir / f"{schedule_id}.txt"
    if subreddit:
        # JSON action file so the subreddit scope threads through to the worker;
        # the pipe format has no positional slot for it.
        entry = {"link": args.query, "action": "search_upvote", "subreddit": subreddit}
        links_path.write_text(json.dumps([entry], indent=2) + "\n", encoding="utf-8")
    else:
        links_path.write_text(f"{args.query}|search_upvote\n", encoding="utf-8")
    data["linksPath"] = str(links_path)

    register_command = [
        "schedules",
        "register",
        "--id",
        schedule_id,
        "--name",
        args.name or f"External search_upvote {timestamp}",
        "--source",
        args.source,
        "--rrule",
        f"DTSTART:{_parse_at(at).strftime('%Y%m%dT%H%M%S')}\nRRULE:FREQ=DAILY;COUNT=1",
        "--status",
        "ACTIVE",
        "--action-class",
        "live",
        "--links",
        str(links_path),
        "--next-run-at",
        at,
        *_schedule_identity_args(args),
    ]
    if not args.ensure_executor:
        register_command.append("--no-ensure-executor")

    try:
        registration = _agentctl_payload(args, register_command)
    except CliError as exc:
        payload = _envelope(
            "external-search-upvote",
            ok=False,
            error=str(exc),
            data=data,
        )
        _json_or_table(args, payload, _print_external_search_upvote)
        return 2
    data["registration"] = registration
    data["resolvedIdentity"] = registration.get("resolvedIdentity") or resolved_identity
    executor = registration.get("executor") or {}
    if executor.get("error"):
        data["diagnostics"].append(
            {
                "code": "executor_ensure_failed",
                "message": executor.get("hint") or executor.get("error"),
            }
        )

    if args.no_run_due:
        payload = _envelope("external-search-upvote", data=data)
        return _json_or_table(args, payload, _print_external_search_upvote)

    if preflight is not None:
        data["profilePreflight"] = preflight

    run_due_command = [
        "schedules",
        "run-due",
        "--id",
        schedule_id,
        "--now",
        args.run_due_now or utc_now().replace(microsecond=0).isoformat(),
        "--limit",
        str(args.limit),
        "--priority",
        str(args.priority),
        "--run-worker",
    ]
    if args.verbose:
        run_due_command.append("--verbose")
    run_due = _agentctl_payload(args, run_due_command)
    data["runDue"] = run_due
    data["diagnostics"].extend(run_due.get("diagnostics") or [])
    data["scheduleIdsProcessed"] = [item.get("id") for item in run_due.get("processed", [])]
    data["scheduleIdProcessed"] = data["scheduleIdsProcessed"][0] if data["scheduleIdsProcessed"] else None

    job_ids = [int(job_id) for item in run_due.get("processed", []) for job_id in item.get("jobIds", []) if job_id is not None]
    data["jobIds"] = job_ids
    if not job_ids:
        data["mutationStatus"] = "no_due_job"
        payload = _envelope(
            "external-search-upvote",
            ok=False,
            error="No queue job was produced by the due schedule run.",
            data=data,
        )
        _json_or_table(args, payload, _print_external_search_upvote)
        return 1

    outcomes = _poll_job_outcomes(
        args,
        job_ids,
        timeout_seconds=args.timeout,
        poll_interval_seconds=args.poll_interval,
    )
    data["jobResults"] = outcomes
    data["selectedPostUrl"] = _selected_post_url_from_outcomes(args, outcomes)
    data["selectionDetails"] = _selection_details_from_outcomes(outcomes)
    if all(item.get("status") == "succeeded" for item in outcomes):
        data["mutationStatus"] = "succeeded"
        payload = _envelope("external-search-upvote", data=data)
        return _json_or_table(args, payload, _print_external_search_upvote)

    if any(item.get("status") == "running" for item in outcomes):
        data["mutationStatus"] = "timed_out_running"
        data["diagnostics"].append(
            {
                "code": "job_still_running",
                "message": (
                    "A job is still running. If it remains locked after its lease expires, "
                    "run `reddit-tool queue recover-stale` before retrying."
                ),
            }
        )
    elif any(item.get("status") == "queued" for item in outcomes):
        data["mutationStatus"] = "queued_not_processed"
    else:
        data["mutationStatus"] = "failed"

    payload = _envelope(
        "external-search-upvote",
        ok=False,
        error="Scheduled search_upvote did not complete successfully.",
        data=data,
    )
    _json_or_table(args, payload, _print_external_search_upvote)
    return 1


def _print_job(payload: dict[str, Any]) -> None:
    data = payload.get("data", {})
    if not data.get("found"):
        print(f"Job {data.get('id')} not found.")
        return
    _print_kv(
        [
            ("id", data.get("id")),
            ("status", data.get("status")),
            ("account", data.get("account")),
            ("action", data.get("action")),
            ("link", data.get("link")),
            ("attempts", f"{data.get('attempts')}/{data.get('maxAttempts')}"),
            ("error", data.get("lastError")),
        ]
    )
    if data.get("result"):
        print("\nResult")
        print(json.dumps(data["result"], indent=2, sort_keys=True))


def command_job(args: argparse.Namespace) -> int:
    payload = _envelope("job", data=_job_outcome(args, args.id))
    payload["ok"] = payload["data"].get("found", False)
    return _json_or_table(args, payload, _print_job)


def _menu_args(args: argparse.Namespace, **overrides: Any) -> argparse.Namespace:
    data: dict[str, Any] = {
        "config": getattr(args, "config", None),
        "db_path": getattr(args, "db_path", None),
        "json": False,
    }
    data.update(overrides)
    return argparse.Namespace(**data)


def _prompt(label: str, *, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _prompt_required(label: str) -> str:
    while True:
        value = _prompt(label)
        if value:
            return value
        print("Required.")


def _prompt_yes_no(label: str, *, default: bool = False) -> bool:
    default_text = "Y/n" if default else "y/N"
    value = input(f"{label} [{default_text}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes"}


def _prompt_menu_choice(label: str, choices: set[str]) -> str:
    while True:
        value = _prompt(label)
        if value in choices:
            return value
        print(f"Choose one of: {', '.join(sorted(choices))}")


def _identity_prompt() -> dict[str, str | None]:
    raw = _prompt("Identity blank=default, or account:<label>, profile:<name>, reddit:<user>")
    identity = {"account_label": None, "profile_name": None, "reddit_user": None}
    if not raw:
        return identity
    if raw.startswith("account:"):
        identity["account_label"] = raw.removeprefix("account:").strip()
    elif raw.startswith("profile:"):
        identity["profile_name"] = raw.removeprefix("profile:").strip()
    elif raw.startswith("reddit:"):
        identity["reddit_user"] = raw.removeprefix("reddit:").strip()
    else:
        identity["reddit_user"] = raw
    return identity


def _pause() -> None:
    input("\nPress Enter to continue...")


def _menu_overview(args: argparse.Namespace) -> None:
    command_overview(_menu_args(args))


def _menu_capabilities(args: argparse.Namespace) -> None:
    command_capabilities(_menu_args(args))


def _menu_schedules(args: argparse.Namespace) -> None:
    command_schedule_list(_menu_args(args, include_crontab=False, all_codex=False, limit=50))


def _menu_queue(args: argparse.Namespace) -> None:
    status = _prompt("Queue status filter blank=all")
    command_queue_list(_menu_args(args, status=status or None, limit=25))


def _menu_job(args: argparse.Namespace) -> None:
    job_id = int(_prompt_required("Queue job id"))
    command_job(_menu_args(args, id=job_id))


def _menu_executor(args: argparse.Namespace) -> None:
    command_executor(
        _menu_args(
            args,
            executor_action="status",
            executor_interval=15.0,
            start_interval=60,
            allow_pid_fallback=False,
        )
    )


def _menu_errors(args: argparse.Namespace) -> None:
    limit = int(_prompt("Error limit", default="10"))
    command_errors(_menu_args(args, limit=limit))


def _menu_profiles(args: argparse.Namespace) -> None:
    command_profiles(_menu_args(args))


def _menu_limits(args: argparse.Namespace) -> None:
    command_limits_list(_menu_args(args, limit=100))


def _menu_add_schedule(args: argparse.Namespace) -> None:
    name = _prompt_required("Schedule name")
    source_choice = _prompt_menu_choice(
        "Action source 1=single link/action, 2=existing links file",
        {"1", "2"},
    )
    links = ""
    link = ""
    action = ""
    comment = ""
    if source_choice == "1":
        link = _prompt_required("Reddit URL")
        action = _prompt_required("Action")
        comment = _prompt("Comment/body optional")
    else:
        links = _prompt_required("Links/action file path")

    schedule_choice = _prompt_menu_choice(
        "Schedule 1=one time, 2=daily, 3=weekly, 4=raw RRULE",
        {"1", "2", "3", "4"},
    )
    at = daily_at = weekly = rrule = next_run_at = ""
    time_value = "09:00"
    if schedule_choice == "1":
        at = _prompt_required("Run at ISO datetime")
    elif schedule_choice == "2":
        daily_at = _prompt_required("Daily time HH:MM")
    elif schedule_choice == "3":
        weekly = _prompt_required("Weekdays, for example MO,WE,FR")
        time_value = _prompt("Time HH:MM", default="09:00")
    else:
        rrule = _prompt_required("RRULE")
        next_run_at = _prompt("First run ISO datetime optional")

    identity = _identity_prompt()
    ensure_executor = _prompt_yes_no("Ensure executor after registering", default=True)
    command_schedule_add(
        _menu_args(
            args,
            id=None,
            name=name,
            source="reddit-tool",
            status="ACTIVE",
            action_class="live",
            links=links,
            link=link,
            action=action,
            comment=comment,
            actions_dir=str(DEFAULT_ACTIONS_DIR),
            rrule=rrule,
            next_run_at=next_run_at,
            at=at,
            daily_at=daily_at,
            weekly=weekly,
            time=time_value,
            no_ensure_executor=not ensure_executor,
            **identity,
        )
    )


def _menu_submit_queue(args: argparse.Namespace) -> None:
    links = _prompt_required("Links/action file path")
    identity = _identity_prompt()
    run_worker = _prompt_yes_no("Run one worker pass now", default=False)
    command_queue_add(
        _menu_args(
            args,
            links=links,
            priority=100,
            scheduled_for="",
            max_attempts=3,
            run_worker=run_worker,
            **identity,
        )
    )


def _menu_run_due(args: argparse.Namespace) -> None:
    run_worker = _prompt_yes_no("Run queue worker for due schedules", default=False)
    command_schedule_run_due(
        _menu_args(
            args,
            now="",
            limit=1,
            priority=100,
            run_worker=run_worker,
            verbose=False,
        )
    )


def _menu_ensure_executor(args: argparse.Namespace) -> None:
    command_executor(
        _menu_args(
            args,
            executor_action="ensure",
            executor_interval=15.0,
            start_interval=60,
            allow_pid_fallback=False,
        )
    )


def command_menu(args: argparse.Namespace) -> int:
    actions = {
        "1": ("Overview", _menu_overview),
        "2": ("Capabilities", _menu_capabilities),
        "3": ("Schedules", _menu_schedules),
        "4": ("Queue", _menu_queue),
        "5": ("Job status", _menu_job),
        "6": ("Executor status", _menu_executor),
        "7": ("Recent errors", _menu_errors),
        "8": ("Profiles", _menu_profiles),
        "9": ("Limits", _menu_limits),
        "10": ("Add schedule", _menu_add_schedule),
        "11": ("Submit queue file", _menu_submit_queue),
        "12": ("Run due schedules", _menu_run_due),
        "13": ("Ensure executor", _menu_ensure_executor),
        "0": ("Quit", None),
    }
    while True:
        print("\nReddit Bot Menu")
        for key, (label, _) in actions.items():
            print(f"{key}. {label}")
        choice = _prompt("Choose")
        if choice == "0":
            return 0
        action = actions.get(choice)
        if action is None:
            print("Unknown choice.")
            continue
        print()
        try:
            action_func = action[1]
            if action_func is not None:
                action_func(args)
        except CliError as exc:
            print(f"Error: {exc}")
        _pause()


def _add_identity_options(parser: argparse.ArgumentParser) -> None:
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument("--reddit-user", help=f"Reddit username. Defaults to {DEFAULT_REDDIT_USER}.")
    identity.add_argument("--profile-name", help=f"Chrome profile name. Default profile is {DEFAULT_PROFILE_NAME}.")
    identity.add_argument("--account-label", help="Execution account label.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reddit-tool",
        description="Small human-friendly CLI for Reddit bot schedules, queues, executor, and errors.",
    )
    parser.add_argument("--config", help="Path to YAML configuration file.")
    parser.add_argument("--db-path", help="Override BotConfig.db_path.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of readable tables.")
    parser.set_defaults(func=command_overview)

    subparsers = parser.add_subparsers(dest="command")

    menu_parser = subparsers.add_parser("menu", help="Open an interactive terminal menu.")
    menu_parser.set_defaults(func=command_menu)

    overview_parser = subparsers.add_parser("overview", help="Show queue, schedule, executor, profile, and error summary.")
    overview_parser.set_defaults(func=command_overview)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Read-only diagnostics for why the bot cannot act (DB, Chrome, queue, executor).",
    )
    doctor_parser.add_argument(
        "--debug-address",
        default="",
        help="Override Chrome DevTools address to probe (default: resolved identity or 127.0.0.1:9222).",
    )
    _add_identity_options(doctor_parser)
    doctor_parser.set_defaults(func=command_doctor)

    capabilities_parser = subparsers.add_parser(
        "capabilities",
        help="Print the machine-readable action schema, URL contract, and defaults.",
    )
    capabilities_parser.add_argument("action_name", nargs="?", help="Optional action name to describe.")
    capabilities_parser.set_defaults(func=command_capabilities, command_name="capabilities")

    describe_parser = subparsers.add_parser(
        "describe",
        help="Describe one action, or print all capabilities if no action is provided.",
    )
    describe_parser.add_argument("action_name", nargs="?", help="Action name to describe.")
    describe_parser.set_defaults(func=command_capabilities, command_name="describe")

    resolve_url_parser = subparsers.add_parser(
        "resolve-url",
        help="Resolve a Reddit /r/.../s/... share shortlink to a canonical /comments/ URL.",
    )
    resolve_url_parser.add_argument(
        "--link",
        required=True,
        help="Reddit URL (share shortlink or already-canonical post URL).",
    )
    resolve_url_parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="HTTP timeout in seconds when following share redirects (default: 15).",
    )
    resolve_url_parser.set_defaults(func=command_resolve_url)

    do_parser = subparsers.add_parser(
        "do",
        help="Run one action end to end from inline args (submit + one worker pass).",
    )
    do_parser.add_argument("--action", required=True, choices=sorted(ACTION_SCHEMA), help="Action to perform.")
    do_parser.add_argument("--link", help="Target Reddit URL (canonical /comments/ URL for post actions).")
    do_parser.add_argument("--comment", help="Comment body for the `comment` action.")
    do_parser.add_argument("--title", help="Post title, or DM subject.")
    do_parser.add_argument("--subreddit", help="Destination community for post/crosspost actions.")
    do_parser.add_argument("--body", help="Post text, or URL/image-path/bio depending on the action.")
    do_parser.add_argument("--flair", help="Optional post flair.")
    do_parser.add_argument("--recipient", help="Recipient username for `dm`.")
    do_parser.add_argument("--message", help="Message body for `dm`.")
    do_parser.add_argument("--query", help="Search query for query-based actions (alias for --link).")
    do_parser.add_argument(
        "--actions-dir",
        default=str(DEFAULT_ACTIONS_DIR),
        help="Directory for the generated action file.",
    )
    do_parser.add_argument("--no-run", action="store_true", help="Queue the action but do not run the worker pass.")
    do_parser.add_argument(
        "--no-profile-preflight",
        action="store_true",
        help="Skip Chrome profile validation before running the worker.",
    )
    do_parser.add_argument(
        "--no-open-profile",
        action="store_true",
        help="Validate Chrome DevTools but do not open the saved profile if it is down.",
    )
    _add_identity_options(do_parser)
    do_parser.set_defaults(func=command_do)

    search_upvote_parser = subparsers.add_parser(
        "search-upvote",
        aliases=["search-then-upvote"],
        help="Search Reddit and upvote the post selected by the search action.",
    )
    search_upvote_parser.add_argument("--query", required=True, help="Reddit search query.")
    search_upvote_parser.add_argument("--link", help=argparse.SUPPRESS)
    search_upvote_parser.add_argument("--subreddit", help="Optional subreddit scope.")
    search_upvote_parser.add_argument(
        "--actions-dir",
        default=str(DEFAULT_ACTIONS_DIR),
        help="Directory for the generated action file.",
    )
    search_upvote_parser.add_argument("--no-run", action="store_true", help="Queue the action but do not run the worker pass.")
    search_upvote_parser.add_argument(
        "--no-profile-preflight",
        action="store_true",
        help="Skip Chrome profile validation before running the worker.",
    )
    search_upvote_parser.add_argument(
        "--no-open-profile",
        action="store_true",
        help="Validate Chrome DevTools but do not open the saved profile if it is down.",
    )
    _add_identity_options(search_upvote_parser)
    search_upvote_parser.set_defaults(func=command_search_upvote)

    external_search_parser = subparsers.add_parser(
        "external-search-upvote",
        aliases=["external-schedule-search-upvote"],
        help="External-project friendly one-shot schedule + run + normalized result for search_upvote.",
    )
    external_search_parser.add_argument("--query", required=True, help="Reddit search query.")
    external_search_parser.add_argument(
        "--subreddit",
        default="",
        help="Optional subreddit to scope the search to (e.g. 'excel' or 'r/excel').",
    )
    external_search_parser.add_argument("--id", help="Schedule id. Defaults to a generated external-search-upvote id.")
    external_search_parser.add_argument("--name", help="Human-readable schedule name.")
    external_search_parser.add_argument("--source", default="external-project")
    external_search_parser.add_argument("--at", help="One-time run at ISO datetime. Defaults to now in UTC.")
    external_search_parser.add_argument("--run-due-now", default="", help="Override scheduler run time as ISO datetime.")
    external_search_parser.add_argument(
        "--actions-dir",
        default=str(DEFAULT_ACTIONS_DIR),
        help="Directory for generated action files.",
    )
    external_search_parser.add_argument("--priority", type=int, default=100)
    external_search_parser.add_argument("--limit", type=int, default=1)
    external_search_parser.add_argument("--timeout", type=float, default=30.0, help="Seconds to poll for terminal job result.")
    external_search_parser.add_argument("--poll-interval", type=float, default=1.0)
    external_search_parser.add_argument(
        "--dedupe-window-seconds",
        type=int,
        default=600,
        help="Reuse the generated schedule/job identity for retries in this time window.",
    )
    external_search_parser.add_argument("--ensure-executor", action="store_true", help="Also try to ensure the background executor.")
    external_search_parser.add_argument(
        "--no-run-due",
        action="store_true",
        help="Only register the schedule; do not run due work now.",
    )
    external_search_parser.add_argument(
        "--no-profile-preflight",
        action="store_true",
        help="Skip Chrome DevTools validation before running due work.",
    )
    external_search_parser.add_argument(
        "--no-open-profile",
        action="store_true",
        help="Validate Chrome DevTools but do not open the saved profile if it is down.",
    )
    external_search_parser.add_argument("--verbose", action="store_true")
    _add_identity_options(external_search_parser)
    external_search_parser.set_defaults(func=command_external_search_upvote)

    job_parser = subparsers.add_parser("job", help="Show one queue job's status and stored result by id.")
    job_parser.add_argument("--id", type=int, required=True, help="Queue job id (from `do`, `queue add`, or `queue`).")
    job_parser.set_defaults(func=command_job)

    schedules_parser = subparsers.add_parser("schedules", help="List project schedules.")
    schedules_parser.add_argument("--include-crontab", action="store_true")
    schedules_parser.add_argument("--all-codex", action="store_true", help="Include Codex automations outside this repo.")
    schedules_parser.add_argument("--limit", type=int, default=50)
    schedules_parser.set_defaults(func=command_schedule_list)

    schedule_parser = subparsers.add_parser("schedule", help="Manage project schedules.")
    schedule_subparsers = schedule_parser.add_subparsers(dest="schedule_action", required=True)

    schedule_list_parser = schedule_subparsers.add_parser("list", help="List project schedules.")
    schedule_list_parser.add_argument("--include-crontab", action="store_true")
    schedule_list_parser.add_argument("--all-codex", action="store_true", help="Include Codex automations outside this repo.")
    schedule_list_parser.add_argument("--limit", type=int, default=50)
    schedule_list_parser.set_defaults(func=command_schedule_list)

    schedule_add_parser = schedule_subparsers.add_parser("add", help="Register a live-action schedule through agentctl.")
    schedule_add_parser.add_argument("--id", help="Schedule id. Defaults to a generated slug.")
    schedule_add_parser.add_argument("--name", help="Human-readable schedule name.")
    schedule_add_parser.add_argument("--source", default="reddit-tool")
    schedule_add_parser.add_argument("--status", default="ACTIVE")
    schedule_add_parser.add_argument("--action-class", default="live")
    schedule_add_parser.add_argument("--links", help="Existing links/action file.")
    schedule_add_parser.add_argument("--link", help="Single Reddit URL to write into a links/action file.")
    schedule_add_parser.add_argument("--query", help="Search query for query-based actions such as search_upvote.")
    schedule_add_parser.add_argument("--action", choices=sorted(VALID_ACTIONS), help="Action for --link.")
    schedule_add_parser.add_argument("--comment", help="Optional comment/body field for pipe-delimited actions.")
    schedule_add_parser.add_argument(
        "--actions-dir",
        default=str(DEFAULT_ACTIONS_DIR),
        help="Directory for generated action files.",
    )
    schedule_add_parser.add_argument("--rrule", help="Raw RRULE text, for example FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0.")
    schedule_add_parser.add_argument("--next-run-at", default="", help="Override first run time for --rrule, as an ISO datetime.")
    schedule_add_parser.add_argument("--at", help="One-time run at ISO datetime, for example 2026-07-06T09:00:00.")
    schedule_add_parser.add_argument("--daily-at", help="Run daily at HH:MM.")
    schedule_add_parser.add_argument("--weekly", help="Run weekly on weekdays, for example MO,WE,FR.")
    schedule_add_parser.add_argument("--time", default="09:00", help="HH:MM time used with --weekly.")
    schedule_add_parser.add_argument(
        "--no-ensure-executor",
        action="store_true",
        help="Register without ensuring the local executor.",
    )
    _add_identity_options(schedule_add_parser)
    schedule_add_parser.set_defaults(func=command_schedule_add)

    schedule_run_parser = schedule_subparsers.add_parser("run-due", help="Run due schedules, optionally with one worker pass.")
    schedule_run_parser.add_argument("--now", default="")
    schedule_run_parser.add_argument("--limit", type=int, default=1)
    schedule_run_parser.add_argument("--priority", type=int, default=100)
    schedule_run_parser.add_argument("--run-worker", action="store_true")
    schedule_run_parser.add_argument("--verbose", action="store_true")
    schedule_run_parser.set_defaults(func=command_schedule_run_due)

    schedule_pause_parser = schedule_subparsers.add_parser("pause", help="Pause a registered project schedule.")
    schedule_pause_parser.add_argument("--id", required=True)
    schedule_pause_parser.set_defaults(func=command_schedule_pause)

    schedule_resume_parser = schedule_subparsers.add_parser("resume", help="Resume a paused project schedule.")
    schedule_resume_parser.add_argument("--id", required=True)
    schedule_resume_parser.set_defaults(func=command_schedule_resume)

    schedule_delete_parser = schedule_subparsers.add_parser("delete", help="Delete a registered project schedule.")
    schedule_delete_parser.add_argument("--id", required=True)
    schedule_delete_parser.set_defaults(func=command_schedule_delete)

    queue_parser = subparsers.add_parser("queue", help="List or submit queue jobs.")
    queue_parser.add_argument("--status", default=None)
    queue_parser.add_argument("--account", default="")
    queue_parser.add_argument("--limit", type=int, default=25)
    queue_parser.set_defaults(func=command_queue_list)
    queue_subparsers = queue_parser.add_subparsers(dest="queue_action")

    queue_add_parser = queue_subparsers.add_parser("add", help="Submit a links/action file to the queue.")
    queue_add_parser.add_argument("--links", required=True)
    queue_add_parser.add_argument("--priority", type=int, default=100)
    queue_add_parser.add_argument("--scheduled-for", default="")
    queue_add_parser.add_argument("--max-attempts", type=int, default=3)
    queue_add_parser.add_argument("--run-worker", action="store_true", help="Run exactly one worker pass after queueing.")
    _add_identity_options(queue_add_parser)
    queue_add_parser.set_defaults(func=command_queue_add)

    queue_run_parser = queue_subparsers.add_parser("run-once", help="Run exactly one queue worker pass.")
    queue_run_parser.add_argument("--max-jobs", type=int, default=1)
    queue_run_parser.add_argument("--verbose", action="store_true")
    queue_run_parser.set_defaults(func=command_queue_run_once)

    queue_recover_parser = queue_subparsers.add_parser("recover-stale", help="Release expired running jobs for retry.")
    queue_recover_parser.add_argument("--now", default="", help="Override current time as ISO datetime.")
    queue_recover_parser.set_defaults(func=command_queue_recover_stale)

    queue_retry_parser = queue_subparsers.add_parser("retry", help="Re-queue failed queue jobs.")
    queue_retry_group = queue_retry_parser.add_mutually_exclusive_group(required=True)
    queue_retry_group.add_argument("--id", type=int, help="Retry one failed queue job id.")
    queue_retry_group.add_argument("--all", action="store_true", help="Retry all failed queue jobs.")
    queue_retry_parser.add_argument(
        "--account",
        default=argparse.SUPPRESS,
        help="Only retry failed jobs for this account label.",
    )
    queue_retry_parser.set_defaults(func=command_queue_retry)

    executor_parser = subparsers.add_parser("executor", help="Check, ensure, or stop the local schedule executor.")
    executor_parser.add_argument("executor_action", nargs="?", choices=["status", "ensure", "stop"], default="status")
    executor_parser.add_argument("--executor-interval", type=float, default=15.0)
    executor_parser.add_argument("--start-interval", type=int, default=60)
    executor_parser.add_argument("--allow-pid-fallback", action="store_true")
    executor_parser.set_defaults(func=command_executor)

    errors_parser = subparsers.add_parser(
        "errors",
        aliases=["last-errors"],
        help="Show recent queue, schedule, action, and executor errors.",
    )
    errors_parser.add_argument("--limit", type=int, default=10)
    errors_parser.set_defaults(func=command_errors)

    profiles_parser = subparsers.add_parser("profiles", help="List saved Chrome profiles and associations.")
    profiles_parser.set_defaults(func=command_profiles)

    limits_parser = subparsers.add_parser("limits", help="List or update account quotas.")
    limits_parser.add_argument("--limit", type=int, default=100)
    limits_parser.set_defaults(func=command_limits_list)
    limits_subparsers = limits_parser.add_subparsers(dest="limits_action")
    limits_set_parser = limits_subparsers.add_parser("set", help="Set a daily action quota.")
    limits_set_parser.add_argument("--account", required=True)
    limits_set_parser.add_argument("--action", default="*")
    limits_set_parser.add_argument("--daily-action-quota", type=int, required=True)
    limits_set_parser.set_defaults(func=command_limits_set)

    return parser


def _normalize_global_flags(argv: list[str]) -> list[str]:
    """Allow wrapper global flags after subcommands for agent ergonomics."""
    bool_flags = {"--json"}
    value_flags = {"--config", "--db-path"}
    prefix: list[str] = []
    normalized: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in bool_flags:
            prefix.append(arg)
            index += 1
            continue
        if arg in value_flags and index + 1 < len(argv):
            prefix.extend([arg, argv[index + 1]])
            index += 2
            continue
        if any(arg.startswith(f"{flag}=") for flag in value_flags):
            prefix.append(arg)
            index += 1
            continue
        normalized.append(arg)
        index += 1
    return [*prefix, *normalized]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    argv = _normalize_global_flags(list(argv))
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as exc:
        parser.exit(2, f"reddit-tool: error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
