"""Reddit URL helpers: classify links and resolve share shortlinks via HTTP."""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse, urlunparse

from bot.utils.user_agents import USER_AGENTS
from bot.utils.validators import (
    is_post_url,
    is_share_url,
    is_subreddit_url,
    is_user_url,
    validate_reddit_url,
)

DEFAULT_RESOLVE_TIMEOUT = 15.0
DEFAULT_USER_AGENT = USER_AGENTS[0]


def classify_reddit_url(url: str) -> str:
    """Return a coarse kind for a Reddit-ish URL string.

    Values: ``post``, ``share``, ``subreddit``, ``user``, ``reddit``, ``invalid``.
    """
    text = (url or "").strip()
    if not text or not validate_reddit_url(text):
        return "invalid"
    if is_share_url(text):
        return "share"
    if is_post_url(text):
        return "post"
    if is_subreddit_url(text):
        return "subreddit"
    if is_user_url(text):
        return "user"
    return "reddit"


def strip_url_noise(url: str) -> str:
    """Drop query/fragment and trailing noise while keeping scheme/host/path."""
    parsed = urlparse(url.strip())
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        # Keep a single trailing slash for Reddit post paths; harmless elsewhere.
        pass
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def follow_http_redirects(
    url: str,
    *,
    timeout: float = DEFAULT_RESOLVE_TIMEOUT,
    user_agent: str | None = None,
) -> str:
    """GET ``url`` with a browser-like User-Agent and return the final URL.

    Uses stdlib ``urllib`` only (no Selenium). Redirects are followed by
    default; ``geturl()`` is the post-redirect location.
    """
    ua = user_agent or DEFAULT_USER_AGENT
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final = response.geturl()
    return strip_url_noise(final)


def resolve_share_url(
    url: str,
    *,
    timeout: float = DEFAULT_RESOLVE_TIMEOUT,
    user_agent: str | None = None,
) -> str:
    """Resolve a Reddit ``/r/.../s/...`` share shortlink to a final URL.

    Raises ``ValueError`` when the input is not a share URL, and
    ``urllib.error.URLError`` / ``TimeoutError`` on network failures.
    """
    text = (url or "").strip()
    if not is_share_url(text):
        raise ValueError(f"Not a Reddit share shortlink: {url!r}")
    return follow_http_redirects(text, timeout=timeout, user_agent=user_agent)


def describe_resolve_result(
    *,
    input_url: str,
    output_url: str,
    resolved: bool,
    kind: str,
) -> dict[str, Any]:
    """Stable JSON shape for resolve-url responses."""
    return {
        "input": input_url,
        "output": output_url,
        "resolved": resolved,
        "kind": kind,
    }
