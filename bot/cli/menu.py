"""Interactive menu for reddit-tool."""

from __future__ import annotations

import argparse
from typing import Any

from bot.cli import actions, bridge
from bot.control import schedules as schedule_control
from bot.control.errors import CliError

DEFAULT_REDDIT_USER = bridge.DEFAULT_REDDIT_USER
DEFAULT_ACTIONS_DIR = bridge.DEFAULT_ACTIONS_DIR
_parse_at = schedule_control.parse_at
_parse_time = schedule_control.parse_time
_normalize_weekdays = schedule_control.normalize_weekdays

# Commands used by menu
command_overview = actions.command_overview
command_capabilities = actions.command_capabilities
command_schedule_list = actions.command_schedule_list
command_queue_list = actions.command_queue_list
command_job = actions.command_job
command_executor = actions.command_executor
command_errors = actions.command_errors
command_profiles = actions.command_profiles
command_limits_list = actions.command_limits_list
command_schedule_add = actions.command_schedule_add
command_queue_add = actions.command_queue_add
command_schedule_run_due = actions.command_schedule_run_due

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
            actions_dir=str(bridge.DEFAULT_ACTIONS_DIR),
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

