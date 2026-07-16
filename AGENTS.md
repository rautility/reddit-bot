# Reddit Bot Agent Runbook

This repository can perform live Reddit account actions. Treat every mutation as
stateful and quota-limited.

> **Fast path for agents:** you usually don't need to read this whole runbook.
> Load the `reddit-bot` skill (`.claude/skills/reddit-bot/` or
> `.codex/skills/reddit-bot/`). Run `reddit-tool capabilities` to learn the
> action schema, then `reddit-tool do --action <a> --link <url>` to execute one
> action (submit + worker + result in one call). This runbook is the deep
> reference the skill points into.

## Required First Step

Run:

```bash
.venv/bin/python scripts/agentctl.py status
```

Read the JSON before scheduling, queueing, or executing work. It reports saved
Chrome profiles, active queue jobs, leases, registered schedules, Codex
automations, account limits, and the default Chrome debugger address.

### Helper Commands

When something looks wrong before acting, run the read-only doctor:

```bash
.venv/bin/python scripts/reddit_tool.py doctor --json
```

It checks DB, profile associations, identity resolve, DevTools, healer extension,
executor, queue depth, and leases. Soft failures (Chrome down) leave exit 0 so
you can parse JSON; only hard misconfig (DB open failure) exits non-zero.

## Default Execution Rule

For any live Reddit action requested from an agent or automation, the default
execution path is:

1. Resolve the Chrome profile/Reddit user with `agentctl profiles resolve`.
2. Write the requested actions to a links/action file.
3. Submit that file with `agentctl queue submit`.
4. Run exactly one queue worker pass with `agentctl queue worker --once`.

Do not schedule prompts that tell a future agent to click, vote, search, or run
`main.py` directly. Scheduled live work must register a project schedule with
`agentctl schedules register --links ...`; the project scheduler then submits
due actions to the queue and runs one queue worker pass. Active schedule
registration best-effort ensures the local executor service so external apps do
not need to manage a separate wakeup process.
Use `scripts/reddit_healer_debug.py` for diagnostics, candidate discovery, and
opening saved profiles, not as the primary live-action scheduler.

## Live Action Policy

- Do not perform live Reddit mutations unless Raul explicitly requested that
  exact action for the current run.
- Do not script Reddit login. Use manually authenticated saved Chrome profiles.
- For agent-run live work, submit actions through `agentctl queue`; do not call
  `main.py` directly unless Raul explicitly asks for a manual direct run.
- For scheduled live work, create or update a project-owned schedule with
  `agentctl schedules register --links ...`, then rely on
  the project executor service to run
  `agentctl schedules run-due --run-worker`.
- Use one Chrome user-data-dir and one DevTools port per Reddit account.
- Acquire queue/profile/account coordination through SQLite; do not implement a
  separate scheduler, lock file, or ad hoc rate limiter.

## Saved Chrome Profile Defaults

Default local profile:

```text
Name:    Chrome Reddit Bot Debug Profile
Path:    /Users/raulvecchione/Library/Application Support/Chrome Reddit Bot Debug Profile
Debug:   127.0.0.1:9222
Healer:  chrome_extension/reddit_healer
```

Inspect saved profiles:

```bash
.venv/bin/python scripts/agentctl.py profiles list
```

Persist a one-time profile/account association:

```bash
.venv/bin/python scripts/agentctl.py profiles associate \
  --profile-name "Chrome Reddit Bot Debug Profile" \
  --reddit-user "u/Particular-Arm2102"
```

Resolve either identity before scheduling live work:

```bash
.venv/bin/python scripts/agentctl.py profiles resolve --profile-name "Chrome Reddit Bot Debug Profile"
.venv/bin/python scripts/agentctl.py profiles resolve --reddit-user "u/Particular-Arm2102"
```

Probe the active debugger:

```bash
.venv/bin/python scripts/agentctl.py profiles probe --debug-address 127.0.0.1:9222
```

If a sandboxed loopback probe fails but Chrome is visibly open, retry the same
probe with the approved escalation flow. Local DevTools access is often blocked
inside the sandbox.

