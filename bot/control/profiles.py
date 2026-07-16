"""Chrome profile discovery, association, resolve, and DevTools probe helpers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from bot.control.common import open_db, print_json
from bot.database import BotDatabase

DEFAULT_PROFILE_PREFIX = "Chrome Reddit Bot Debug Profile"
DEFAULT_PROFILE_NAME = "Chrome Reddit Bot Debug Profile"
DEFAULT_DEBUG_ADDRESS = "127.0.0.1:9222"
DEFAULT_EXTENSION_PATH = Path(__file__).resolve().parents[2] / "chrome_extension/reddit_healer"
# Env override when no CLI identity is given and multiple (or zero) associations exist.
DEFAULT_USER_ENV = "REDDIT_BOT_DEFAULT_USER"


def profile_search_root() -> Path:
    return Path.home() / "Library/Application Support"


def discover_saved_profiles() -> list[dict[str, Any]]:
    """Return saved Chrome user-data dirs that match this project's convention."""
    root = profile_search_root()
    profiles = []
    if not root.exists():
        return profiles

    for index, profile_path in enumerate(sorted(root.glob(f"{DEFAULT_PROFILE_PREFIX}*"))):
        profile_name = profile_path.name
        suggested_port = 9222 + index
        profiles.append(
            {
                "profileName": profile_name,
                "profilePath": str(profile_path),
                "suggestedDebugAddress": f"127.0.0.1:{suggested_port}",
                "isDefault": profile_name == DEFAULT_PROFILE_NAME,
            }
        )
    return profiles


def profile_by_name(profile_name: str) -> dict[str, Any] | None:
    for profile in discover_saved_profiles():
        if profile["profileName"] == profile_name:
            return profile
    return None


def association_for_profile(
    associations: list[dict[str, Any]],
    profile_name: str,
) -> dict[str, Any] | None:
    return next(
        (association for association in associations if association["profile_name"] == profile_name),
        None,
    )


def discover_profiles_with_associations(db: BotDatabase) -> list[dict[str, Any]]:
    """Return discovered profiles annotated with persisted Reddit account data."""
    associations = db.list_chrome_profile_associations()
    profiles = discover_saved_profiles()
    seen_profile_names = set()
    for profile in profiles:
        seen_profile_names.add(profile["profileName"])
        association = association_for_profile(associations, profile["profileName"])
        if association:
            profile["redditUsername"] = association["reddit_username"]
            profile["accountLabel"] = association["account_label"]
            profile["configuredDebugAddress"] = association["debug_address"]

    for association in associations:
        if association["profile_name"] in seen_profile_names:
            continue
        profiles.append(
            {
                "profileName": association["profile_name"],
                "profilePath": association["profile_path"],
                "suggestedDebugAddress": association["debug_address"],
                "configuredDebugAddress": association["debug_address"],
                "isDefault": association["profile_name"] == DEFAULT_PROFILE_NAME,
                "redditUsername": association["reddit_username"],
                "accountLabel": association["account_label"],
                "missingLocalProfile": True,
            }
        )
    return profiles


