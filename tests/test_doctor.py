"""Tests for read-only ``reddit-tool doctor`` diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

from bot import tool_cli
from bot.control import doctor as doctor_control
from bot.database import BotDatabase


def _run(argv, capsys):
    exit_code = tool_cli.main(argv)
    return exit_code, capsys.readouterr().out


def _healthy_probe(address: str) -> dict:
    return {
        "ok": True,
        "debugAddress": address,
        "endpoint": f"http://{address}/json/version",
        "browser": "Chrome/test",
        "protocolVersion": "1.3",
        "webSocketDebuggerUrl": f"ws://{address}/devtools/browser/test",
    }


def _failed_probe(address: str) -> dict:
    return {
        "ok": False,
        "debugAddress": address,
        "endpoint": f"http://{address}/json/version",
        "error": f"connection refused {address}",
    }


def _seed_association(db_path: Path) -> None:
    db = BotDatabase(str(db_path))
    try:
        db.associate_chrome_profile(
            "Chrome Reddit Bot Debug Profile",
            "u/Particular-Arm2102",
            profile_path="/tmp/fake-chrome-profile",
            debug_address="127.0.0.1:9222",
            account_label="Particular-Arm2102",
        )
        db.set_account_limit("Particular-Arm2102", 25)
    finally:
        db.close()


def test_run_doctor_healthy_db_and_soft_probe_failure(tmp_path):
    db_path = tmp_path / "agent.db"
    _seed_association(db_path)
    ext = tmp_path / "healer"
    ext.mkdir()

    report = doctor_control.run_doctor(
        db_path=str(db_path),
        probe_fn=_failed_probe,
        executor_status_fn=lambda: {
            "method": "launchd",
            "available": True,
            "running": False,
            "label": "test",
        },
        extension_path=ext,
    )

    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["db"]["ok"] is True
    assert by_id["account_limits"]["ok"] is True
    assert by_id["default_identity"]["ok"] is True
    assert by_id["chrome_debugger"]["ok"] is False
    assert "connection refused" in by_id["chrome_debugger"]["detail"]
    assert by_id["chrome_debugger"]["hard"] is False
    assert by_id["healer_bridge"]["ok"] is False  # debugger down → soft fail
    assert by_id["executor"]["ok"] is False
    assert by_id["queue_depth"]["ok"] is True
    assert by_id["active_leases"]["ok"] is True

    assert report["summary"]["ok"] is False
    assert "chrome_debugger" in report["summary"]["failed"]
    assert report["summary"]["hardFailed"] == []
    assert doctor_control.process_exit_code(report) == 0


def test_run_doctor_all_soft_checks_pass(tmp_path):
    db_path = tmp_path / "agent.db"
    _seed_association(db_path)
    ext = tmp_path / "healer"
    ext.mkdir()

    report = doctor_control.run_doctor(
        db_path=str(db_path),
        probe_fn=_healthy_probe,
        executor_status_fn=lambda: {
            "method": "launchd",
            "available": True,
            "running": True,
            "label": "test",
        },
        extension_path=ext,
    )

    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["db"]["ok"] is True
    assert by_id["chrome_debugger"]["ok"] is True
    assert by_id["healer_bridge"]["ok"] is True
    assert by_id["healer_bridge"]["data"]["pingSkipped"] is True
    assert by_id["executor"]["ok"] is True
    assert report["summary"]["ok"] is True
    assert report["summary"]["failed"] == []
    assert doctor_control.process_exit_code(report) == 0


def test_run_doctor_hard_failure_when_db_unopenable(tmp_path):
    # Path points at a directory so sqlite open fails.
    bad_path = tmp_path / "not-a-file"
    bad_path.mkdir()

    report = doctor_control.run_doctor(
        db_path=str(bad_path),
        probe_fn=_failed_probe,
        executor_status_fn=lambda: {"method": "pid-loop", "running": False},
        extension_path=tmp_path / "missing-ext",
    )

    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["db"]["ok"] is False
    assert by_id["db"]["hard"] is True
    assert "db" in report["summary"]["hardFailed"]
    assert doctor_control.process_exit_code(report) == 1
    # Other checks are still present for a stable schema.
    assert "chrome_debugger" in by_id
    assert "queue_depth" in by_id


def test_run_doctor_bridge_ping_injection(tmp_path):
    db_path = tmp_path / "agent.db"
    _seed_association(db_path)
    ext = tmp_path / "healer"
    ext.mkdir()

    report = doctor_control.run_doctor(
        db_path=str(db_path),
        probe_fn=_healthy_probe,
        executor_status_fn=lambda: {"method": "launchd", "running": True},
        extension_path=ext,
        bridge_ping_fn=lambda _addr: {"ok": False, "detail": "bridge timeout"},
    )

    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["healer_bridge"]["ok"] is False
    assert "bridge timeout" in by_id["healer_bridge"]["detail"]


def test_run_doctor_failed_queue_jobs_soft_fail(tmp_path):
    db_path = tmp_path / "agent.db"
    db = BotDatabase(str(db_path))
    try:
        db.associate_chrome_profile(
            "Chrome Reddit Bot Debug Profile",
            "u/Particular-Arm2102",
            profile_path="/tmp/fake",
            debug_address="127.0.0.1:9222",
        )
        job = db.enqueue_action(
            "Particular-Arm2102",
            "upvote",
            {"action": "upvote", "link": "https://www.reddit.com/r/t/comments/a/b/"},
            link="https://www.reddit.com/r/t/comments/a/b/",
        )
        # Force failed status via direct SQL for a stable soft-fail signal.
        db.conn.execute(
            "UPDATE agent_queue SET status = 'failed', last_error = 'boom' WHERE id = ?",
            (job["id"],),
        )
        db.conn.commit()
    finally:
        db.close()

    ext = tmp_path / "healer"
    ext.mkdir()
    report = doctor_control.run_doctor(
        db_path=str(db_path),
        probe_fn=_healthy_probe,
        executor_status_fn=lambda: {"method": "launchd", "running": True},
        extension_path=ext,
    )
    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["queue_depth"]["ok"] is False
    assert "failed=1" in by_id["queue_depth"]["detail"]
    assert doctor_control.process_exit_code(report) == 0


def test_doctor_cli_json_envelope(tmp_path, capsys, mocker):
    db_path = tmp_path / "agent.db"
    _seed_association(db_path)

    mocker.patch(
        "bot.control.doctor.probe_debug_address",
        side_effect=_failed_probe,
    )
    mocker.patch(
        "bot.control.doctor.executor_status",
        return_value={"method": "launchd", "running": False, "available": True},
    )
    mocker.patch(
        "bot.control.doctor.DEFAULT_EXTENSION_PATH",
        tmp_path / "healer",
    )
    (tmp_path / "healer").mkdir()

    exit_code, out = _run(
        ["--db-path", str(db_path), "--json", "doctor"],
        capsys,
    )

    assert exit_code == 0  # soft probe failure → still 0
    payload = json.loads(out)
    assert payload["ok"] is True  # no hard failures
    assert payload["command"] == "doctor"
    assert payload["schemaVersion"] == tool_cli.SCHEMA_VERSION
    assert "checks" in payload["data"]
    ids = [c["id"] for c in payload["data"]["checks"]]
    assert "db" in ids
    assert "chrome_debugger" in ids
    assert payload["data"]["summary"]["ok"] is False
    assert "chrome_debugger" in payload["data"]["summary"]["failed"]
    assert "exitPolicy" in payload["data"]["summary"]


def test_doctor_cli_json_flag_after_subcommand(tmp_path, capsys, mocker):
    db_path = tmp_path / "agent.db"
    BotDatabase(str(db_path)).close()
    mocker.patch(
        "bot.control.doctor.probe_debug_address",
        side_effect=_failed_probe,
    )
    mocker.patch(
        "bot.control.doctor.executor_status",
        return_value={"method": "pid-loop", "running": False},
    )
    mocker.patch("bot.control.doctor.DEFAULT_EXTENSION_PATH", tmp_path / "ext")
    (tmp_path / "ext").mkdir()

    exit_code, out = _run(["doctor", "--json", "--db-path", str(db_path)], capsys)
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["command"] == "doctor"
    assert isinstance(payload["data"]["checks"], list)


def test_doctor_cli_human_table(tmp_path, capsys, mocker):
    db_path = tmp_path / "agent.db"
    _seed_association(db_path)
    mocker.patch(
        "bot.control.doctor.probe_debug_address",
        side_effect=_healthy_probe,
    )
    mocker.patch(
        "bot.control.doctor.executor_status",
        return_value={"method": "launchd", "running": True},
    )
    mocker.patch("bot.control.doctor.DEFAULT_EXTENSION_PATH", tmp_path / "ext")
    (tmp_path / "ext").mkdir()

    exit_code, out = _run(["--db-path", str(db_path), "doctor"], capsys)
    assert exit_code == 0
    assert "Doctor diagnostics" in out
    assert "db" in out
    assert "chrome_debugger" in out
    assert "summary:" in out


def test_format_checks_table_includes_exit_policy():
    report = doctor_control.build_report(
        [
            doctor_control._check("db", True, "ok", hard=True),
            doctor_control._check("chrome_debugger", False, "down"),
        ]
    )
    text = doctor_control.format_checks_table(report)
    assert "Doctor diagnostics" in text
    assert "chrome_debugger" in text
    assert "Non-zero exit only on hard" in text
