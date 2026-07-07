# Local Web UI for reddit-bot — Implementation Plan (for Codex)

Audience: an autonomous coding agent (Codex) working in this repository.
Goal: build a **simple, localhost-only web dashboard** to operate the existing
Reddit bot control plane. This is a plan/spec, not finished code — but it is
specific enough to implement without re-discovering the architecture.

> **Read this first, then reuse what exists.** The bot already has a complete
> queue/schedule/quota/profile control plane with a **stable, versioned JSON
> contract**. Do **not** re-implement scheduling, quota, dedupe, or Reddit
> execution. The UI is a thin presentation + form layer over the existing CLIs
> and SQLite database.

---

## 0. What already exists (the backend you build on)

| Layer | File | Role |
|---|---|---|
| Human CLI | [bot/tool_cli.py](../bot/tool_cli.py) (`reddit-tool`) | Versioned JSON envelope (`{ok, schemaVersion, command, data, error}`), `--json` on every command. Primary contract. |
| Control plane | [bot/agentctl.py](../bot/agentctl.py) (`reddit-agentctl`) | Lower-level commands; `main(argv)` prints JSON to stdout and returns an exit code. Importable in-process. |
| Data access | [bot/database.py](../bot/database.py) (`BotDatabase`) | SQLite (`reddit_bot.db`). Read helpers for every dashboard view; write helpers for queue/schedule/limits/profiles. |
| Action schema | [bot/action_schema.py](../bot/action_schema.py) | `describe_actions()` → required/optional fields per action. Drives the "Add task" form. |
| Docs | [docs/scheduler-and-rate-limits.md](scheduler-and-rate-limits.md) | Quota/lease/executor semantics. Respect these. |

**Key architectural facts (verified in source):**

- Every `reddit-tool` command accepts `--json` and emits a stable envelope.
  `capabilities`, `overview`, `queue list`, `schedules list`, `errors`,
  `profiles`, `limits` are all read-only JSON. `do`, `queue add`,
  `schedule add`, `schedule run-due`, `limits set` mutate.
- `bot.tool_cli` runs `bot.agentctl` **in-process** by redirecting stdout and
  calling `agentctl.main([...])`, then `json.loads` the output (see
  `_agentctl_payload`). The web backend should use the **same pattern** — no
  subprocesses, no duplicated logic.
- Identity is resolved to an **`account_label`**. A profile switcher value maps
  cleanly: `profiles list` returns `{profileName, accountLabel, redditUsername,
  configuredDebugAddress|suggestedDebugAddress, profilePath, isDefault}`, and
  `queue submit`/`schedule register` return `resolvedIdentity = {accountLabel,
  profileName, profilePath, debugAddress, redditUsername, associationFound}`.
  All history/queue/stats/schedule rows key on `account_label`.

**Requirement → data source map:**

| User requirement | Table / command | Notes |
|---|---|---|
| Visual **schedule** | `schedule_registry` via `reddit-tool schedules list --json` → `registeredSchedules` | `id, name, rrule, status(ACTIVE/PAUSED), next_run_at, last_run_at, last_error, account, profile, action_class` |
| **Failed attempts** | `agent_queue` (`status='failed'`) + `action_log` (`success=0`) via `reddit-tool errors --json` / `queue list --status failed --json` | `last_error`, `attempts/max_attempts`, `error_message`, `screenshot_path` |
| **Re-try failed** | ⚠️ **Does not exist yet — you must add it** (see §4) | New DB method + `agentctl queue retry` + `reddit-tool queue retry` |
| **Successful tasks ran** | `agent_queue` (`status='succeeded'`) + `action_log` (`success=1`) | history table |
| **Add task (one-time / recurring)** | `schedule add` (`--at` one-time, `--daily-at`/`--weekly`/`--rrule` recurring) and `do`/`queue add` (immediate) | already fully supported |
| **Actions per day count** | `account_stats(account, action_date, action_count)` + `account_limits(daily_action_quota)` | today's count vs quota; history is per-day rows |
| **Multiple profiles / switch view** | `chrome_profile_accounts` via `profiles list` | header dropdown filters all views by `account_label` |

---

## 1. Scope & non-goals

**In scope:** a single-user dashboard bound to `127.0.0.1`, that (a) visualizes
schedule, failed/successful history, and per-day action counts; (b) lets the
user add one-time/recurring tasks; (c) retries failed jobs; (d) switches between
Reddit profiles/accounts.

