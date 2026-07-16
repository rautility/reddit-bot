"""Human-friendly operations CLI for the Reddit bot control plane."""

from __future__ import annotations

import argparse
import sys

from bot import agentctl  # noqa: F401  # re-export for tests (tool_cli.agentctl)
from bot.action_schema import ACTION_SCHEMA, SCHEMA_VERSION  # noqa: F401
from bot.agentctl import DEFAULT_PROFILE_NAME, REPO_ROOT  # noqa: F401
from bot.cli import actions, bridge, menu, render
from bot.control import schedules as schedule_control
from bot.control.errors import CliError
from bot.utils.input_parser import VALID_ACTIONS

# Public constants (tests / imports)
DEFAULT_REDDIT_USER = bridge.DEFAULT_REDDIT_USER
DEFAULT_ACTIONS_DIR = bridge.DEFAULT_ACTIONS_DIR
ERROR_KEYWORDS = bridge.ERROR_KEYWORDS
INLINE_ACTION_FIELDS = actions.INLINE_ACTION_FIELDS
QUERY_ACTIONS = actions.QUERY_ACTIONS

WEEKDAYS = schedule_control.WEEKDAYS
_normalize_weekdays = schedule_control.normalize_weekdays
_parse_at = schedule_control.parse_at
_parse_time = schedule_control.parse_time
_schedule_rule = schedule_control.schedule_rule
_slugify = schedule_control.slugify

# Re-export helpers tests may patch or call
_envelope = render._envelope
_truncate = render._truncate
_print_table = render._print_table
_print_kv = render._print_kv
_global_agentctl_args = bridge._global_agentctl_args
_agentctl_payload = bridge._agentctl_payload
_load_config = bridge._load_config
_open_db = bridge._open_db
_json_or_table = render._json_or_table
_identity_args = bridge._identity_args
_debug_host_port = bridge._debug_host_port
_open_profile_for_identity = bridge._open_profile_for_identity
_profile_preflight = bridge._profile_preflight
_schedule_identity_args = bridge._schedule_identity_args
_repo_codex_automations = bridge._repo_codex_automations
_action_line = bridge._action_line
_resolve_links_file = bridge._resolve_links_file
_job_outcome = bridge._job_outcome
_collect_errors_from_db = bridge._collect_errors_from_db
_tail_executor_errors = bridge._tail_executor_errors

# Command re-exports
command_overview = actions.command_overview
command_doctor = actions.command_doctor
command_schedule_list = actions.command_schedule_list
command_schedule_add = actions.command_schedule_add
command_schedule_run_due = actions.command_schedule_run_due
command_schedule_pause = actions.command_schedule_pause
command_schedule_resume = actions.command_schedule_resume
command_schedule_delete = actions.command_schedule_delete
command_queue_list = actions.command_queue_list
command_queue_add = actions.command_queue_add
command_queue_run_once = actions.command_queue_run_once
command_queue_recover_stale = actions.command_queue_recover_stale
command_queue_retry = actions.command_queue_retry
command_executor = actions.command_executor
command_errors = actions.command_errors
command_profiles = actions.command_profiles
command_limits_list = actions.command_limits_list
command_limits_set = actions.command_limits_set
command_resolve_url = actions.command_resolve_url
command_capabilities = actions.command_capabilities
command_do = actions.command_do
command_search_upvote = actions.command_search_upvote
command_external_search_upvote = actions.command_external_search_upvote
command_job = actions.command_job
command_menu = menu.command_menu

# Print helpers re-exported for tests
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

# External-search helpers
_terminal_job_status = actions._terminal_job_status
_selected_result_link = actions._selected_result_link
_is_post_url = actions._is_post_url
_queue_timestamp = actions._queue_timestamp
_external_schedule_window = actions._external_schedule_window
_external_search_schedule_id = actions._external_search_schedule_id
_find_matching_search_upvote_job = actions._find_matching_search_upvote_job
_previous_selected_result_link = actions._previous_selected_result_link
_selected_post_url_from_outcomes = actions._selected_post_url_from_outcomes
_selection_details_from_outcomes = actions._selection_details_from_outcomes
_poll_job_outcomes = actions._poll_job_outcomes


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
    sys.exit(main())
