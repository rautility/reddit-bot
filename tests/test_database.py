"""Tests for the database tracking module."""

import os

import pytest

from bot.database import BotDatabase


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = BotDatabase(db_path)
    yield database
    database.close()


class TestBotDatabase:
    def test_log_action(self, db):
        db.log_action("user1", "upvote", "https://reddit.com/r/test/comments/abc")
        assert db.was_action_performed("user1", "upvote", "https://reddit.com/r/test/comments/abc")

    def test_action_not_performed(self, db):
        assert not db.was_action_performed("user1", "upvote", "https://reddit.com/r/test/comments/xyz")

    def test_failed_action_not_counted_as_performed(self, db):
        db.log_action("user1", "upvote", "https://reddit.com/r/test", success=False)
        assert not db.was_action_performed("user1", "upvote", "https://reddit.com/r/test")

    def test_daily_action_count(self, db):
        db.log_action("user1", "upvote", "https://reddit.com/r/a")
        db.log_action("user1", "downvote", "https://reddit.com/r/b")
        db.log_action("user1", "comment", "https://reddit.com/r/c")
        assert db.get_daily_action_count("user1") == 3

    def test_daily_action_count_separate_accounts(self, db):
        db.log_action("user1", "upvote", "https://reddit.com/r/a")
        db.log_action("user2", "upvote", "https://reddit.com/r/a")
        assert db.get_daily_action_count("user1") == 1
        assert db.get_daily_action_count("user2") == 1

    def test_action_summary(self, db):
        db.log_action("user1", "upvote", "https://reddit.com/r/a", success=True)
        db.log_action("user1", "upvote", "https://reddit.com/r/b", success=False)
        db.log_action("user1", "comment", "https://reddit.com/r/c", success=True)

        summary = db.get_action_summary()
        assert len(summary) == 2  # upvote and comment groups

        upvote_row = next(r for r in summary if r["action"] == "upvote")
        assert upvote_row["succeeded"] == 1
        assert upvote_row["failed"] == 1