**Non-goals:** authentication/multi-user, remote hosting, real-time Reddit
scraping, rewriting the scheduler or executor, any new Reddit-automation logic.
The UI must **not** click Reddit controls or run `main.py` directly — it only
drives `agentctl`/`reddit-tool` (per the conflict rules in
`docs/scheduler-and-rate-limits.md`).

---

## 2. Architecture decision

**Backend:** a single-file Python HTTP server using the **standard library
`http.server`** — zero new dependencies, matching this repo's lean dependency
set (`pyproject.toml` has no web framework). It imports `bot.database` for reads
and calls `bot.agentctl.main(...)` in-process for mutations.

- *Recommended default:* stdlib `http.server` (no venv changes, no build step).
- *Acceptable alternative if you prefer:* FastAPI + uvicorn (add to the `dev`
  extra). Only do this if it clearly simplifies the code; otherwise prefer
  stdlib. **Do not** introduce a Node/npm build step.

**Frontend:** zero-build single-page app — `index.html` + `app.js` +
`styles.css`, plain `fetch()` and vanilla JS/DOM. No React/Vue/bundler. One tiny
inline chart (per-day bars) is fine as hand-rolled SVG/`<div>` bars.

**Entry point:** add a `scripts/reddit_ui.py` launcher **and** a `make ui`
target (`ui: \t$(PY) scripts/reddit_ui.py --port 8765`). Optionally a
`reddit-tool ui` subcommand that starts the same server. Default bind
`127.0.0.1:8765`; open the browser automatically is optional.

**Reads vs. writes split (important):**
- **Reads** → query `BotDatabase` directly (fast, simple) *or* call the
  `reddit-tool ... --json` command functions in-process. Prefer direct DB reads
  for dashboards.
- **Writes/mutations** → always go through `agentctl`/`tool_cli` command
  functions so URL validation, dedupe, atomic quota reservation, executor
  ensure, and identity resolution are preserved. Never hand-write INSERTs into
  `agent_queue`/`schedule_registry` from the web layer (except the new retry
  helper in §4, which lives in `BotDatabase`).

---

## 3. Backend HTTP API

All JSON. All accept an optional `account` query param (the selected
`account_label`; omitted / `all` = aggregate across profiles).

**Reads**
- `GET /api/profiles` → profile switcher list (`profiles list` payload).
- `GET /api/overview?account=` → queue counts, today's action totals, next
  schedule, executor status, recent-error count. (Back with `reddit-tool
  overview --json`.)
- `GET /api/schedules?account=` → `registeredSchedules`, each augmented with a
  `humanCadence` string (see §5.2).
- `GET /api/queue?status=&account=&limit=` → `agent_queue` rows.
- `GET /api/history?account=&result=success|fail&limit=` → `action_log` rows.
- `GET /api/daily?account=&days=30` → array of `{action_date, action_count}`
  from `account_stats` plus the account's `daily_action_quota`.
- `GET /api/errors?account=&limit=` → `reddit-tool errors --json` payload
  (`queueErrors`, `scheduleErrors`, `actionErrors`, `executorLogErrors`).
- `GET /api/capabilities` → `describe_actions()` (drives the Add-task form).

**Writes**
- `POST /api/tasks` — unified add. Body: `{identity:{account_label|profile_name|
  reddit_user}, action, fields:{link,comment,title,...}, timing:{mode:"now"|
  "once"|"daily"|"weekly"|"rrule", at?, dailyAt?, weekdays?, time?, rrule?}}`.
  - `mode:"now"` → `command_do` (submit + one worker pass).
  - `mode:"once"` → `schedule add --at`.
  - `mode:"daily"|"weekly"|"rrule"` → `schedule add --daily-at/--weekly/--rrule`.
- `POST /api/queue/{id}/retry` and `POST /api/queue/retry-failed?account=` — the
  **new** retry capability (§4).
- `POST /api/schedules/run-due` → `schedule run-due --run-worker`.
- `POST /api/schedules/{id}/pause` | `/resume` | `/delete` — status toggle /
  removal (§4 notes the small gap here).
- `POST /api/limits` → `limits set` (optional; lets the user edit daily quota).

Return the underlying command envelope verbatim in `data` so the frontend can
show `ok`/`error`/`fieldErrors` inline.

---

## 4. Gaps to close in the backend (do these before wiring the UI)

These capabilities the UI needs **do not exist today**. Add them at the lowest
sensible layer so the CLI and UI share one implementation, and cover them with
tests (mirror the style in `tests/test_agentctl.py` / `tests/test_tool_cli.py`).

