# Reddit Bot Agent Playbook

## Default Browser Workflow

Use saved Chrome debug profiles for Reddit tasks. The default profile is:

- Name: `Chrome Reddit Bot Debug Profile`
- Path: `/Users/raulvecchione/Library/Application Support/Chrome Reddit Bot Debug Profile`
- DevTools address: `127.0.0.1:9222`
- Healer extension: `chrome_extension/reddit_healer`

Do not log in to Reddit programmatically unless the user explicitly asks for that specific test. Login should happen manually inside the saved Chrome profile.

## Action Flow

For Reddit UI actions:

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
.venv/bin/python main.py -a accounts.txt -l links.txt --verbose \
  --use-existing-chrome \
  --chrome-debugging-address 127.0.0.1:9222 \
  --chrome-extension-healer
```

In attach mode, the account file is an execution label. The active Reddit account is the one manually logged in inside the attached profile.

## New Profile Setup

Use one profile directory and one port per Reddit account. Keep profile names descriptive and stable, for example:

- `Chrome Reddit Bot Debug Profile`
- `Chrome Reddit Bot Debug Profile - account2`
- `Chrome Reddit Bot Debug Profile - account3`

Launch the new profile with `open-profile`, log in manually, then run `ping-bridge`. If the bridge times out, open `chrome://extensions`, enable Developer mode, and load unpacked from `chrome_extension/reddit_healer`.

