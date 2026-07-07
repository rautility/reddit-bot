# Chrome DevTools & Healer Control Discovery

Read this for low-level Reddit UI work: attaching to a Chrome debugger, checking
the Reddit Bot Healer extension bridge, and discovering a UI control before a
click. For normal actions use `reddit-tool do` instead — this is diagnostics.

```bash
cd /Users/raulvecchione/MEGA/rvScripts/reddit-bot
```

## Attach / probe the debugger

```bash
.venv/bin/python scripts/agentctl.py profiles probe --debug-address 127.0.0.1:9222
# or, raw:
curl -s http://127.0.0.1:9222/json/version
```

If a sandboxed probe fails but Chrome is visibly open, retry the same probe with
the approved escalation — local DevTools access is often blocked in the sandbox.
If it still fails, reopen the saved profile:

```bash
.venv/bin/python scripts/reddit_healer_debug.py open-profile
.venv/bin/python scripts/reddit_healer_debug.py open-profile \
  --profile-name "Chrome Reddit Bot Debug Profile - account2" --port 9223
```

## Healer bridge

```bash
.venv/bin/python scripts/reddit_healer_debug.py ping-bridge --debug-address 127.0.0.1:9222
```

If it returns `Chrome extension bridge timed out`, the content script isn't
responding in that profile. Open `chrome://extensions` there, enable Developer
mode, confirm **Reddit Bot Healer** is enabled (Load unpacked from
`chrome_extension/reddit_healer` if missing), then reload `https://www.reddit.com/`.

## Discover a control (report before clicking)

```bash
.venv/bin/python scripts/reddit_healer_debug.py find-control \
  --debug-address 127.0.0.1:9222 --intent upvote --url "<POST_URL>"
```

Report the best candidate's **intent, confidence, selector, bounding box, state,
and evidence**. Click only when Raul explicitly asked for the real action or
confirms after seeing the candidate. Confirm post-click state (e.g.
`aria-pressed="true"` for votes).

## ChromeDriver mismatch

If Selenium reports ChromeDriver supports an older Chrome version, avoid a stale
`/usr/local/bin/chromedriver`; use the helper script or `ChromeDriverManager().install()`.

## Rules

- Never script Reddit login — log in manually in the saved profile.
- One user-data-dir and one DevTools port per account.
- Diagnostics only: this path is not the default scheduler for live actions.
  Route live mutations through `reddit-tool do` / the queue.
