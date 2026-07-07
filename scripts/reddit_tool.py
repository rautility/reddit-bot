#!/usr/bin/env python3
"""Thin wrapper for the human-friendly Reddit bot operations CLI."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from bot.tool_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
