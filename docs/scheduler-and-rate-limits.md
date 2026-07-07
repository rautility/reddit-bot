# Scheduler And Rate Limits

The project uses SQLite as the shared coordination point for agents, schedules,
workers, account quotas, and Chrome profile leases.

## Tables

`agent_queue`

- Stores queued, running, succeeded, failed, and cancelled action jobs.
- Uses an active dedupe key so duplicate queued/running jobs collapse to one job.
- Workers lease jobs before execution.

`agent_leases`

- Stores leases for shared resources such as Chrome profiles.
- Resource ids should be stable, for example `127.0.0.1:9222` or a profile path.
- Expired leases can be replaced by a new worker.

`account_limits`

- Stores optional per-account or per-account/action daily quotas.
- Action `*` is the account-wide default.

`account_action_reservations`

- Reserves a quota slot before action execution.
- Reservation is made inside `BEGIN IMMEDIATE` so parallel agents cannot reserve
  the same remaining slot.
- Completed actions are logged in `action_log`, and `account_stats` remains the
  durable daily count.

`schedule_registry`

- Stores project-owned recurring work metadata and execution state:
  `next_run_at`, `last_run_at`, lock owner/expiry, and the last scheduler error.
- Scheduled live Reddit work should be registered here with a links/action file,
  then executed by the project executor through `agentctl schedules run-due`.
- Codex automations are still read from `$HOME/.codex/automations` for
  visibility, but live work should rely on the project executor instead of
  directly clicking controls, running `main.py`, or bypassing `agentctl`.

`chrome_profile_accounts`

- Stores one-time associations between a saved Chrome profile and a Reddit
  username.
- Lets agents schedule or queue work by either `--profile-name` or
  `--reddit-user`.
- The resolved `account_label` is used for queue jobs, leases, duplicate checks,
  and daily quota accounting.

## Quota Semantics

Existing behavior is preserved:

- Successful actions count toward `account_stats`.
- Failed logged actions also count toward `account_stats`.
- Duplicate successful actions are skipped before reserving quota.
- In-flight reservations count while their status is `reserved`.
- Expired reservations do not count.

The effective daily usage check is:

```text
account_stats count for today + active reserved slots for today < daily quota
```

## Scheduled Execution Flow

1. An agent registers recurring live work with `agentctl schedules register`,
   including an RRULE, account/profile identity, and `--links`.
2. For active schedules with links and a resolved account,
   `schedules register` best-effort ensures the local executor service.
3. On macOS, the executor is a user LaunchAgent that wakes periodically and
   runs:

   ```bash
   .venv/bin/python scripts/agentctl.py schedules run-due --run-worker
   ```

4. `run-due` leases due `schedule_registry` rows, reads each schedule's
   links/action file, and enqueues those actions into `agent_queue`.
5. `run-due --run-worker` runs the normal queue worker for the submitted jobs.
6. The schedule row is updated with `last_run_at`, the next computed
   `next_run_at`, or `last_error`.

Schedule registration does not fail if launchd is unavailable. It still stores
the schedule and returns executor status JSON with `ensured: false` and an
error. This keeps sandboxed agents, SSH sessions, and non-macOS test
environments from losing scheduled work.

## Queue Worker Flow

1. Lease the next due `agent_queue` job.
2. Lease the configured Chrome profile/debugger resource.
3. Run the existing `run_account()` path for one queued action.
4. `RedditBot.perform_action()` reserves quota atomically before mutation.
5. Log the action result.
6. Mark the quota reservation succeeded or failed.
7. Mark the queue job succeeded or failed.
8. Release the Chrome profile lease.

Scheduled live Reddit work must use this flow by queueing jobs first. A Codex
automation prompt should not instruct a future agent to directly click controls,
run `main.py`, or bypass `agentctl`.

## Links File Validation

For post-level actions, links files must use canonical Reddit comments URLs:

```text
https://www.reddit.com/r/<subreddit>/comments/<post_id>/<slug>/
```

`agentctl queue submit` and `agentctl schedules register` reject Reddit share
shortlinks such as `/r/<subreddit>/s/<share_id>` for `upvote`, `downvote`,
`comment`, `save`, `hide`, and `award`. Resolve share links before registration
so the queued worker receives the same canonical URL shape it will inspect in
Chrome.

## Conflict Rules

Agents should not start live work when any of these are true:

- A running queue job uses the same account/profile.
- An active lease exists for the same Chrome profile/debug address.
- A registered schedule or Codex automation is due to use the same live action
  surface.
- The account is at or near its configured daily quota.

Maintenance tasks may inspect logs, screenshots, selectors, and tests, but must
not mutate Reddit account state unless Raul gives a separate exact instruction.

## Profile Account Resolution

Create or update an association:

```bash
.venv/bin/python scripts/agentctl.py profiles associate \
  --profile-name "Chrome Reddit Bot Debug Profile" \
  --reddit-user "u/Particular-Arm2102"
```

Queue by Reddit username:

```bash
.venv/bin/python scripts/agentctl.py queue submit \
  --reddit-user "u/Particular-Arm2102" \
  --links links.txt
```

Queue by Chrome profile:

```bash
.venv/bin/python scripts/agentctl.py queue submit \
  --profile-name "Chrome Reddit Bot Debug Profile" \
  --links links.txt
```

Register a recurring live schedule:

```bash
.venv/bin/python scripts/agentctl.py schedules register \
  --id "reddit-bot-example" \
  --name "Reddit Bot Example" \
  --source "agentctl" \
  --rrule "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0" \
  --reddit-user "u/Particular-Arm2102" \
  --action-class "live" \
  --links links.txt
```

Active schedules with `--links` and a resolved account automatically try to
ensure the local executor. To inspect or manage it directly:

```bash
.venv/bin/python scripts/agentctl.py executor status
.venv/bin/python scripts/agentctl.py executor ensure
.venv/bin/python scripts/agentctl.py executor stop
```

`executor ensure` writes or updates:

```text
~/Library/LaunchAgents/com.raul.reddit-bot.agentctl-scheduler.plist
```

The LaunchAgent runs the project executor from this repository and logs to
`.agent-executor/executor.log`.

## Useful Commands

```bash
.venv/bin/python scripts/agentctl.py status
.venv/bin/python scripts/agentctl.py executor status
.venv/bin/python scripts/agentctl.py schedules list
.venv/bin/python scripts/agentctl.py schedules run-due --run-worker
.venv/bin/python scripts/agentctl.py limits list
.venv/bin/python scripts/agentctl.py queue list
.venv/bin/python scripts/agentctl.py profiles list
.venv/bin/python scripts/agentctl.py profiles resolve --reddit-user "u/Particular-Arm2102"
.venv/bin/python scripts/agentctl.py profiles probe --debug-address 127.0.0.1:9222
```
