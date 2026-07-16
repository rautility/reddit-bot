"""WP-G: default Reddit identity resolves from DB associations / env, not a hardcoded user."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot import agentctl
from bot.control.profiles import (
    DEFAULT_USER_ENV,
    resolve_default_association,
    resolve_profile_identity,
)
from bot.database import BotDatabase


def _associate(
    db_path: Path,
    *,
    profile_name: str,
    reddit_user: str,
    account_label: str | None = None,
    debug_address: str = "127.0.0.1:9222",
) -> None:
    db = BotDatabase(str(db_path))
    try:
        db.associate_chrome_profile(
            profile_name,
            reddit_user,
            profile_path=f"/tmp/{profile_name}",
            debug_address=debug_address,
            account_label=account_label,
        )
    finally:
        db.close()


def test_zero_associations_errors(tmp_path, monkeypatch):
    monkeypatch.delenv(DEFAULT_USER_ENV, raising=False)
    db = BotDatabase(str(tmp_path / "agent.db"))
    try:
        with pytest.raises(SystemExit) as exc:
            resolve_profile_identity(db)
        message = str(exc.value)
        assert "No Reddit identity specified" in message
        assert "profiles associate" in message or "profiles list" in message
        assert DEFAULT_USER_ENV in message
    finally:
        db.close()


def test_single_association_auto_resolves(tmp_path, monkeypatch):
    monkeypatch.delenv(DEFAULT_USER_ENV, raising=False)
    db_path = tmp_path / "agent.db"
    _associate(db_path, profile_name="Chrome Reddit Bot Debug Profile", reddit_user="u/SoloUser")
    db = BotDatabase(str(db_path))
    try:
        identity = resolve_profile_identity(db)
        assert identity["associationFound"] is True
        assert identity["redditUsername"] == "SoloUser"
        assert identity["accountLabel"] == "SoloUser"
        assert identity["profileName"] == "Chrome Reddit Bot Debug Profile"
        assert identity["resolvedVia"] == "single_association"

        association, via = resolve_default_association(db)
        assert association["reddit_username"] == "SoloUser"
        assert via == "single_association"
    finally:
        db.close()


def test_explicit_flag_wins_over_single_association(tmp_path, monkeypatch):
    monkeypatch.delenv(DEFAULT_USER_ENV, raising=False)
    db_path = tmp_path / "agent.db"
    _associate(
        db_path,
        profile_name="Chrome Reddit Bot Debug Profile",
        reddit_user="u/SoloUser",
    )
    _associate(
        db_path,
        profile_name="Chrome Reddit Bot Debug Profile - account2",
        reddit_user="u/OtherUser",
        account_label="other",
        debug_address="127.0.0.1:9223",
    )
    db = BotDatabase(str(db_path))
    try:
        identity = resolve_profile_identity(db, reddit_user="u/OtherUser")
        assert identity["redditUsername"] == "OtherUser"
        assert identity["accountLabel"] == "other"
        assert identity["resolvedVia"] == "reddit_user"

        by_profile = resolve_profile_identity(
            db, profile_name="Chrome Reddit Bot Debug Profile"
        )
        assert by_profile["redditUsername"] == "SoloUser"
        assert by_profile["resolvedVia"] == "profile_name"

        by_label = resolve_profile_identity(db, account_label="other")
        assert by_label["redditUsername"] == "OtherUser"
        assert by_label["resolvedVia"] == "account_label"
    finally:
        db.close()


def test_env_default_user_when_multiple_associations(tmp_path, monkeypatch):
    db_path = tmp_path / "agent.db"
    _associate(
        db_path,
        profile_name="Chrome Reddit Bot Debug Profile",
        reddit_user="u/Alpha",
    )
    _associate(
        db_path,
        profile_name="Chrome Reddit Bot Debug Profile - account2",
        reddit_user="u/Beta",
        debug_address="127.0.0.1:9223",
    )
    monkeypatch.setenv(DEFAULT_USER_ENV, "u/Beta")
    db = BotDatabase(str(db_path))
    try:
        identity = resolve_profile_identity(db)
        assert identity["redditUsername"] == "Beta"
        assert identity["resolvedVia"] == f"env:{DEFAULT_USER_ENV}"
    finally:
        db.close()


def test_env_default_user_when_zero_associations_but_env_missing_association(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(DEFAULT_USER_ENV, "u/Ghost")
    db = BotDatabase(str(tmp_path / "agent.db"))
    try:
        with pytest.raises(SystemExit) as exc:
            resolve_profile_identity(db)
        assert DEFAULT_USER_ENV in str(exc.value)
        assert "Ghost" in str(exc.value)
    finally:
        db.close()


def test_multiple_associations_without_env_errors(tmp_path, monkeypatch):
    monkeypatch.delenv(DEFAULT_USER_ENV, raising=False)
    db_path = tmp_path / "agent.db"
    _associate(db_path, profile_name="P1", reddit_user="u/Alpha")
    _associate(
        db_path,
        profile_name="P2",
        reddit_user="u/Beta",
        debug_address="127.0.0.1:9223",
    )
    db = BotDatabase(str(db_path))
    try:
        with pytest.raises(SystemExit) as exc:
            resolve_profile_identity(db)
        message = str(exc.value)
        assert "Multiple Chrome profile associations" in message
        assert DEFAULT_USER_ENV in message
    finally:
        db.close()


def test_agentctl_queue_submit_auto_identity_with_single_association(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(DEFAULT_USER_ENV, raising=False)
    db_path = tmp_path / "agent.db"
    links_path = tmp_path / "links.txt"
    links_path.write_text("https://reddit.com/r/test/comments/abc|upvote\n")
    _associate(
        db_path,
        profile_name="Chrome Reddit Bot Debug Profile",
        reddit_user="u/AutoUser",
    )

    exit_code = agentctl.main(
        [
            "--db-path",
            str(db_path),
            "queue",
            "submit",
            "--links",
            str(links_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["resolvedIdentity"]["accountLabel"] == "AutoUser"
    assert payload["resolvedIdentity"]["resolvedVia"] == "single_association"
    assert payload["jobs"][0]["account"] == "AutoUser"


def test_agentctl_queue_submit_without_identity_errors_when_empty(tmp_path, monkeypatch):
    monkeypatch.delenv(DEFAULT_USER_ENV, raising=False)
    db_path = tmp_path / "agent.db"
    links_path = tmp_path / "links.txt"
    links_path.write_text("https://reddit.com/r/test/comments/abc|upvote\n")

    with pytest.raises(SystemExit) as exc:
        agentctl.main(
            [
                "--db-path",
                str(db_path),
                "queue",
                "submit",
                "--links",
                str(links_path),
            ]
        )
    assert "No Reddit identity specified" in str(exc.value)


def test_agentctl_profiles_resolve_without_flags_uses_single_association(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.delenv(DEFAULT_USER_ENV, raising=False)
    db_path = tmp_path / "agent.db"
    _associate(
        db_path,
        profile_name="Chrome Reddit Bot Debug Profile",
        reddit_user="u/ResolveMe",
    )

    exit_code = agentctl.main(["--db-path", str(db_path), "profiles", "resolve"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["redditUsername"] == "ResolveMe"
    assert payload["resolvedVia"] == "single_association"


def test_no_hardcoded_particular_arm_in_execution_modules():
    """Execution-path modules must not hardcode the example Reddit username."""
    repo = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for rel in (
        "bot/cli/bridge.py",
        "bot/control/profiles.py",
        "bot/control/doctor.py",
        "bot/tool_cli.py",
        "bot/agentctl.py",
        "bot/cli/actions.py",
    ):
        text = (repo / rel).read_text(encoding="utf-8")
        if "Particular-Arm2102" in text:
            offenders.append(rel)
    assert offenders == []
