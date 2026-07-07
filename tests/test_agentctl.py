"""Tests for the agent-facing control CLI."""

import argparse
import json
import plistlib
import subprocess

from bot import agentctl
from bot.actions.base import ActionResult
from bot.database import BotDatabase
from bot.reporting import ExecutionSummary


def test_status_outputs_agent_state_json(tmp_path, capsys):
    db_path = tmp_path / "agent.db"

    exit_code = agentctl.main(["--db-path", str(db_path), "status"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dbPath"] == str(db_path)
    assert "queueCounts" in payload
    assert "savedChromeProfiles" in payload
    assert payload["defaultChromeDebugAddress"] == "127.0.0.1:9222"


def test_queue_submit_outputs_queued_jobs(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    links_path = tmp_path / "links.txt"
    links_path.write_text("https://reddit.com/r/test/comments/abc|upvote\n")

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "queue",
            "submit",
            "--account-label",
            "default",
            "--links",
            str(links_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["submitted"] == 1
    assert payload["jobs"][0]["status"] == "queued"
    assert payload["jobs"][0]["account"] == "default"


def test_queue_submit_rejects_reddit_share_link_for_post_action(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    links_path = tmp_path / "links.txt"
    links_path.write_text("https://www.reddit.com/r/excel/s/Ipw1C8yg0P|upvote\n")

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "queue",
            "submit",
            "--account-label",
            "default",
            "--links",
            str(links_path),
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["submitted"] == 0
    assert payload["linkErrors"][0]["action"] == "upvote"
    assert "share links must be resolved" in payload["linkErrors"][0]["error"]


def test_probe_debug_address_reports_sandbox_hint(mocker):
    mocker.patch("bot.agentctl.urlopen", side_effect=OSError(1, "Operation not permitted"))

    payload = agentctl.probe_debug_address("127.0.0.1:9222")

    assert payload["ok"] is False
    assert "Operation not permitted" in payload["error"]
    assert "sandboxed" in payload["hint"]


def test_queue_worker_enables_failure_screenshots_for_live_jobs(tmp_path, mocker):
    db_path = tmp_path / "agent.db"
    db = BotDatabase(str(db_path))
    try:
        db.enqueue_action(
            "Particular-Arm2102",
            "upvote",
            {
                "action": "upvote",
                "link": "https://www.reddit.com/r/test/comments/abc/title/",
                "_agent_profile": {
                    "profileName": "Chrome Reddit Bot Debug Profile",
                    "profilePath": str(tmp_path / "profile"),
                    "debugAddress": "127.0.0.1:9222",
                    "redditUsername": "Particular-Arm2102",
                },
            },
            link="https://www.reddit.com/r/test/comments/abc/title/",
        )
    finally:
        db.close()

    summary = ExecutionSummary()
    summary.add(
        ActionResult(
            success=True,
            action="upvote",
            link="https://www.reddit.com/r/test/comments/abc/title/",
            message="Vote registered",
        )
    )
    run_account = mocker.patch("main.run_account", return_value=summary)
    mocker.patch("bot.agentctl.setup_structured_logger", return_value=mocker.Mock())

    payload = agentctl._run_queue_worker(
        argparse.Namespace(
            config=None,
            db_path=str(db_path),
            worker_id="test-worker",
            lease_seconds=60,
            max_jobs=1,
            once=True,
            idle_sleep=0,
            verbose=False,
        )
    )

    assert payload["processed"] == 1
    run_config = run_account.call_args.args[2]
    assert run_config.screenshot_on_failure is True


def test_profiles_associate_and_resolve_by_reddit_user(tmp_path, capsys, mocker):
    db_path = tmp_path / "agent.db"
    profile_path = tmp_path / "Chrome Reddit Bot Debug Profile"
    mocker.patch(
        "bot.agentctl.discover_saved_profiles",
        return_value=[
            {
                "profileName": "Chrome Reddit Bot Debug Profile",
                "profilePath": str(profile_path),
                "suggestedDebugAddress": "127.0.0.1:9222",
                "isDefault": True,
            }
        ],
    )

    associate_exit = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "profiles",
            "associate",
            "--profile-name",
            "Chrome Reddit Bot Debug Profile",
            "--reddit-user",
            "u/Particular-Arm2102",
        ]
    )
    assert associate_exit == 0
    associate_payload = json.loads(capsys.readouterr().out)
    assert associate_payload["association"]["reddit_username"] == "Particular-Arm2102"
    assert associate_payload["association"]["debug_address"] == "127.0.0.1:9222"

    resolve_exit = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "profiles",
            "resolve",
            "--reddit-user",
            "Particular-Arm2102",
        ]
    )

    assert resolve_exit == 0
    resolve_payload = json.loads(capsys.readouterr().out)
    assert resolve_payload["profileName"] == "Chrome Reddit Bot Debug Profile"
    assert resolve_payload["accountLabel"] == "Particular-Arm2102"


def test_queue_submit_by_reddit_user_embeds_profile_metadata(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    links_path = tmp_path / "links.txt"
    links_path.write_text("https://reddit.com/r/test/comments/abc|upvote\n")
    agentctl.main(
        [
            "--db-path",
            str(db_path),
            "profiles",
            "associate",
            "--profile-name",
            "Chrome Reddit Bot Debug Profile",
            "--reddit-user",
            "u/Particular-Arm2102",
            "--profile-path",
            str(tmp_path / "profile"),
            "--debug-address",
            "127.0.0.1:9222",
        ]
    )
    capsys.readouterr()

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "queue",
            "submit",
            "--reddit-user",
            "u/Particular-Arm2102",
            "--links",
            str(links_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    job_payload = json.loads(payload["jobs"][0]["payload_json"])
    assert payload["resolvedIdentity"]["accountLabel"] == "Particular-Arm2102"
    assert payload["jobs"][0]["account"] == "Particular-Arm2102"
    assert job_payload["_agent_profile"]["profileName"] == "Chrome Reddit Bot Debug Profile"
    assert job_payload["_agent_profile"]["debugAddress"] == "127.0.0.1:9222"


def test_profiles_probe_reports_browser_metadata(mocker, capsys):
    response = mocker.MagicMock()
    response.read.return_value = json.dumps(
        {
            "Browser": "Chrome/149",
            "Protocol-Version": "1.3",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/id",
        }
    ).encode("utf-8")
    response.__enter__.return_value = response
    urlopen = mocker.patch("bot.agentctl.urlopen", return_value=response)

    exit_code = agentctl.main(["profiles", "probe", "--debug-address", "127.0.0.1:9222"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["browser"] == "Chrome/149"
    urlopen.assert_called_once_with(
        "http://127.0.0.1:9222/json/version",
        timeout=2.0,
    )


def test_attached_chrome_driver_uses_repo_managed_chromedriver(mocker):
    install = mocker.patch("bot.utils.chromedriver.install_chromedriver", return_value="/tmp/chromedriver")
    chrome = mocker.patch("selenium.webdriver.Chrome", return_value=object())
    service = mocker.patch("selenium.webdriver.chrome.service.Service")

    result = agentctl._attached_chrome_driver("127.0.0.1:9222")

    assert result is chrome.return_value
    install.assert_called_once_with()
    service.assert_called_once_with("/tmp/chromedriver")
    chrome.assert_called_once()


def test_schedule_register_stores_links_and_next_run(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    links_path = tmp_path / "links.txt"
    links_path.write_text("https://reddit.com/r/test/comments/abc|upvote\n")

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "schedules",
            "register",
            "--id",
            "daily-actions",
            "--name",
            "Daily Actions",
            "--source",
            "agentctl",
            "--rrule",
            "FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            "--account",
            "default",
            "--action-class",
            "live",
            "--links",
            str(links_path),
            "--next-run-at",
            "2026-07-04T09:00:00",
            "--no-ensure-executor",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    schedule = payload["schedules"][0]
    metadata = json.loads(schedule["metadata_json"])
    assert schedule["next_run_at"] == "2026-07-04T09:00:00"
    assert metadata["linksPath"] == str(links_path)


def test_schedule_register_rejects_reddit_share_link_for_post_action(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    links_path = tmp_path / "links.txt"
    links_path.write_text("https://www.reddit.com/r/excel/s/Ipw1C8yg0P|upvote\n")

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "schedules",
            "register",
            "--id",
            "daily-actions",
            "--name",
            "Daily Actions",
            "--rrule",
            "FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            "--account",
            "default",
            "--links",
            str(links_path),
            "--next-run-at",
            "2026-07-04T09:00:00",
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["registered"] is None
    assert "share links must be resolved" in payload["linkErrors"][0]["error"]


def test_schedule_register_ensures_executor_for_active_links_schedule(tmp_path, capsys, mocker):
    db_path = tmp_path / "agent.db"
    links_path = tmp_path / "links.txt"
    links_path.write_text("https://reddit.com/r/test/comments/abc|upvote\n")
    ensure = mocker.patch(
        "bot.agentctl.ensure_executor_service",
        return_value={"ensured": True, "method": "launchd", "running": True},
    )

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "schedules",
            "register",
            "--id",
            "daily-actions",
            "--name",
            "Daily Actions",
            "--rrule",
            "FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            "--account",
            "default",
            "--links",
            str(links_path),
            "--next-run-at",
            "2026-07-04T09:00:00",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["executor"]["ensured"] is True
    ensure.assert_called_once()


def test_schedule_register_reports_executor_error_without_failing_registration(
    tmp_path,
    capsys,
    mocker,
):
    db_path = tmp_path / "agent.db"
    links_path = tmp_path / "links.txt"
    links_path.write_text("https://reddit.com/r/test/comments/abc|upvote\n")
    mocker.patch(
        "bot.agentctl.ensure_executor_service",
        side_effect=RuntimeError("launchctl unavailable"),
    )

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "schedules",
            "register",
            "--id",
            "daily-actions",
            "--name",
            "Daily Actions",
            "--rrule",
            "FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            "--account",
            "default",
            "--links",
            str(links_path),
            "--next-run-at",
            "2026-07-04T09:00:00",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["registered"] == "daily-actions"
    assert payload["executor"]["ensured"] is False
    assert payload["executor"]["error"] == "launchctl unavailable"


def test_executor_ensure_writes_expected_launchagent_plist(tmp_path, capsys, mocker):
    db_path = tmp_path / "agent.db"
    launch_agents = tmp_path / "LaunchAgents"
    mocker.patch("bot.agentctl.platform.system", return_value="Darwin")
    mocker.patch("bot.agentctl._launch_agents_dir", return_value=launch_agents)
    run = mocker.patch(
        "bot.agentctl.subprocess.run",
        side_effect=[
            subprocess.CompletedProcess(["launchctl", "bootstrap"], 0, "", ""),
            subprocess.CompletedProcess(["launchctl", "kickstart"], 0, "", ""),
            subprocess.CompletedProcess(["launchctl", "print"], 0, "loaded", ""),
        ],
    )

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "executor",
            "ensure",
            "--start-interval",
            "120",
            "--executor-interval",
            "30",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    plist_path = launch_agents / "com.raul.reddit-bot.agentctl-scheduler.plist"
    plist = plistlib.loads(plist_path.read_bytes())
    assert payload["ensured"] is True
    assert payload["method"] == "launchd"
    assert plist["Label"] == "com.raul.reddit-bot.agentctl-scheduler"
    assert plist["StartInterval"] == 120
    assert plist["ProgramArguments"][-3:] == [
        "schedules",
        "run-due",
        "--run-worker",
    ]
    assert run.call_count == 3


def test_executor_status_outputs_json_on_non_macos(capsys, mocker):
    mocker.patch("bot.agentctl.platform.system", return_value="Linux")

    exit_code = agentctl.main(["executor", "status"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["available"] is False
    assert payload["method"] == "pid-loop"


def test_schedule_run_due_enqueues_links_without_worker(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    links_path = tmp_path / "links.txt"
    links_path.write_text("https://reddit.com/r/test/comments/abc|upvote\n")
    agentctl.main(
        [
            "--db-path",
            str(db_path),
            "schedules",
            "register",
            "--id",
            "daily-actions",
            "--name",
            "Daily Actions",
            "--rrule",
            "FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            "--account",
            "default",
            "--links",
            str(links_path),
            "--next-run-at",
            "2026-07-04T09:00:00",
            "--no-ensure-executor",
        ]
    )
    capsys.readouterr()

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "schedules",
            "run-due",
            "--now",
            "2026-07-04T09:01:00",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dueSchedules"] == 1
    assert payload["processed"][0]["submitted"] == 1
    assert payload["processed"][0]["queuedJobIds"] == payload["processed"][0]["jobIds"]
    assert payload["processed"][0]["jobStatuses"][0]["status"] == "queued"
    assert payload["runnableJobIds"] == payload["processed"][0]["jobIds"]
    assert payload["recoveredStaleJobs"] == []
    assert payload["diagnostics"] == []
    assert payload["processed"][0]["nextRunAt"] == "2026-07-05T09:00:00"

    agentctl.main(["--db-path", str(db_path), "queue", "list"])
    queue_payload = json.loads(capsys.readouterr().out)
    assert queue_payload["queueCounts"] == {"queued": 1}


def test_schedule_run_due_can_target_one_schedule_id(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    links_one = tmp_path / "one.txt"
    links_two = tmp_path / "two.txt"
    links_one.write_text("https://reddit.com/r/test/comments/one|save\n")
    links_two.write_text("https://reddit.com/r/test/comments/two|save\n")

    for schedule_id, links_path in (("first-due", links_one), ("second-due", links_two)):
        agentctl.main(
            [
                "--db-path",
                str(db_path),
                "schedules",
                "register",
                "--id",
                schedule_id,
                "--name",
                schedule_id,
                "--rrule",
                "FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
                "--account",
                "default",
                "--links",
                str(links_path),
                "--next-run-at",
                "2026-07-04T09:00:00",
                "--no-ensure-executor",
            ]
        )
        capsys.readouterr()

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "schedules",
            "run-due",
            "--id",
            "second-due",
            "--now",
            "2026-07-04T09:01:00",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in payload["processed"]] == ["second-due"]

    db = BotDatabase(str(db_path))
    try:
        schedules = {item["id"]: item for item in db.list_registered_schedules()}
        jobs = db.list_queue_jobs()
    finally:
        db.close()

    assert schedules["first-due"]["next_run_at"] == "2026-07-04T09:00:00"
    assert schedules["second-due"]["next_run_at"] == "2026-07-05T09:00:00"
    assert len(jobs) == 1
    assert jobs[0]["link"] == "https://reddit.com/r/test/comments/two"


def test_queue_retry_requeues_failed_job(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    links_path = tmp_path / "links.txt"
    links_path.write_text("https://reddit.com/r/test/comments/abc|upvote\n")
    agentctl.main(
        [
            "--db-path",
            str(db_path),
            "queue",
            "submit",
            "--account-label",
            "default",
            "--links",
            str(links_path),
            "--max-attempts",
            "1",
        ]
    )
    submitted = json.loads(capsys.readouterr().out)
    job_id = submitted["jobs"][0]["id"]
    db = BotDatabase(str(db_path))
    try:
        leased = db.lease_next_job("worker-1")
        assert leased["attempts"] == 1
        db.release_queue_job(job_id, "boom")
    finally:
        db.close()

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "queue",
            "retry",
            "--id",
            str(job_id),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["queueCounts"] == {"queued": 1}
    assert payload["retried"][0]["status"] == "queued"
    assert payload["retried"][0]["max_attempts"] == 2


def test_queue_retry_all_filters_account(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    db = BotDatabase(str(db_path))
    try:
        first = db.enqueue_action(
            "default",
            "upvote",
            {"link": "https://reddit.com/r/a/comments/abc", "action": "upvote"},
            link="https://reddit.com/r/a/comments/abc",
        )
        second = db.enqueue_action(
            "other",
            "upvote",
            {"link": "https://reddit.com/r/b/comments/def", "action": "upvote"},
            link="https://reddit.com/r/b/comments/def",
        )
        db.complete_queue_job(first["id"], success=False, error="default failed")
        db.complete_queue_job(second["id"], success=False, error="other failed")
    finally:
        db.close()

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "queue",
            "retry",
            "--all",
            "--account",
            "other",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["retried"][0]["account"] == "other"
    assert payload["queueCounts"] == {"failed": 1, "queued": 1}


def test_schedule_set_status_and_delete(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    links_path = tmp_path / "links.txt"
    links_path.write_text("https://reddit.com/r/test/comments/abc|upvote\n")
    agentctl.main(
        [
            "--db-path",
            str(db_path),
            "schedules",
            "register",
            "--id",
            "daily-actions",
            "--name",
            "Daily Actions",
            "--rrule",
            "FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            "--account",
            "default",
            "--links",
            str(links_path),
            "--next-run-at",
            "2026-07-04T09:00:00",
            "--no-ensure-executor",
        ]
    )
    capsys.readouterr()

    pause_exit = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "schedules",
            "set-status",
            "--id",
            "daily-actions",
            "--status",
            "PAUSED",
        ]
    )
    assert pause_exit == 0
    pause_payload = json.loads(capsys.readouterr().out)
    assert pause_payload["changed"] is True
    assert pause_payload["schedule"]["status"] == "PAUSED"

    delete_exit = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "schedules",
            "delete",
            "--id",
            "daily-actions",
        ]
    )
    assert delete_exit == 0
    delete_payload = json.loads(capsys.readouterr().out)
    assert delete_payload["deleted"] is True
    assert delete_payload["schedules"] == []


def test_vote_click_visible_resolves_profile_and_calls_helper(tmp_path, capsys, mocker):
    db_path = tmp_path / "agent.db"
    agentctl.main(
        [
            "--db-path",
            str(db_path),
            "profiles",
            "associate",
            "--profile-name",
            "Chrome Reddit Bot Debug Profile",
            "--reddit-user",
            "u/Particular-Arm2102",
            "--profile-path",
            str(tmp_path / "profile"),
            "--debug-address",
            "127.0.0.1:9222",
        ]
    )
    capsys.readouterr()
    driver = mocker.Mock()
    attached = mocker.patch("bot.agentctl._attached_chrome_driver", return_value=driver)
    click_visible = mocker.patch(
        "bot.utils.visible_vote.click_visible_vote_control",
        return_value={
            "ok": True,
            "clicked": True,
            "confirmed": True,
            "url": "https://reddit.com/r/test/comments/abc",
        },
    )

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "vote",
            "click-visible",
            "--reddit-user",
            "u/Particular-Arm2102",
            "--url",
            "https://reddit.com/r/test/comments/abc",
            "--action",
            "downvote",
            "--settle-seconds",
            "0",
            "--screenshot",
            str(tmp_path / "vote.png"),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["clicked"] is True
    assert payload["resolvedIdentity"]["accountLabel"] == "Particular-Arm2102"
    assert payload["leaseResource"] == "127.0.0.1:9222"
    attached.assert_called_once_with("127.0.0.1:9222")
    click_visible.assert_called_once_with(
        driver,
        intent="downvote",
        url="https://reddit.com/r/test/comments/abc",
        settle_seconds=0.0,
        screenshot_path=str(tmp_path / "vote.png"),
    )
    driver.quit.assert_called_once()


def test_vote_click_visible_reserves_quota_and_logs_action(tmp_path, capsys, mocker):
    db_path = tmp_path / "agent.db"
    agentctl.main(
        [
            "--db-path",
            str(db_path),
            "profiles",
            "associate",
            "--profile-name",
            "Chrome Reddit Bot Debug Profile",
            "--reddit-user",
            "u/Particular-Arm2102",
            "--profile-path",
            str(tmp_path / "profile"),
            "--debug-address",
            "127.0.0.1:9222",
        ]
    )
    capsys.readouterr()
    db = BotDatabase(str(db_path))
    try:
        db.set_account_limit("Particular-Arm2102", 1)
    finally:
        db.close()

    driver = mocker.Mock()
    attached = mocker.patch("bot.agentctl._attached_chrome_driver", return_value=driver)
    mocker.patch(
        "bot.utils.visible_vote.click_visible_vote_control",
        return_value={
            "ok": True,
            "clicked": True,
            "confirmed": True,
            "url": "https://reddit.com/r/test/comments/abc",
            "screenshotPath": None,
        },
    )

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "vote",
            "click-visible",
            "--reddit-user",
            "u/Particular-Arm2102",
            "--url",
            "https://reddit.com/r/test/comments/abc",
            "--action",
            "downvote",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["quota"]["reserved"] is True
    assert payload["audit"] == {"logged": True, "success": True}
    attached.assert_called_once_with("127.0.0.1:9222")

    db = BotDatabase(str(db_path))
    try:
        assert db.was_action_performed(
            "Particular-Arm2102",
            "downvote",
            "https://reddit.com/r/test/comments/abc",
        )
        reservations = db.list_account_reservations(account="Particular-Arm2102")
    finally:
        db.close()
    assert reservations[0]["status"] == "succeeded"


def test_vote_click_visible_blocks_when_daily_quota_reached(tmp_path, capsys, mocker):
    db_path = tmp_path / "agent.db"
    agentctl.main(
        [
            "--db-path",
            str(db_path),
            "profiles",
            "associate",
            "--profile-name",
            "Chrome Reddit Bot Debug Profile",
            "--reddit-user",
            "u/Particular-Arm2102",
            "--profile-path",
            str(tmp_path / "profile"),
            "--debug-address",
            "127.0.0.1:9222",
        ]
    )
    capsys.readouterr()
    db = BotDatabase(str(db_path))
    try:
        db.set_account_limit("Particular-Arm2102", 1)
        db.log_action(
            "Particular-Arm2102",
            "downvote",
            "https://reddit.com/r/test/comments/already",
        )
    finally:
        db.close()
    attached = mocker.patch("bot.agentctl._attached_chrome_driver")

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "vote",
            "click-visible",
            "--reddit-user",
            "u/Particular-Arm2102",
            "--url",
            "https://reddit.com/r/test/comments/abc",
            "--action",
            "downvote",
        ]
    )

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["quotaBlocked"] is True
    assert "Daily quota (1) reached" in payload["error"]
    attached.assert_not_called()
