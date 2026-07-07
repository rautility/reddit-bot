"""Randomized timeout utilities for human-like delays."""

import random
import time


class Timeouts:
    @staticmethod
    def srt() -> None:
        """Short timeout (0-3s)."""
        time.sleep(random.random() + random.randint(0, 2))

    @staticmethod
    def med() -> None:
        """Medium timeout (2-6s)."""
        time.sleep(random.random() + random.randint(2, 5))

    @staticmethod
    def lng() -> None:
        """Long timeout (5-11s)."""
        time.sleep(random.random() + random.randint(5, 10))

    @staticmethod
    def custom(min_sec: float, max_sec: float) -> None:
        """Custom timeout with specified range."""
        time.sleep(random.uniform(min_sec, max_sec))
