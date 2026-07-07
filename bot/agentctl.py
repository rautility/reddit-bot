"""Agent-facing control plane for safe Reddit bot orchestration."""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import platform
import plistlib
import signal
import socket
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from bot.config import BotConfig
from bot.database import BotDatabase
from bot.reporting import setup_structured_logger
from bot.utils.credentials import Account
from bot.utils.input_parser import ActionEntry, parse_links_file
from bot.utils.validators import is_post_url, is_share_url, validate_reddit_url


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_PREFIX = "Chrome Reddit Bot Debug Profile"
DEFAULT_PROFILE_NAME = "Chrome Reddit Bot Debug Profile"
DEFAULT_DEBUG_ADDRESS = "127.0.0.1:9222"
DEFAULT_EXTENSION_PATH = REPO_ROOT / "chrome_extension/reddit_healer"
EXECUTOR_DIR = REPO_ROOT / ".agent-executor"
EXECUTOR_PID_PATH = EXECUTOR_DIR / "executor.pid"
EXECUTOR_LOG_PATH = EXECUTOR_DIR / "executor.log"
EXECUTOR_LABEL = "com.raul.reddit-bot.agentctl-scheduler"
WEEKDAY_INDEX = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
CANONICAL_POST_ACTIONS = {"upvote", "downvote", "comment", "save", "hide", "award"}


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _agentctl_script_path() -> Path:
    return REPO_ROOT / "scripts" / "agentctl.py"


