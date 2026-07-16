"""Agent-facing control plane for safe Reddit bot orchestration."""

from __future__ import annotations

import argparse
import os
import socket
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from bot.control import executor as executor_control
from bot.control import limits as limits_control
from bot.control import profiles as profile_control
from bot.control import queue as queue_control
from bot.control import schedules as schedule_control
from bot.control import status as status_control
from bot.control.common import REPO_ROOT, load_config, open_db, print_json
from bot.control.executor import (
    EXECUTOR_DIR,
    EXECUTOR_LABEL,
    EXECUTOR_LOG_PATH,
    EXECUTOR_PID_PATH,
    ensure_executor_service,
    executor_status,
)
from bot.control.profiles import (
    DEFAULT_DEBUG_ADDRESS,
    DEFAULT_EXTENSION_PATH,
    DEFAULT_PROFILE_NAME,
    DEFAULT_PROFILE_PREFIX,
    discover_profiles_with_associations,
    discover_saved_profiles,
    probe_debug_address,
    profile_by_name,
    resolve_profile_identity,
)
from bot.control.queue import (
    CANONICAL_POST_ACTIONS,
    action_entry_from_payload,
    parse_agent_links_file,
    run_due_schedules,
    run_queue_worker,
    summary_payload,
    validate_canonical_post_actions,
)
from bot.control.status import read_codex_automations, read_crontab
from bot.utils.clock import utc_now

# Keep public names bound so re-exports are used (F401) and external imports stay stable.
__all__ = [
    "CANONICAL_POST_ACTIONS",
    "DEFAULT_DEBUG_ADDRESS",
    "DEFAULT_EXTENSION_PATH",
    "DEFAULT_PROFILE_NAME",
    "DEFAULT_PROFILE_PREFIX",
    "EXECUTOR_DIR",
    "EXECUTOR_LABEL",
    "EXECUTOR_LOG_PATH",
    "EXECUTOR_PID_PATH",
    "REPO_ROOT",
    "discover_profiles_with_associations",
    "discover_saved_profiles",
    "ensure_executor_service",
    "executor_status",
    "main",
    "probe_debug_address",
    "run_due_schedules",
    "run_queue_worker",
]

# Historical private aliases (tests / internal callers).
_print_json = print_json
_load_config = load_config
_open_db = open_db
_profile_by_name = profile_by_name
_resolve_profile_identity = resolve_profile_identity
_action_entry_from_payload = action_entry_from_payload
_validate_canonical_post_actions = validate_canonical_post_actions
_parse_agent_links_file = parse_agent_links_file
_summary_payload = summary_payload
_run_queue_worker = run_queue_worker
_run_due_schedules = run_due_schedules
_read_codex_automations = read_codex_automations
_read_crontab = read_crontab
_parse_toml_scalar = status_control.parse_toml_scalar
_launch_agents_dir = executor_control.launch_agents_dir
_agentctl_script_path = executor_control.agentctl_script_path
_launch_agent_path = executor_control.launch_agent_path
_pid_is_running = executor_control.pid_is_running
_pid_file_status = executor_control.pid_file_status
_launchctl_domain = executor_control.launchctl_domain
_agentctl_base_command = executor_control.agentctl_base_command
_launch_agent_program_arguments = executor_control.launch_agent_program_arguments
_launch_agent_plist = executor_control.launch_agent_plist
_write_launch_agent = executor_control.write_launch_agent
_launchctl_print = executor_control.launchctl_print
_launchd_status = executor_control.launchd_status
_ensure_pid_loop = executor_control.ensure_pid_loop

WEEKDAY_INDEX = schedule_control.WEEKDAY_INDEX
_parse_dt = schedule_control.parse_dt
_parse_dtstart = schedule_control.parse_dtstart
_parse_rrule_text = schedule_control.parse_rrule_text
_next_run_after = schedule_control.next_run_after


def command_status(args: argparse.Namespace) -> int:
    return status_control.command_status(args)


def command_profiles_list(args: argparse.Namespace) -> int:
    return profile_control.command_profiles_list(args)


def command_profiles_probe(args: argparse.Namespace) -> int:
    return profile_control.command_profiles_probe(args)