### 4.1 Retry failed queue jobs (required by "re-try failed attempts")
> ⚠️ Do **not** confuse this with the existing *within-run* retry
> (`bot/utils/retry.py` `retry_action` + `RedditBot._execute_with_retry`) or
> `BotDatabase.release_queue_job` (which only re-queues while `attempts <
> max_attempts`). Once `attempts >= max_attempts` the job is **terminally
> `failed`** and nothing re-queues it. This new capability re-activates such
> terminal jobs on demand.

- `BotDatabase.retry_queue_job(job_id) -> dict`: for a `failed` job, set
  `status='queued'`, `locked_by=NULL`, `locked_until=NULL`,
  `last_error=NULL`, `updated_at=now`, and if `attempts >= max_attempts` bump
  `max_attempts` (e.g. `max_attempts = attempts + 1`) so the worker will pick it
  up again. Return the updated row. Reuse the existing dedupe unique index —
  since the job already exists and is being flipped back to `queued`, ensure no
  duplicate-active-dedupe collision (the row keeps its own `dedupe_key`).
- `BotDatabase.retry_failed_jobs(account: str | None) -> list[dict]`: bulk
  version over all `failed` jobs (optionally filtered by `account`).
- `agentctl queue retry --id <n>` and `queue retry --all [--account <label>]`
  subcommands, emitting JSON `{retried:[...], count:n}`.
- `reddit-tool queue retry --id <n> | --all [--account]` wrapper + table print.
- Tests: failed→queued transition, exhausted-attempts bump, `--all` filter,
  non-failed job is a no-op with a clear message.

### 4.2 Schedule pause / resume / delete (needed for schedule controls)
- Pause/resume: `schedule_registry.status` toggles ACTIVE⇄PAUSED. `register`
  already upserts status; add a thin `agentctl schedules set-status --id
  --status` (or reuse register) so the UI doesn't have to resend rrule/links.
- Delete: add `BotDatabase.delete_schedule(schedule_id)` +
  `agentctl schedules delete --id` (there is currently no delete path). Tests
  for both.

### 4.3 Optional: per-day history endpoint helper
`account_stats` already stores one row per `(account, action_date)`. A small
`BotDatabase.get_daily_action_history(account, days)` returning the last N days
(zero-filled) keeps the chart endpoint clean.

> If you want to minimize new CLI surface, the web backend *may* call
> `BotDatabase.retry_queue_job` / `delete_schedule` directly instead of adding
> `agentctl` subcommands — but adding the CLI commands is preferred so the
> behavior is testable and reusable from the terminal too.

---

## 5. Frontend views (one per requirement)

Single page, left-nav or top-tab layout, with a persistent **profile switcher**
in the header. Selected profile is stored in `localStorage` and sent as
`?account=` on every request. Include an **"All profiles"** aggregate option.

### 5.1 Home / Overview
Cards: queue counts (queued/running/succeeded/failed), **today's actions** for
the selected profile (count vs quota, progress bar), next scheduled run,
executor running/available, recent-error count. Data: `/api/overview`.

### 5.2 Schedule
Table (and optionally a simple week timeline): `name`, **cadence** (human
string), `next_run_at`, `last_run_at`, `status` badge, `account/profile`,
`last_error`. Row actions: **Pause/Resume**, **Run now** (`run-due`), **Delete**.
- Add a small RRULE→human formatter (e.g. `FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=9`
  → "Weekly on Mon, Wed at 09:00"; `COUNT=1` → "One-time"). Keep it a lookup
  over the handful of shapes `reddit-tool schedule add` generates (`--at`,
  `--daily-at`, `--weekly`); fall back to showing the raw rrule.

### 5.3 Failed attempts
Table from `/api/queue?status=failed` + `/api/errors` (`actionErrors`): `time`,
`account`, `action`, `link`, `attempts/max`, `error`, screenshot link if
present. Per-row **Retry** button → `POST /api/queue/{id}/retry`; header
**Retry all failed** → `POST /api/queue/retry-failed`. After retry, refresh and
show the job moving back to `queued`.

### 5.4 Successful tasks
History table from `/api/history?result=success` (+ `agent_queue` succeeded):
`time`, `account`, `action`, `link`, result summary. Filter by profile/date.

### 5.5 Add new task
Form driven by `/api/capabilities`:
1. **Profile** select (from `/api/profiles`).
2. **Action** select (from schema); reveal required/optional field inputs
   dynamically (`link`, `comment`, `title`, `subreddit`, `body`, `flair`,
   `recipient`, `message`, `query`).
3. **Timing** radio: **Now** · **One-time** (datetime-local) · **Daily** (HH:MM)
   · **Weekly** (weekday checkboxes + HH:MM) · **Advanced RRULE** (text).
