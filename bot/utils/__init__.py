"""Utility modules for the Reddit bot.

Imports are kept lightweight — modules with heavy dependencies
(cryptography, selenium) are imported on demand.
"""

from .input_parser import parse_links_file as parse_links_file
from .proxy import get_next_proxy as get_next_proxy
from .proxy import load_proxies as load_proxies
from .retry import retry_action as retry_action
from .timeouts import Timeouts as Timeouts
from .user_agents import get_random_user_agent as get_random_user_agent
from .validators import validate_reddit_url as validate_reddit_url


def __getattr__(name):
    if name in ("read_accounts", "encrypt_file", "decrypt_file"):
        from . import credentials

        return getattr(credentials, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
