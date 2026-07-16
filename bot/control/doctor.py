"""Read-only diagnostics answering “why can’t I act?” for agents.

Exit policy (documented for agents):
  Process exit is non-zero **only** for hard local misconfiguration (currently
  ``db`` — SQLite cannot be opened). Soft failures (Chrome not running, bridge
  unreachable, executor stopped, quota exhausted, etc.) set ``ok: false`` on
  that check and ``summary.ok: false``, but the process still exits 0 so agents
  can parse the JSON envelope reliably.

This module has no Reddit mutations and does not submit queue work. Healer
bridge full Selenium attach is skipped by default (side-effecting); doctor
reports extension path + debugger readiness instead, unless a callable
``bridge_ping_fn`` is injected (tests / advanced use).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from bot.agentctl import (
    DEFAULT_DEBUG_ADDRESS,
    DEFAULT_EXTENSION_PATH,
    DEFAULT_PROFILE_NAME,
    discover_profiles_with_associations,
    executor_status,
    probe_debug_address,
)
from bot.database import BotDatabase

# Checks whose failure means exit code != 0.
HARD_CHECK_IDS = frozenset({"db"})

EXIT_POLICY = (
    "Non-zero exit only on hard local misconfiguration (currently: db open failure). "
    "Soft failures (Chrome down, bridge, executor, quotas) leave process exit 0 "
    "so agents can parse JSON."
)

DEFAULT_REDDIT_USER = "u/Particular-Arm2102"

ProbeFn = Callable[[str], dict[str, Any]]
ExecutorStatusFn = Callable[[], dict[str, Any]]
BridgePingFn = Callable[[str], dict[str, Any]]


def _check(
    check_id: str,
    ok: bool,
    detail: str,
    *,
    hard: bool | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    is_hard = bool(HARD_CHECK_IDS & {check_id}) if hard is None else hard
    item: dict[str, Any] = {
        "id": check_id,
        "ok": bool(ok),
        "detail": detail,
        "hard": is_hard,
    }
    if data is not None:
        item["data"] = data
    return item


def _summarize(checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [c["id"] for c in checks if not c.get("ok")]
    hard_failed = [c["id"] for c in checks if not c.get("ok") and c.get("hard")]
    return {
        "ok": not failed,
        "failed": failed,
        "hardFailed": hard_failed,
        "exitPolicy": EXIT_POLICY,
    }


def build_report(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the doctor ``data`` payload from check results."""
    summary = _summarize(checks)
    return {
        "checks": checks,
        "summary": summary,
    }


def process_exit_code(report: dict[str, Any]) -> int:
    """Return process exit code from a doctor report (0 unless hard failures)."""
    hard_failed = (report.get("summary") or {}).get("hardFailed") or []
    return 1 if hard_failed else 0


def format_checks_table(report: dict[str, Any]) -> str:
    """Human-readable multi-line table of checks."""
    checks = report.get("checks") or []
    summary = report.get("summary") or {}
    headers = ("STATUS", "ID", "DETAIL")
    rows: list[tuple[str, str, str]] = []
    for item in checks:
        status = "OK" if item.get("ok") else ("HARD" if item.get("hard") else "FAIL")
        detail = str(item.get("detail") or "").replace("\n", " ")
        rows.append((status, str(item.get("id") or ""), detail))

    if not rows:
        body = "(no checks)"
    else:
        widths = [
            max(len(headers[i]), *(len(row[i]) for row in rows))
            for i in range(len(headers))
        ]
        # Cap detail column so wide messages stay readable in terminals.
        widths[2] = min(widths[2], 96)
        lines = [
            "  ".join(headers[i].ljust(widths[i]) for i in range(3)),
            "  ".join("-" * widths[i] for i in range(3)),
        ]
        for row in rows:
            detail = row[2] if len(row[2]) <= widths[2] else row[2][: widths[2] - 3] + "..."
            lines.append(
                f"{row[0].ljust(widths[0])}  {row[1].ljust(widths[1])}  {detail}"
            )
        body = "\n".join(lines)

    overall = "healthy" if summary.get("ok") else "issues detected"
    failed = summary.get("failed") or []
    hard = summary.get("hardFailed") or []
    footer_parts = [f"summary: {overall}"]
    if failed:
        footer_parts.append(f"failed=[{', '.join(failed)}]")
    if hard:
        footer_parts.append(f"hard=[{', '.join(hard)}]")
    footer_parts.append(EXIT_POLICY)
    return f"Doctor diagnostics\n{body}\n\n{'; '.join(footer_parts)}"


