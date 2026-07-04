---
name: reddit-bot-debug-chrome
description: Use the saved Reddit bot Chrome debug profiles, DevTools attach ports, and Reddit Bot Healer extension. Trigger when working in this repo on Reddit UI actions, upvote/downvote tests, existing/manual Reddit login, Chrome profile setup, or 127.0.0.1 Chrome debugger sessions.
---

# Reddit Bot Debug Chrome

Use this skill for local Reddit UI work in `/Users/raulvecchione/MEGA/rvScripts/reddit-bot`.

## Fixed Defaults

- Default profile name: `Chrome Reddit Bot Debug Profile`
- Default profile path: `/Users/raulvecchione/Library/Application Support/Chrome Reddit Bot Debug Profile`
- Default DevTools address: `127.0.0.1:9222`
- Healer extension path: `/Users/raulvecchione/MEGA/rvScripts/reddit-bot/chrome_extension/reddit_healer`
- Helper script: `/Users/raulvecchione/MEGA/rvScripts/reddit-bot/scripts/reddit_healer_debug.py`
- Python: `/Users/raulvecchione/MEGA/rvScripts/reddit-bot/.venv/bin/python`

## Rules

- Do not log in to Reddit programmatically unless the user explicitly asks for that test.
- Prefer saved Chrome profiles and `--use-existing-chrome --chrome-debugging-address 127.0.0.1:<port>`.
- Use one Chrome user-data-dir and one DevTools port per Reddit account.
- Use the Healer extension first for Reddit UI control discovery.
- Before a click, report candidate confidence, bounding box, state, and evidence unless the user has already asked for the real action.
- If sandboxed access to `127.0.0.1:<port>` fails, retry the same probe with escalation.

## Core Commands

Open the default profile:

```bash
cd /Users/raulvecchione/MEGA/rvScripts/reddit-bot
.venv/bin/python scripts/reddit_healer_debug.py open-profile
```

Open another profile:

```bash
cd /Users/raulvecchione/MEGA/rvScripts/reddit-bot
.venv/bin/python scripts/reddit_healer_debug.py open-profile --profile-name "Chrome Reddit Bot Debug Profile - account2" --port 9223 --url "https://www.reddit.com/login/"
```

Ping the Healer bridge:

```bash
cd /Users/raulvecchione/MEGA/rvScripts/reddit-bot
.venv/bin/python scripts/reddit_healer_debug.py ping-bridge --debug-address 127.0.0.1:9222
```

Find a control:

```bash
cd /Users/raulvecchione/MEGA/rvScripts/reddit-bot
.venv/bin/python scripts/reddit_healer_debug.py find-control --debug-address 127.0.0.1:9222 --intent upvote --url "<POST_URL>"
```

Run the bot through the attached profile:

```bash
cd /Users/raulvecchione/MEGA/rvScripts/reddit-bot
.venv/bin/python main.py -a accounts.txt -l links.txt --verbose --use-existing-chrome --chrome-debugging-address 127.0.0.1:9222 --chrome-extension-healer
```

Print profile metadata:

```bash
cd /Users/raulvecchione/MEGA/rvScripts/reddit-bot
.venv/bin/python scripts/reddit_healer_debug.py profile-info --profile-name "Chrome Reddit Bot Debug Profile" --port 9222
```

## References

- `AGENT.md`
- `docs/chrome-debug-profiles.md`
- `references/troubleshooting.md`

