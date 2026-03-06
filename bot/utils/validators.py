"""URL and input validation utilities."""

from __future__ import annotations

import re
from urllib.parse import urlparse


REDDIT_DOMAINS = {"reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com"}

REDDIT_POST_PATTERN = re.compile(
    r"https?://(www\.|old\.|new\.)?reddit\.com/r/\w+/comments/\w+"
)
REDDIT_SUBREDDIT_PATTERN = re.compile(
    r"https?://(www\.|old\.|new\.)?reddit\.com/r/\w+/?$"
)
REDDIT_USER_PATTERN = re.compile(
    r"https?://(www\.|old\.|new\.)?reddit\.com/u(ser)?/\w+"
)


def validate_reddit_url(url: str) -> bool:
    """Check if a URL is a valid Reddit URL."""
    try:
        parsed = urlparse(url)
        return parsed.hostname in REDDIT_DOMAINS and parsed.scheme in ("http", "https")
    except Exception:
        return False


def is_post_url(url: str) -> bool:
    """Check if URL points to a Reddit post."""
    return bool(REDDIT_POST_PATTERN.match(url))


def is_subreddit_url(url: str) -> bool:
    """Check if URL points to a subreddit."""
    return bool(REDDIT_SUBREDDIT_PATTERN.match(url))


def is_user_url(url: str) -> bool:
    """Check if URL points to a Reddit user profile."""
    return bool(REDDIT_USER_PATTERN.match(url))