def _check_db(db_path: str) -> tuple[dict[str, Any], BotDatabase | None]:
    try:
        db = BotDatabase(db_path)
        # Touch a cheap read so a half-broken connection still fails here.
        _ = db.get_queue_counts()
        return (
            _check("db", True, f"SQLite openable at {db_path}", hard=True),
            db,
        )
    except Exception as exc:  # noqa: BLE001 — diagnostic surface
        return (
            _check("db", False, f"Cannot open database at {db_path}: {exc}", hard=True),
            None,
        )


def _check_account_limits(db: BotDatabase) -> dict[str, Any]:
    try:
        limits = db.list_account_limits()
        if not limits:
            return _check(
                "account_limits",
                True,
                "No account quotas configured (unlimited by default).",
                data={"accounts": []},
            )
        accounts: list[dict[str, Any]] = []
        exhausted: list[str] = []
        parts: list[str] = []
        for row in limits:
            account = row.get("account") or ""
            action = row.get("action") or "*"
            quota = int(row.get("daily_action_quota") or 0)
            used = db.get_daily_action_count(account) if account else 0
            remaining = max(0, quota - used) if quota > 0 else None
            entry = {
                "account": account,
                "action": action,
                "quota": quota,
                "usedToday": used,
                "remainingToday": remaining,
            }
            accounts.append(entry)
            if remaining is not None and remaining <= 0:
                exhausted.append(account or action)
            label = f"{account}/{action}" if action != "*" else account
            parts.append(f"{label}: {used}/{quota} used ({remaining} remaining)")
        detail = "; ".join(parts)
        if exhausted:
            return _check(
                "account_limits",
                False,
                f"Daily quota exhausted for: {', '.join(exhausted)}. {detail}",
                data={"accounts": accounts},
            )
        return _check(
            "account_limits",
            True,
            detail,
            data={"accounts": accounts},
        )
    except Exception as exc:  # noqa: BLE001
        return _check("account_limits", False, f"Failed to read account limits: {exc}")


def _check_chrome_profiles(db: BotDatabase) -> dict[str, Any]:
    try:
        associations = db.list_chrome_profile_associations()
        profiles = discover_profiles_with_associations(db)
        n_assoc = len(associations)
        n_profiles = len(profiles)
        if n_assoc == 0 and n_profiles == 0:
            return _check(
                "chrome_profiles",
                False,
                "No saved Chrome profiles discovered and no DB associations.",
                data={"profiles": profiles, "associations": associations},
            )
        if n_assoc == 0:
            return _check(
                "chrome_profiles",
                False,
                f"Found {n_profiles} local profile dir(s) but no DB associations "
                f"(run profiles associate).",
                data={"profiles": profiles, "associations": associations},
            )
        names = [a.get("profile_name") or a.get("reddit_username") for a in associations]
        return _check(
            "chrome_profiles",
            True,
            f"{n_assoc} association(s), {n_profiles} profile record(s): "
            + ", ".join(str(n) for n in names if n),
            data={"profiles": profiles, "associations": associations},
        )
    except Exception as exc:  # noqa: BLE001
        return _check("chrome_profiles", False, f"Failed to list profiles: {exc}")


