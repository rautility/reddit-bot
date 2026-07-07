# Chrome Profiles & Accounts

Read this when a task involves a non-default account, setting up a new account,
or confirming which Chrome profile/port to use.

## Defaults

- Profile: `Chrome Reddit Bot Debug Profile`
- Path: `/Users/raulvecchione/Library/Application Support/Chrome Reddit Bot Debug Profile`
- DevTools: `127.0.0.1:9222`
- Reddit user: `u/Particular-Arm2102`

`reddit-tool capabilities` prints the current defaults; `reddit-tool profiles`
lists every saved profile and its account association.

## Identity resolution

Any live command accepts one of:

- `--reddit-user "u/<name>"` — resolves via a stored association
- `--profile-name "<Chrome profile>"`
- `--account-label "<label>"`

Associate a profile with a Reddit account once:

```bash
.venv/bin/python scripts/agentctl.py profiles associate \
  --profile-name "Chrome Reddit Bot Debug Profile" --reddit-user "u/Particular-Arm2102"
```

## One account = one profile + one port

Use a distinct user-data-dir and DevTools port per account, e.g.
`... - account2` on `9223`, `... - account3` on `9224`.

Open a saved profile (manual login happens in the browser — never scripted):

```bash
.venv/bin/python scripts/reddit_healer_debug.py open-profile \
  --profile-name "Chrome Reddit Bot Debug Profile - account2" --port 9223 \
  --url "https://www.reddit.com/login/"
```

## Rules

- Never script Reddit login. Log in manually inside the saved profile.
- Keep profile names descriptive and stable so associations keep resolving.

Deeper Chrome/DevTools/healer control-discovery work: `references/debug-chrome.md`
and repo `docs/chrome-debug-profiles.md`.
