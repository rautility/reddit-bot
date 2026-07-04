# Saved Chrome Debug Profiles

This project should use manually authenticated Chrome profiles for local Reddit actions. Each Reddit account gets a separate Chrome user-data-dir and DevTools port.

## Default Profile

| Field | Value |
|-------|-------|
| Profile name | `Chrome Reddit Bot Debug Profile` |
| Profile path | `/Users/raulvecchione/Library/Application Support/Chrome Reddit Bot Debug Profile` |
| DevTools address | `127.0.0.1:9222` |
| Healer extension | `chrome_extension/reddit_healer` |

## Open A Saved Profile

```bash
.venv/bin/python scripts/reddit_healer_debug.py open-profile
```

This opens Chrome with:

- `--remote-debugging-address=127.0.0.1`
- `--remote-debugging-port=9222`
- `--user-data-dir=/Users/raulvecchione/Library/Application Support/Chrome Reddit Bot Debug Profile`
- `--load-extension=chrome_extension/reddit_healer`

## Create Another Reddit Account Profile

Pick a stable profile name and a free port:

```bash
.venv/bin/python scripts/reddit_healer_debug.py open-profile \
  --profile-name "Chrome Reddit Bot Debug Profile - account2" \
  --port 9223 \
  --url "https://www.reddit.com/login/"
```

Chrome creates the user-data-dir if it does not exist:

```text
/Users/raulvecchione/Library/Application Support/Chrome Reddit Bot Debug Profile - account2
```

Log in to Reddit manually in that Chrome window. Do not use scripted login for this workflow.

## Confirm The Healer Extension

Probe the bridge:

```bash
.venv/bin/python scripts/reddit_healer_debug.py ping-bridge \
  --debug-address 127.0.0.1:9223
```

Expected result:

```json
{
  "ok": true,
  "name": "reddit-bot-healer"
}
```

If the bridge times out, open `chrome://extensions` in that profile, enable Developer mode, and load unpacked from:

```text
/Users/raulvecchione/MEGA/rvScripts/reddit-bot/chrome_extension/reddit_healer
```

## Find Before Clicking

Use the Healer candidate probe before a real UI action:

```bash
.venv/bin/python scripts/reddit_healer_debug.py find-control \
  --debug-address 127.0.0.1:9223 \
  --intent downvote \
  --url "https://www.reddit.com/r/example/comments/abc/title/"
```

Report:

- `confidence`
- `boundingBox`
- `state`
- `evidence`

Click only when the user explicitly asks for the action. For vote actions, confirm `ariaPressed` or `aria-pressed` changes to `true`.

## Run The Bot Against A Saved Profile

```bash
.venv/bin/python main.py -a accounts.txt -l links.txt --verbose \
  --use-existing-chrome \
  --chrome-debugging-address 127.0.0.1:9223 \
  --chrome-extension-healer
```

In attach mode, `accounts.txt` identifies the run label. The actual Reddit identity is the account manually logged in inside the Chrome profile attached to that port.

Run one saved profile/port at a time. The bot forces attach mode to sequential execution because a single DevTools address represents a single active Chrome profile.

## Print Profile Metadata

```bash
.venv/bin/python scripts/reddit_healer_debug.py profile-info \
  --profile-name "Chrome Reddit Bot Debug Profile - account2" \
  --port 9223
```

This prints JSON containing the resolved profile path, DevTools address, opener command, bot command, and login rule.

