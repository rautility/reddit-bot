"""ChromeDriver resolution helpers for local and sandboxed runs."""

from __future__ import annotations

import os
from pathlib import Path

from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.driver_cache import DriverCacheManager

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = REPO_ROOT / ".webdriver"
ENV_CACHE_DIR = "REDDIT_BOT_WDM_CACHE"


def chromedriver_cache_dir() -> Path:
    """Return a writable cache dir for webdriver-manager artifacts."""
    override = os.environ.get(ENV_CACHE_DIR, "").strip()
    return Path(override).expanduser() if override else DEFAULT_CACHE_DIR


def install_chromedriver() -> str:
    """Install or resolve ChromeDriver using a repo-local cache."""
    cache_dir = chromedriver_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    manager = ChromeDriverManager(cache_manager=DriverCacheManager(root_dir=str(cache_dir)))
    return manager.install()