def command_profiles_associate(args: argparse.Namespace) -> int:
    return profile_control.command_profiles_associate(args)


def command_profiles_resolve(args: argparse.Namespace) -> int:
    return profile_control.command_profiles_resolve(args)


def command_schedules_list(args: argparse.Namespace) -> int:
    _print_json(status_control.schedules_list_payload(args))
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
                utc_now() - timedelta(seconds=1),
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


def command_schedules_set_status(args: argparse.Namespace) -> int:
    db = _open_db(args)
    try:
        schedule = db.set_schedule_status(args.id, args.status)
        payload = {
            "schedule": schedule,
            "changed": bool(schedule.get("changed")),
            "schedules": db.list_registered_schedules(),
        }
    finally:
        db.close()
    _print_json(payload)
    return 0


def command_schedules_delete(args: argparse.Namespace) -> int:
    db = _open_db(args)
    try:
        deleted = db.delete_schedule(args.id)
        payload = {
            "schedule": deleted,
            "deleted": bool(deleted.get("deleted")),
            "schedules": db.list_registered_schedules(),
        }
    finally:
        db.close()
    _print_json(payload)
    return 0


def command_schedules_run_due(args: argparse.Namespace) -> int:
    return queue_control.command_schedules_run_due(args)


def command_executor_ensure(args: argparse.Namespace) -> int:
    return executor_control.command_executor_ensure(args)


def command_executor_status(args: argparse.Namespace) -> int:
    return executor_control.command_executor_status(args)


def command_executor_stop(args: argparse.Namespace) -> int:
    return executor_control.command_executor_stop(args)


def command_executor_run(args: argparse.Namespace) -> int:
    return executor_control.command_executor_run(args, run_due_schedules=_run_due_schedules)


def command_limits_list(args: argparse.Namespace) -> int:
    return limits_control.command_limits_list(args)


def command_limits_set(args: argparse.Namespace) -> int:
    return limits_control.command_limits_set(args)


def command_queue_submit(args: argparse.Namespace) -> int:
    return queue_control.command_queue_submit(args)


def command_queue_list(args: argparse.Namespace) -> int:
    return queue_control.command_queue_list(args)


def command_queue_recover_stale(args: argparse.Namespace) -> int:
    return queue_control.command_queue_recover_stale(args)


def command_queue_retry(args: argparse.Namespace) -> int:
    return queue_control.command_queue_retry(args)


def command_queue_worker(args: argparse.Namespace) -> int:
    return queue_control.command_queue_worker(args)


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
    reservation_id: int | None = None
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
        action_success = bool(result.get("ok") and result.get("clicked") and result.get("confirmed"))
        action_message = (
            "Visible vote click confirmed." if action_success else result.get("error") or "Visible vote click was not confirmed."
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

    schedules_status_parser = schedules_subparsers.add_parser("set-status")
    schedules_status_parser.add_argument("--id", required=True)
    schedules_status_parser.add_argument(
        "--status",
        required=True,
        choices=["ACTIVE", "PAUSED", "active", "paused"],
    )
    schedules_status_parser.set_defaults(func=command_schedules_set_status)
    schedules_delete_parser = schedules_subparsers.add_parser("delete")
    schedules_delete_parser.add_argument("--id", required=True)
    schedules_delete_parser.set_defaults(func=command_schedules_delete)

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
    queue_list_parser.add_argument("--account", default="")
    queue_list_parser.add_argument("--limit", type=int, default=100)
    queue_list_parser.set_defaults(func=command_queue_list)
    queue_recover_parser = queue_subparsers.add_parser("recover-stale")
    queue_recover_parser.add_argument("--now", default="")
    queue_recover_parser.set_defaults(func=command_queue_recover_stale)
    queue_retry_parser = queue_subparsers.add_parser("retry")
    queue_retry_group = queue_retry_parser.add_mutually_exclusive_group(required=True)
    queue_retry_group.add_argument("--id", type=int)
    queue_retry_group.add_argument("--all", action="store_true")
    queue_retry_parser.add_argument("--account", default="")
    queue_retry_parser.set_defaults(func=command_queue_retry)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
