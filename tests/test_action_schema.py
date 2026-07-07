"""Tests for the machine-readable action schema."""

from bot import action_schema
from bot.actions.registry import ActionRegistry


def test_schema_action_set_matches_registry():
    """The schema must describe exactly the actions the registry can execute."""
    assert set(action_schema.action_names()) == set(ActionRegistry.list_actions())


def test_validate_reports_missing_required_fields():
    assert action_schema.validate_action_fields("upvote", {}) == [
        {
            "field": "link",
            "error": "'upvote' requires 'link': Target Reddit URL. For post actions, "
            "a canonical /comments/ post URL.",
        }
    ]

    comment_errors = action_schema.validate_action_fields("comment", {"link": "https://x"})
    assert [e["field"] for e in comment_errors] == ["comment"]

    dm_errors = action_schema.validate_action_fields("dm", {"recipient": "u/foo"})
    assert [e["field"] for e in dm_errors] == ["message"]


def test_validate_accepts_complete_payload():
    assert action_schema.validate_action_fields(
        "dm", {"recipient": "u/foo", "message": "hi"}
    ) == []
    assert action_schema.validate_action_fields(
        "upvote", {"link": "https://www.reddit.com/r/x/comments/a/s/"}
    ) == []


def test_validate_rejects_blank_values():
    errors = action_schema.validate_action_fields("upvote", {"link": "   "})
    assert [e["field"] for e in errors] == ["link"]


def test_unknown_action_reports_action_error():
    errors = action_schema.validate_action_fields("nope", {})
    assert errors[0]["field"] == "action"
    assert "Unknown action" in errors[0]["error"]


def test_describe_actions_is_json_shaped():
    described = action_schema.describe_actions()
    assert described["schemaVersion"] == action_schema.SCHEMA_VERSION
    assert "upvote" in described["actions"]
    assert described["urlContract"]["canonicalFormat"].startswith("https://www.reddit.com/")
