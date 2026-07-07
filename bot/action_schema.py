"""Machine-readable action schema — the single source of truth for what each
Reddit action needs.

This module is intentionally dependency-free (no selenium, no DB) so it can be
imported cheaply by the `capabilities` command, by input validation, and by
tests. The action set is asserted against ``ActionRegistry`` in the test suite
so this file cannot silently drift from the real implementations.

Field names are the transport fields carried by
:class:`bot.utils.input_parser.ActionEntry` (``link``, ``action``, ``comment``,
``title``, ``subreddit``, ``body``, ``flair``, ``recipient``, ``message``).
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "1.0"

# Canonical post-URL contract, mirrored from bot.utils.validators / agentctl.
POST_URL_FORMAT = "https://www.reddit.com/r/<subreddit>/comments/<post_id>/<slug>/"

URL_CONTRACT = {
    "postActions": sorted(["upvote", "downvote", "comment", "save", "hide", "crosspost"]),
    "canonicalFormat": POST_URL_FORMAT,
    "rejects": "Reddit share shortlinks like /r/<subreddit>/s/<share_id>. "
    "Resolve them to the canonical /comments/ URL before submitting.",
}

# What each transport field means, so an agent never has to read prose to build
# a valid payload.
FIELD_GLOSSARY = {
    "link": "Target Reddit URL. For post actions, a canonical /comments/ post URL.",
    "comment": "Comment body text (used by the `comment` action).",
    "title": "Post title, or the subject line for a `dm`.",
    "subreddit": "Destination community name or URL for post/crosspost actions.",
    "body": "Overloaded free-text field: post text, or the URL for `post_link`, "
    "or the local image path for `post_image`, or the new bio for `update_bio`.",
    "flair": "Optional flair text for a submitted post.",
    "recipient": "Reddit username to receive a `dm`.",
    "message": "Message body for a `dm`.",
}

# action -> spec. `required`/`optional` are transport field names.
# `link_kind` is a hint for the caller: post_url | community_url | user_url | none | query.
ACTION_SCHEMA: dict[str, dict[str, Any]] = {
    "upvote": {
        "summary": "Upvote a post.",
        "required": ["link"],
        "optional": [],
        "link_kind": "post_url",
    },
    "downvote": {
        "summary": "Downvote a post.",
        "required": ["link"],
        "optional": [],
        "link_kind": "post_url",
    },
    "comment": {
        "summary": "Post a top-level comment on a post.",
        "required": ["link", "comment"],
        "optional": [],
        "link_kind": "post_url",
    },
    "save": {
        "summary": "Save a post.",
        "required": ["link"],
        "optional": [],
        "link_kind": "post_url",
    },
    "hide": {
        "summary": "Hide a post.",
        "required": ["link"],
        "optional": [],
        "link_kind": "post_url",
    },
    "join": {
        "summary": "Join a community.",
        "required": ["link"],
        "optional": [],
        "link_kind": "community_url",
    },
    "leave": {
        "summary": "Leave a community.",
        "required": ["link"],
        "optional": [],
        "link_kind": "community_url",
    },
    "follow": {
        "summary": "Follow a user.",
        "required": ["link"],
        "optional": [],
        "link_kind": "user_url",
    },
    "unfollow": {
        "summary": "Unfollow a user.",
        "required": ["link"],
        "optional": [],
        "link_kind": "user_url",
    },
    "update_bio": {
        "summary": "Update the logged-in account's profile bio.",
        "required": ["body"],
        "optional": [],
        "link_kind": "none",
        "notes": "body is the new bio text; link is ignored.",
    },
    "dm": {
        "summary": "Send a direct message to a user.",
        "required": ["recipient", "message"],
        "optional": ["title"],
        "link_kind": "none",
        "notes": "title is the optional subject line.",
    },
    "post_text": {
        "summary": "Create a text (self) post in a community.",
        "required": ["title", "subreddit"],
        "optional": ["body", "flair"],
        "link_kind": "none",
        "notes": "body is the post text.",
    },
    "post_link": {
        "summary": "Create a link post in a community.",
        "required": ["title", "subreddit", "body"],
        "optional": ["flair"],
        "link_kind": "none",
        "notes": "body is the URL to submit.",
    },
    "post_image": {
        "summary": "Create an image post in a community.",
        "required": ["title", "subreddit", "body"],
        "optional": ["flair"],
        "link_kind": "none",
        "notes": "body is the local image file path.",
    },
    "crosspost": {
        "summary": "Crosspost an existing post to another community.",
        "required": ["link", "subreddit"],
        "optional": ["title"],
        "link_kind": "post_url",
        "notes": "link is the source post; subreddit is the destination community.",
    },
    "human_search": {
        "summary": "Run a human-like Reddit search.",
        "required": ["link"],
        "optional": ["subreddit"],
        "link_kind": "query",
        "notes": "For queued runs, put the search query text in the link field.",
    },
    "search_upvote": {
        "summary": "Search Reddit and upvote the selected organic post.",
        "required": ["link"],
        "optional": ["subreddit"],
        "link_kind": "query",
        "notes": (
            "For queued or scheduled runs, put the search query text in the link "
            "field. The worker records the selected post URL in the action result."
        ),
    },
}


def action_names() -> list[str]:
    """Return the sorted set of actions this schema describes."""
    return sorted(ACTION_SCHEMA)


def _has_value(provided: dict[str, Any], field: str) -> bool:
    value = provided.get(field)
    return value is not None and str(value).strip() != ""


def validate_action_fields(action: str, provided: dict[str, Any]) -> list[dict[str, str]]:
    """Return a list of structured errors for a proposed action payload.

    Each error is ``{"field": name, "error": message}``. An empty list means the
    payload has every field the action requires. Unknown actions yield a single
    ``action`` error.
    """
    spec = ACTION_SCHEMA.get(action)
    if spec is None:
        return [
            {
                "field": "action",
                "error": f"Unknown action '{action}'. Valid actions: "
                + ", ".join(action_names())
                + ".",
            }
        ]
    errors: list[dict[str, str]] = []
    for field in spec["required"]:
        if not _has_value(provided, field):
            errors.append(
                {
                    "field": field,
                    "error": f"'{action}' requires '{field}': {FIELD_GLOSSARY.get(field, '')}".strip(),
                }
            )
    return errors


def describe_actions() -> dict[str, Any]:
    """Return the full, JSON-serializable capability description."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "actions": ACTION_SCHEMA,
        "fieldGlossary": FIELD_GLOSSARY,
        "urlContract": URL_CONTRACT,
    }