def _launch_agents_dir() -> Path:
    override = os.environ.get("REDDIT_BOT_LAUNCH_AGENTS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "LaunchAgents"


def _launch_agent_path() -> Path:
    return _launch_agents_dir() / f"{EXECUTOR_LABEL}.plist"


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _parse_rrule_text(rrule_text: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for raw_line in (rrule_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("DTSTART"):
            _, value = line.split(":", 1)
            parts["DTSTART"] = value
            continue
        if line.startswith("RRULE:"):
            line = line.removeprefix("RRULE:")
        for token in line.split(";"):
            if "=" in token:
                key, value = token.split("=", 1)
                parts[key.upper()] = value
    return parts


def _parse_dtstart(value: str) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _next_run_after(
    rrule_text: str,
    after: datetime,
    previous_runs: int = 0,
) -> Optional[datetime]:
    parts = _parse_rrule_text(rrule_text)
    freq = parts.get("FREQ", "").upper()
    count = int(parts["COUNT"]) if parts.get("COUNT", "").isdigit() else None
    if count is not None and previous_runs >= count:
        return None

    dtstart = _parse_dtstart(parts.get("DTSTART", "")) or after
    hour = int(parts.get("BYHOUR", dtstart.hour))
    minute = int(parts.get("BYMINUTE", dtstart.minute))
    second = int(parts.get("BYSECOND", dtstart.second))

    if freq == "DAILY":
        candidate = after.replace(hour=hour, minute=minute, second=second, microsecond=0)
        if candidate <= after:
            candidate += timedelta(days=1)
        return max(candidate, dtstart)

    if freq == "WEEKLY":
        bydays = parts.get("BYDAY")
        weekdays = (
            [WEEKDAY_INDEX[day] for day in bydays.split(",") if day in WEEKDAY_INDEX]
            if bydays
            else [dtstart.weekday()]
        )
        candidates = []
        base_date = after.date()
        for offset in range(0, 8):
            day = base_date + timedelta(days=offset)
            if day.weekday() not in weekdays:
                continue
            candidate = datetime.combine(day, datetime.min.time()).replace(
                hour=hour,
                minute=minute,
                second=second,
            )
            if candidate > after and candidate >= dtstart:
                candidates.append(candidate)
        return min(candidates) if candidates else None

    raise ValueError(f"Unsupported schedule frequency: {freq or '<missing>'}")


def _load_config(args: argparse.Namespace) -> BotConfig:
    config = BotConfig.from_yaml(args.config) if args.config else BotConfig()
    config.merge_env_vars()
    if args.db_path:
        config.db_path = args.db_path
    return config


def _open_db(args: argparse.Namespace) -> BotDatabase:
    return BotDatabase(_load_config(args).db_path)


def _profile_search_root() -> Path:
    return Path.home() / "Library/Application Support"


def discover_saved_profiles() -> list[dict[str, Any]]:
    """Return saved Chrome user-data dirs that match this project's convention."""
    root = _profile_search_root()
    profiles = []
    if not root.exists():
        return profiles

    for index, profile_path in enumerate(sorted(root.glob(f"{DEFAULT_PROFILE_PREFIX}*"))):
        profile_name = profile_path.name
        suggested_port = 9222 + index
        profiles.append(
            {
                "profileName": profile_name,
                "profilePath": str(profile_path),
                "suggestedDebugAddress": f"127.0.0.1:{suggested_port}",
                "isDefault": profile_name == DEFAULT_PROFILE_NAME,
            }
        )
    return profiles


def _profile_by_name(profile_name: str) -> Optional[dict[str, Any]]:
    for profile in discover_saved_profiles():
        if profile["profileName"] == profile_name:
            return profile
    return None


def _association_for_profile(
    associations: list[dict[str, Any]],
    profile_name: str,
) -> Optional[dict[str, Any]]:
    return next(
        (
            association
            for association in associations
            if association["profile_name"] == profile_name
        ),
        None,
    )


def discover_profiles_with_associations(db: BotDatabase) -> list[dict[str, Any]]:
    """Return discovered profiles annotated with persisted Reddit account data."""
    associations = db.list_chrome_profile_associations()
    profiles = discover_saved_profiles()
    seen_profile_names = set()
    for profile in profiles:
        seen_profile_names.add(profile["profileName"])
        association = _association_for_profile(associations, profile["profileName"])
        if association:
            profile["redditUsername"] = association["reddit_username"]
            profile["accountLabel"] = association["account_label"]
            profile["configuredDebugAddress"] = association["debug_address"]

    for association in associations:
        if association["profile_name"] in seen_profile_names:
            continue
        profiles.append(
            {
                "profileName": association["profile_name"],
                "profilePath": association["profile_path"],
                "suggestedDebugAddress": association["debug_address"],
                "configuredDebugAddress": association["debug_address"],
                "isDefault": association["profile_name"] == DEFAULT_PROFILE_NAME,
                "redditUsername": association["reddit_username"],
                "accountLabel": association["account_label"],
                "missingLocalProfile": True,
            }
        )
    return profiles


def _resolve_profile_identity(
    db: BotDatabase,
    *,
    account_label: Optional[str] = None,
    profile_name: Optional[str] = None,
    reddit_user: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve account/profile identity from an explicit label, profile, or user."""
    association = None
    if profile_name:
        association = db.get_chrome_profile_association(profile_name=profile_name)
        if association is None:
            profile = _profile_by_name(profile_name)
            if profile is None:
                raise SystemExit(f"Unknown Chrome profile: {profile_name}")
            return {
                "accountLabel": account_label or profile_name,
                "profileName": profile_name,
                "profilePath": profile["profilePath"],
                "debugAddress": profile["suggestedDebugAddress"],
                "redditUsername": None,
                "associationFound": False,
            }
    elif reddit_user:
        association = db.get_chrome_profile_association(reddit_username=reddit_user)
        if association is None:
            raise SystemExit(
                f"Unknown Reddit username association: {reddit_user}. "
                "Run `agentctl profiles associate` first."
            )
    elif account_label:
        association = db.get_chrome_profile_association(account_label=account_label)

    if association:
        return {
            "accountLabel": account_label or association["account_label"],
            "profileName": association["profile_name"],
            "profilePath": association["profile_path"],
            "debugAddress": association["debug_address"],
            "redditUsername": association["reddit_username"],
            "associationFound": True,
        }

    if account_label:
        return {
            "accountLabel": account_label,
            "profileName": None,
            "profilePath": None,
            "debugAddress": None,
            "redditUsername": None,
            "associationFound": False,
        }

    raise SystemExit("Provide --account-label, --profile-name, or --reddit-user.")


def probe_debug_address(address: str, timeout: float = 2.0) -> dict[str, Any]:
    """Probe a Chrome DevTools endpoint without mutating browser state."""
    endpoint = address if address.startswith(("http://", "https://")) else f"http://{address}"
    endpoint = endpoint.rstrip("/") + "/json/version"
    try:
        with urlopen(endpoint, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {
            "ok": True,
            "debugAddress": address.replace("http://", "").replace("https://", ""),
            "endpoint": endpoint,
            "browser": payload.get("Browser"),
            "protocolVersion": payload.get("Protocol-Version"),
            "webSocketDebuggerUrl": payload.get("webSocketDebuggerUrl"),
        }
    except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        error = str(exc)
        result = {
            "ok": False,
            "debugAddress": address,
            "endpoint": endpoint,
            "error": error,
        }
        if "Operation not permitted" in error or "Errno 1" in error:
            result["hint"] = (
                "Chrome may be reachable from the host, but this process is sandboxed "
                "from local DevTools/loopback. Rerun with local DevTools access."
            )
        return result


def _parse_toml_scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text.strip('"')


def _read_codex_automations() -> list[dict[str, Any]]:
    automation_root = Path.home() / ".codex/automations"
    automations = []
    if not automation_root.exists():
        return automations

    for path in sorted(automation_root.glob("*/automation.toml")):
        item: dict[str, Any] = {"path": str(path)}
        try:
            for raw_line in path.read_text().splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key in {"id", "kind", "name", "status", "rrule", "model"}:
                    item[key] = _parse_toml_scalar(value)
                elif key == "cwds":
                    item[key] = _parse_toml_scalar(value)
        except OSError as exc:
            item["error"] = str(exc)
        automations.append(item)
    return automations


def _read_crontab() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["crontab", "-l"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "error": str(exc)}

    if completed.returncode != 0:
        return {"available": False, "error": completed.stderr.strip()}
    return {
        "available": True,
        "entries": [
            line
            for line in completed.stdout.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ],
    }


def _action_entry_from_payload(payload_json: str) -> ActionEntry:
    payload = json.loads(payload_json)
    allowed = {
        "link",
        "action",
        "comment",
        "title",
        "subreddit",
        "body",
        "flair",
        "recipient",
        "message",
    }
    return ActionEntry(**{key: payload.get(key) for key in allowed if key in payload})


def _validate_canonical_post_actions(entries: list[ActionEntry]) -> list[dict[str, Any]]:
    errors = []
    for index, entry in enumerate(entries, start=1):
        action = (entry.action or "").strip().lower()
        if action not in CANONICAL_POST_ACTIONS:
            continue
        link = (entry.link or "").strip()
        if not validate_reddit_url(link):
            errors.append(
                {
                    "line": index,
                    "link": link,
                    "action": action,
                    "error": "Post action requires a valid reddit.com URL.",
                }
            )
            continue
        if is_share_url(link):
            errors.append(
                {
                    "line": index,
                    "link": link,
                    "action": action,
                    "error": (
                        "Reddit share links must be resolved before scheduling. "
                        "Use the canonical /r/<subreddit>/comments/<post_id>/... URL."
                    ),
                }
            )
            continue
        if not is_post_url(link):
            errors.append(
                {
                    "line": index,
                    "link": link,
                    "action": action,
                    "error": (
                        "Post action requires a canonical Reddit post URL matching "
                        "/r/<subreddit>/comments/<post_id>/..."
                    ),
                }
            )
    return errors


def _parse_agent_links_file(path: str) -> tuple[list[ActionEntry], list[dict[str, Any]]]:
    entries = parse_links_file(path)
    return entries, _validate_canonical_post_actions(entries)


def _summary_payload(summary: Any) -> dict[str, Any]:
    return {
        "total": summary.total,
        "succeeded": summary.succeeded,
        "failed": summary.failed,
        "results": [asdict(result) for result in summary.results],
    }


def command_status(args: argparse.Namespace) -> int:
    config = _load_config(args)
    db = BotDatabase(config.db_path)
    try:
        payload = {
            "cwd": str(REPO_ROOT),
            "dbPath": config.db_path,
            "queueCounts": db.get_queue_counts(),
            "activeLeases": db.list_leases(),
            "accountLimits": db.list_account_limits(),
            "profileAccountAssociations": db.list_chrome_profile_associations(),
            "registeredSchedules": db.list_registered_schedules(),
            "executor": executor_status(),
            "codexAutomations": _read_codex_automations(),
            "crontab": _read_crontab() if args.include_crontab else {"checked": False},
            "savedChromeProfiles": discover_profiles_with_associations(db),
            "defaultChromeDebugAddress": DEFAULT_DEBUG_ADDRESS,
            "healerExtensionPath": str(DEFAULT_EXTENSION_PATH),
            "liveActionPolicy": (
                "Agents should register scheduled live Reddit mutations with "
                "agentctl schedules register --links or submit immediate live "
                "mutations through agentctl queue; manual direct main.py runs "
                "remain supported for owner-controlled use."
            ),
        }
    finally:
        db.close()
    _print_json(payload)
    return 0


def command_profiles_list(args: argparse.Namespace) -> int:
    db = _open_db(args)
    try:
        payload = {
            "profiles": discover_profiles_with_associations(db),
            "associations": db.list_chrome_profile_associations(),
        }
    finally:
        db.close()
    _print_json(payload)
    return 0


def command_profiles_probe(args: argparse.Namespace) -> int:
    _print_json(probe_debug_address(args.debug_address, timeout=args.timeout))
    return 0


def command_profiles_associate(args: argparse.Namespace) -> int:
    db = _open_db(args)
    try:
        profile = _profile_by_name(args.profile_name)
        profile_path = args.profile_path or (profile or {}).get("profilePath")
        debug_address = (
            args.debug_address
            or (profile or {}).get("suggestedDebugAddress")
            or DEFAULT_DEBUG_ADDRESS
        )
        association = db.associate_chrome_profile(
            args.profile_name,
            args.reddit_user,
            profile_path=profile_path,
            debug_address=debug_address,
            account_label=args.account_label,
        )
        payload = {
            "association": association,
            "profiles": discover_profiles_with_associations(db),
        }
    finally:
        db.close()
    _print_json(payload)
    return 0


def command_profiles_resolve(args: argparse.Namespace) -> int:
    db = _open_db(args)
    try:
        payload = _resolve_profile_identity(
            db,
            account_label=args.account_label,
            profile_name=args.profile_name,
            reddit_user=args.reddit_user,
        )
    finally:
        db.close()
    _print_json(payload)
    return 0


def command_schedules_list(args: argparse.Namespace) -> int:
    db = _open_db(args)
    try:
        payload = {
            "registeredSchedules": db.list_registered_schedules(),
            "codexAutomations": _read_codex_automations(),
            "crontab": _read_crontab() if args.include_crontab else {"checked": False},
        }
    finally:
        db.close()
    _print_json(payload)
    return 0


def command_schedules_register(args: argparse.Namespace) -> int:
    link_errors: list[dict[str, Any]] = []
    if args.links:
        _, link_errors = _parse_agent_links_file(args.links)
    if link_errors:
        _print_json(
            {
                "registered": None,
                "ok": False,
                "error": "Links file contains unsupported Reddit URL formats.",
                "linkErrors": link_errors,
            }
        )
        return 2

    db = _open_db(args)
    try:
        if args.account or args.profile_name or args.profile or args.reddit_user:
            identity = _resolve_profile_identity(
                db,
                account_label=args.account,
                profile_name=args.profile_name or args.profile,
                reddit_user=args.reddit_user,
            )
        else:
            identity = {
                "accountLabel": "",
                "profileName": "",
                "profilePath": "",
                "debugAddress": "",
                "redditUsername": "",
                "associationFound": False,
            }
        metadata = {
            "redditUsername": identity["redditUsername"],
            "profilePath": identity["profilePath"],
            "debugAddress": identity["debugAddress"],
            "associationFound": identity["associationFound"],
        }
        if args.links:
            metadata["linksPath"] = str(Path(args.links).expanduser().resolve())
        next_run_at = args.next_run_at
        if not next_run_at and args.rrule:
            next_run = _next_run_after(
                args.rrule,
                datetime.utcnow() - timedelta(seconds=1),
            )
            next_run_at = next_run.isoformat() if next_run else None
        db.register_schedule(
            args.id,
            args.name,
            source=args.source,
            rrule=args.rrule,
            status=args.status,
            account=identity["accountLabel"],
            profile=identity["profileName"] or args.profile,
            action_class=args.action_class,
            metadata=metadata,
            next_run_at=next_run_at,
        )
        payload = {
            "registered": args.id,
            "resolvedIdentity": identity,
            "schedules": db.list_registered_schedules(),
        }
    finally:
        db.close()
    should_ensure_executor = (
        not args.no_ensure_executor
        and args.status.upper() == "ACTIVE"
        and bool(args.links)
        and bool(next_run_at)
        and bool(identity["accountLabel"])
    )
    if should_ensure_executor:
        try:
            payload["executor"] = ensure_executor_service(args)
        except Exception as exc:
            payload["executor"] = {
                "ensured": False,
                "error": str(exc),
                "hint": (
                    "Schedule registration succeeded, but ensuring the local executor "
                    "requires host LaunchAgent permissions. Run executor ensure on the "
                    "host or call schedules run-due --run-worker from a permitted process."
                ),
            }
    else:
        payload["executor"] = {
            "ensured": False,
            "reason": "Schedule is not actionable yet.",
        }
    _print_json(payload)
    return 0


def _run_due_schedules(args: argparse.Namespace) -> dict[str, Any]:
    worker_id = args.worker_id or f"{socket.gethostname()}:{os.getpid()}"
    now = _parse_dt(args.now) if args.now else datetime.utcnow()
    db = _open_db(args)
    processed = []
    recovered_stale = []
    try:
        recovered_stale = db.recover_stale_queue_jobs(now_iso=now.isoformat())
        schedules = db.lease_due_schedules(
            worker_id,
            now_iso=now.isoformat(),
            lease_seconds=args.lease_seconds,
            limit=args.limit,
            schedule_id=getattr(args, "id", "") or None,
        )
        for schedule in schedules:
            metadata = json.loads(schedule["metadata_json"] or "{}")
            links_path = metadata.get("linksPath") or metadata.get("actionFile")
            submitted_jobs = []
            try:
                if not links_path:
                    raise ValueError("Schedule metadata must include linksPath.")
                if not schedule["account"]:
                    raise ValueError("Schedule must resolve to an account before execution.")
                entries, link_errors = _parse_agent_links_file(links_path)
                if link_errors:
                    raise ValueError(
                        "Links file contains unsupported Reddit URL formats: "
                        + json.dumps(link_errors, sort_keys=True)
                    )
                for entry in entries:
                    payload = asdict(entry)
                    payload["_agent_profile"] = {
                        "profileName": schedule["profile"],
                        "profilePath": metadata.get("profilePath", ""),
                        "debugAddress": metadata.get("debugAddress", ""),
                        "redditUsername": metadata.get("redditUsername", ""),
                    }
                    submitted_jobs.append(
                        db.enqueue_action(
                            schedule["account"],
                            entry.action,
                            payload,
                            link=entry.link,
                            priority=args.priority,
                            scheduled_for=now.isoformat(),
                        )
                    )
                previous_runs = 1 if schedule.get("last_run_at") else 0
                next_run = _next_run_after(
                    schedule["rrule"] or "",
                    now,
                    previous_runs=previous_runs + 1,
                )
                db.complete_schedule_run(
                    schedule["id"],
                    next_run_at=next_run.isoformat() if next_run else None,
                    last_run_at=now.isoformat(),
                    deactivate=next_run is None,
                )
                processed.append(
                    {
                        "id": schedule["id"],
                        "submitted": len(submitted_jobs),
                        "jobIds": [job["id"] for job in submitted_jobs],
                        "jobStatuses": [
                            {"id": job["id"], "status": job["status"]}
                            for job in submitted_jobs
                        ],
                        "queuedJobIds": [
                            job["id"]
                            for job in submitted_jobs
                            if job.get("status") == "queued"
                        ],
                        "nextRunAt": next_run.isoformat() if next_run else None,
                    }
                )
            except Exception as exc:
                error = str(exc)
                db.complete_schedule_run(
                    schedule["id"],
                    next_run_at=schedule["next_run_at"],
                    last_run_at=None,
                    error=error,
                )
                processed.append({"id": schedule["id"], "submitted": 0, "error": error})
    finally:
        db.close()

    worker_payload = None
    runnable_job_ids = [
        job_id
        for item in processed
        for job_id in item.get("queuedJobIds", [])
    ]
    total_submitted = sum(item.get("submitted", 0) for item in processed)
    if args.run_worker and runnable_job_ids:
        worker_args = argparse.Namespace(
            config=args.config,
            db_path=args.db_path,
            worker_id=worker_id,
            lease_seconds=args.lease_seconds,
            max_jobs=len(runnable_job_ids),
            once=True,
            idle_sleep=0,
            verbose=args.verbose,
        )
        worker_payload = _run_queue_worker(worker_args)
        worker_payload["requestedMaxJobs"] = len(runnable_job_ids)

    diagnostics = []
    if total_submitted and not runnable_job_ids:
        diagnostics.append(
            {
                "code": "no_runnable_jobs",
                "message": (
                    "Due schedules resolved only to active non-queued jobs. "
                    "They may already be running because of deduplication."
                ),
            }
        )

    return {
        "workerId": worker_id,
        "dueSchedules": len(processed),
        "processed": processed,
        "recoveredStaleJobs": recovered_stale,
        "runnableJobIds": runnable_job_ids,
        "worker": worker_payload,
        "diagnostics": diagnostics,
    }


def command_schedules_run_due(args: argparse.Namespace) -> int:
    _print_json(_run_due_schedules(args))
    return 0


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_file_status() -> dict[str, Any]:
    pid = None
    if EXECUTOR_PID_PATH.exists():
        raw_pid = EXECUTOR_PID_PATH.read_text(encoding="utf-8").strip()
        if raw_pid:
            try:
                pid = int(raw_pid)
            except ValueError:
                pid = None
    running = _pid_is_running(pid) if pid is not None else False
    return {
        "running": running,
        "pid": pid,
        "pidPath": str(EXECUTOR_PID_PATH),
        "logPath": str(EXECUTOR_LOG_PATH),
    }


def _launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def _agentctl_base_command(args: argparse.Namespace) -> list[str]:
    command = [sys.executable, str(_agentctl_script_path())]
    if args.config:
        command.extend(["--config", args.config])
    if args.db_path:
        command.extend(["--db-path", args.db_path])
    return command


def _launch_agent_program_arguments(args: argparse.Namespace) -> list[str]:
    command = _agentctl_base_command(args)
    command.extend(
        [
            "schedules",
            "run-due",
            "--run-worker",
        ]
    )
    return command


def _launch_agent_plist(args: argparse.Namespace) -> dict[str, Any]:
    EXECUTOR_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "Label": EXECUTOR_LABEL,
        "ProgramArguments": _launch_agent_program_arguments(args),
        "WorkingDirectory": str(REPO_ROOT),
        "StartInterval": int(getattr(args, "start_interval", 60)),
        "RunAtLoad": True,
        "StandardOutPath": str(EXECUTOR_LOG_PATH),
        "StandardErrorPath": str(EXECUTOR_LOG_PATH),
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
        },
    }


def _write_launch_agent(args: argparse.Namespace) -> Path:
    plist_path = _launch_agent_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    with plist_path.open("wb") as file_obj:
        plistlib.dump(_launch_agent_plist(args), file_obj, sort_keys=False)
    return plist_path


def _launchctl_print() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", "print", f"{_launchctl_domain()}/{EXECUTOR_LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )


def _launchd_status() -> dict[str, Any]:
    if platform.system() != "Darwin":
        pid_status = _pid_file_status()
        return {
            "method": "pid-loop",
            "available": False,
            "running": pid_status["running"],
            "pid": pid_status["pid"],
            "label": EXECUTOR_LABEL,
            "plistPath": str(_launch_agent_path()),
            "pidPath": pid_status["pidPath"],
            "logPath": pid_status["logPath"],
            "error": "launchd executor is only available on macOS.",
        }
    result = _launchctl_print()
    return {
        "method": "launchd",
        "available": True,
        "running": result.returncode == 0,
        "label": EXECUTOR_LABEL,
        "plistPath": str(_launch_agent_path()),
        "pidPath": str(EXECUTOR_PID_PATH),
        "logPath": str(EXECUTOR_LOG_PATH),
        "launchctlReturnCode": result.returncode,
    }


def executor_status() -> dict[str, Any]:
    return _launchd_status()


def _ensure_pid_loop(args: argparse.Namespace) -> dict[str, Any]:
    status = _pid_file_status()
    if status["running"]:
        return {"ensured": True, "started": False, "method": "pid-loop", **status}

    EXECUTOR_DIR.mkdir(parents=True, exist_ok=True)
    log_file = EXECUTOR_LOG_PATH.open("ab")
    command = _agentctl_base_command(args)
    command.extend(
        [
            "executor",
            "run",
            "--interval",
            str(getattr(args, "executor_interval", 15.0)),
            "--run-worker",
        ]
    )
    process = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    EXECUTOR_PID_PATH.write_text(f"{process.pid}\n", encoding="utf-8")
    return {
        "ensured": True,
        "started": True,
        "method": "pid-loop",
        "running": True,
        "pid": process.pid,
        "pidPath": str(EXECUTOR_PID_PATH),
        "logPath": str(EXECUTOR_LOG_PATH),
    }


def ensure_executor_service(args: argparse.Namespace) -> dict[str, Any]:
    if platform.system() != "Darwin":
        if getattr(args, "allow_pid_fallback", False):
            return _ensure_pid_loop(args)
        return {
            "ensured": False,
            **executor_status(),
        }

    plist_path = _write_launch_agent(args)
    domain = _launchctl_domain()
    bootstrap = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if bootstrap.returncode not in (0, 5):
        return {
            "ensured": False,
            **executor_status(),
            "error": (bootstrap.stderr or bootstrap.stdout).strip(),
        }
    kickstart = subprocess.run(
        ["launchctl", "kickstart", "-k", f"{domain}/{EXECUTOR_LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    status = executor_status()
    return {
        "ensured": kickstart.returncode == 0 or status["running"],
        **status,
        "plistWritten": str(plist_path),
        "bootstrapReturnCode": bootstrap.returncode,
        "kickstartReturnCode": kickstart.returncode,
        "error": None if kickstart.returncode == 0 or status["running"] else (kickstart.stderr or kickstart.stdout).strip(),
    }


def command_executor_ensure(args: argparse.Namespace) -> int:
    _print_json(ensure_executor_service(args))
    return 0


def command_executor_status(args: argparse.Namespace) -> int:
    _print_json(executor_status())
    return 0


def command_executor_stop(args: argparse.Namespace) -> int:
    if platform.system() == "Darwin":
        result = subprocess.run(
            ["launchctl", "bootout", _launchctl_domain(), str(_launch_agent_path())],
            capture_output=True,
            text=True,
            check=False,
        )
        if EXECUTOR_PID_PATH.exists():
            EXECUTOR_PID_PATH.unlink()
        _print_json(
            {
                "stopped": result.returncode == 0,
                **executor_status(),
                "bootoutReturnCode": result.returncode,
                "error": None if result.returncode == 0 else (result.stderr or result.stdout).strip(),
            }
        )
        return 0

    status = _pid_file_status()
    stopped = False
    if status["running"] and status["pid"] is not None:
        os.kill(status["pid"], signal.SIGTERM)
        stopped = True
    if EXECUTOR_PID_PATH.exists():
        EXECUTOR_PID_PATH.unlink()
    _print_json({"stopped": stopped, **executor_status()})
    return 0


def command_executor_run(args: argparse.Namespace) -> int:
    worker_id = args.worker_id or f"executor:{socket.gethostname()}:{os.getpid()}"
    EXECUTOR_DIR.mkdir(parents=True, exist_ok=True)
    EXECUTOR_PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")
    iterations = 0
    try:
        while True:
            run_args = argparse.Namespace(
                config=args.config,
                db_path=args.db_path,
                worker_id=worker_id,
                now="",
                lease_seconds=args.lease_seconds,
                limit=args.limit,
                priority=args.priority,
                run_worker=args.run_worker,
                verbose=args.verbose,
            )
            payload = _run_due_schedules(run_args)
            payload["executor"] = {
                "pid": os.getpid(),
                "iteration": iterations + 1,
                "interval": args.interval,
            }
            print(json.dumps(payload, sort_keys=True), flush=True)
            iterations += 1
            if args.max_iterations and iterations >= args.max_iterations:
                break
            time.sleep(args.interval)
    finally:
        status = executor_status()
        if status["pid"] == os.getpid() and EXECUTOR_PID_PATH.exists():
            EXECUTOR_PID_PATH.unlink()
    return 0


def command_limits_list(args: argparse.Namespace) -> int:
    db = _open_db(args)
    try:
        payload = {
            "accountLimits": db.list_account_limits(),
            "activeReservations": db.list_account_reservations(limit=args.limit),
        }
    finally:
        db.close()
    _print_json(payload)
    return 0


def command_limits_set(args: argparse.Namespace) -> int:
    db = _open_db(args)
    try:
        db.set_account_limit(
            args.account,
            args.daily_action_quota,
            action=args.action,
        )
        payload = {"accountLimits": db.list_account_limits()}
    finally:
        db.close()
    _print_json(payload)
    return 0


def command_queue_submit(args: argparse.Namespace) -> int:
    entries, link_errors = _parse_agent_links_file(args.links)
    if link_errors:
        _print_json(
            {
                "submitted": 0,
                "ok": False,
                "error": "Links file contains unsupported Reddit URL formats.",
                "linkErrors": link_errors,
            }
        )
        return 2

    db = _open_db(args)
    try:
        identity = _resolve_profile_identity(
            db,
            account_label=args.account_label,
            profile_name=args.profile_name,
            reddit_user=args.reddit_user,
        )
        jobs = []
        for entry in entries:
            payload = asdict(entry)
            payload["_agent_profile"] = {
                "profileName": identity["profileName"],
                "profilePath": identity["profilePath"],
                "debugAddress": identity["debugAddress"],
                "redditUsername": identity["redditUsername"],
            }
            jobs.append(
                db.enqueue_action(
                    identity["accountLabel"],
                    entry.action,
                    payload,
                    link=entry.link,
                    priority=args.priority,
                    scheduled_for=args.scheduled_for,
                    max_attempts=args.max_attempts,
                )
            )
        payload = {
            "submitted": len(jobs),
            "resolvedIdentity": identity,
            "jobs": jobs,
        }
    finally:
        db.close()
    _print_json(payload)
    return 0


def command_queue_list(args: argparse.Namespace) -> int:
    db = _open_db(args)
    try:
        payload = {
            "queueCounts": db.get_queue_counts(),
            "jobs": db.list_queue_jobs(status=args.status, limit=args.limit),
        }
    finally:
        db.close()
    _print_json(payload)
    return 0


def command_queue_recover_stale(args: argparse.Namespace) -> int:
    db = _open_db(args)
    try:
        recovered = db.recover_stale_queue_jobs(now_iso=args.now or None)
        payload = {
            "recovered": len(recovered),
            "jobs": recovered,
            "queueCounts": db.get_queue_counts(),
        }
    finally:
        db.close()
    _print_json(payload)
    return 0


def _run_queue_worker(args: argparse.Namespace) -> dict[str, Any]:
    from main import run_account

    config = _load_config(args)
    worker_id = args.worker_id or f"{socket.gethostname()}:{os.getpid()}"
    logger = setup_structured_logger(
        "reddit-bot.agentctl",
        level=logging.INFO,
        log_dir=config.log_dir,
        log_file=config.log_file,
        console=args.verbose,
        file_level=logging.INFO,
    )
    processed = 0

    while args.max_jobs == 0 or processed < args.max_jobs:
        db = BotDatabase(config.db_path)
        job: Optional[dict[str, Any]] = None
        lease_acquired = False
        lease_resource = (
            config.chrome_debugging_address
            or config.chrome_user_data_dir
            or DEFAULT_DEBUG_ADDRESS
        )
        try:
            job = db.lease_next_job(worker_id, lease_seconds=args.lease_seconds)
            if job is None:
                if args.once:
                    return {"workerId": worker_id, "processed": processed, "idle": True}
                time.sleep(args.idle_sleep)
                continue

            job_payload = json.loads(job["payload_json"])
            agent_profile = job_payload.get("_agent_profile") or {}
            lease_resource = (
                agent_profile.get("debugAddress")
                or agent_profile.get("profilePath")
                or lease_resource
            )
            lease_acquired, lease_message = db.acquire_lease(
                "chrome_profile",
                lease_resource,
                worker_id,
                ttl_seconds=args.lease_seconds,
                metadata={"jobId": job["id"]},
            )
            if not lease_acquired:
                db.release_queue_job(job["id"], lease_message)
                continue

            entry = _action_entry_from_payload(job["payload_json"])
            run_config = copy.deepcopy(config)
            run_config.screenshot_on_failure = True
            if agent_profile.get("debugAddress"):
                run_config.use_existing_chrome = True
                run_config.chrome_debugging_address = agent_profile["debugAddress"]
                run_config.chrome_extension_healer_enabled = True
                run_config.parallel_accounts = 1
            elif agent_profile.get("profilePath"):
                run_config.use_existing_chrome = True
                run_config.chrome_user_data_dir = agent_profile["profilePath"]
                run_config.parallel_accounts = 1

            summary = run_account(
                Account(username=job["account"], password=""),
                [entry],
                run_config,
                logger,
            )
            result_payload = _summary_payload(summary)
            success = summary.failed == 0
            db.complete_queue_job(
                job["id"],
                success=success,
                result=result_payload,
                error=None if success else "One or more action results failed.",
            )
            processed += 1
        except Exception as exc:
            if job is not None:
                db.release_queue_job(job["id"], str(exc))
            logger.exception("Agent queue worker failed while processing a job")
            if args.once:
                raise
        finally:
            if lease_acquired:
                db.release_lease("chrome_profile", lease_resource, worker_id)
            db.close()

    return {"workerId": worker_id, "processed": processed, "idle": False}


def command_queue_worker(args: argparse.Namespace) -> int:
    _print_json(_run_queue_worker(args))
    return 0


def _attached_chrome_driver(debug_address: str):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from bot.utils.chromedriver import install_chromedriver

    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", debug_address)
    service = Service(install_chromedriver())
    return webdriver.Chrome(service=service, options=options)


def command_vote_click_visible(args: argparse.Namespace) -> int:
    from bot.utils.visible_vote import click_visible_vote_control

    db = _open_db(args)
    worker_id = args.worker_id or f"{socket.gethostname()}:{os.getpid()}"
    lease_acquired = False
    lease_resource = DEFAULT_DEBUG_ADDRESS
    reservation_id: Optional[int] = None
    action_logged = False
    driver = None
    try:
        identity = _resolve_profile_identity(
            db,
            account_label=args.account_label,
            profile_name=args.profile_name,
            reddit_user=args.reddit_user,
        )
        debug_address = args.debug_address or identity.get("debugAddress") or DEFAULT_DEBUG_ADDRESS
        lease_resource = debug_address or identity.get("profilePath") or DEFAULT_DEBUG_ADDRESS
        lease_acquired, lease_message = db.acquire_lease(
            "chrome_profile",
            lease_resource,
            worker_id,
            ttl_seconds=args.lease_seconds,
            metadata={
                "command": "vote click-visible",
                "url": args.url,
                "action": args.action,
                "account": identity["accountLabel"],
            },
        )
        if not lease_acquired:
            _print_json(
                {
                    "ok": False,
                    "clicked": False,
                    "error": lease_message,
                    "resolvedIdentity": identity,
                }
            )
            return 1

        account = identity["accountLabel"]
        action = args.action
        link = args.url
        if db.was_action_performed(account, action, link):
            _print_json(
                {
                    "ok": True,
                    "clicked": False,
                    "skipped": True,
                    "reason": "Action already performed by this account.",
                    "resolvedIdentity": identity,
                    "leaseResource": lease_resource,
                }
            )
            return 0

        reserved, quota_message, reservation_id = db.reserve_account_action(
            account,
            action,
            link,
            ttl_seconds=args.lease_seconds,
        )
        if not reserved:
            _print_json(
                {
                    "ok": False,
                    "clicked": False,
                    "quotaBlocked": True,
                    "error": quota_message,
                    "resolvedIdentity": identity,
                    "leaseResource": lease_resource,
                }
            )
            return 1

        driver = _attached_chrome_driver(debug_address)
        result = click_visible_vote_control(
            driver,
            intent=args.action,
            url=args.url,
            settle_seconds=args.settle_seconds,
            screenshot_path=args.screenshot,
        )
        action_success = bool(
            result.get("ok") and result.get("clicked") and result.get("confirmed")
        )
        action_message = (
            "Visible vote click confirmed."
            if action_success
            else result.get("error") or "Visible vote click was not confirmed."
        )
        db.log_action(
            account,
            action,
            link,
            success=action_success,
            error_message=None if action_success else action_message,
            screenshot_path=result.get("screenshotPath"),
        )
        action_logged = True
        db.finish_account_action_reservation(
            reservation_id,
            success=action_success,
            message=action_message,
        )
        result["resolvedIdentity"] = identity
        result["leaseResource"] = lease_resource
        result["quota"] = {"reserved": True, "message": quota_message}
        result["audit"] = {"logged": True, "success": action_success}
        _print_json(result)
        return 0 if result.get("ok") else 1
    except Exception as exc:
        if reservation_id is not None:
            db.finish_account_action_reservation(
                reservation_id,
                success=False,
                message=str(exc),
            )
            if not action_logged:
                db.log_action(
                    identity["accountLabel"],
                    args.action,
                    args.url,
                    success=False,
                    error_message=str(exc),
                )
        raise
    finally:
        if driver is not None:
            driver.quit()
        if lease_acquired:
            db.release_lease("chrome_profile", lease_resource, worker_id)
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentctl",
        description="Agent-safe Reddit bot queue, profile, schedule, and quota control.",
    )
    parser.add_argument("--config", help="Path to YAML configuration file.")
    parser.add_argument("--db-path", help="Override BotConfig.db_path.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--include-crontab", action="store_true")
    status_parser.set_defaults(func=command_status)

    profiles_parser = subparsers.add_parser("profiles")
    profiles_subparsers = profiles_parser.add_subparsers(dest="profiles_command", required=True)
    profiles_list_parser = profiles_subparsers.add_parser("list")
    profiles_list_parser.set_defaults(func=command_profiles_list)
    profiles_probe_parser = profiles_subparsers.add_parser("probe")
    profiles_probe_parser.add_argument(
        "--debug-address",
        default=DEFAULT_DEBUG_ADDRESS,
        help="Chrome DevTools address to probe.",
    )
    profiles_probe_parser.add_argument("--timeout", type=float, default=2.0)
    profiles_probe_parser.set_defaults(func=command_profiles_probe)
    profiles_associate_parser = profiles_subparsers.add_parser("associate")
    profiles_associate_parser.add_argument("--profile-name", required=True)
    profiles_associate_parser.add_argument("--reddit-user", required=True)
    profiles_associate_parser.add_argument("--profile-path", default="")
    profiles_associate_parser.add_argument("--debug-address", default="")
    profiles_associate_parser.add_argument(
        "--account-label",
        default="",
        help="Optional execution label. Defaults to the Reddit username without u/.",
    )
    profiles_associate_parser.set_defaults(func=command_profiles_associate)
    profiles_resolve_parser = profiles_subparsers.add_parser("resolve")
    profile_resolve_group = profiles_resolve_parser.add_mutually_exclusive_group(required=True)
    profile_resolve_group.add_argument("--profile-name")
    profile_resolve_group.add_argument("--reddit-user")
    profile_resolve_group.add_argument("--account-label")
    profiles_resolve_parser.set_defaults(func=command_profiles_resolve)

    schedules_parser = subparsers.add_parser("schedules")
    schedules_subparsers = schedules_parser.add_subparsers(dest="schedules_command", required=True)
    schedules_list_parser = schedules_subparsers.add_parser("list")
    schedules_list_parser.add_argument("--include-crontab", action="store_true")
    schedules_list_parser.set_defaults(func=command_schedules_list)
    schedules_register_parser = schedules_subparsers.add_parser("register")
    schedules_register_parser.add_argument("--id", required=True)
    schedules_register_parser.add_argument("--name", required=True)
    schedules_register_parser.add_argument("--source", default="agentctl")
    schedules_register_parser.add_argument("--rrule", default="")
    schedules_register_parser.add_argument("--status", default="ACTIVE")
    schedules_register_parser.add_argument("--account", default="")
    schedules_register_parser.add_argument("--profile", default="")
    schedules_register_parser.add_argument("--profile-name", default="")
    schedules_register_parser.add_argument("--reddit-user", default="")
    schedules_register_parser.add_argument("--action-class", default="")
    schedules_register_parser.add_argument("--links", default="")
    schedules_register_parser.add_argument("--next-run-at", default="")
    schedules_register_parser.add_argument(
        "--no-ensure-executor",
        action="store_true",
        help="Register the schedule without ensuring the local executor service.",
    )
    schedules_register_parser.add_argument(
        "--executor-interval",
        type=float,
        default=15.0,
        help="Polling interval used only by the non-macOS PID fallback executor.",
    )
    schedules_register_parser.add_argument(
        "--start-interval",
        type=int,
        default=60,
        help="launchd StartInterval in seconds for the local executor service.",
    )
    schedules_register_parser.set_defaults(func=command_schedules_register)
    schedules_run_parser = schedules_subparsers.add_parser("run-due")
    schedules_run_parser.add_argument("--id", help="Only run the due schedule with this id.")
    schedules_run_parser.add_argument("--now", default="")
    schedules_run_parser.add_argument("--worker-id", default="")
    schedules_run_parser.add_argument("--lease-seconds", type=int, default=600)
    schedules_run_parser.add_argument("--limit", type=int, default=1)
    schedules_run_parser.add_argument("--priority", type=int, default=100)
    schedules_run_parser.add_argument("--run-worker", action="store_true")
    schedules_run_parser.add_argument("--verbose", action="store_true")
    schedules_run_parser.set_defaults(func=command_schedules_run_due)

    executor_parser = subparsers.add_parser("executor")
    executor_subparsers = executor_parser.add_subparsers(dest="executor_command", required=True)
    executor_status_parser = executor_subparsers.add_parser("status")
    executor_status_parser.set_defaults(func=command_executor_status)
    executor_ensure_parser = executor_subparsers.add_parser("ensure")
    executor_ensure_parser.add_argument("--executor-interval", type=float, default=15.0)
    executor_ensure_parser.add_argument("--start-interval", type=int, default=60)
    executor_ensure_parser.add_argument(
        "--allow-pid-fallback",
        action="store_true",
        help="On non-macOS systems, start a detached PID-file loop instead of reporting launchd unavailable.",
    )
    executor_ensure_parser.set_defaults(func=command_executor_ensure)
    executor_stop_parser = executor_subparsers.add_parser("stop")
    executor_stop_parser.set_defaults(func=command_executor_stop)
    executor_run_parser = executor_subparsers.add_parser("run")
    executor_run_parser.add_argument("--interval", type=float, default=15.0)
    executor_run_parser.add_argument("--worker-id", default="")
    executor_run_parser.add_argument("--lease-seconds", type=int, default=600)
    executor_run_parser.add_argument("--limit", type=int, default=1)
    executor_run_parser.add_argument("--priority", type=int, default=100)
    executor_run_parser.add_argument("--run-worker", action="store_true")
    executor_run_parser.add_argument("--max-iterations", type=int, default=0)
    executor_run_parser.add_argument("--verbose", action="store_true")
    executor_run_parser.set_defaults(func=command_executor_run)

    limits_parser = subparsers.add_parser("limits")
    limits_subparsers = limits_parser.add_subparsers(dest="limits_command", required=True)
    limits_list_parser = limits_subparsers.add_parser("list")
    limits_list_parser.add_argument("--limit", type=int, default=100)
    limits_list_parser.set_defaults(func=command_limits_list)
    limits_set_parser = limits_subparsers.add_parser("set")
    limits_set_parser.add_argument("--account", required=True)
    limits_set_parser.add_argument("--action", default="*")
    limits_set_parser.add_argument("--daily-action-quota", type=int, required=True)
    limits_set_parser.set_defaults(func=command_limits_set)

    queue_parser = subparsers.add_parser("queue")
    queue_subparsers = queue_parser.add_subparsers(dest="queue_command", required=True)
    queue_submit_parser = queue_subparsers.add_parser("submit")
    queue_identity_group = queue_submit_parser.add_mutually_exclusive_group(required=True)
    queue_identity_group.add_argument("--account-label")
    queue_identity_group.add_argument("--profile-name")
    queue_identity_group.add_argument("--reddit-user")
    queue_submit_parser.add_argument("--links", required=True)
    queue_submit_parser.add_argument("--priority", type=int, default=100)
    queue_submit_parser.add_argument("--scheduled-for", default=None)
    queue_submit_parser.add_argument("--max-attempts", type=int, default=3)
    queue_submit_parser.set_defaults(func=command_queue_submit)
    queue_list_parser = queue_subparsers.add_parser("list")
    queue_list_parser.add_argument("--status", default=None)
    queue_list_parser.add_argument("--limit", type=int, default=100)
    queue_list_parser.set_defaults(func=command_queue_list)
    queue_recover_parser = queue_subparsers.add_parser("recover-stale")
    queue_recover_parser.add_argument("--now", default="")
    queue_recover_parser.set_defaults(func=command_queue_recover_stale)
    queue_worker_parser = queue_subparsers.add_parser("worker")
    queue_worker_parser.add_argument("--worker-id", default="")
    queue_worker_parser.add_argument("--lease-seconds", type=int, default=600)
    queue_worker_parser.add_argument("--max-jobs", type=int, default=1)
    queue_worker_parser.add_argument("--once", action="store_true")
    queue_worker_parser.add_argument("--idle-sleep", type=float, default=5.0)
    queue_worker_parser.add_argument("--verbose", action="store_true")
    queue_worker_parser.set_defaults(func=command_queue_worker)

    vote_parser = subparsers.add_parser("vote")
    vote_subparsers = vote_parser.add_subparsers(dest="vote_command", required=True)
    vote_click_visible_parser = vote_subparsers.add_parser("click-visible")
    vote_identity_group = vote_click_visible_parser.add_mutually_exclusive_group(required=True)
    vote_identity_group.add_argument("--account-label")
    vote_identity_group.add_argument("--profile-name")
    vote_identity_group.add_argument("--reddit-user")
    vote_click_visible_parser.add_argument("--url", required=True)
    vote_click_visible_parser.add_argument("--action", choices=["upvote", "downvote"], required=True)
    vote_click_visible_parser.add_argument("--debug-address", default="")
    vote_click_visible_parser.add_argument("--worker-id", default="")
    vote_click_visible_parser.add_argument("--lease-seconds", type=int, default=120)
    vote_click_visible_parser.add_argument("--settle-seconds", type=float, default=2.0)
    vote_click_visible_parser.add_argument("--screenshot", default="")
    vote_click_visible_parser.set_defaults(func=command_vote_click_visible)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