def _nonempty(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def identity_resolution_help() -> str:
    """Human-readable guidance when identity cannot be resolved."""
    return (
        "Provide --reddit-user, --profile-name, or --account-label; "
        "associate exactly one Chrome profile "
        "(`agentctl profiles associate` / `agentctl profiles list`); "
        f"or set {DEFAULT_USER_ENV}."
    )


def association_to_identity(
    association: dict[str, Any],
    *,
    account_label: str | None = None,
    resolved_via: str,
) -> dict[str, Any]:
    """Map a chrome_profile_accounts row to the standard identity payload."""
    return {
        "accountLabel": account_label or association["account_label"],
        "profileName": association["profile_name"],
        "profilePath": association["profile_path"],
        "debugAddress": association["debug_address"],
        "redditUsername": association["reddit_username"],
        "associationFound": True,
        "resolvedVia": resolved_via,
    }


def resolve_default_association(db: BotDatabase) -> tuple[dict[str, Any], str]:
    """Resolve default association when no CLI identity flag is provided.

    Order:
      1. Exactly one row in ``chrome_profile_accounts``
      2. ``REDDIT_BOT_DEFAULT_USER`` env (must match an association)
      3. Fail with a clear error

    Returns ``(association, resolved_via)``.
    """
    associations = db.list_chrome_profile_associations()
    if len(associations) == 1:
        return associations[0], "single_association"

    env_user = _nonempty(os.environ.get(DEFAULT_USER_ENV))
    if env_user:
        association = db.get_chrome_profile_association(reddit_username=env_user)
        if association is None:
            raise SystemExit(
                f"{DEFAULT_USER_ENV}={env_user!r} is set but no Chrome profile "
                "association exists for that user. "
                "Run `agentctl profiles associate` first, or "
                "`agentctl profiles list` to inspect associations."
            )
        return association, f"env:{DEFAULT_USER_ENV}"

    if len(associations) > 1:
        listed = ", ".join(
            f"u/{item['reddit_username']}@{item['profile_name']}" for item in associations
        )
        raise SystemExit(
            f"Multiple Chrome profile associations found ({listed}). " + identity_resolution_help()
        )

    raise SystemExit(
        "No Reddit identity specified and no default could be resolved. " + identity_resolution_help()
    )


def resolve_profile_identity(
    db: BotDatabase,
    *,
    account_label: str | None = None,
    profile_name: str | None = None,
    reddit_user: str | None = None,
) -> dict[str, Any]:
    """Resolve account/profile identity from an explicit label, profile, or user.

    When no explicit identity is provided, falls back to a sole DB association
    or ``REDDIT_BOT_DEFAULT_USER`` (see :func:`resolve_default_association`).
    """
    account_label = _nonempty(account_label)
    profile_name = _nonempty(profile_name)
    reddit_user = _nonempty(reddit_user)

    association = None
    resolved_via: str | None = None
    if profile_name:
        association = db.get_chrome_profile_association(profile_name=profile_name)
        resolved_via = "profile_name"
        if association is None:
            profile = profile_by_name(profile_name)
            if profile is None:
                raise SystemExit(f"Unknown Chrome profile: {profile_name}")
            return {
                "accountLabel": account_label or profile_name,
                "profileName": profile_name,
                "profilePath": profile["profilePath"],
                "debugAddress": profile["suggestedDebugAddress"],
                "redditUsername": None,
                "associationFound": False,
                "resolvedVia": resolved_via,
            }
    elif reddit_user:
        association = db.get_chrome_profile_association(reddit_username=reddit_user)
        resolved_via = "reddit_user"
        if association is None:
            raise SystemExit(
                f"Unknown Reddit username association: {reddit_user}. "
                "Run `agentctl profiles associate` first."
            )
    elif account_label:
        association = db.get_chrome_profile_association(account_label=account_label)
        resolved_via = "account_label"

    if association:
        return association_to_identity(
            association,
            account_label=account_label,
            resolved_via=resolved_via or "association",
        )

    if account_label:
        return {
            "accountLabel": account_label,
            "profileName": None,
            "profilePath": None,
            "debugAddress": None,
            "redditUsername": None,
            "associationFound": False,
            "resolvedVia": "account_label",
        }

    association, via = resolve_default_association(db)
    return association_to_identity(association, resolved_via=via)


def probe_debug_address(address: str, timeout: float = 2.0) -> dict[str, Any]:
    """Probe a Chrome DevTools endpoint without mutating browser state."""
    endpoint = address if address.startswith(("http://", "https://")) else f"http://{address}"
    endpoint = endpoint.rstrip("/") + "/json/version"
    try:
        with urlopen(endpoint, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {
            "ok": True,
            "debugAddress": address.replace("http://", "").replace("https://", ""),
            "endpoint": endpoint,
            "browser": payload.get("Browser"),
            "protocolVersion": payload.get("Protocol-Version"),
            "webSocketDebuggerUrl": payload.get("webSocketDebuggerUrl"),
        }
    except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        error = str(exc)
        result = {
            "ok": False,
            "debugAddress": address,
            "endpoint": endpoint,
            "error": error,
        }
        if "Operation not permitted" in error or "Errno 1" in error:
            result["hint"] = (
                "Chrome may be reachable from the host, but this process is sandboxed "
                "from local DevTools/loopback. Rerun with local DevTools access."
            )
        return result


def command_profiles_list(args: argparse.Namespace) -> int:
    db = open_db(args)
    try:
        payload = {
            "profiles": discover_profiles_with_associations(db),
            "associations": db.list_chrome_profile_associations(),
        }
    finally:
        db.close()
    print_json(payload)
    return 0


def command_profiles_probe(args: argparse.Namespace) -> int:
    print_json(probe_debug_address(args.debug_address, timeout=args.timeout))
    return 0


def command_profiles_associate(args: argparse.Namespace) -> int:
    db = open_db(args)
    try:
        profile = profile_by_name(args.profile_name)
        profile_path = args.profile_path or (profile or {}).get("profilePath")
        debug_address = args.debug_address or (profile or {}).get("suggestedDebugAddress") or DEFAULT_DEBUG_ADDRESS
        association = db.associate_chrome_profile(
            args.profile_name,
            args.reddit_user,
            profile_path=profile_path,
            debug_address=debug_address,
            account_label=args.account_label,
        )
        payload = {
            "association": association,
            "profiles": discover_profiles_with_associations(db),
        }
    finally:
        db.close()
    print_json(payload)
    return 0


def command_profiles_resolve(args: argparse.Namespace) -> int:
    db = open_db(args)
    try:
        payload = resolve_profile_identity(
            db,
            account_label=args.account_label,
            profile_name=args.profile_name,
            reddit_user=args.reddit_user,
        )
    finally:
        db.close()
    print_json(payload)
    return 0
