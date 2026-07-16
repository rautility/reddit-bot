"""reddit-tool command handlers (non-interactive)."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bot.action_schema import (
    ACTION_SCHEMA,
    FIELD_GLOSSARY,
    SCHEMA_VERSION,
    URL_CONTRACT,
    describe_actions,
    validate_action_fields,
)
from bot.agentctl import DEFAULT_DEBUG_ADDRESS, DEFAULT_PROFILE_NAME
from bot.cli import bridge, render
from bot.control import doctor as doctor_control
from bot.control import schedules as schedule_control
from bot.control.errors import CliError
from bot.control.resolve import resolve_reddit_url
from bot.utils.clock import utc_now

DEFAULT_REDDIT_USER = bridge.DEFAULT_REDDIT_USER
DEFAULT_ACTIONS_DIR = bridge.DEFAULT_ACTIONS_DIR
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

# Bridge re-exports used by handlers
_agentctl_payload = bridge._agentctl_payload
_identity_args = bridge._identity_args
_schedule_identity_args = bridge._schedule_identity_args
_repo_codex_automations = bridge._repo_codex_automations
_load_config = bridge._load_config
_open_db = bridge._open_db
_profile_preflight = bridge._profile_preflight
_action_line = bridge._action_line
_resolve_links_file = bridge._resolve_links_file
_job_outcome = bridge._job_outcome
_collect_errors_from_db = bridge._collect_errors_from_db
_tail_executor_errors = bridge._tail_executor_errors
EXECUTOR_LOG_PATH = bridge.EXECUTOR_LOG_PATH
ERROR_KEYWORDS = bridge.ERROR_KEYWORDS

# Render re-exports
_envelope = render._envelope
_json_or_table = render._json_or_table
_print_overview = render._print_overview
_print_doctor = render._print_doctor
_print_schedule_list = render._print_schedule_list
_print_schedule_add = render._print_schedule_add
_print_run_due = render._print_run_due
_print_schedule_change = render._print_schedule_change
_print_queue = render._print_queue
_print_queue_add = render._print_queue_add
_print_worker = render._print_worker
_print_queue_recover_stale = render._print_queue_recover_stale
_print_queue_retry = render._print_queue_retry
_print_executor = render._print_executor
_print_error_summary = render._print_error_summary
_print_profiles = render._print_profiles
_print_limits = render._print_limits
_print_capabilities = render._print_capabilities
_print_resolve_url = render._print_resolve_url
_print_do = render._print_do
_print_external_search_upvote = render._print_external_search_upvote
_print_job = render._print_job
_print_kv = render._print_kv
_print_table = render._print_table

def command_overview(args: argparse.Namespace) -> int:
    payload = _agentctl_payload(args, ["status"])
    return _json_or_table(args, payload, _print_overview)


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


def command_queue_list(args: argparse.Namespace) -> int:
    command = ["queue", "list", "--limit", str(args.limit)]
    if args.status:
        command.extend(["--status", args.status])
    if args.account:
        command.extend(["--account", args.account])
    payload = _agentctl_payload(args, command)
    return _json_or_table(args, payload, _print_queue)


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


def command_queue_run_once(args: argparse.Namespace) -> int:
    command = ["queue", "worker", "--once", "--max-jobs", str(args.max_jobs)]
    if args.verbose:
        command.append("--verbose")
    payload = _agentctl_payload(args, command)
    return _json_or_table(args, payload, _print_worker)


def command_queue_recover_stale(args: argparse.Namespace) -> int:
    command = ["queue", "recover-stale"]
    if args.now:
        command.extend(["--now", args.now])
    payload = _agentctl_payload(args, command)
    return _json_or_table(args, payload, _print_queue_recover_stale)


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


def command_executor(args: argparse.Namespace) -> int:
    command = ["executor", args.executor_action]
    if args.executor_action == "ensure":
        command.extend(["--executor-interval", str(args.executor_interval)])
        command.extend(["--start-interval", str(args.start_interval)])
        if args.allow_pid_fallback:
            command.append("--allow-pid-fallback")
    payload = _agentctl_payload(args, command)
    return _json_or_table(args, payload, _print_executor)


def command_errors(args: argparse.Namespace) -> int:
    config = _load_config(args)
    payload = _collect_errors_from_db(limit=args.limit, db_path=config.db_path)
    payload["executorLogErrors"] = _tail_executor_errors(args.limit)
    return _json_or_table(
        args,
        payload,
        lambda data: _print_error_summary(data, include_logs=True),
    )


def command_profiles(args: argparse.Namespace) -> int:
    payload = _agentctl_payload(args, ["profiles", "list"])
    return _json_or_table(args, payload, _print_profiles)


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


def command_job(args: argparse.Namespace) -> int:
    payload = _envelope("job", data=_job_outcome(args, args.id))
    payload["ok"] = payload["data"].get("found", False)
    return _json_or_table(args, payload, _print_job)

