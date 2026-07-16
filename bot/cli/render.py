"""Human-readable rendering helpers for reddit-tool output."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from typing import Any

from bot.action_schema import SCHEMA_VERSION
from bot.cli import bridge
from bot.control import doctor as doctor_control

_collect_errors_from_db = bridge._collect_errors_from_db
_repo_codex_automations = bridge._repo_codex_automations

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


def _json_or_table(args: argparse.Namespace, payload: dict[str, Any], printer) -> int:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        printer(payload)
    return 0


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


def _print_doctor(payload: dict[str, Any]) -> None:
    data = payload.get("data") or {}
    print(doctor_control.format_checks_table(data))


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


def _print_worker(payload: dict[str, Any]) -> None:
    print("Queue worker")
    _print_kv(
        [
            ("worker", payload.get("workerId")),
            ("processed", payload.get("processed")),
            ("idle", payload.get("idle")),
        ]
    )


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
            ("reddit user", defaults.get("redditUser") or "(resolved from DB/env)"),
            ("resolved via", defaults.get("redditUserResolvedVia") or "—"),
            ("profile name", defaults.get("profileName")),
            ("debug address", defaults.get("debugAddress")),
            ("identity flags", ", ".join(defaults.get("identityOptions", []))),
            ("identity resolution", defaults.get("identityResolution")),
            ("default user env", defaults.get("defaultUserEnv")),
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

