# Troubleshooting

## DevTools Port

Probe the active Chrome debugger:

```bash
curl -s http://127.0.0.1:9222/json/version
```

If sandboxed access fails but Chrome is open, retry the same command with escalation. If it still fails, reopen the saved profile:

```bash
cd /Users/raulvecchione/MEGA/rvScripts/reddit-bot
.venv/bin/python scripts/reddit_healer_debug.py open-profile
```

For another profile, use its port:

```bash
cd /Users/raulvecchione/MEGA/rvScripts/reddit-bot
.venv/bin/python scripts/reddit_healer_debug.py open-profile --profile-name "Chrome Reddit Bot Debug Profile - account2" --port 9223
```

## Extension Bridge Timeout

If `ping-bridge` returns `Chrome extension bridge timed out`, the extension content script is not responding in the attached profile.

Open `chrome://extensions` in that Chrome profile, enable Developer mode, and confirm `Reddit Bot Healer` is installed and enabled. If needed, Load unpacked from:

```text
/Users/raulvecchione/MEGA/rvScripts/reddit-bot/chrome_extension/reddit_healer
```

Reload `https://www.reddit.com/` after loading the extension.

## ChromeDriver Mismatch

If Selenium says ChromeDriver only supports an older Chrome version, avoid `/usr/local/bin/chromedriver`. Use the helper script or `ChromeDriverManager().install()`.

## Safe Action Flow

For a vote request, use `find-control` first and report:

- intent
- confidence
- selector
- bounding box
- state
- evidence

Click only when the user explicitly asked for a real action or confirms after seeing the candidate.

