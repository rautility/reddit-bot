"""Account limit set/list helpers for the control plane."""

from __future__ import annotations

import argparse
from typing import Any

from bot.control.common import open_db, print_json


def list_limits_payload(args: argparse.Namespace) -> dict[str, Any]:
    db = open_db(args)
    try:
        return {
            "accountLimits": db.list_account_limits(),
            "activeReservations": db.list_account_reservations(limit=args.limit),
        }
    finally:
        db.close()


def set_limit_payload(args: argparse.Namespace) -> dict[str, Any]:
    db = open_db(args)
    try:
        db.set_account_limit(
            args.account,
            args.daily_action_quota,
            action=args.action,
        )
        return {"accountLimits": db.list_account_limits()}
    finally:
        db.close()


def command_limits_list(args: argparse.Namespace) -> int:
    print_json(list_limits_payload(args))
    return 0


def command_limits_set(args: argparse.Namespace) -> int:
    print_json(set_limit_payload(args))
    return 0
