"""Tests for the human-friendly Reddit bot operations CLI."""

import json

from bot import tool_cli
from bot.database import BotDatabase


def test_selection_details_from_outcomes_extracts_attempts():
    outcomes = [
        {"result": {"results": [{"link": "x"}]}},  # no details -> skipped
        {
            "result": {
                "results": [
                    {
                        "details": {
                            "selectedUrl": "https://www.reddit.com/r/x/comments/b/two/",
                            "attempts": [{"index": 1, "outcome": "upvoted"}],
                        }
                    }
                ]
            }
        },
    ]
    details = tool_cli._selection_details_from_outcomes(outcomes)
    assert details["selectedUrl"] == "https://www.reddit.com/r/x/comments/b/two/"
    assert details["attempts"][0]["outcome"] == "upvoted"


def test_selection_details_from_outcomes_none_when_absent():
    assert tool_cli._selection_details_from_outcomes([]) is None
    assert tool_cli._selection_details_from_outcomes(
        [{"result": {"results": [{"link": "x"}]}}]
    ) is None


def test_schedule_add_writes_action_file_and_registers_schedule(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    actions_dir = tmp_path / "actions"

    exit_code = tool_cli.main(
        [
            "--db-path",
            str(db_path),
            "schedule",
            "add",
            "--name",
            "Daily Test Action",
            "--link",
            "https://www.reddit.com/r/test/comments/abc/title/",
            "--action",
            "upvote",
            "--daily-at",
            "09:30",
            "--account-label",
            "default",
            "--actions-dir",
            str(actions_dir),
            "--no-ensure-executor",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Schedule registered" in output

    db = BotDatabase(str(db_path))
    try:
        schedules = db.list_registered_schedules()
    finally:
        db.close()

    assert len(schedules) == 1
    schedule = schedules[0]
    assert schedule["name"] == "Daily Test Action"
    assert schedule["account"] == "default"
    assert schedule["rrule"] == "FREQ=DAILY;BYHOUR=9;BYMINUTE=30"

    metadata = json.loads(schedule["metadata_json"])
    links_path = actions_dir / f"{schedule['id']}.txt"
    assert metadata["linksPath"] == str(links_path)
    assert links_path.read_text() == (
        "https://www.reddit.com/r/test/comments/abc/title/|upvote\n"
    )


def test_schedule_add_json_outputs_registered_payload(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    links_path = tmp_path / "links.txt"
    links_path.write_text("https://www.reddit.com/r/test/comments/abc/title/|save\n")

    exit_code = tool_cli.main(
        [
            "--db-path",
            str(db_path),
            "--json",
            "schedule",
            "add",
            "--id",
            "one-time-save",
            "--name",
            "One Time Save",
            "--links",
            str(links_path),
            "--at",
            "2026-07-06T09:00:00",
            "--account-label",
            "default",
            "--no-ensure-executor",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["registered"] == "one-time-save"
    assert payload["linksPath"] == str(links_path)
    assert payload["executor"]["ensured"] is False


def test_schedule_add_accepts_query_for_search_upvote(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    actions_dir = tmp_path / "actions"

    exit_code = tool_cli.main(
        [
            "--db-path",
            str(db_path),
            "schedule",
            "add",
            "--name",
            "Search Excel Tips",
            "--query",
            "best Excel tips",
            "--action",
            "search_upvote",
            "--at",
            "2026-07-06T09:00:00",
            "--account-label",
            "default",
            "--actions-dir",
            str(actions_dir),
            "--no-ensure-executor",
        ]
    )

    assert exit_code == 0
    capsys.readouterr()

    db = BotDatabase(str(db_path))
    try:
        schedule = db.list_registered_schedules()[0]
    finally:
        db.close()

    links_path = actions_dir / f"{schedule['id']}.txt"
    assert links_path.read_text() == "best Excel tips|search_upvote\n"


def test_external_search_upvote_registers_one_shot_schedule_without_running(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    actions_dir = tmp_path / "actions"

    exit_code = tool_cli.main(
        [
            "--db-path",
            str(db_path),
            "--json",
            "external-search-upvote",
            "--query",
            "Excel for medical doctors cdu",
            "--id",
            "external-test",
            "--at",
            "2026-07-06T09:00:00",
            "--account-label",
            "default",
            "--actions-dir",
            str(actions_dir),
            "--no-run-due",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["scheduleId"] == "external-test"
    assert payload["data"]["mutationStatus"] == "not_run"

    db = BotDatabase(str(db_path))
    try:
        schedule = db.list_registered_schedules()[0]
    finally:
        db.close()

    assert schedule["source"] == "external-project"
    assert schedule["next_run_at"] == "2026-07-06T09:00:00"
    links_path = actions_dir / "external-test.txt"
    assert links_path.read_text() == "Excel for medical doctors cdu|search_upvote\n"


def test_external_search_upvote_preflights_before_registration(tmp_path, capsys, mocker):
    db_path = tmp_path / "agent.db"
    actions_dir = tmp_path / "actions"
    mocker.patch(
        "bot.tool_cli._profile_preflight",
        side_effect=tool_cli.CliError("Chrome unavailable"),
    )

    exit_code = tool_cli.main(
        [
            "--db-path",
            str(db_path),
            "--json",
            "external-search-upvote",
            "--query",
            "Excel for medical doctors cdu",
            "--at",
            "2026-07-06T09:00:00",
            "--account-label",
            "default",
            "--actions-dir",
            str(actions_dir),
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["data"]["mutationStatus"] == "blocked_before_registration"

    db = BotDatabase(str(db_path))
    try:
        schedules = db.list_registered_schedules()
    finally:
        db.close()

    assert schedules == []
    assert not actions_dir.exists()


def test_external_search_upvote_generated_id_is_stable_in_retry_window(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    actions_dir = tmp_path / "actions"

    exit_code = tool_cli.main(
        [
            "--db-path",
            str(db_path),
            "--json",
            "external-search-upvote",
            "--query",
            "Excel for medical doctors cdu",
            "--at",
            "2026-07-06T09:04:30",
            "--account-label",
            "default",
            "--actions-dir",
            str(actions_dir),
            "--no-run-due",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    expected_id = "external-search-upvote-excel-for-medical-doctors-cdu-default-20260706T090000"
    assert payload["data"]["scheduleId"] == expected_id
    assert payload["data"]["scheduleIdRegistered"] == expected_id
    assert (actions_dir / f"{expected_id}.txt").exists()


def test_external_search_upvote_reuses_successful_job_in_retry_window(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    actions_dir = tmp_path / "actions"
    query = "Excel for medical doctors cdu"
    selected = "https://www.reddit.com/r/medschoolph/comments/1lmbi2i/honest_talk/"

    db = BotDatabase(str(db_path))
    try:
        job = db.enqueue_action(
            "default",
            "search_upvote",
            {"action": "search_upvote", "link": query},
            link=query,
        )
        db.conn.execute(
            "UPDATE agent_queue SET created_at = ?, updated_at = ? WHERE id = ?",
            ("2026-07-06T09:02:00", "2026-07-06T09:02:30", job["id"]),
        )
        db.conn.commit()
        db.complete_queue_job(
            job["id"],
            success=True,
            result={
                "failed": 0,
                "succeeded": 1,
                "total": 1,
                "results": [
                    {
                        "action": "search_upvote",
                        "link": selected,
                        "message": "Vote registered",
                        "success": True,
                    }
                ],
            },
        )
    finally:
        db.close()

    exit_code = tool_cli.main(
        [
            "--db-path",
            str(db_path),
            "--json",
            "external-search-upvote",
            "--query",
            query,
            "--at",
            "2026-07-06T09:04:30",
            "--account-label",
            "default",
            "--actions-dir",
            str(actions_dir),
            "--no-profile-preflight",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["idempotency"]["reusedExistingJob"] is True
    assert payload["data"]["jobIds"] == [job["id"]]
    assert payload["data"]["selectedPostUrl"] == selected

    db = BotDatabase(str(db_path))
    try:
        schedules = db.list_registered_schedules()
    finally:
        db.close()

    assert schedules == []
    assert not actions_dir.exists()


def test_selected_post_url_falls_back_to_prior_successful_result(tmp_path):
    db_path = tmp_path / "agent.db"
    query = "Excel for medical doctors cdu"
    selected = "https://www.reddit.com/r/medschoolph/comments/1lmbi2i/honest_talk/"
    db = BotDatabase(str(db_path))
    try:
        previous = db.enqueue_action(
            "default",
            "search_upvote",
            {"action": "search_upvote", "link": query},
            link=query,
        )
        db.complete_queue_job(
            previous["id"],
            success=True,
            result={
                "results": [
                    {
                        "action": "search_upvote",
                        "link": selected,
                        "success": True,
                    }
                ]
            },
        )
        current = db.enqueue_action(
            "default",
            "search_upvote",
            {"action": "search_upvote", "link": query, "retry": True},
            link=query,
        )
        db.complete_queue_job(
            current["id"],
            success=True,
            result={
                "results": [
                    {
                        "action": "search_upvote",
                        "link": query,
                        "message": "Action already performed by default",
                        "success": True,
                    }
                ]
            },
        )
    finally:
        db.close()

    args = type("Args", (), {"config": None, "db_path": str(db_path)})()
    outcome = tool_cli._job_outcome(args, current["id"])

    assert tool_cli._selected_post_url_from_outcomes(args, [outcome]) == selected


def test_queue_default_lists_jobs(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    db = BotDatabase(str(db_path))
    try:
        db.enqueue_action(
            "default",
            "upvote",
            {"link": "https://reddit.com/r/test/comments/abc", "action": "upvote"},
            link="https://reddit.com/r/test/comments/abc",
        )
    finally:
        db.close()

    exit_code = tool_cli.main(["--db-path", str(db_path), "queue"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Queue" in output
    assert "queued" in output
    assert "upvote" in output


def test_errors_include_queue_schedule_and_action_failures(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    db = BotDatabase(str(db_path))
    try:
        job = db.enqueue_action(
            "default",
            "downvote",
            {"link": "https://reddit.com/r/test/comments/abc", "action": "downvote"},
            link="https://reddit.com/r/test/comments/abc",
        )
        db.complete_queue_job(job["id"], success=False, error="queue boom")
        db.register_schedule(
            "broken-schedule",
            "Broken Schedule",
            source="test",
            rrule="FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            account="default",
            action_class="live",
        )
        db.complete_schedule_run(
            "broken-schedule",
            next_run_at="2026-07-06T09:00:00",
            last_run_at=None,
            error="schedule boom",
        )
        db.log_action(
            "default",
            "upvote",
            "https://reddit.com/r/test/comments/xyz",
            success=False,
            error_message="action boom",
        )
    finally:
        db.close()

    exit_code = tool_cli.main(["--db-path", str(db_path), "errors", "--limit", "5"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "queue boom" in output
    assert "schedule boom" in output
    assert "action boom" in output


def test_menu_can_show_overview_and_exit(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "agent.db"
    inputs = iter(["1", "", "0"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    exit_code = tool_cli.main(["--db-path", str(db_path), "menu"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Reddit Bot Menu" in output
    assert "Reddit Bot Overview" in output


def test_menu_add_schedule_uses_prompts(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "agent.db"
    actions_dir = tmp_path / "menu-actions"
    monkeypatch.setattr(tool_cli, "DEFAULT_ACTIONS_DIR", actions_dir)
    inputs = iter(
        [
            "10",
            "Menu Daily Save",
            "1",
            "https://www.reddit.com/r/test/comments/menu/title/",
            "save",
            "",
            "2",
            "10:15",
            "account:default",
            "n",
            "",
            "0",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    exit_code = tool_cli.main(["--db-path", str(db_path), "menu"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Schedule registered" in output

    db = BotDatabase(str(db_path))
    try:
        schedules = db.list_registered_schedules()
    finally:
        db.close()

    assert len(schedules) == 1
    schedule = schedules[0]
    assert schedule["name"] == "Menu Daily Save"
    assert schedule["rrule"] == "FREQ=DAILY;BYHOUR=10;BYMINUTE=15"
    metadata = json.loads(schedule["metadata_json"])
    assert metadata["linksPath"].startswith(str(actions_dir))
