"""Utility modules for the Reddit bot.

Imports are kept lightweight — modules with heavy dependencies
(cryptography, selenium) are imported on demand.
"""

from .timeouts import Timeouts
from .retry import retry_action
from .user_agents import get_random_user_agent
from .input_parser import parse_links_file
from .validators import validate_reddit_url
from .proxy import load_proxies, get_next_proxy


def __getattr__(name):
    if name in ("read_accounts", "encrypt_file", "decrypt_file"):
        from . import credentials
        return getattr(credentials, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