def _check_default_identity(
    db: BotDatabase,
    *,
    reddit_user: str | None,
    profile_name: str | None,
    account_label: str | None,
) -> tuple[dict[str, Any], str | None]:
    """Resolve default/requested identity. Returns (check, debug_address or None)."""
    try:
        association = None
        resolved_via = None
        if account_label:
            association = db.get_chrome_profile_association(account_label=account_label)
            resolved_via = f"account_label={account_label}"
        if association is None and profile_name:
            association = db.get_chrome_profile_association(profile_name=profile_name)
            resolved_via = f"profile_name={profile_name}"
        if association is None and reddit_user:
            association = db.get_chrome_profile_association(reddit_username=reddit_user)
            resolved_via = f"reddit_user={reddit_user}"
        if association is None:
            # Fall back to project defaults.
            association = db.get_chrome_profile_association(profile_name=DEFAULT_PROFILE_NAME)
            if association is not None:
                resolved_via = f"default profile_name={DEFAULT_PROFILE_NAME}"
            else:
                association = db.get_chrome_profile_association(
                    reddit_username=DEFAULT_REDDIT_USER
                )
                if association is not None:
                    resolved_via = f"default reddit_user={DEFAULT_REDDIT_USER}"

        if association is None:
            return (
                _check(
                    "default_identity",
                    False,
                    "No Chrome profile association for the requested/default identity. "
                    "Run profiles associate first.",
                    data={
                        "redditUser": reddit_user,
                        "profileName": profile_name,
                        "accountLabel": account_label,
                        "defaults": {
                            "profileName": DEFAULT_PROFILE_NAME,
                            "redditUser": DEFAULT_REDDIT_USER,
                        },
                    },
                ),
                None,
            )

        debug_address = association.get("debug_address") or DEFAULT_DEBUG_ADDRESS
        detail = (
            f"Resolved via {resolved_via}: "
            f"user={association.get('reddit_username')} "
            f"profile={association.get('profile_name')} "
            f"debug={debug_address}"
        )
        return (
            _check(
                "default_identity",
                True,
                detail,
                data={
                    "association": association,
                    "resolvedVia": resolved_via,
                    "debugAddress": debug_address,
                },
            ),
            debug_address,
        )
    except Exception as exc:  # noqa: BLE001
        return (
            _check("default_identity", False, f"Identity resolve failed: {exc}"),
            None,
        )


def _check_chrome_debugger(
    debug_address: str,
    *,
    probe_fn: ProbeFn,
) -> tuple[dict[str, Any], bool]:
    try:
        probe = probe_fn(debug_address)
        if probe.get("ok"):
            browser = probe.get("browser") or "unknown browser"
            return (
                _check(
                    "chrome_debugger",
                    True,
                    f"DevTools reachable at {debug_address} ({browser})",
                    data={"probe": probe},
                ),
                True,
            )
        error = probe.get("error") or "unreachable"
        hint = probe.get("hint")
        detail = f"{error}"
        if hint:
            detail = f"{detail} ({hint})"
        detail = f"DevTools not reachable at {debug_address}: {detail}"
        return (
            _check(
                "chrome_debugger",
                False,
                detail,
                data={"probe": probe},
            ),
            False,
        )
    except Exception as exc:  # noqa: BLE001
        return (
            _check(
                "chrome_debugger",
                False,
                f"Probe raised for {debug_address}: {exc}",
            ),
            False,
        )


