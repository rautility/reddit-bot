"""Reddit Bot package.

Core imports are lazy to allow utility modules (config, database, credentials, etc.)
to be used and tested without selenium installed.
"""

from .config import BotConfig as BotConfig
from .ghost_logger import GhostLogger as GhostLogger


def __getattr__(name):
    if name == "RedditBot":
        from .bot import RedditBot

        return RedditBot
    if name == "BotDatabase":
        from .database import BotDatabase

        return BotDatabase
    if name == "ExecutionSummary":
        from .reporting import ExecutionSummary

        return ExecutionSummary
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
