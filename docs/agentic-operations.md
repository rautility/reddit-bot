# Agentic Operations

This document describes the supported path for LLM agents operating this
project. It is intentionally operational: commands should produce JSON and
state should go through the shared SQLite database (WAL mode).

## Dual path

| Path | Entry points | Use when |
|------|----------------|----------|
| **Control plane (default)** | `scripts/agentctl.py`, `scripts/reddit_tool.py`, local UI | All agent / schedule / day-to-day live work |
| **Legacy batch (owner only)** | `main.py`, Docker headless | Explicit multi-account password/cookie runs |

Do not invent subcommands; verify with `--help`. Policy details live in
[`AGENTS.md`](../AGENTS.md).

## Control Plane

Use `scripts/agentctl.py` for agent-facing operations:

```bash
.venv/bin/python scripts/agentctl.py status
.venv/bin/python scripts/agentctl.py executor status
.venv/bin/python scripts/agentctl.py profiles list
.venv/bin/python scripts/agentctl.py schedules list
.venv/bin/python scripts/agentctl.py limits list
.venv/bin/python scripts/agentctl.py queue list
```

Read-only diagnostics when “why can’t I act?”:

```bash
.venv/bin/python scripts/reddit_tool.py doctor --json
```

For any live Reddit action initiated by an agent or automation, prefer:

```bash
# One action (submit + one worker pass + result)
.venv/bin/python scripts/reddit_tool.py do \
  --action upvote \
  --link "https://www.reddit.com/r/example/comments/abc/title/" \
  --reddit-user "u/Particular-Arm2102"

# Multi-action file
.venv/bin/python scripts/agentctl.py profiles resolve --reddit-user "u/Particular-Arm2102"
.venv/bin/python scripts/agentctl.py queue submit --reddit-user "u/Particular-Arm2102" --links links.txt
.venv/bin/python scripts/agentctl.py queue worker --once
```

When identity flags are omitted, resolution uses a sole
`chrome_profile_accounts` association, else `REDDIT_BOT_DEFAULT_USER` if set
and associated. Multiple associations without a flag is an error.

Do not schedule future agents to perform live clicks, votes, searches, or direct
`main.py` runs. Scheduled live work should queue actions and run one queue worker
pass. Register scheduled live work with `agentctl schedules register --links`;
for active schedules with a resolved account, registration best-effort ensures
the local executor service.

Package entry points after installation:

```bash
reddit-agentctl status
reddit-tool doctor --json
reddit-ui   # localhost dashboard; see docs/local-ui.md
```

Optional UI write token: set `REDDIT_BOT_UI_TOKEN` and send
`X-Reddit-Bot-Token` on `POST` routes.

## Local Executor

External apps can rely on `agentctl` to keep the project executor available for
scheduled work:

```bash
.venv/bin/python scripts/agentctl.py executor status
.venv/bin/python scripts/agentctl.py executor ensure
.venv/bin/python scripts/agentctl.py executor stop
```

On macOS, `executor ensure` writes a user LaunchAgent at:

```text
~/Library/LaunchAgents/com.raul.reddit-bot.agentctl-scheduler.plist
```

The LaunchAgent wakes periodically and runs:

```bash
.venv/bin/python scripts/agentctl.py schedules run-due --run-worker
```

Do not create separate external schedulers for Reddit mutations. External apps
should register schedules through `agentctl`, then let the project executor and
SQLite leases handle timing, queueing, profile coordination, and quotas.

## Status Checklist

Before queueing or scheduling work, check:

1. `queueCounts` for pending/running jobs.
2. `activeLeases` for Chrome profile or account leases.
3. `accountLimits` and active reservations.
4. `registeredSchedules` and `codexAutomations`.
5. `savedChromeProfiles` and the intended `debugAddress`.

Do not proceed with live Reddit mutations if another active lease or schedule is
using the same account/profile/action class.

## Saved Chrome Profiles

Saved profiles are discovered under:

```text
/Users/raulvecchione/Library/Application Support/Chrome Reddit Bot Debug Profile*
```

Default profile:

```text
Chrome Reddit Bot Debug Profile
127.0.0.1:9222
```

Use:

```bash
.venv/bin/python scripts/agentctl.py profiles probe --debug-address 127.0.0.1:9222
```

Associate the default saved Chrome profile with its Reddit account once:

```bash
.venv/bin/python scripts/agentctl.py profiles associate \
  --profile-name "Chrome Reddit Bot Debug Profile" \
  --reddit-user "u/Particular-Arm2102"
```

After association, agents can resolve either side:

```bash
.venv/bin/python scripts/agentctl.py profiles resolve --profile-name "Chrome Reddit Bot Debug Profile"
.venv/bin/python scripts/agentctl.py profiles resolve --reddit-user "u/Particular-Arm2102"
```

For Reddit UI control discovery, use the existing healer helper:

```bash
.venv/bin/python scripts/reddit_healer_debug.py ping-bridge --debug-address 127.0.0.1:9222
.venv/bin/python scripts/reddit_healer_debug.py find-control --debug-address 127.0.0.1:9222 --intent upvote --url "<POST_URL>"
```

Report candidate confidence, bounding box, state, and evidence before a manual
test click unless Raul already requested the real action.

## Action URL Contract

For post-level actions, use canonical Reddit comments URLs:

```text
https://www.reddit.com/r/<subreddit>/comments/<post_id>/<slug>/
```

This applies to `upvote`, `downvote`, `comment`, `save`, `hide`, and `award`.
Do not submit Reddit share shortlinks like:

```text
https://www.reddit.com/r/<subreddit>/s/<share_id>
```

`agentctl queue submit` and `agentctl schedules register` reject those links
before they can enter the queue. Resolve share links first:

```bash
.venv/bin/python scripts/reddit_tool.py resolve-url \
  --link "https://www.reddit.com/r/<subreddit>/s/<share_id>" --json
```

Use the returned `output` canonical `/comments/` URL for queue, schedule, or
`reddit-tool do`.

## Queue Commands

Queue one links file for one manually authenticated account label:

```bash
.venv/bin/python scripts/agentctl.py queue submit \
  --reddit-user "u/Particular-Arm2102" \
  --links links.txt
```

The same task can be queued by profile:

```bash
.venv/bin/python scripts/agentctl.py queue submit \
  --profile-name "Chrome Reddit Bot Debug Profile" \
  --links links.txt
```

Run a single worker pass:

```bash
.venv/bin/python scripts/agentctl.py --config config.yaml queue worker --once
```

For attach mode, `config.yaml` should include:

```yaml
use_existing_chrome: true
chrome_debugging_address: "127.0.0.1:9222"
chrome_extension_healer_enabled: true
parallel_accounts: 1
```

## Direct Runs (legacy / owner escape hatch)

`main.py` remains available for owner-controlled password/cookie batch runs,
dry-runs, and rare direct attach tests. Agents must prefer the queue /
`reddit-tool do` because they centralize leases and quota reservations.
Automations must not call `main.py` or Docker headless directly unless Raul
explicitly asks for that exception.

## Failure Handling

- Start with `reddit-tool doctor --json` for environment issues (DB, Chrome,
  identity, executor).
- Queue jobs move to `failed` when their worker result fails or max attempts are
  exceeded.
- Retry with `agentctl queue retry --id <N>` or `queue retry --all`.
- Jobs released before max attempts return to `queued`.
- Quota reservations expire if a worker crashes before completion.
- The existing action log remains the durable source for completed attempts and
  duplicate prevention.
