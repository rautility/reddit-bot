"""Tests for reporting and summary generation."""

import json

from bot.actions.base import ActionResult
from bot.reporting import ExecutionSummary, setup_structured_logger


class TestExecutionSummary:
    def test_empty_summary(self):
        s = ExecutionSummary()
        assert s.total == 0
        assert s.succeeded == 0
        assert s.failed == 0

    def test_add_results(self):
        s = ExecutionSummary()
        s.add(ActionResult(success=True, action="upvote", link="https://r.com/1"))
        s.add(ActionResult(success=True, action="comment", link="https://r.com/2"))
        s.add(ActionResult(success=False, action="join", link="https://r.com/3", message="failed"))
        assert s.total == 3
        assert s.succeeded == 2
        assert s.failed == 1

    def test_print_table(self):
        s = ExecutionSummary()
        s.add(ActionResult(success=True, action="upvote", link="https://r.com/1"))
        s.finalize()
        table = s.print_table()
        assert "EXECUTION SUMMARY" in table
        assert "upvote" in table
        assert "Total: 1" in table

    def test_to_dict(self):
        s = ExecutionSummary()
        s.add(ActionResult(success=True, action="upvote", link="https://r.com/1"))
        s.finalize()
        d = s.to_dict()
        assert d["total"] == 1
        assert d["succeeded"] == 1
        assert len(d["results"]) == 1


def test_structured_logger_writes_json_file(tmp_path):
    logger = setup_structured_logger(
        "test-reddit-bot-reporting",
        log_dir=tmp_path,
        log_file="bot.log",
        console=False,
    )

    logger.error("Failure to inspect later")

    log_path = tmp_path / "bot.log"
    assert log_path.exists()
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["level"] == "ERROR"
    assert record["message"] == "Failure to inspect later"
    assert record["logger"] == "test-reddit-bot-reporting"


def test_structured_logger_does_not_duplicate_managed_handlers(tmp_path):
    logger = setup_structured_logger(
        "test-reddit-bot-no-duplicates",
        log_dir=tmp_path,
        log_file="bot.log",
        console=False,
    )
    setup_structured_logger(
        "test-reddit-bot-no-duplicates",
        log_dir=tmp_path,
        log_file="bot.log",
        console=False,
    )

    logger.error("Write once")

    assert len((tmp_path / "bot.log").read_text().splitlines()) == 1