4. Submit → `POST /api/tasks`; render `ok`/`error`/`fieldErrors`/`linkErrors`
   from the returned envelope. Validate canonical `/comments/` URLs client-side
   for post actions (mirror the backend's rejection of `/s/` shortlinks) but let
   the backend be the source of truth.

### 5.6 Actions per day
For the selected profile: today's `action_count` vs `daily_action_quota`
(progress bar, turns red near/over quota), plus a **last-30-days bar chart**
from `/api/daily`. If "All profiles" is selected, show a small multiples / total.
Optional inline quota editor → `POST /api/limits`.

### 5.7 Profile switcher (cross-cutting)
Header dropdown listing each profile as `accountLabel (u/redditUsername)`, marking
the default, plus "All profiles". Changing it refetches the active view. Also
surface the profile's `debugAddress` and whether an executor/lease is active, so
the user knows which Chrome the actions will drive.

---

## 6. Implementation order (for Codex)

1. **Backend gaps (§4)** — `retry_queue_job`/`retry_failed_jobs`,
   `delete_schedule`, schedule status setter, plus `agentctl`/`reddit-tool`
   subcommands. Write tests. `make test` green before moving on.
2. **Web server skeleton** — `scripts/reddit_ui.py`: `http.server` handler
   serving `/api/*` (JSON) and static files from `web/`. In-process agentctl
   call helper (reuse the `_agentctl_payload` redirect pattern). Bind
   `127.0.0.1`.
3. **Read endpoints** — profiles, overview, schedules, queue, history, daily,
   errors, capabilities.
4. **Write endpoints** — tasks, retry, schedules run-due/pause/resume/delete.
5. **Frontend** — static shell + profile switcher + the 7 views, wired to the
   API. Zero build step.
6. **Launcher polish** — `make ui`, README section, optional `reddit-tool ui`.
7. **Tests** — API-level tests for each endpoint (spin the handler against a
   temp `reddit_bot.db` seeded via `BotDatabase`); a smoke test that the page
   loads and `/api/overview` returns `ok`.

---

## 7. Acceptance criteria

- `make ui` starts a server on `http://127.0.0.1:8765`; opening it shows the
  overview for the default profile.
- Schedule view lists `schedule_registry` rows with human cadence, next/last
  run, and working Pause/Resume/Run-now/Delete.
- Failed view lists failed queue jobs + action-log errors; **Retry** flips a
  failed job back to `queued` (verified by re-querying), and **Retry all**
  works.
- Successful view lists completed actions per profile.
- Add-task form creates: an immediate action (Now), a one-time schedule (`--at`),
  and a recurring schedule (daily/weekly), each visible afterward in Schedule or
  Queue.
- Actions-per-day shows today's count vs quota and a 30-day history for the
  selected profile.
- Profile switcher changes every view's data; "All profiles" aggregates.
- `make test` passes, including new retry/delete/endpoint tests.

---

## 8. Constraints & safety

- **Localhost only.** Bind `127.0.0.1`; no external interface, no auth layer
  needed but never bind `0.0.0.0`.
- **Live actions are real.** "Now" submissions and `run-due` perform real Reddit
  actions through the existing worker. Add a confirm step in the UI for
  mutating actions and consider surfacing the config `dry_run` flag.
- **Respect the control plane.** All mutations go through `agentctl`/`tool_cli`
  so quota reservations, dedupe, leases, and executor-ensure keep working. Honor
  the conflict rules in `docs/scheduler-and-rate-limits.md` (don't start work
  that collides with a running job/lease/quota).
- **Keep it dependency-light.** Prefer stdlib; no npm/bundler; if adding
  FastAPI, put it under the `dev` extra and document it.
- **Sync skill copies** if you touch anything the skill references
  (`make check-skill`).

---

## 9. New files (expected)

```
scripts/reddit_ui.py          # http.server launcher + JSON API (or thin wrapper)
bot/web/__init__.py           # optional: API handlers if you factor them out of scripts/
web/index.html                # SPA shell
web/app.js                    # views + fetch logic (vanilla)
web/styles.css                # styling
tests/test_web_api.py         # endpoint tests against a temp DB
docs/local-ui.md              # short usage doc (how to run, what each view shows)
```

Plus edits to: `bot/database.py` (retry/delete helpers), `bot/agentctl.py` +
`bot/tool_cli.py` (retry/delete/status subcommands), `Makefile` (`ui` target),
`README.md` (UI section), and matching tests.
