---
name: reddit-bot
description: Take real Reddit actions through the local reddit-bot (upvote, downvote, comment, save/hide, join/leave, follow/unfollow, DM, post, crosspost, human search) using Raul's saved Chrome profiles. Use whenever a task needs to act on a Reddit URL, queue or schedule Reddit actions, or check the bot's queue/quota/errors. Run `reddit-tool capabilities` to learn the exact action fields, then `reddit-tool do` to execute. Local only — same laptop, no network, no programmatic login.
---

# Reddit Bot

Operate the Reddit automation bot at `/Users/raulvecchione/MEGA/rvScripts/reddit-bot`.
Do **not** read the repo's large runbooks (`AGENTS.md`, `docs/`) to act — the tools
below describe themselves. Read a `references/` file only for the specific sub-task
it names.

All commands run from the repo root. Use the venv Python:

```bash
cd /Users/raulvecchione/MEGA/rvScripts/reddit-bot
TOOL=".venv/bin/python scripts/reddit_tool.py"   # or the installed `reddit-tool`
```

Add `--json` to any command for a machine-readable, versioned envelope
(`{ok, schemaVersion, command, data, error}`).

## 1. Learn what's possible (do this instead of reading docs)

```bash
$TOOL capabilities            # actions, required fields per action, URL rule, defaults, live quota
$TOOL resolve-url --link "<url>"   # share shortlink → canonical /comments/ URL
```

This is the source of truth for which fields each action needs. Never guess fields.

## 2. Run one action end to end

`do` builds the action file, submits it to the queue, runs one worker pass, and
returns the real outcome — one call, no temp files to write yourself:

```bash
$TOOL do --action upvote --link "https://www.reddit.com/r/<sub>/comments/<id>/<slug>/"
$TOOL do --action comment --link "<post_url>" --comment "Nice write-up."
$TOOL do --action dm --recipient "u/someone" --message "hi"
$TOOL search-upvote --query "best Excel tips"
$TOOL external-search-upvote --query "best Excel tips" --json
```

- Default account/profile is used automatically (see `capabilities` → defaults).
  Target another with `--reddit-user`, `--profile-name`, or `--account-label`.
- Add `--no-run` to queue without executing; run it later with `$TOOL queue run-once`.
- Live worker runs preflight the resolved Chrome debugger and opens the saved
  profile when needed. Use `--no-profile-preflight` only for diagnostics.
- Post actions require a **canonical** `/comments/` URL. Share links
  (`/r/<sub>/s/<id>`) are rejected by default — resolve first:
  `$TOOL resolve-url --link "<share_url>"` (use the `output` field).

For scheduled search-then-upvote work, register the compound action directly:

```bash
$TOOL schedule add --action search_upvote --query "best Excel tips" --at 2026-07-06T09:00:00
```

For external projects that want a single normalized workflow, use:

```bash
$TOOL external-search-upvote --query "best Excel tips" --json
```

It registers a one-shot schedule, runs due work, polls the queue result, and
returns the selected post URL plus final mutation status when available.

## 3. Check state, results, and failures

```bash
$TOOL doctor --json          # read-only: why can't I act? (DB, Chrome, queue, executor)
$TOOL overview               # queue, schedules, executor, profiles, recent errors
$TOOL job --id <N>           # one job's status + stored result (from `do`/`queue`)
$TOOL queue --status failed  # queued/failed jobs
$TOOL queue recover-stale    # release expired running jobs for retry
$TOOL queue retry --id 123   # requeue one failed job
$TOOL queue retry --all      # requeue failed jobs
$TOOL errors                 # recent queue, schedule, action, and executor errors
```

`doctor` is pure diagnostics (no Reddit mutations, no queue submit). Soft
failures (Chrome not running) set `summary.ok: false` but process exit stays 0
so you can parse the envelope; only hard misconfig (DB unopenable) exits non-zero.

## Safety rules (do not violate)

- Only perform a live Reddit mutation Raul explicitly asked for in this run.
- Never script Reddit login. Sessions come from manually authenticated saved
  Chrome profiles.
- Always go through `reddit-tool` / the queue. Do **not** call `main.py` directly
  and do **not** click/vote via a browser as the default path.
- One Chrome user-data-dir and one DevTools port per Reddit account.
- Do not build a separate scheduler, lock file, or rate limiter — the queue,
  SQLite leases, and per-account quotas already coordinate this.

## Go deeper only when the task needs it

| Task | Read |
|------|------|
| Full action list + per-action examples (offline) | `references/actions.md` |
| Recurring / timed schedules and the executor | `references/scheduling.md` |
| Chrome profiles, ports, new account setup | `references/chrome-profiles.md` |
| Attach to DevTools, healer bridge, discover a control before clicking | `references/debug-chrome.md` |
| A command failed / share link / sandbox probe | `references/troubleshooting.md` |
