"""Configuration management — supports YAML files, CLI args, and env vars."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class ProxyConfig:
    enabled: bool = False
    proxy_list_path: str | None = None
    rotate_per_account: bool = True


@dataclass
class RateLimitConfig:
    min_action_delay: float = 2.0
    max_action_delay: float = 8.0
    min_account_delay: float = 5.0
    max_account_delay: float = 15.0
    daily_action_quota: int = 0  # 0 = unlimited


@dataclass
class WebhookConfig:
    enabled: bool = False
    url: str | None = None
    on_completion: bool = True
    on_failure: bool = True


@dataclass
class BotConfig:
    # Input files
    accounts_path: str | None = None
    links_path: str | None = None

    # Modes
    verbose: bool = False
    headless: bool = False
    dry_run: bool = False

    # Anti-detection
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    rotate_user_agent: bool = False
    randomize_actions: bool = False
    human_mouse: bool = True
    manual_login: bool = True
    use_existing_chrome: bool = False
    chrome_user_data_dir: str | None = None
    chrome_profile_name: str | None = None
    chrome_debugging_address: str | None = None
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)

    # Orchestration
    parallel_accounts: int = 1
    schedule_cron: str | None = None
    session_persistence: bool = False
    session_dir: str = ".sessions"

    # Reporting
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
    log_dir: str = "logs"
    log_file: str = "reddit-bot.log"

    # Database
    db_path: str = "reddit_bot.db"

    # Credentials
    encrypt_credentials: bool = False
    credentials_key_env: str = "REDDIT_BOT_KEY"

    # Screenshots
    screenshot_on_failure: bool = False
    screenshot_dir: str = "screenshots"

    # Self-healing selectors
    selector_cache_path: str = ".selector-healing/reddit_selectors.json"
    selector_diagnostics_dir: str = ".selector-healing/diagnostics"
    selector_fallback_wait: float = 1.0
    selenium_implicit_wait: int = 20

    # Chrome extension healer bridge
    chrome_extension_healer_enabled: bool = False
    chrome_extension_path: str = "chrome_extension/reddit_healer"
    chrome_extension_bridge_timeout_ms: int = 1500
    chrome_extension_min_confidence: float = 0.72

    # search_upvote: how many ranked organic results to try before giving up.
    # Lets the worker fall through past a selected post that turns out deleted,
    # removed, or archived (i.e. unvotable) and vote the next viable one instead.
    search_upvote_max_candidates: int = 5
    # Posts older than this (days) are tried last, since old posts are the ones
    # most likely to be archived/unvotable. Reordering only — none are dropped.
    search_upvote_recent_days: int = 365
    # Global budget of extra vote attempts spent on *transient* failures (vote
    # button not found, click did not register) where the post is probably still
    # votable. Definitive failures (deleted/removed/archived) never retry. Bounds
    # total attempts to search_upvote_max_candidates + this value.
    search_upvote_transient_retries: int = 1

    @classmethod
    def from_yaml(cls, path: str) -> BotConfig:
        """Load config from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls._from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BotConfig:
        """Load config from a dictionary."""
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> BotConfig:
        config = cls()
        simple_fields = {
            "accounts_path",
            "links_path",
            "verbose",
            "headless",
            "dry_run",
            "rotate_user_agent",
            "randomize_actions",
            "human_mouse",
            "manual_login",
            "use_existing_chrome",
            "chrome_user_data_dir",
            "chrome_profile_name",
            "chrome_debugging_address",
            "parallel_accounts",
            "schedule_cron",
            "session_persistence",
            "session_dir",
            "db_path",
            "log_dir",
            "log_file",
            "encrypt_credentials",
            "credentials_key_env",
            "screenshot_on_failure",
            "screenshot_dir",
            "selector_cache_path",
            "selector_diagnostics_dir",
            "selector_fallback_wait",
            "selenium_implicit_wait",
            "chrome_extension_healer_enabled",
            "chrome_extension_path",
            "chrome_extension_bridge_timeout_ms",
            "chrome_extension_min_confidence",
            "search_upvote_max_candidates",
            "search_upvote_recent_days",
            "search_upvote_transient_retries",
        }
        for key in simple_fields:
            if key in data:
                setattr(config, key, data[key])

        if "proxy" in data and isinstance(data["proxy"], dict):
            config.proxy = ProxyConfig(**data["proxy"])

        if "rate_limit" in data and isinstance(data["rate_limit"], dict):
            config.rate_limit = RateLimitConfig(**data["rate_limit"])

        if "webhook" in data and isinstance(data["webhook"], dict):
            config.webhook = WebhookConfig(**data["webhook"])

        return config

    def merge_cli_args(self, args: dict[str, Any]) -> None:
        """Override config values with CLI arguments (non-None values win)."""
        mapping = {
            "accounts": "accounts_path",
            "links": "links_path",
            "verbose": "verbose",
            "headless": "headless",
            "dry_run": "dry_run",
            "proxy_list": "proxy.proxy_list_path",
            "rotate_user_agent": "rotate_user_agent",
            "randomize_actions": "randomize_actions",
            "human_mouse": "human_mouse",
            "manual_login": "manual_login",
            "use_existing_chrome": "use_existing_chrome",
            "chrome_user_data_dir": "chrome_user_data_dir",
            "chrome_profile_name": "chrome_profile_name",
            "chrome_debugging_address": "chrome_debugging_address",
            "chrome_extension_healer_enabled": "chrome_extension_healer_enabled",
            "chrome_extension_path": "chrome_extension_path",
            "parallel": "parallel_accounts",
            "schedule": "schedule_cron",
            "session_persistence": "session_persistence",
            "screenshot_on_failure": "screenshot_on_failure",
            "log_dir": "log_dir",
            "log_file": "log_file",
            "selector_cache_path": "selector_cache_path",
            "selector_diagnostics_dir": "selector_diagnostics_dir",
            "selector_fallback_wait": "selector_fallback_wait",
            "selenium_implicit_wait": "selenium_implicit_wait",
            "encrypt_credentials": "encrypt_credentials",
            "webhook_url": "webhook.url",
        }
        for arg_key, config_key in mapping.items():
            value = args.get(arg_key)
            if value is None:
                continue
            if "." in config_key:
                obj_name, attr_name = config_key.split(".")
                obj = getattr(self, obj_name)
                setattr(obj, attr_name, value)
                if obj_name == "proxy" and attr_name == "proxy_list_path":
                    self.proxy.enabled = True
                if obj_name == "webhook" and attr_name == "url":
                    self.webhook.enabled = True
            else:
                setattr(self, config_key, value)

    def merge_env_vars(self) -> None:
        """Read configuration from environment variables."""
        env_map = {
            "REDDIT_BOT_ACCOUNTS": "accounts_path",
            "REDDIT_BOT_LINKS": "links_path",
            "REDDIT_BOT_HEADLESS": "headless",
            "REDDIT_BOT_DRY_RUN": "dry_run",
            "REDDIT_BOT_DB_PATH": "db_path",
            "REDDIT_BOT_LOG_DIR": "log_dir",
            "REDDIT_BOT_LOG_FILE": "log_file",
            "REDDIT_BOT_WEBHOOK_URL": "webhook.url",
            "REDDIT_BOT_MANUAL_LOGIN": "manual_login",
            "REDDIT_BOT_HUMAN_MOUSE": "human_mouse",
            "REDDIT_BOT_USE_EXISTING_CHROME": "use_existing_chrome",
            "REDDIT_BOT_CHROME_USER_DATA_DIR": "chrome_user_data_dir",
            "REDDIT_BOT_CHROME_PROFILE_NAME": "chrome_profile_name",
            "REDDIT_BOT_CHROME_DEBUGGING_ADDRESS": "chrome_debugging_address",
            "REDDIT_BOT_SELECTOR_CACHE_PATH": "selector_cache_path",
            "REDDIT_BOT_SELECTOR_DIAGNOSTICS_DIR": "selector_diagnostics_dir",
            "REDDIT_BOT_SELECTOR_FALLBACK_WAIT": "selector_fallback_wait",
            "REDDIT_BOT_SELENIUM_IMPLICIT_WAIT": "selenium_implicit_wait",
            "REDDIT_BOT_CHROME_EXTENSION_HEALER_ENABLED": "chrome_extension_healer_enabled",
            "REDDIT_BOT_CHROME_EXTENSION_PATH": "chrome_extension_path",
            "REDDIT_BOT_CHROME_EXTENSION_BRIDGE_TIMEOUT_MS": "chrome_extension_bridge_timeout_ms",
            "REDDIT_BOT_CHROME_EXTENSION_MIN_CONFIDENCE": "chrome_extension_min_confidence",
        }
        for env_key, config_key in env_map.items():
            value = os.environ.get(env_key)
            if value is None:
                continue
            if "." in config_key:
                obj_name, attr_name = config_key.split(".")
                obj = getattr(self, obj_name)
                setattr(obj, attr_name, value)
                if obj_name == "webhook":
                    self.webhook.enabled = True
            else:
                attr = getattr(self, config_key)
                if isinstance(attr, bool):
                    setattr(self, config_key, value.lower() in ("1", "true", "yes"))
                elif isinstance(attr, int):
                    setattr(self, config_key, int(value))
                elif isinstance(attr, float):
                    setattr(self, config_key, float(value))
                else:
                    setattr(self, config_key, value)