def _check_healer_bridge(
    debug_address: str,
    *,
    debugger_ok: bool,
    extension_path: Path,
    bridge_ping_fn: BridgePingFn | None,
) -> dict[str, Any]:
    path = Path(extension_path)
    if not path.exists():
        return _check(
            "healer_bridge",
            False,
            f"Healer extension path missing: {path}",
            data={"extensionPath": str(path), "debuggerOk": debugger_ok},
        )

    if bridge_ping_fn is not None:
        try:
            result = bridge_ping_fn(debug_address)
            ok = bool(result.get("ok"))
            detail = result.get("detail") or result.get("error") or (
                "bridge ping ok" if ok else "bridge ping failed"
            )
            return _check(
                "healer_bridge",
                ok,
                str(detail),
                data={
                    "extensionPath": str(path),
                    "debuggerOk": debugger_ok,
                    "ping": result,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return _check(
                "healer_bridge",
                False,
                f"Bridge ping raised: {exc}",
                data={"extensionPath": str(path), "debuggerOk": debugger_ok},
            )

    # Default: no Selenium attach (side-effect free). Report readiness only.
    if not debugger_ok:
        return _check(
            "healer_bridge",
            False,
            f"Extension present at {path}; debugger down so bridge cannot be pinged "
            f"(full ping skipped; doctor is side-effect free).",
            data={
                "extensionPath": str(path),
                "debuggerOk": False,
                "pingSkipped": True,
            },
        )
    return _check(
        "healer_bridge",
        True,
        f"Extension present at {path}; debugger up. Full Selenium bridge ping skipped "
        f"(side-effect free; use reddit_healer_debug.py ping-bridge for live ping).",
        data={
            "extensionPath": str(path),
            "debuggerOk": True,
            "pingSkipped": True,
        },
    )


def _check_executor(*, executor_status_fn: ExecutorStatusFn) -> dict[str, Any]:
    try:
        status = executor_status_fn()
        running = bool(status.get("running"))
        method = status.get("method") or "unknown"
        if running:
            return _check(
                "executor",
                True,
                f"Executor running via {method}",
                data={"executor": status},
            )
        error = status.get("error")
        detail = f"Executor not running (method={method})"
        if error:
            detail = f"{detail}: {error}"
        return _check(
            "executor",
            False,
            detail,
            data={"executor": status},
        )
    except Exception as exc:  # noqa: BLE001
        return _check("executor", False, f"Executor status failed: {exc}")


def _check_queue_depth(db: BotDatabase) -> dict[str, Any]:
    try:
        counts = db.get_queue_counts()
        queued = int(counts.get("queued") or 0)
        running = int(counts.get("running") or 0)
        failed = int(counts.get("failed") or 0)
        succeeded = int(counts.get("succeeded") or 0)
        detail = (
            f"queued={queued} running={running} failed={failed} succeeded={succeeded}"
        )
        # Informational: failed jobs are a soft warning, not a hard misconfig.
        ok = True
        if failed > 0:
            ok = False
            detail = f"{detail} (failed jobs present; inspect queue / errors)"
        return _check(
            "queue_depth",
            ok,
            detail,
            data={"queueCounts": counts},
        )
    except Exception as exc:  # noqa: BLE001
        return _check("queue_depth", False, f"Queue counts failed: {exc}")


def _check_active_leases(db: BotDatabase) -> dict[str, Any]:
    try:
        leases = db.list_leases()
        if not leases:
            return _check(
                "active_leases",
                True,
                "No active leases.",
                data={"leases": []},
            )
        parts = [
            f"{item.get('resource_type')}:{item.get('resource_id')} "
            f"by {item.get('acquired_by')} until {item.get('expires_at')}"
            for item in leases
        ]
        return _check(
            "active_leases",
            True,
            f"{len(leases)} active lease(s): " + "; ".join(parts),
            data={"leases": leases},
        )
    except Exception as exc:  # noqa: BLE001
        return _check("active_leases", False, f"Lease list failed: {exc}")


def run_doctor(
    *,
    db_path: str,
    debug_address: str | None = None,
    reddit_user: str | None = None,
    profile_name: str | None = None,
    account_label: str | None = None,
    probe_fn: ProbeFn | None = None,
    executor_status_fn: ExecutorStatusFn | None = None,
    bridge_ping_fn: BridgePingFn | None = None,
    extension_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run all best-effort diagnostics and return the doctor ``data`` payload.

    Parameters allow injecting probe/executor/bridge callables for tests so no
    real Chrome session is required.
    """
    probe = probe_fn or probe_debug_address
    exec_status = executor_status_fn or executor_status
    ext_path = Path(extension_path) if extension_path is not None else DEFAULT_EXTENSION_PATH

    checks: list[dict[str, Any]] = []

    db_check, db = _check_db(db_path)
    checks.append(db_check)
    if db is None:
        # Still emit placeholders so agents always see the full check id set.
        for check_id, detail in (
            ("account_limits", "Skipped: database unavailable."),
            ("chrome_profiles", "Skipped: database unavailable."),
            ("default_identity", "Skipped: database unavailable."),
            ("chrome_debugger", "Skipped: database unavailable."),
            ("healer_bridge", "Skipped: database unavailable."),
            ("executor", "Skipped: database unavailable."),
            ("queue_depth", "Skipped: database unavailable."),
            ("active_leases", "Skipped: database unavailable."),
        ):
            # Executor does not need DB — still try it for better signal.
            if check_id == "executor":
                checks.append(_check_executor(executor_status_fn=exec_status))
            else:
                checks.append(_check(check_id, False, detail, hard=check_id in HARD_CHECK_IDS))
        return build_report(checks)

    try:
        checks.append(_check_account_limits(db))
        checks.append(_check_chrome_profiles(db))

        identity_check, resolved_debug = _check_default_identity(
            db,
            reddit_user=reddit_user,
            profile_name=profile_name,
            account_label=account_label,
        )
        checks.append(identity_check)

        address = debug_address or resolved_debug or DEFAULT_DEBUG_ADDRESS
        debugger_check, debugger_ok = _check_chrome_debugger(address, probe_fn=probe)
        checks.append(debugger_check)

        checks.append(
            _check_healer_bridge(
                address,
                debugger_ok=debugger_ok,
                extension_path=ext_path,
                bridge_ping_fn=bridge_ping_fn,
            )
        )
        checks.append(_check_executor(executor_status_fn=exec_status))
        checks.append(_check_queue_depth(db))
        checks.append(_check_active_leases(db))
    finally:
        db.close()

    return build_report(checks)
