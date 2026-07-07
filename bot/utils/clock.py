"""UTC clock helpers that preserve existing naive-UTC storage format."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return current UTC time as a naive datetime for legacy ISO string storage."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_now_iso() -> str:
    """Return current UTC time as a naive ISO-8601 string."""
    return utc_now().isoformat()
