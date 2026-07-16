"""Tests for the local web UI API helpers and HTTP surface."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

import pytest

from bot.database import BotDatabase
from bot.web.server import (
    LOCAL_BIND_HOSTS,
    UI_TOKEN_ENV,
    UI_TOKEN_HEADER,
    create_server,
    main,
    make_handler,
    resolve_ui_token,
)


@pytest.fixture
def ui_handler(tmp_path):
    db_path = tmp_path / "ui.db"
    static_dir = tmp_path / "web"
    actions_dir = tmp_path / "actions"
    static_dir.mkdir()
    static_dir.joinpath("index.html").write_text("<html>ok</html>", encoding="utf-8")
    handler_class = make_handler(
        db_path=str(db_path),
        static_dir=static_dir,
        actions_dir=actions_dir,
        quiet=True,
        ui_token="",  # force open mode regardless of developer env
    )
    handler = object.__new__(handler_class)
    return {
        "handler": handler,
        "handler_class": handler_class,
        "db_path": db_path,
        "actions_dir": actions_dir,
        "static_dir": static_dir,
    }


@pytest.fixture
def live_server(tmp_path):
    """Background ThreadingHTTPServer on an ephemeral local port."""
    db_path = tmp_path / "live.db"
    static_dir = tmp_path / "web"
    actions_dir = tmp_path / "actions"
    static_dir.mkdir()
    static_dir.joinpath("index.html").write_text("<html>live</html>", encoding="utf-8")

    def _start(*, ui_token: str | None = ""):
        server = create_server(
            host="127.0.0.1",
            port=0,
            db_path=str(db_path),
            static_dir=static_dir,
            actions_dir=actions_dir,
            quiet=True,
            ui_token=ui_token,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address[:2]
        return {
            "server": server,
            "thread": thread,
            "host": host,
            "port": port,
            "db_path": db_path,
            "actions_dir": actions_dir,
        }

    started: list[dict] = []

    def factory(*, ui_token: str | None = ""):
        ctx = _start(ui_token=ui_token)
        started.append(ctx)
        return ctx

    yield factory

    for ctx in started:
        ctx["server"].shutdown()
        ctx["server"].server_close()
        ctx["thread"].join(timeout=2)


def _http_json(
    host: str,
    port: int,
    method: str,
    path: str,
    *,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    conn = HTTPConnection(host, port, timeout=5)
    try:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        if payload is not None:
            req_headers["Content-Length"] = str(len(payload))
        conn.request(method, path, body=payload, headers=req_headers)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
        return response.status, data
    finally:
        conn.close()


def test_resolve_ui_token_env_and_explicit(monkeypatch):
    monkeypatch.delenv(UI_TOKEN_ENV, raising=False)
    assert resolve_ui_token() is None
    assert resolve_ui_token("") is None

    monkeypatch.setenv(UI_TOKEN_ENV, "  env-secret  ")
    assert resolve_ui_token() == "env-secret"
    assert resolve_ui_token("explicit") == "explicit"
    assert resolve_ui_token("") is None


def test_overview_endpoint_returns_account_filtered_counts(ui_handler):
    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        db.enqueue_action(
            "default",
            "upvote",
            {"link": "https://reddit.com/r/test/comments/abc", "action": "upvote"},
            link="https://reddit.com/r/test/comments/abc",
        )
        db.enqueue_action(
            "other",
            "upvote",
            {"link": "https://reddit.com/r/test/comments/xyz", "action": "upvote"},
            link="https://reddit.com/r/test/comments/xyz",
        )
        db.set_account_limit("default", 10)
    finally:
        db.close()

    data = ui_handler["handler"]._overview("default")

    assert data["queueCounts"] == {"queued": 1}
    assert data["today"]["daily_action_quota"] == 10
    assert data["today"]["action_count"] == 0
    assert "executor" in data
    assert "recentErrorCount" in data
    assert data["nextSchedule"] is None


def test_overview_aggregate_sums_counts_and_quotas(ui_handler):
    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        db.enqueue_action(
            "a",
            "upvote",
            {"link": "https://reddit.com/r/test/comments/a1", "action": "upvote"},
            link="https://reddit.com/r/test/comments/a1",
        )
        db.enqueue_action(
            "b",
            "upvote",
            {"link": "https://reddit.com/r/test/comments/b1", "action": "upvote"},
            link="https://reddit.com/r/test/comments/b1",
        )
        db.set_account_limit("a", 5)
        db.set_account_limit("b", 7)
    finally:
        db.close()

    data = ui_handler["handler"]._overview(None)
    assert data["queueCounts"] == {"queued": 2}
    assert data["today"]["daily_action_quota"] == 12


def test_queue_retry_endpoint_requeues_failed_job(ui_handler):
    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        job = db.enqueue_action(
            "default",
            "upvote",
            {"link": "https://reddit.com/r/test/comments/abc", "action": "upvote"},
            link="https://reddit.com/r/test/comments/abc",
            max_attempts=1,
        )
        db.lease_next_job("worker-1")
        db.release_queue_job(job["id"], "boom")
    finally:
        db.close()

    payload = ui_handler["handler"]._agentctl(["queue", "retry", "--id", str(job["id"])])

    assert payload["ok"] is True
    assert payload["data"]["count"] == 1
    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        assert db.get_queue_job(job["id"])["status"] == "queued"
    finally:
        db.close()


def test_schedule_pause_resume_and_delete_endpoints(ui_handler):
    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        db.register_schedule(
            "daily-actions",
            "Daily Actions",
            source="test",
            rrule="FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            status="ACTIVE",
            account="default",
        )
    finally:
        db.close()

    pause = ui_handler["handler"]._agentctl(
        ["schedules", "set-status", "--id", "daily-actions", "--status", "PAUSED"]
    )
    assert pause["ok"] is True
    assert pause["data"]["schedule"]["status"] == "PAUSED"

    resume = ui_handler["handler"]._agentctl(
        ["schedules", "set-status", "--id", "daily-actions", "--status", "ACTIVE"]
    )
    assert resume["ok"] is True
    assert resume["data"]["schedule"]["status"] == "ACTIVE"

    delete = ui_handler["handler"]._agentctl(["schedules", "delete", "--id", "daily-actions"])
    assert delete["ok"] is True
    assert delete["data"]["deleted"] is True


def test_task_endpoint_registers_one_time_schedule(ui_handler):
    payload = ui_handler["handler"]._create_task(
        {
            "action": "upvote",
            "fields": {
                "link": "https://www.reddit.com/r/test/comments/abc/title/",
            },
            "identity": {"account_label": "default"},
            "timing": {"mode": "once", "at": "2026-07-06T09:00:00"},
            "noEnsureExecutor": True,
        },
    )

    assert payload["ok"] is True
    assert payload["data"]["registered"].startswith("reddit-ui-upvote-task")
    assert ui_handler["actions_dir"].exists()

    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        schedules = db.list_registered_schedules()
    finally:
        db.close()
    assert len(schedules) == 1
    assert schedules[0]["next_run_at"] == "2026-07-06T09:00:00"


def test_failed_queue_jobs_include_attempt_error_and_result_json(ui_handler):
    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        job = db.enqueue_action(
            "default",
            "upvote",
            {"link": "https://reddit.com/r/test/comments/fail1", "action": "upvote"},
            link="https://reddit.com/r/test/comments/fail1",
            max_attempts=2,
        )
        leased = db.lease_next_job("worker-detail")
        assert leased is not None
        db.complete_queue_job(
            job["id"],
            success=False,
            error="selector miss",
            result={"message": "no upvote button", "code": "MISS"},
        )
    finally:
        db.close()

    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        jobs = db.list_queue_jobs(status="failed", account="default", limit=10)
    finally:
        db.close()

    assert len(jobs) == 1
    failed = jobs[0]
    assert failed["attempts"] == 1
    assert failed["max_attempts"] == 2
    assert failed["last_error"] == "selector miss"
    assert failed["result_json"]
    result = json.loads(failed["result_json"])
    assert result["code"] == "MISS"

    # HTTP /api/queue path uses the same list_queue_jobs helper.
    handler = ui_handler["handler"]
    # Simulate the queue GET payload assembly used by the server.
    db = handler._open_db()
    try:
        data = {
            "jobs": db.list_queue_jobs(status="failed", account="default", limit=10),
            "queueCounts": handler._queue_counts(db, "default"),
        }
    finally:
        db.close()
    assert data["jobs"][0]["result_json"]
    assert data["jobs"][0]["attempts"] == 1
    assert data["jobs"][0]["max_attempts"] == 2
    assert data["jobs"][0]["last_error"] == "selector miss"
    assert data["queueCounts"].get("failed") == 1


def test_errors_endpoint_surfaces_failed_queue_jobs(ui_handler):
    db = BotDatabase(str(ui_handler["db_path"]))
    try:
        job = db.enqueue_action(
            "default",
            "comment",
            {
                "link": "https://reddit.com/r/test/comments/err1",
                "action": "comment",
                "comment": "x",
            },
            link="https://reddit.com/r/test/comments/err1",
            max_attempts=1,
        )
        db.lease_next_job("worker-err")
        db.complete_queue_job(job["id"], success=False, error="timeout", result={"ok": False})
    finally:
        db.close()

    payload = ui_handler["handler"]._errors("default", limit=20)
    assert any(item["id"] == job["id"] for item in payload["queueErrors"])
    failed = next(item for item in payload["queueErrors"] if item["id"] == job["id"])
    assert failed["last_error"] == "timeout"
    assert failed["attempts"] >= 1
    assert "result_json" in failed


def test_main_rejects_non_local_host():
    with pytest.raises(SystemExit) as excinfo:
        main(["--host", "0.0.0.0", "--port", "8765"])
    assert excinfo.value.code == 2


def test_main_rejects_lan_bind_host():
    with pytest.raises(SystemExit) as excinfo:
        main(["--host", "192.168.1.10", "--port", "8765"])
    assert excinfo.value.code == 2


def test_create_server_rejects_non_local_host(tmp_path):
    with pytest.raises(ValueError, match="localhost-only"):
        create_server(
            host="0.0.0.0",
            port=0,
            db_path=str(tmp_path / "x.db"),
            static_dir=tmp_path,
            actions_dir=tmp_path / "actions",
            quiet=True,
            ui_token="",
        )


def test_local_bind_hosts_constant():
    assert LOCAL_BIND_HOSTS == frozenset({"127.0.0.1", "localhost", "::1"})


def test_http_overview_and_queue_without_token(live_server):
    ctx = live_server(ui_token="")
    db = BotDatabase(str(ctx["db_path"]))
    try:
        db.enqueue_action(
            "default",
            "upvote",
            {"link": "https://reddit.com/r/test/comments/http1", "action": "upvote"},
            link="https://reddit.com/r/test/comments/http1",
        )
        db.set_account_limit("default", 3)
    finally:
        db.close()

    status, payload = _http_json(ctx["host"], ctx["port"], "GET", "/api/overview?account=default")
    assert status == 200
    assert payload["ok"] is True
    assert payload["data"]["queueCounts"] == {"queued": 1}
    assert payload["data"]["today"]["daily_action_quota"] == 3

    status, payload = _http_json(
        ctx["host"], ctx["port"], "GET", "/api/queue?status=queued&account=default"
    )
    assert status == 200
    assert len(payload["data"]["jobs"]) == 1


def test_http_post_allowed_when_token_unset(live_server):
    ctx = live_server(ui_token="")
    db = BotDatabase(str(ctx["db_path"]))
    try:
        db.register_schedule(
            "sched-open",
            "Open Schedule",
            source="test",
            rrule="FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            status="ACTIVE",
            account="default",
        )
    finally:
        db.close()

    status, payload = _http_json(
        ctx["host"],
        ctx["port"],
        "POST",
        "/api/schedules/sched-open/pause",
        body={},
    )
    assert status == 200
    assert payload["ok"] is True
    assert payload["data"]["schedule"]["status"] == "PAUSED"


def test_http_post_requires_token_when_configured(live_server):
    token = "test-write-token-abc"
    ctx = live_server(ui_token=token)
    db = BotDatabase(str(ctx["db_path"]))
    try:
        db.register_schedule(
            "sched-locked",
            "Locked Schedule",
            source="test",
            rrule="FREQ=DAILY;BYHOUR=10;BYMINUTE=0",
            status="ACTIVE",
            account="default",
        )
        job = db.enqueue_action(
            "default",
            "upvote",
            {"link": "https://reddit.com/r/test/comments/tok1", "action": "upvote"},
            link="https://reddit.com/r/test/comments/tok1",
            max_attempts=1,
        )
        db.lease_next_job("worker-tok")
        db.release_queue_job(job["id"], "fail once")
    finally:
        db.close()

    # GET remains open.
    status, payload = _http_json(ctx["host"], ctx["port"], "GET", "/api/overview")
    assert status == 200
    assert payload["ok"] is True

    # POST without header → 401.
    status, payload = _http_json(
        ctx["host"],
        ctx["port"],
        "POST",
        "/api/schedules/sched-locked/pause",
        body={},
    )
    assert status == 401
    assert payload["ok"] is False
    assert "token" in payload["error"].lower()

    # POST with wrong token → 401.
    status, payload = _http_json(
        ctx["host"],
        ctx["port"],
        "POST",
        "/api/schedules/sched-locked/pause",
        body={},
        headers={UI_TOKEN_HEADER: "wrong"},
    )
    assert status == 401

    # POST with correct token → mutation succeeds.
    status, payload = _http_json(
        ctx["host"],
        ctx["port"],
        "POST",
        "/api/schedules/sched-locked/pause",
        body={},
        headers={UI_TOKEN_HEADER: token},
    )
    assert status == 200
    assert payload["ok"] is True
    assert payload["data"]["schedule"]["status"] == "PAUSED"

    status, payload = _http_json(
        ctx["host"],
        ctx["port"],
        "POST",
        "/api/schedules/sched-locked/resume",
        body={},
        headers={UI_TOKEN_HEADER: token},
    )
    assert status == 200
    assert payload["data"]["schedule"]["status"] == "ACTIVE"

    status, payload = _http_json(
        ctx["host"],
        ctx["port"],
        "POST",
        f"/api/queue/{job['id']}/retry",
        body={},
        headers={UI_TOKEN_HEADER: token},
    )
    assert status == 200
    assert payload["ok"] is True
    assert payload["data"]["count"] == 1


def test_http_token_from_env(live_server, monkeypatch):
    monkeypatch.setenv(UI_TOKEN_ENV, "env-only-token")
    # ui_token=None means read env at make_handler time.
    ctx = live_server(ui_token=None)
    status, payload = _http_json(
        ctx["host"],
        ctx["port"],
        "POST",
        "/api/limits",
        body={"account": "default", "daily_action_quota": 4},
    )
    assert status == 401

    status, payload = _http_json(
        ctx["host"],
        ctx["port"],
        "POST",
        "/api/limits",
        body={"account": "default", "daily_action_quota": 4},
        headers={UI_TOKEN_HEADER: "env-only-token"},
    )
    assert status == 200
    assert payload["ok"] is True


def test_http_retry_failed_bulk(live_server):
    ctx = live_server(ui_token="")
    db = BotDatabase(str(ctx["db_path"]))
    try:
        for suffix in ("a", "b"):
            job = db.enqueue_action(
                "default",
                "upvote",
                {
                    "link": f"https://reddit.com/r/test/comments/{suffix}",
                    "action": "upvote",
                },
                link=f"https://reddit.com/r/test/comments/{suffix}",
                max_attempts=1,
            )
            db.lease_next_job(f"w-{suffix}")
            db.release_queue_job(job["id"], f"err-{suffix}")
    finally:
        db.close()

    status, payload = _http_json(
        ctx["host"],
        ctx["port"],
        "POST",
        "/api/queue/retry-failed?account=default",
        body={},
    )
    assert status == 200
    assert payload["ok"] is True
    assert payload["data"]["count"] == 2


def test_http_capabilities_and_static(live_server):
    ctx = live_server(ui_token="")
    status, payload = _http_json(ctx["host"], ctx["port"], "GET", "/api/capabilities")
    assert status == 200
    assert payload["ok"] is True
    assert "actions" in payload["data"]

    conn = HTTPConnection(ctx["host"], ctx["port"], timeout=5)
    try:
        conn.request("GET", "/")
        response = conn.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert "live" in body
    finally:
        conn.close()


def test_create_task_rejects_missing_fields(ui_handler):
    payload = ui_handler["handler"]._create_task(
        {
            "action": "upvote",
            "fields": {},
            "timing": {"mode": "once", "at": "2026-07-06T09:00:00"},
            "noEnsureExecutor": True,
        },
    )
    assert payload["ok"] is False
    assert "fieldErrors" in payload["data"]


def test_human_cadence_helpers():
    from bot.web.server import human_cadence

    assert "Daily at 09:00" in human_cadence("FREQ=DAILY;BYHOUR=9;BYMINUTE=0")
    assert "Weekly on Mon" in human_cadence("FREQ=WEEKLY;BYDAY=MO;BYHOUR=8;BYMINUTE=30")
    assert "One-time" in human_cadence("DTSTART:20260706T090000\nRRULE:FREQ=DAILY;COUNT=1")


def test_make_handler_reads_env_token(tmp_path, monkeypatch):
    monkeypatch.setenv(UI_TOKEN_ENV, "from-env")
    static_dir = tmp_path / "web"
    static_dir.mkdir()
    handler_class = make_handler(
        db_path=str(tmp_path / "db.db"),
        static_dir=static_dir,
        actions_dir=tmp_path / "actions",
        quiet=True,
        # omit ui_token → env
    )
    assert handler_class.ui_token == "from-env"

    open_class = make_handler(
        db_path=str(tmp_path / "db.db"),
        static_dir=static_dir,
        actions_dir=tmp_path / "actions",
        quiet=True,
        ui_token="",
    )
    assert open_class.ui_token is None