## Queue Workflow

Submit actions:

```bash
.venv/bin/python scripts/agentctl.py queue submit \
  --reddit-user "u/Particular-Arm2102" \
  --links links.txt
```

Agents may also submit by profile:

```bash
.venv/bin/python scripts/agentctl.py queue submit \
  --profile-name "Chrome Reddit Bot Debug Profile" \
  --links links.txt
```

Run one worker:

```bash
.venv/bin/python scripts/agentctl.py --config config.yaml queue worker --once
```

If no config file is needed, still run the worker through `agentctl`:

```bash
.venv/bin/python scripts/agentctl.py queue worker --once
```

List queue state:

```bash
.venv/bin/python scripts/agentctl.py queue list
```

Retry failed queue jobs:

```bash
.venv/bin/python scripts/agentctl.py queue retry --id 123
.venv/bin/python scripts/agentctl.py queue retry --all --account "Particular-Arm2102"
```

The worker leases one queued job, leases the configured Chrome profile/debug
address, runs the existing bot action path, and records the result back to
SQLite.

For post-level actions such as `upvote`, `downvote`, `comment`, `save`, `hide`,
and `award`, links files must use canonical Reddit comments URLs:

```text
https://www.reddit.com/r/<subreddit>/comments/<post_id>/<slug>/
```

Do not submit Reddit share shortlinks like `/r/<subreddit>/s/<share_id>`.
`agentctl queue submit` and `agentctl schedules register` reject them before
they can enter the queue. Resolve shortlinks first, then schedule the canonical
`/comments/` URL.

## Quotas And Limits

Set a per-account daily quota:

```bash
.venv/bin/python scripts/agentctl.py limits set \
  --account "<account-label>" \
  --daily-action-quota 25
```

List limits and active reservations:

```bash
.venv/bin/python scripts/agentctl.py limits list
```

Quota reservations use `BEGIN IMMEDIATE` transactions so parallel agents cannot
all pass the same remaining daily slot. Existing behavior is preserved: logged
failures count toward the daily account action count.

## Schedules

Inspect schedules before creating new recurring work:

```bash
.venv/bin/python scripts/agentctl.py schedules list
```

Register project-owned schedules in SQLite:

```bash
.venv/bin/python scripts/agentctl.py schedules register \
  --id "reddit-bot-example" \
  --name "Reddit Bot Example" \
  --source "codex" \
  --rrule "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0" \
  --reddit-user "u/Particular-Arm2102" \
  --action-class "live" \
  --links links.txt
```

The command above ensures the local executor when the schedule is active,
has a links file, and resolves to an account. Inspect or manage the executor:

```bash
.venv/bin/python scripts/agentctl.py schedules set-status --id "reddit-bot-example" --status PAUSED
.venv/bin/python scripts/agentctl.py schedules set-status --id "reddit-bot-example" --status ACTIVE
.venv/bin/python scripts/agentctl.py schedules delete --id "reddit-bot-example"
```

Pause/resume/delete commands update the existing registry row; do not reregister
the schedule just to change status.

```bash
.venv/bin/python scripts/agentctl.py executor status
.venv/bin/python scripts/agentctl.py executor ensure
.venv/bin/python scripts/agentctl.py executor stop
```

The executor is a macOS LaunchAgent that periodically wakes the project
scheduler:

```bash
cd /Users/raulvecchione/MEGA/rvScripts/reddit-bot
.venv/bin/python scripts/agentctl.py schedules run-due --run-worker
```

Codex automations or external apps should not directly call `main.py`, directly
click vote controls, or bypass `agentctl` unless Raul explicitly asks for that
exception.

Known Codex automation: `reddit-bot-weekly-log-maintenance`. It is maintenance
only and explicitly forbids live Reddit actions unless Raul gives a separate
exact instruction for that run.

## Related Docs

- `docs/agentic-operations.md`
- `docs/scheduler-and-rate-limits.md`
- `docs/chrome-debug-profiles.md`
- `docs/weekly-log-maintenance.md`
