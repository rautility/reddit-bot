# Local Web UI

The local dashboard is a single-user, localhost-only control surface for the
existing reddit-bot queue, schedules, quotas, profiles, and action history.

Start it from the repository root:

```bash
make ui
```

After an editable install, the same server is available as `reddit-ui`.

Then open:

```text
http://127.0.0.1:8765
```

The server binds to `127.0.0.1` by default and rejects non-local bind hosts
(`0.0.0.0`, LAN addresses, etc.). Allowed hosts are only `127.0.0.1`,
`localhost`, and `::1`. It uses the standard library `http.server`; there is no
Node, bundler, or web framework dependency.

## What It Shows

- Overview: queue counts, today's action count versus quota, next active
  schedule, executor status, and recent error count.
- Schedule: registered project schedules with a human cadence, next/last run,
  status, account, last error, pause/resume, delete, and run-due controls.
- Failed: failed queue jobs plus action-log errors, with per-row retry and
  retry-all controls. Failed queue rows include `attempts`, `max_attempts`,
  `last_error`, and `result_json` from the queue table.
- Successful: successful action history from `action_log`.
- Add Task: action-schema-driven form for immediate, one-time, daily, weekly,
  and raw RRULE tasks.
- Per Day: today's count versus quota and the last 30 days of action counts.

## Safety

The UI does not click Reddit controls directly and does not run `main.py`
directly. Writes go through `agentctl` or `reddit-tool` in-process so queue
dedupe, URL validation, quotas, leases, profile resolution, and executor
behavior stay centralized.

Immediate tasks and `Run Due Now` can perform real Reddit actions through the
existing worker. The browser UI asks for confirmation before those actions.

### Optional write token

By default the UI trusts the localhost single-user model: any process that can
reach `127.0.0.1:8765` can call mutation endpoints.

To require a shared secret on **all `POST` routes** (reads stay open):

```bash
export REDDIT_BOT_UI_TOKEN='your-long-random-token'
make ui
```

When that env var is set (non-empty), every write must send:

```http
X-Reddit-Bot-Token: your-long-random-token
```

Missing or wrong tokens receive `401` with
`{"ok": false, "error": "Missing or invalid write token."}`.

Supply the token to the browser UI in one of these ways (do not commit a real
token into the repo):

1. **localStorage (preferred):** in DevTools console on the UI origin:
   `localStorage.setItem("redditBotUiToken", "your-long-random-token")`
2. **Meta tag:** set
   `<meta name="reddit-bot-ui-token" content="...">` in a local-only copy of
   `web/index.html` (the shipped file leaves `content` empty).

`web/app.js` attaches `X-Reddit-Bot-Token` on non-GET requests when either
source is present. GET endpoints remain unauthenticated so the dashboard can
still load overview data without a token.

## API Shape

Read endpoints return:

```json
{"ok": true, "data": {}}
```

Mutation endpoints return the underlying `agentctl` or `reddit-tool` JSON in
`data`, plus `ok`, `exitCode`, and `error` at the HTTP API envelope.

Important endpoints:

- `GET /api/profiles`
- `GET /api/overview?account=<account_label>`
- `GET /api/schedules?account=<account_label>`
- `GET /api/queue?status=failed&account=<account_label>`
- `GET /api/history?result=success&account=<account_label>`
- `GET /api/daily?days=30&account=<account_label>`
- `GET /api/errors?account=<account_label>`
- `GET /api/capabilities`
- `POST /api/tasks`
- `POST /api/queue/{id}/retry`
- `POST /api/queue/retry-failed?account=<account_label>`
- `POST /api/schedules/{id}/pause`
- `POST /api/schedules/{id}/resume`
- `POST /api/schedules/{id}/delete`
- `POST /api/schedules/run-due`
- `POST /api/limits`
