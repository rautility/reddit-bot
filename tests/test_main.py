"""Tests for top-level execution orchestration."""

import logging

from bot.config import BotConfig
from bot.reporting import ExecutionSummary
from bot.utils.credentials import Account
from bot.utils.input_parser import ActionEntry
from main import _execute_run, run_account


def test_execute_run_dry_run_skips_account_execution(mocker):
    run_account = mocker.patch("main.run_account")
    account_delay = mocker.patch("main.Timeouts.custom")
    logger = logging.getLogger("test-reddit-bot")

    summary = _execute_run(
        BotConfig(dry_run=True),
        [Account(username="user1", password="pass1")],
        [ActionEntry(link="https://reddit.com/r/test", action="join")],
        logger,
    )

    assert summary.total == 1
    assert summary.succeeded == 1
    assert summary.results[0].action == "join"
    assert summary.results[0].message == "Would execute for user1"
    run_account.assert_not_called()
    account_delay.assert_not_called()


def test_run_account_returns_failed_summary_on_browser_startup_error(mocker):
    mocker.patch(
        "main.RedditBot",
        side_effect=RuntimeError("Chrome debugger is not reachable at 127.0.0.1:9222"),
    )
    logger = logging.getLogger("test-reddit-bot")

    summary = run_account(
        Account(username="user1", password="pass1"),
        [ActionEntry(link="https://reddit.com/r/test", action="join")],
        BotConfig(use_existing_chrome=True, chrome_debugging_address="127.0.0.1:9222"),
        logger,
    )

    assert summary.total == 1
    assert summary.failed == 1
    assert summary.results[0].action == "browser_startup"
    assert "Chrome debugger is not reachable" in summary.results[0].message


def test_run_account_records_manual_login_failure(mocker):
    class FakeBot:
        def __init__(self):
            self.summary = ExecutionSummary()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.summary.finalize()
            return False

        def login_with_existing_chrome(self, username):
            return False

        def login_interactively(self, username):
            raise RuntimeError("Manual login timeout for user: user1")

    mocker.patch("main.RedditBot", return_value=FakeBot())
    logger = logging.getLogger("test-reddit-bot")

    summary = run_account(
        Account(username="user1", password="pass1"),
        [ActionEntry(link="https://reddit.com/r/test", action="join")],
        BotConfig(use_existing_chrome=True),
        logger,
    )

    assert summary.total == 1
    assert summary.failed == 1
    assert summary.results[0].action == "manual_login"
    assert "Manual login timeout" in summary.results[0].message
