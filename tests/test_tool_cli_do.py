"""Tests for the agent-facing `capabilities`, `do`, and `job` commands."""

import json

from bot import tool_cli
from bot.database import BotDatabase

CANONICAL_URL = "https://www.reddit.com/r/test/comments/abc123/slug/"


def _run(argv, capsys):
    exit_code = tool_cli.main(argv)
    return exit_code, capsys.readouterr().out


def test_capabilities_json_returns_versioned_envelope(tmp_path, capsys):
    exit_code, out = _run(
        ["--db-path", str(tmp_path / "agent.db"), "--json", "capabilities"], capsys
    )
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["command"] == "capabilities"
    assert payload["schemaVersion"] == tool_cli.SCHEMA_VERSION
    data = payload["data"]
    assert "upvote" in data["actions"]
    assert data["actions"]["comment"]["required"] == ["link", "comment"]
    assert data["defaults"]["identityOptions"]
    assert data["urlContract"]["canonicalFormat"].startswith("https://www.reddit.com/")


def test_capabilities_accepts_json_after_subcommand(tmp_path, capsys):
    exit_code, out = _run(
        ["--db-path", str(tmp_path / "agent.db"), "capabilities", "--json"], capsys
    )

    assert exit_code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["command"] == "capabilities"


def test_global_value_flags_are_accepted_after_subcommand(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    exit_code, out = _run(
        ["capabilities", "--json", "--db-path", str(db_path)], capsys
    )

    assert exit_code == 0
    payload = json.loads(out)
    assert payload["ok"] is True


def test_describe_single_action_json(tmp_path, capsys):
    exit_code, out = _run(
        [
            "--db-path", str(tmp_path / "agent.db"),
            "describe", "search_upvote",
            "--json",
        ],
        capsys,
    )

    assert exit_code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["command"] == "describe"
    assert payload["data"]["action"] == "search_upvote"
    assert payload["data"]["spec"]["link_kind"] == "query"


def test_do_missing_required_field_exits_2(tmp_path, capsys):
    exit_code, out = _run(
        ["--db-path", str(tmp_path / "agent.db"), "--json", "do", "--action", "upvote"],
        capsys,
    )
    assert exit_code == 2
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["data"]["fieldErrors"][0]["field"] == "link"


def test_do_no_run_writes_json_action_file_and_enqueues(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    actions_dir = tmp_path / "actions"
    exit_code, out = _run(
        [
            "--db-path", str(db_path),
            "--json",
            "do",
            "--action", "upvote",
            "--link", CANONICAL_URL,
            "--account-label", "default",
            "--actions-dir", str(actions_dir),
            "--no-run",
        ],
        capsys,
    )
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["data"]["submitted"] == 1
    assert payload["data"]["ranWorker"] is False

    action_file = payload["data"]["actionFile"]
    entries = json.loads(open(action_file).read())
    assert entries == [{"action": "upvote", "link": CANONICAL_URL}]

    db = BotDatabase(str(db_path))
    try:
        jobs = db.list_queue_jobs()
    finally:
        db.close()
    assert len(jobs) == 1
    assert jobs[0]["action"] == "upvote"
    assert jobs[0]["link"] == CANONICAL_URL


def test_do_search_upvote_accepts_query_alias(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    actions_dir = tmp_path / "actions"
    exit_code, out = _run(
        [
            "--db-path", str(db_path),
            "do",
            "--action", "search_upvote",
            "--query", "best Excel tips",
            "--account-label", "default",
            "--actions-dir", str(actions_dir),
            "--no-run",
            "--json",
        ],
        capsys,
    )

    assert exit_code == 0
    payload = json.loads(out)
    action_file = payload["data"]["actionFile"]
    entries = json.loads(open(action_file).read())
    assert entries == [{"action": "search_upvote", "link": "best Excel tips"}]

    db = BotDatabase(str(db_path))
    try:
        jobs = db.list_queue_jobs()
    finally:
        db.close()
    assert jobs[0]["action"] == "search_upvote"
    assert jobs[0]["link"] == "best Excel tips"


def test_search_upvote_command_queues_compound_action(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    actions_dir = tmp_path / "actions"
    exit_code, out = _run(
        [
            "--db-path", str(db_path),
            "search-upvote",
            "--query", "best Excel tips",
            "--account-label", "default",
            "--actions-dir", str(actions_dir),
            "--no-run",
            "--json",
        ],
        capsys,
    )

    assert exit_code == 0
    payload = json.loads(out)
    assert payload["data"]["action"] == "search_upvote"
    assert payload["data"]["submitted"] == 1


def test_do_profile_preflight_blocks_before_queue_when_debugger_down(
    tmp_path,
    capsys,
    mocker,
):
    db_path = tmp_path / "agent.db"
    tool_cli.agentctl.main(
        [
            "--db-path",
            str(db_path),
            "profiles",
            "associate",
            "--profile-name",
            "Chrome Reddit Bot Debug Profile",
            "--reddit-user",
            "u/Particular-Arm2102",
            "--profile-path",
            str(tmp_path / "profile"),
            "--debug-address",
            "127.0.0.1:9222",
        ]
    )
    capsys.readouterr()
    mocker.patch(
        "bot.agentctl.probe_debug_address",
        return_value={
            "ok": False,
            "debugAddress": "127.0.0.1:9222",
            "error": "connection refused",
            "hint": "rerun with local DevTools access",
        },
    )

    exit_code, out = _run(
        [
            "--db-path", str(db_path),
            "--json",
            "do",
            "--action", "upvote",
            "--link", CANONICAL_URL,
            "--reddit-user", "u/Particular-Arm2102",
            "--no-open-profile",
        ],
        capsys,
    )

    assert exit_code == 2
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "preflight failed" in payload["error"]
    assert "local DevTools access" in payload["error"]

    db = BotDatabase(str(db_path))
    try:
        assert db.list_queue_jobs() == []
    finally:
        db.close()


def test_do_rejects_share_links_with_link_errors(tmp_path, capsys):
    exit_code, out = _run(
        [
            "--db-path", str(tmp_path / "agent.db"),
            "--json",
            "do",
            "--action", "upvote",
            "--link", "https://www.reddit.com/r/test/s/abc123XYZ",
            "--account-label", "default",
            "--actions-dir", str(tmp_path / "actions"),
            "--no-run",
        ],
        capsys,
    )
    assert exit_code == 2
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["data"]["linkErrors"]


def test_job_reports_status_and_result(tmp_path, capsys):
    db_path = tmp_path / "agent.db"
    actions_dir = tmp_path / "actions"
    _, out = _run(
        [
            "--db-path", str(db_path),
            "--json",
            "do",
            "--action", "save",
            "--link", CANONICAL_URL,
            "--account-label", "default",
            "--actions-dir", str(actions_dir),
            "--no-run",
        ],
        capsys,
    )
    job_id = json.loads(out)["data"]["jobIds"][0]

    exit_code, out = _run(
        ["--db-path", str(db_path), "--json", "job", "--id", str(job_id)], capsys
    )
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["data"]["found"] is True
    assert payload["data"]["status"] == "queued"
    assert payload["data"]["action"] == "save"

    # Pin the success-status contract that `do`'s ok-computation depends on:
    # a completed job must read back as "succeeded" with its stored result.
    db = BotDatabase(str(db_path))
    try:
        db.complete_queue_job(job_id, success=True, result={"total": 1, "succeeded": 1})
    finally:
        db.close()
    _, out = _run(
        ["--db-path", str(db_path), "--json", "job", "--id", str(job_id)], capsys
    )
    done = json.loads(out)["data"]
    assert done["status"] == "succeeded"
    assert done["result"] == {"total": 1, "succeeded": 1}
