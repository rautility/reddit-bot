"""Shared helpers for control-plane modules (config, DB, JSON, paths)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bot.config import BotConfig
from bot.database import BotDatabase

REPO_ROOT = Path(__file__).resolve().parents[2]


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def load_config(args: argparse.Namespace) -> BotConfig:
    config = BotConfig.from_yaml(args.config) if args.config else BotConfig()
    config.merge_env_vars()
    if args.db_path:
        config.db_path = args.db_path
    return config


def open_db(args: argparse.Namespace) -> BotDatabase:
    return BotDatabase(load_config(args).db_path)
