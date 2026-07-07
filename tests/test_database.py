"""Tests for the database tracking module."""

import pytest

from bot.database import BotDatabase
from bot.utils.clock import utc_now_iso


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = BotDatabase(db_path)
    yield database
    database.close()


class TestBotDatabase:
    def test_utc_now_iso_preserves_legacy_sortable_naive_format(self):
        now = utc_now_iso()

        assert "+00:00" not in now
        assert "Z" not in now
        assert "2026-01-01T00:00:00" < now

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

    def test_queue_deduplicates_active_jobs(self, db):
        payload = {"link": "https://reddit.com/r/a", "action": "upvote"}

        first = db.enqueue_action("user1", "upvote", payload, link=payload["link"])
        second = db.enqueue_action("user1", "upvote", payload, link=payload["link"])

        assert first["id"] == second["id"]
        assert db.get_queue_counts() == {"queued": 1}

    def test_lease_next_job_marks_running(self, db):
        db.enqueue_action(
            "user1",
            "upvote",
            {"link": "https://reddit.com/r/a", "action": "upvote"},
            link="https://reddit.com/r/a",
        )

        job = db.lease_next_job("worker-1", lease_seconds=60)

        assert job is not None
        assert job["status"] == "running"
        assert job["locked_by"] == "worker-1"
        assert db.lease_next_job("worker-2", lease_seconds=60) is None

    def test_recover_stale_queue_jobs_releases_expired_running_job(self, db):
        queued = db.enqueue_action(
            "user1",
            "upvote",
            {"link": "https://reddit.com/r/a", "action": "upvote"},
            link="https://reddit.com/r/a",
        )
        leased = db.lease_next_job("worker-1", lease_seconds=60)
        assert leased["id"] == queued["id"]

        recovered = db.recover_stale_queue_jobs(now_iso="2999-01-01T00:00:00")

        assert recovered == [
            {
                "id": queued["id"],
                "previousStatus": "running",
                "status": "queued",
                "account": "user1",
                "action": "upvote",
                "link": "https://reddit.com/r/a",
                "attempts": 1,
                "maxAttempts": 3,
                "lockedBy": "worker-1",
                "lockedUntil": leased["locked_until"],
                "message": "Queue job lease expired before completion; released for retry.",
            }
        ]
        job = db.get_queue_job(queued["id"])
        assert job["status"] == "queued"
        assert job["locked_by"] is None

    def test_enqueue_reuses_recovered_stale_job(self, db):
        payload = {"link": "https://reddit.com/r/a", "action": "upvote"}
        first = db.enqueue_action("user1", "upvote", payload, link=payload["link"])
        db.lease_next_job("worker-1", lease_seconds=-1)

        second = db.enqueue_action("user1", "upvote", payload, link=payload["link"])

        assert second["id"] == first["id"]
        assert second["status"] == "queued"

    def test_profile_lease_blocks_other_owner(self, db):
        acquired, message = db.acquire_lease(
            "chrome_profile",
            "127.0.0.1:9222",
            "worker-1",
            ttl_seconds=60,
        )
        assert acquired is True
        assert "Lease acquired" in message

        acquired, message = db.acquire_lease(
            "chrome_profile",
            "127.0.0.1:9222",
            "worker-2",
            ttl_seconds=60,
        )

        assert acquired is False
        assert "worker-1" in message

    def test_account_limit_round_trip(self, db):
        db.set_account_limit("user1", 10)
        db.set_account_limit("user1", 3, action="comment")

        assert db.get_account_limit("user1") == 10
        assert db.get_account_limit("user1", "comment") == 3
        assert db.list_account_limits()[0]["account"] == "user1"

    def test_quota_reservation_blocks_parallel_connection(self, tmp_path):
        db_path = str(tmp_path / "quota.db")
        first = BotDatabase(db_path)
        second = BotDatabase(db_path)
        try:
            ok, message, reservation_id = first.reserve_account_action(
                "user1",
                "upvote",
                "https://reddit.com/r/a",
                daily_quota=1,
            )
            assert ok is True
            assert reservation_id is not None
            assert message == "Reserved daily quota slot."

            ok, message, reservation_id = second.reserve_account_action(
                "user1",
                "upvote",
                "https://reddit.com/r/b",
                daily_quota=1,
            )

            assert ok is False
            assert reservation_id is None
            assert "Daily quota (1) reached for user1" == message
        finally:
            first.close()
            second.close()

    def test_chrome_profile_account_association_round_trip(self, db):
        association = db.associate_chrome_profile(
            "Chrome Reddit Bot Debug Profile",
            "u/Particular-Arm2102",
            profile_path="/Users/example/Chrome Reddit Bot Debug Profile",
            debug_address="127.0.0.1:9222",
        )

        assert association["reddit_username"] == "Particular-Arm2102"
        assert association["account_label"] == "Particular-Arm2102"

        by_profile = db.get_chrome_profile_association(profile_name="Chrome Reddit Bot Debug Profile")
        by_user = db.get_chrome_profile_association(reddit_username="u/Particular-Arm2102")

        assert by_profile == by_user
        assert db.list_chrome_profile_associations()[0]["debug_address"] == "127.0.0.1:9222"

    def test_due_schedule_lease_and_completion(self, db):
        db.register_schedule(
            "daily-actions",
            "Daily Actions",
            source="agentctl",
            rrule="FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            account="user1",
            profile="Chrome Reddit Bot Debug Profile",
            action_class="live",
            metadata={"linksPath": "/tmp/links.txt"},
            next_run_at="2026-07-04T09:00:00",
        )

        due = db.lease_due_schedules(
            "worker-1",
            now_iso="2026-07-04T09:01:00",
            lease_seconds=60,
        )

        assert len(due) == 1
        assert due[0]["id"] == "daily-actions"

        db.complete_schedule_run(
            "daily-actions",
            next_run_at="2026-07-05T09:00:00",
            last_run_at="2026-07-04T09:01:00",
        )
        schedule = db.list_registered_schedules()[0]
        assert schedule["next_run_at"] == "2026-07-05T09:00:00"
        assert schedule["last_run_at"] == "2026-07-04T09:01:00"
        assert schedule["locked_by"] is None
