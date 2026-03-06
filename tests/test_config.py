"""Tests for BotConfig loading and merging."""

import os
import tempfile

import pytest
import yaml

from bot.config import BotConfig


class TestBotConfigDefaults:
    def test_default_values(self):
        config = BotConfig()
        assert config.verbose is False
        assert config.headless is False
        assert config.dry_run is False
        assert config.parallel_accounts == 1
        assert config.proxy.enabled is False
        assert config.rate_limit.daily_action_quota == 0

    def test_from_dict(self):
        data = {
            "verbose": True,
            "headless": True,
            "parallel_accounts": 4,
            "proxy": {"enabled": True, "proxy_list_path": "proxies.txt"},
        }
        config = BotConfig.from_dict(data)
        assert config.verbose is True
        assert config.headless is True
        assert config.parallel_accounts == 4
        assert config.proxy.enabled is True
        assert config.proxy.proxy_list_path == "proxies.txt"


class TestBotConfigYaml:
    def test_from_yaml(self, tmp_path):
        yaml_content = {
            "verbose": True,
            "accounts_path": "accs.txt",
            "rate_limit": {"daily_action_quota": 50},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(yaml_content))

        config = BotConfig.from_yaml(str(config_file))
        assert config.verbose is True
        assert config.accounts_path == "accs.txt"
        assert config.rate_limit.daily_action_quota == 50


class TestBotConfigMerge:
    def test_merge_cli_args(self):
        config = BotConfig()
        args = {
            "accounts": "test_accounts.txt",
            "verbose": True,
            "headless": True,
            "proxy_list": "proxy.txt",
        }
        config.merge_cli_args(args)
        assert config.accounts_path == "test_accounts.txt"
        assert config.verbose is True
        assert config.headless is True
        assert config.proxy.enabled is True
        assert config.proxy.proxy_list_path == "proxy.txt"

    def test_merge_cli_args_none_values_ignored(self):
        config = BotConfig(verbose=True)
        args = {"verbose": None, "accounts": None}
        config.merge_cli_args(args)
        assert config.verbose is True  # Not overwritten

    def test_merge_env_vars(self, monkeypatch):
        monkeypatch.setenv("REDDIT_BOT_HEADLESS", "true")
        monkeypatch.setenv("REDDIT_BOT_DRY_RUN", "1")
        config = BotConfig()
        config.merge_env_vars()
        assert config.headless is True
        assert config.dry_run is True
