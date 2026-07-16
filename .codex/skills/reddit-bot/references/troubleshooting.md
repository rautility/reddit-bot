# Troubleshooting

Read when a command failed or returned `ok: false`.

## First, get the structured error

Every command supports `--json` and returns `{ok, error, data}`. Then:

```bash
TOOL=".venv/bin/python scripts/reddit_tool.py"
$TOOL doctor --json     # structured checks: DB, identity, DevTools, queue, executor
$TOOL errors            # recent queue, schedule, action, and executor failures
$TOOL job --id <N>      # one job's status, last error, and stored result
$TOOL overview          # queue counts, executor state, active leases
```

Start with `doctor` when the question is “why can’t I act?”. Soft check failures
(Chrome down, executor stopped) leave exit 0; only DB open failure exits non-zero.

## Common cases

**`fieldErrors` (missing required field).** The payload lacked a field the action
needs. Run `capabilities` and supply it. Example: `comment` needs `--comment`,
`dm` needs `--recipient` and `--message`.

**`linkErrors` / share link rejected.** A post action got a non-canonical URL.
Open the `/r/<sub>/s/<id>` share link in the saved Chrome profile, copy the
resulting `/comments/` URL, and retry.

**Unknown Reddit username association.** The `--reddit-user` isn't linked to a
profile yet. Associate it (see `references/chrome-profiles.md`) or pass
`--profile-name` instead.

**Job stuck `queued` / nothing happened.** No worker ran. `do` runs one pass
automatically; if you used `--no-run` or a schedule, run
`$TOOL queue run-once` (or `$TOOL schedule run-due --run-worker`).

**Existing Chrome session not authenticated.** The saved profile isn't logged in.
Open it and log in manually — do not script login.

**Lease held / another run in progress.** Another worker holds the Chrome
profile lease. Wait for it, or check `overview` → active leases. Do not bypass
with a direct `main.py` run.

**Sandboxed `127.0.0.1:<port>` probe fails but Chrome is open.** Local DevTools
access is often blocked inside the sandbox. Retry the same probe with the
approved escalation.

## Escalation

`main.py` is an owner-only manual escape hatch, not the agent default. Only use it
if Raul explicitly asks. Otherwise every fix stays on the `reddit-tool` path.
