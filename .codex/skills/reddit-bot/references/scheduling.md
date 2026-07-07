# Scheduling & Recurring Work

Read this only when the task is to run Reddit actions on a timer. For a single
immediate action, use `reddit-tool do` instead (see SKILL.md).

```bash
cd /Users/raulvecchione/MEGA/rvScripts/reddit-bot
TOOL=".venv/bin/python scripts/reddit_tool.py"
```

## Add a schedule

One-time at a specific moment:

```bash
$TOOL schedule add --name "Upvote launch post" \
  --action upvote --link "<canonical_post_url>" \
  --at "2026-07-06T09:00:00"
```

Daily / weekly:

```bash
$TOOL schedule add --name "Morning save" --action save --link "<url>" --daily-at 09:30
$TOOL schedule add --name "Weekday actions" --links links.txt --weekly MO,WE,FR --time 09:30
```

- `--link/--action` writes the action file for you; `--links FILE` uses an existing one.
- Registering an ACTIVE schedule with a resolved account best-effort starts the
  local executor (a macOS LaunchAgent) so it runs unattended.
- Target a non-default account with `--reddit-user` / `--profile-name` / `--account-label`.

## Inspect & run

```bash
$TOOL schedules                 # registered schedules + Codex automations
$TOOL schedule run-due --run-worker   # submit anything due now and run one worker pass
$TOOL executor                  # status of the background scheduler service
```

## Rules

- Do not schedule prompts that tell a future agent to click/vote/search or call
  `main.py`. Scheduled live work must go through this schedule → queue → worker path.
- Do not create a second scheduler, cron entry, or lock file. SQLite leases and
  per-account daily quotas already serialize execution.

Full detail: repo `docs/scheduler-and-rate-limits.md`.
