"""Aggregate control-plane status payload builders."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from bot.control.common import REPO_ROOT, load_config, print_json
from bot.control.executor import executor_status
from bot.control.profiles import (
    DEFAULT_DEBUG_ADDRESS,
    DEFAULT_EXTENSION_PATH,
    discover_profiles_with_associations,
)
from bot.database import BotDatabase


def parse_toml_scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text.strip('"')


def read_codex_automations() -> list[dict[str, Any]]:
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
                    item[key] = parse_toml_scalar(value)
                elif key == "cwds":
                    item[key] = parse_toml_scalar(value)
        except OSError as exc:
            item["error"] = str(exc)
        automations.append(item)
    return automations


def read_crontab() -> dict[str, Any]:
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


def build_status_payload(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args)
    db = BotDatabase(config.db_path)
    try:
        return {
            "cwd": str(REPO_ROOT),
            "dbPath": config.db_path,
            "queueCounts": db.get_queue_counts(),
            "activeLeases": db.list_leases(),
            "accountLimits": db.list_account_limits(),
            "profileAccountAssociations": db.list_chrome_profile_associations(),
            "registeredSchedules": db.list_registered_schedules(),
            "executor": executor_status(),
            "codexAutomations": read_codex_automations(),
            "crontab": read_crontab() if args.include_crontab else {"checked": False},
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


def command_status(args: argparse.Namespace) -> int:
    print_json(build_status_payload(args))
    return 0


def schedules_list_payload(args: argparse.Namespace) -> dict[str, Any]:
    """Shared list payload used by agentctl schedules list."""
    from bot.control.common import open_db

    db = open_db(args)
    try:
        return {
            "registeredSchedules": db.list_registered_schedules(),
            "codexAutomations": read_codex_automations(),
            "crontab": read_crontab() if args.include_crontab else {"checked": False},
        }
    finally:
        db.close()
