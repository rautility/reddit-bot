"""Retry logic with exponential backoff for bot actions."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)


def retry_action(
    max_retries: int = 3,
    base_delay: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """Decorator that retries a function with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay in seconds (doubles each retry).
        exceptions: Tuple of exception types to catch and retry on.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            f"Action '{func.__name__}' failed (attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"Action '{func.__name__}' failed after {max_retries + 1} attempts: {e}")
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator
