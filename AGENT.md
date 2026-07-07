# Reddit Bot Agent Playbook

Read `AGENTS.md` first. It is the canonical runbook for multi-agent operation,
queueing, leases, quotas, and schedule checks. This file keeps the saved Chrome
profile workflow close at hand for agents that still look for singular
`AGENT.md`.

## Agent Control Plane

Before scheduling or running work, inspect shared state:

```bash
.venv/bin/python scripts/agentctl.py status
```

For live Reddit mutations initiated by agents, submit actions through the queue:

```bash
.venv/bin/python scripts/agentctl.py queue submit --reddit-user "u/Particular-Arm2102" --links links.txt
.venv/bin/python scripts/agentctl.py queue worker --once
```

For scheduled live Reddit actions, register a project-owned schedule with
`agentctl schedules register --links ...`, then wake the project executor with
`agentctl schedules run-due --run-worker`. Do not schedule future agents to
click, vote, search, or call `main.py` directly unless Raul explicitly asks for
that exception.

Do not create separate lock files, schedulers, or rate limiters. Use the SQLite
coordination mechanisms exposed by `agentctl`.

## Default Browser Workflow

Use saved Chrome debug profiles for Reddit tasks. The default profile is:

- Name: `Chrome Reddit Bot Debug Profile`
- Path: `/Users/raulvecchione/Library/Application Support/Chrome Reddit Bot Debug Profile`
- DevTools address: `127.0.0.1:9222`
- Healer extension: `chrome_extension/reddit_healer`
- Reddit user: `u/Particular-Arm2102`

Do not log in to Reddit programmatically unless the user explicitly asks for that specific test. Login should happen manually inside the saved Chrome profile.

## Action Flow

For live Reddit UI actions, default to the queued flow in `AGENTS.md`. For
diagnostics or owner-approved manual action checks:

1. Attach to the requested `127.0.0.1:<port>` Chrome debugger.
2. Use the Reddit Bot Healer extension first to find the intended control.
3. Report the best candidate's confidence, bounding box, state, and evidence before clicking.
4. Click only when the user explicitly asks for the real action.
5. Confirm the post-click state, preferably `aria-pressed="true"` for vote actions.

If sandboxed access to `127.0.0.1:<port>` fails, retry the same probe with escalation. Local DevTools access is often blocked in the sandbox but reachable outside it.

## Helper Commands

Open the default saved profile:

```bash
.venv/bin/python scripts/reddit_healer_debug.py open-profile
```

Open another saved profile for another Reddit account:

```bash
.venv/bin/python scripts/reddit_healer_debug.py open-profile \
  --profile-name "Chrome Reddit Bot Debug Profile - account2" \
  --port 9223 \
  --url "https://www.reddit.com/login/"
```

Check the extension bridge:

```bash
.venv/bin/python scripts/reddit_healer_debug.py ping-bridge \
  --debug-address 127.0.0.1:9222
```

Find a vote control:

```bash
.venv/bin/python scripts/reddit_healer_debug.py find-control \
  --debug-address 127.0.0.1:9222 \
  --intent upvote \
  --url "<POST_URL>"
```

Run the bot through the attached Chrome session:

```bash
.venv/bin/python scripts/agentctl.py queue submit --reddit-user "u/Particular-Arm2102" --links links.txt
.venv/bin/python scripts/agentctl.py queue worker --once
```

Direct `main.py --use-existing-chrome` remains a manual owner-controlled escape
hatch, not the default for agents or schedules.

## New Profile Setup

Use one profile directory and one port per Reddit account. Keep profile names descriptive and stable, for example:

- `Chrome Reddit Bot Debug Profile`
- `Chrome Reddit Bot Debug Profile - account2`
- `Chrome Reddit Bot Debug Profile - account3`

Launch the new profile with `open-profile`, log in manually, then run `ping-bridge`. If the bridge times out, open `chrome://extensions`, enable Developer mode, and load unpacked from `chrome_extension/reddit_healer`.
