"""Tests for the local web UI API helpers."""

from __future__ import annotations

import pytest

from bot.database import BotDatabase
from bot.web.server import make_handler


@pytest.fixture
def ui_handler(tmp_path):
    db_path = tmp_path / "ui.db"
    static_dir = tmp_path / "web"
    actions_dir = tmp_path / "actions"
    static_dir.mkdir()
    static_dir.joinpath("index.html").write_text("<html>ok</html>", encoding="utf-8")
    handler_class = make_handler(
        db_path=str(db_path),
        static_dir=static_dir,
        actions_dir=actions_dir,
        quiet=True,
    )
    handler = object.__new__(handler_class)
    return {
        "handler": handler,
        "db_path": db_path,
        "actions_dir": actions_dir,
    }


def test_overview_endpoint_returns_account_filtered_counts(ui_handler):
    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        db.enqueue_action(
            "default",
            "upvote",
            {"link": "https://reddit.com/r/test/comments/abc", "action": "upvote"},
            link="https://reddit.com/r/test/comments/abc",
        )
        db.enqueue_action(
            "other",
            "upvote",
            {"link": "https://reddit.com/r/test/comments/xyz", "action": "upvote"},
            link="https://reddit.com/r/test/comments/xyz",
        )
        db.set_account_limit("default", 10)
    finally:
        db.close()

    data = ui_handler["handler"]._overview("default")

    assert data["queueCounts"] == {"queued": 1}
    assert data["today"]["daily_action_quota"] == 10
    assert "executor" in data


def test_queue_retry_endpoint_requeues_failed_job(ui_handler):
    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        job = db.enqueue_action(
            "default",
            "upvote",
            {"link": "https://reddit.com/r/test/comments/abc", "action": "upvote"},
            link="https://reddit.com/r/test/comments/abc",
            max_attempts=1,
        )
        db.lease_next_job("worker-1")
        db.release_queue_job(job["id"], "boom")
    finally:
        db.close()

    payload = ui_handler["handler"]._agentctl(["queue", "retry", "--id", str(job["id"])])

    assert payload["ok"] is True
    assert payload["data"]["count"] == 1
    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        assert db.get_queue_job(job["id"])["status"] == "queued"
    finally:
        db.close()


def test_schedule_pause_and_delete_endpoints(ui_handler):
    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        db.register_schedule(
            "daily-actions",
            "Daily Actions",
            source="test",
            rrule="FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            status="ACTIVE",
            account="default",
        )
    finally:
        db.close()

    pause = ui_handler["handler"]._agentctl(["schedules", "set-status", "--id", "daily-actions", "--status", "PAUSED"])
    assert pause["ok"] is True
    assert pause["data"]["schedule"]["status"] == "PAUSED"

    delete = ui_handler["handler"]._agentctl(["schedules", "delete", "--id", "daily-actions"])
    assert delete["ok"] is True
    assert delete["data"]["deleted"] is True


def test_task_endpoint_registers_one_time_schedule(ui_handler):
    payload = ui_handler["handler"]._create_task(
        {
            "action": "upvote",
            "fields": {
                "link": "https://www.reddit.com/r/test/comments/abc/title/",
            },
            "identity": {"account_label": "default"},
            "timing": {"mode": "once", "at": "2026-07-06T09:00:00"},
            "noEnsureExecutor": True,
        },
    )

    assert payload["ok"] is True
    assert payload["data"]["registered"].startswith("reddit-ui-upvote-task")
    assert ui_handler["actions_dir"].exists()

    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        schedules = db.list_registered_schedules()
    finally:
        db.close()
    assert len(schedules) == 1
    assert schedules[0]["next_run_at"] == "2026-07-06T09:00:00"
