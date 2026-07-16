"""Resolve Reddit share shortlinks to canonical /comments/ URLs."""

from __future__ import annotations

import urllib.error
from typing import Any

from bot.control.errors import CliError
from bot.utils.reddit_urls import (
    DEFAULT_RESOLVE_TIMEOUT,
    classify_reddit_url,
    describe_resolve_result,
    resolve_share_url,
    strip_url_noise,
)
from bot.utils.validators import is_post_url


def resolve_reddit_url(
    url: str,
    *,
    timeout: float = DEFAULT_RESOLVE_TIMEOUT,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Resolve a Reddit URL for agent use.

    Behavior:
    - Canonical post URL → returned as-is with ``resolved: false``, ``kind: post``
    - Share shortlink (``/r/.../s/...``) → HTTP redirect follow; final URL must be
      a post URL, with ``resolved: true``, ``kind: post``
    - Other valid Reddit URLs → passthrough with ``resolved: false``
    - Invalid / empty / non-Reddit → raises :class:`CliError`

    Returns a dict with keys ``input``, ``output``, ``resolved``, ``kind``.
    """
    text = (url or "").strip()
    if not text:
        raise CliError("A non-empty --link URL is required.")

    kind = classify_reddit_url(text)
    if kind == "invalid":
        raise CliError(
            f"Not a valid Reddit URL: {text!r}. "
            "Expected a reddit.com http(s) link."
        )

    if kind == "post":
        output = strip_url_noise(text)
        return describe_resolve_result(
            input_url=text,
            output_url=output,
            resolved=False,
            kind="post",
        )

    if kind != "share":
        # Subreddit, user, or other reddit.com paths: passthrough, no network.
        output = strip_url_noise(text)
        return describe_resolve_result(
            input_url=text,
            output_url=output,
            resolved=False,
            kind=kind if kind in {"subreddit", "user"} else "other",
        )

    try:
        final = resolve_share_url(text, timeout=timeout, user_agent=user_agent)
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    except TimeoutError as exc:
        raise CliError(
            f"Timed out resolving share URL after {timeout}s: {text}"
        ) from exc
    except urllib.error.HTTPError as exc:
        raise CliError(
            f"HTTP {exc.code} while resolving share URL: {text}"
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        raise CliError(f"Failed to resolve share URL {text!r}: {reason}") from exc
    except OSError as exc:
        raise CliError(f"Failed to resolve share URL {text!r}: {exc}") from exc

    if not is_post_url(final):
        raise CliError(
            "Share URL did not redirect to a canonical post URL "
            f"(/r/<sub>/comments/<id>/...). Got: {final!r}"
        )

    return describe_resolve_result(
        input_url=text,
        output_url=final,
        resolved=True,
        kind="post",
    )
