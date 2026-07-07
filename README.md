<div align="center">

# Reddit Bot

### A feature-rich Reddit automation bot using Selenium

![Python Versions](https://img.shields.io/badge/python-3.10%20%7C%203.12-blue)
![License](https://img.shields.io/badge/license-MIT-brightgreen)

</div>

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Saved Chrome Debug Profiles](#saved-chrome-debug-profiles)
- [Configuration](#configuration)
- [Input Formats](#input-formats)
- [Supported Actions](#supported-actions)
- [Anti-Detection](#anti-detection)
- [Orchestration](#orchestration)
- [Agentic Operation](#agentic-operation)
- [Credentials & Security](#credentials--security)
- [Reporting & Notifications](#reporting--notifications)
- [Database Tracking](#database-tracking)
- [Docker](#docker)
- [CLI Reference](#cli-reference)
- [Testing](#testing)
- [Architecture](#architecture)
- [Contributing](#contributing)

---

## Features

### Core Actions
- **Upvote / Downvote** posts
- **Comment** under posts
- **Join / Leave** communities
- **Save / Hide** posts
- **Direct Message** users
- **Post Submission** — text, link, image posts
- **Crosspost** content to other subreddits
- **Follow / Unfollow** users
- **Update Profile** bio

### Reliability & Error Handling
- **Retry logic with exponential backoff** — failed actions automatically retry up to 3 times with increasing delays (2s, 4s, 8s)
- **Action verification** — checks DOM state after actions to confirm success (e.g., `aria-pressed` on vote buttons)
- **Screenshot on failure** — captures a browser screenshot when an action fails, saved to `screenshots/` directory
- **Graceful degradation** — if one action or account fails, the bot continues with the remaining work

### Anti-Detection
- **Proxy support** — load a list of proxies and rotate them per account session
- **User-Agent rotation** — randomize the browser fingerprint with realistic Chrome UA strings
- **Headless mode** — run without a visible browser window (`--headless`)
- **Rate limiting** — configurable random delays between actions and between accounts
- **Randomized action ordering** — shuffle the action list per account so each executes a unique sequence
- **Human-like mouse movement** — move the cursor along Bezier curves before clicking elements
- **Anti-automation flags** — disables `navigator.webdriver` and Chrome automation indicators

### Input & Configuration
- **YAML config file** — store all settings in a `config.yaml` instead of CLI flags
- **Multiple input formats** — pipe-delimited (`|`), CSV, and JSON for both accounts and action files
- **Environment variable credentials** — read accounts from `REDDIT_ACCOUNT_1`, `REDDIT_ACCOUNT_2`, etc.
- **Credential encryption** — encrypt account files at rest with a passphrase, decrypt at runtime
- **URL validation** — validates that links are actual Reddit URLs before attempting actions

### Orchestration
- **Scheduled execution** — run on a cron-like schedule (e.g., every 6 hours)
- **Staggered account switching** — configurable random delays between accounts
- **Daily action quotas** — limit the number of actions per account per day
- **Parallel accounts** — run multiple browser instances concurrently
- **Session persistence** — save and restore browser cookies between runs to avoid repeated logins

### Reporting & Observability
- **Structured logging** — JSON log output option for machine parsing, with colored terminal output
- **Execution summary** — ASCII table printed at the end showing success/failure per action
- **Progress bar** — visual progress indicator via `tqdm` for long runs
- **Webhook notifications** — send results to Discord, Slack, or any generic JSON webhook on completion or failure

### Database Tracking
- **SQLite action log** — every action is logged with timestamp, account, result, and optional screenshot path
- **Duplicate prevention** — skips actions already successfully performed by the same account
- **Daily stats** — tracks action counts per account per day for quota enforcement
- **Summary queries** — query aggregated success/failure stats from the database

### Developer Experience
- **Unit tests** — comprehensive test suite for config, parsing, validation, database, proxy, and reporting
- **Docker support** — `Dockerfile` with Chrome pre-installed for portable execution
- **CI pipeline** — GitHub Actions workflow for automated testing on supported Python versions
- **Plugin architecture** — actions are modular classes; add new actions without modifying core bot logic
- **Installable package** — `pyproject.toml` for `pip install .` support

---

## Installation

### Standard Installation

```bash
git clone https://github.com/markmelnic/Reddit-Bot
cd Reddit-Bot
pip install -e .
```

### Development Installation

```bash
pip install -e ".[dev]"
```

### Preferred Local Workflow With uv

```bash
uv sync --extra dev
uv run pytest -q
```

### Docker Installation

```bash
docker build -t reddit-bot .
```

> **Note:** Chrome and chromedriver are automatically managed by `webdriver-manager` — no manual download required.

### Local Web UI

```bash
make ui
```

The dashboard binds to `127.0.0.1:8765` by default and uses the same
`agentctl`/`reddit-tool` control plane as the terminal workflow.

---

## Quick Start

### Minimal Example

```bash
python main.py --accounts accounts.txt --links links.txt --verbose
```

### With Config File

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your settings
python main.py --config config.yaml
```

### Dry Run (Preview Without Executing)

```bash
python main.py -a accounts.txt -l links.txt --dry-run --verbose
```

---

## Saved Chrome Debug Profiles

The preferred local workflow is to use manually authenticated Chrome profiles and attach through Chrome DevTools. This avoids scripted Reddit login and lets the Reddit Bot Healer extension identify controls before actions are clicked.

Default saved profile:

| Name | Path | DevTools |
|------|------|----------|
| `Chrome Reddit Bot Debug Profile` | `/Users/raulvecchione/Library/Application Support/Chrome Reddit Bot Debug Profile` | `127.0.0.1:9222` |

Open the default profile:

```bash
.venv/bin/python scripts/reddit_healer_debug.py open-profile
```

Open a saved profile for another Reddit account on a different port:

```bash
.venv/bin/python scripts/reddit_healer_debug.py open-profile \
  --profile-name "Chrome Reddit Bot Debug Profile - account2" \
  --port 9223 \
  --url "https://www.reddit.com/login/"
```

Log in manually in that Chrome window. Do not automate Reddit login for this workflow. The helper passes `--load-extension=chrome_extension/reddit_healer`; if Chrome does not show `Reddit Bot Healer` under `chrome://extensions`, enable Developer mode and load that unpacked extension manually.

Check the extension bridge:

```bash
.venv/bin/python scripts/reddit_healer_debug.py ping-bridge \
  --debug-address 127.0.0.1:9223
```

Find a control candidate before clicking:

```bash
.venv/bin/python scripts/reddit_healer_debug.py find-control \
  --debug-address 127.0.0.1:9223 \
  --intent downvote \
  --url "https://www.reddit.com/r/example/comments/abc/title/"
```

The expected action report includes candidate confidence, bounding box, state, and evidence. Click only when the command or user request explicitly calls for a real action.

Run the bot through an attached profile:

```bash
.venv/bin/python main.py -a accounts.txt -l links.txt --verbose \
  --use-existing-chrome \
  --chrome-debugging-address 127.0.0.1:9223 \
  --chrome-extension-healer
```

For attach mode, `accounts.txt` is only used as the account label. The active Reddit account is whatever is manually logged in inside the Chrome profile attached to that port. Run one saved profile/port at a time.

Print reusable setup details for any profile:

```bash
.venv/bin/python scripts/reddit_healer_debug.py profile-info \
  --profile-name "Chrome Reddit Bot Debug Profile - account2" \
  --port 9223
```

---

## Configuration

Settings can be provided via YAML config file, CLI flags, or environment variables. Priority order (highest to lowest):

1. **CLI arguments** — override everything
2. **Environment variables** — override config file
3. **YAML config file** — base configuration

### Example `config.yaml`

```yaml
accounts_path: "accounts.txt"
links_path: "links.txt"

verbose: true
headless: false
dry_run: false

rotate_user_agent: true
randomize_actions: true
human_mouse: false

proxy:
  enabled: true
  proxy_list_path: "proxies.txt"
  rotate_per_account: true

rate_limit:
  min_action_delay: 2.0
  max_action_delay: 8.0
  min_account_delay: 5.0
  max_account_delay: 15.0
  daily_action_quota: 50

parallel_accounts: 1
session_persistence: true

screenshot_on_failure: true
db_path: "reddit_bot.db"

webhook:
  enabled: true
  url: "https://discord.com/api/webhooks/..."
  on_completion: true
  on_failure: true
```

See [`config.example.yaml`](config.example.yaml) for the full template with comments.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `REDDIT_ACCOUNT_1` | Account credentials as `username\|password` |
| `REDDIT_ACCOUNT_2` | Second account, and so on |
| `REDDIT_BOT_KEY` | Passphrase for encrypted credential files |
| `REDDIT_BOT_ACCOUNTS` | Path to accounts file |
| `REDDIT_BOT_LINKS` | Path to links file |
| `REDDIT_BOT_HEADLESS` | Enable headless mode (`true`/`false`) |
| `REDDIT_BOT_DRY_RUN` | Enable dry run (`true`/`false`) |
| `REDDIT_BOT_DB_PATH` | Path to SQLite database |
| `REDDIT_BOT_LOG_DIR` | Directory for durable JSONL logs |
| `REDDIT_BOT_LOG_FILE` | File name for durable bot logs |
| `REDDIT_BOT_WEBHOOK_URL` | Webhook URL for notifications |
| `REDDIT_BOT_USE_EXISTING_CHROME` | Use already-authenticated Chrome profile/instance (`true`/`false`) |
| `REDDIT_BOT_CHROME_USER_DATA_DIR` | Path to Chrome user data directory |
| `REDDIT_BOT_CHROME_PROFILE_NAME` | Chrome profile folder name (e.g. `Default`) |
| `REDDIT_BOT_CHROME_DEBUGGING_ADDRESS` | Existing Chrome debugger address (e.g. `127.0.0.1:9222`) |
| `REDDIT_BOT_SELECTOR_CACHE_PATH` | Path for healed Reddit selector cache |
| `REDDIT_BOT_SELECTOR_DIAGNOSTICS_DIR` | Directory for selector diagnostics when healing fails |
| `REDDIT_BOT_SELECTOR_FALLBACK_WAIT` | Short wait for legacy selector fallbacks |
| `REDDIT_BOT_SELENIUM_IMPLICIT_WAIT` | Default Selenium implicit wait |
| `REDDIT_BOT_CHROME_EXTENSION_HEALER_ENABLED` | Enable the Reddit healer Chrome extension bridge |
| `REDDIT_BOT_CHROME_EXTENSION_PATH` | Path to the unpacked healer extension |
| `REDDIT_BOT_CHROME_EXTENSION_BRIDGE_TIMEOUT_MS` | Timeout for extension bridge requests |
| `REDDIT_BOT_CHROME_EXTENSION_MIN_CONFIDENCE` | Minimum control confidence required before clicking |

---

## Input Formats

Both accounts and actions files support three formats:

### Accounts

**Pipe-delimited** (default):
```
username1|password1
username2|password2
```

**CSV:**
```csv
username,password
username1,password1
username2,password2
```

**JSON:**
```json
[
  {"username": "username1", "password": "password1"},
  {"username": "username2", "password": "password2"}
]
```

### Actions / Links

**Pipe-delimited** (default):
```
https://www.reddit.com/r/ProgrammerHumor/comments/abc123/title|upvote
https://www.reddit.com/r/ProgrammerHumor/comments/xyz789/title|comment|Great post!
https://www.reddit.com/r/ProgrammerHumor/|join
https://www.reddit.com/r/ProgrammerHumor/comments/abc123/title|save
https://www.reddit.com/user/someone|follow
```

**CSV:**
```csv
link,action,comment,title,subreddit,body,recipient,message
https://reddit.com/r/test/comments/abc,upvote,,,,,,
https://reddit.com/r/test/comments/abc,comment,Hello!,,,,,
https://reddit.com/r/test,join,,,,,,
,dm,,,,,targetuser,Hello from the bot!
,post_text,,,My Post Title,ProgrammerHumor,Post body text,,
```

**JSON:**
```json
[
  {"link": "https://reddit.com/r/test/comments/abc", "action": "upvote"},
  {"link": "https://reddit.com/r/test/comments/abc", "action": "comment", "comment": "Hello!"},
  {"action": "dm", "recipient": "targetuser", "title": "Subject", "message": "Hello!"},
  {"action": "post_text", "subreddit": "ProgrammerHumor", "title": "My Post", "body": "Content here"}
]
```

---

## Supported Actions

| Action | Description | Required Fields |
|--------|-------------|-----------------|
| `upvote` | Upvote a post | `link` |
| `downvote` | Downvote a post | `link` |
| `comment` | Post a comment | `link`, `comment` |
| `join` | Join a subreddit | `link` |
| `leave` | Leave a subreddit | `link` |
| `save` | Save a post | `link` |
| `hide` | Hide a post | `link` |
| `dm` | Send a direct message | `recipient`, `message` (optional: `title`) |
| `post_text` | Create a text post | `subreddit`, `title` (optional: `body`, `flair`) |
| `post_link` | Create a link post | `subreddit`, `title`, `body` (the URL) |
| `post_image` | Create an image post | `subreddit`, `title`, `body` (image file path) |
| `crosspost` | Crosspost to another sub | `link`, `subreddit` (optional: `title`) |
| `follow` | Follow a user | `link` (user profile URL) |
| `unfollow` | Unfollow a user | `link` (user profile URL) |
| `update_bio` | Update profile bio | `body` (bio text) |

---

## Anti-Detection

### Proxy Rotation

Create a `proxies.txt` file:
```
host1:port1
host2:port2
host3:port3:username:password
```

```bash
python main.py -a accounts.txt -l links.txt --proxy-list proxies.txt
```

Proxies rotate round-robin for each new account session.

### User-Agent Rotation

```bash
python main.py -a accounts.txt -l links.txt --rotate-ua
```

Each browser session starts with a random Chrome user agent from a pool of realistic UA strings.

### Human-Like Mouse Movement

```bash
python main.py -a accounts.txt -l links.txt --human-mouse
```

Uses Bezier curves to generate natural cursor paths before clicking elements. Requires the `bezier` and `numpy` packages.

### Headless Mode

```bash
python main.py -a accounts.txt -l links.txt --headless
```

Runs Chrome without a visible window. Useful for servers and Docker.

### Action Randomization

```bash
python main.py -a accounts.txt -l links.txt --randomize-actions
```

Shuffles the action list for each account so they don't all perform the same sequence.

---

## Orchestration

### Agentic Operation

LLM agents should start with the agent runbook:

```bash
cat AGENTS.md
.venv/bin/python scripts/agentctl.py status
```

For live Reddit mutations, agents should submit actions to the shared queue
instead of running `main.py` directly:

```bash
.venv/bin/python scripts/agentctl.py profiles associate \
  --profile-name "Chrome Reddit Bot Debug Profile" \
  --reddit-user "u/Particular-Arm2102"

.venv/bin/python scripts/agentctl.py queue submit \
  --reddit-user "u/Particular-Arm2102" \
  --links links.txt

.venv/bin/python scripts/agentctl.py --config config.yaml queue worker --once
```

Agents can also queue by Chrome profile with `--profile-name "Chrome Reddit Bot Debug Profile"`.
The queue uses SQLite leases and atomic daily quota reservations to coordinate
parallel agents. See `docs/agentic-operations.md` and
`docs/scheduler-and-rate-limits.md`.

### Human-Friendly Operations CLI

Use `scripts/reddit_tool.py` for day-to-day inspection and simple scheduling. It
is a thin `argparse` wrapper around `agentctl`, so live work still goes through
the project queue, schedule registry, executor, leases, and quotas.

Open the interactive terminal menu:

```bash
.venv/bin/python scripts/reddit_tool.py menu
```

The menu covers overview, capabilities, schedules, queue, job lookup, executor
status, recent errors, profiles, limits, adding schedules, queue submission, and
running due schedules.

Direct commands are still available when you know what you want:

```bash
.venv/bin/python scripts/reddit_tool.py overview
.venv/bin/python scripts/reddit_tool.py schedules
.venv/bin/python scripts/reddit_tool.py queue --status failed
.venv/bin/python scripts/reddit_tool.py executor
.venv/bin/python scripts/reddit_tool.py errors
```

Add a one-time scheduled action by writing the action file automatically:

```bash
.venv/bin/python scripts/reddit_tool.py schedule add \
  --name "Upvote example post" \
  --link "https://www.reddit.com/r/example/comments/abc/title/" \
  --action upvote \
  --at "2026-07-06T09:00:00"
```

Register a recurring schedule from an existing links/action file:

```bash
.venv/bin/python scripts/reddit_tool.py schedule add \
  --name "Weekday Reddit actions" \
  --links links.txt \
  --weekly MO,WE,FR \
  --time 09:30
```

Submit immediate queue work without running it yet:

```bash
.venv/bin/python scripts/reddit_tool.py queue add --links links.txt
```

Run due project schedules and exactly one worker pass:

```bash
.venv/bin/python scripts/reddit_tool.py schedule run-due --run-worker
```

After editable install, the same CLI is available as `reddit-tool`.

### Parallel Execution

Run multiple accounts simultaneously:

```bash
python main.py -a accounts.txt -l links.txt --parallel 3
```

### Scheduled Execution

Run on a schedule (simple interval-based):

```bash
python main.py -a accounts.txt -l links.txt --schedule "0 */6 * * *"
```

The bot will run every 6 hours and repeat indefinitely.

### Session Persistence

Save cookies between runs to avoid re-logging in:

```bash
python main.py -a accounts.txt -l links.txt --session-persistence
```

Sessions are stored in `.sessions/` as JSON cookie files.

### Use your already logged-in Chrome

If you want to avoid credentials entirely, use the saved debug profile workflow above and attach to its DevTools address:

```bash
.venv/bin/python scripts/reddit_healer_debug.py open-profile \
  --profile-name "Chrome Reddit Bot Debug Profile" \
  --port 9222
```

Then run:

```bash
.venv/bin/python main.py -a accounts.txt -l links.txt \
  --use-existing-chrome \
  --chrome-debugging-address 127.0.0.1:9222 \
  --chrome-extension-healer
```

You can still point directly to a Chrome user-data directory when you are not attaching to an already running debugger:

```bash
python main.py -a accounts.txt -l links.txt \
  --use-existing-chrome \
  --chrome-user-data-dir "/Users/<you>/Library/Application Support/Chrome Reddit Bot Debug Profile"
```

Attach mode is safer for this project because it keeps login manual, exposes `127.0.0.1:<port>` for inspection, and works with the Healer extension already loaded in that profile.

### Saved profile per account

Use one Chrome user-data-dir and one port per Reddit account. Example:

```bash
.venv/bin/python scripts/reddit_healer_debug.py open-profile \
  --profile-name "Chrome Reddit Bot Debug Profile - account3" \
  --port 9224 \
  --url "https://www.reddit.com/login/"
```

After manual login, target that profile with `--chrome-debugging-address 127.0.0.1:9224`.

### Daily Quotas

Set in config:

```yaml
rate_limit:
  daily_action_quota: 50
```

Once an account reaches 50 actions in a day, remaining actions are skipped.

---

## Credentials & Security

### Encrypt Credentials

First, encrypt your accounts file:

```python
from bot.utils.credentials import encrypt_file
encrypt_file("accounts.txt", "accounts.bin", "your-secret-passphrase")
```

Then run with the encrypted file:

```bash
export REDDIT_BOT_KEY="your-secret-passphrase"
python main.py -a accounts.bin -l links.txt --encrypt-credentials
```

### Environment Variable Accounts

```bash
export REDDIT_ACCOUNT_1="username1|password1"
export REDDIT_ACCOUNT_2="username2|password2"
python main.py -l links.txt
```

---

## Reporting & Notifications

### Durable Logs

Every bot run creates durable JSON-line logs at `logs/reddit-bot.log` by default, even when `--verbose` is not enabled. The Chrome debug helper writes command failures to `logs/reddit-healer-debug.log`.

Weekly troubleshooting instructions live in [`docs/weekly-log-maintenance.md`](docs/weekly-log-maintenance.md).

Override the bot log location from config, environment variables, or CLI:

```yaml
log_dir: "logs"
log_file: "reddit-bot.log"
```

```bash
python main.py -a accounts.txt -l links.txt --log-dir logs --log-file reddit-bot.log
```

### Execution Summary

With `--verbose`, a summary table is printed after completion:

```
================================================================================
EXECUTION SUMMARY
================================================================================
Duration: 142.3s | Total: 12 | Success: 10 | Failed: 2
--------------------------------------------------------------------------------
Status   Action          Link                                Message
--------------------------------------------------------------------------------
OK       upvote          https://reddit.com/r/test/comme..   Vote registered
OK       comment         https://reddit.com/r/test/comme..   Comment posted
FAIL     join            https://reddit.com/r/private        Message: NoSuchElem..
OK       follow          https://reddit.com/user/someone     User followed
================================================================================
```

### Webhook Notifications

#### Discord

```yaml
webhook:
  enabled: true
  url: "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN"
```

Sends a rich embed with color-coded success/failure status.

#### Slack

```yaml
webhook:
  enabled: true
  url: "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
```

#### Generic JSON

Any other URL receives the full execution summary as JSON.

### Screenshots on Failure

```bash
python main.py -a accounts.txt -l links.txt --screenshot-on-failure
```

Screenshots are saved to `screenshots/` with descriptive filenames including the action name and timestamp.

### Self-Healing Selectors

Reddit changes UI markup frequently. The bot keeps a local selector cache in `.selector-healing/reddit_selectors.json` and writes compact diagnostics to `.selector-healing/diagnostics/` when an action cannot find a control.

When a normal selector misses, actions can run a browser-side probe that logs a `reddit-bot:self-healing` response in the page console, reads the structured result back through Selenium, and stores the discovered selector for future runs.

### Chrome Extension Healer

The repo includes an unpacked Chrome extension at `chrome_extension/reddit_healer`. When enabled, vote actions ask the extension for a control candidate before falling back to Selenium selectors. The extension observes Reddit from inside Chrome, including dynamic DOM state, open shadow DOM, button attribute changes, clicks, page console logs, and fetch/XHR responses.

Enable it in config:

```yaml
chrome_extension_healer_enabled: true
chrome_extension_path: "chrome_extension/reddit_healer"
chrome_extension_min_confidence: 0.8
```

Or from the CLI:

```bash
python main.py -a accounts.txt -l links.txt --chrome-extension-healer
```

For Chrome launched by the bot, the extension is loaded automatically from `chrome_extension_path`. For `--use-existing-chrome --chrome-debugging-address`, install or load the unpacked extension in that Chrome profile before running the bot.

When operating through saved debug profiles, use the helper first:

```bash
.venv/bin/python scripts/reddit_healer_debug.py ping-bridge --debug-address 127.0.0.1:9222
.venv/bin/python scripts/reddit_healer_debug.py find-control --debug-address 127.0.0.1:9222 --intent upvote --url "<POST_URL>"
```

Report the returned best candidate's confidence, bounding box, state, and evidence before executing the click in manual testing tasks.

---

## Database Tracking

All actions are logged to a SQLite database (`reddit_bot.db` by default):

```sql
-- View all actions
SELECT * FROM action_log ORDER BY timestamp DESC;

-- View failures
SELECT * FROM action_log WHERE success = 0;

-- View daily stats per account
SELECT * FROM account_stats WHERE action_date = date('now');
```

The database prevents duplicate actions — if an account has already successfully upvoted a post, it will be skipped on subsequent runs.

---

## Docker

### Build and Run

```bash
docker build -t reddit-bot .

docker run -v $(pwd)/accounts.txt:/app/accounts.txt \
           -v $(pwd)/links.txt:/app/links.txt \
           reddit-bot -a accounts.txt -l links.txt --verbose
```

### With Config File

```bash
docker run -v $(pwd)/config.yaml:/app/config.yaml \
           -v $(pwd)/accounts.txt:/app/accounts.txt \
           -v $(pwd)/links.txt:/app/links.txt \
           reddit-bot --config config.yaml
```

The Docker image automatically runs in headless mode.

---

## CLI Reference

```
usage: reddit-bot [-h] [-a ACCOUNTS] [-l LINKS] [-c CONFIG] [-v]
                  [--headless] [--dry-run] [--proxy-list PROXY_LIST]
                  [--rotate-ua] [--randomize-actions] [--human-mouse]
                  [--manual-login] [--use-existing-chrome]
                  [--chrome-user-data-dir CHROME_USER_DATA_DIR]
                  [--chrome-profile-name CHROME_PROFILE_NAME]
                  [--chrome-debugging-address CHROME_DEBUGGING_ADDRESS]
                  [--parallel PARALLEL] [--schedule SCHEDULE]
                  [--session-persistence] [--encrypt-credentials]
                  [--screenshot-on-failure] [--webhook-url WEBHOOK_URL]

A feature-rich Reddit automation bot using Selenium.

options:
  -h, --help            Show this help message and exit
  -a, --accounts        Path to accounts file (pipe, CSV, or JSON)
  -l, --links           Path to actions file (pipe, CSV, or JSON)
  -c, --config          Path to YAML configuration file
  -v, --verbose         Enable verbose logging to stdout
  --headless            Run browser in headless mode
  --dry-run             Log actions without executing them
  --proxy-list          Path to proxy list file (host:port per line)
  --rotate-ua           Randomize User-Agent per session
  --randomize-actions   Shuffle action order per account
  --human-mouse         Use Bezier curve mouse movements
  --manual-login        Pause for manual browser login when automatic login fails
  --use-existing-chrome Use an already logged-in Chrome instance instead of automated login
  --chrome-user-data-dir CHROME_USER_DATA_DIR
                        Chrome user-data-dir to reuse profile/session
  --chrome-profile-name CHROME_PROFILE_NAME
                        Chrome profile directory under user-data-dir (default: Default)
  --chrome-debugging-address CHROME_DEBUGGING_ADDRESS
                        Existing Chrome debugger address (e.g. 127.0.0.1:9222)
  --parallel N          Number of parallel browser instances
  --schedule CRON       Cron expression for scheduled runs
  --session-persistence Save/restore browser sessions
  --encrypt-credentials Accounts file is encrypted
  --screenshot-on-failure Capture screenshots on action failure
  --webhook-url URL     Webhook URL for notifications
  --log-dir DIR         Directory for durable bot logs
  --log-file FILE       File name for durable bot logs
```

---

## Testing

Run the test suite:

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v

# Run specific test module
pytest tests/test_config.py -v
pytest tests/test_database.py -v
```

Tests cover:
- Configuration loading, merging, and env var parsing
- Input file parsing (pipe-delimited, CSV, JSON)
- URL validation
- Credential encryption/decryption
- Proxy loading and rotation
- Database action logging and queries
- Execution summary reporting

---

## Architecture

```
reddit-bot/
├── main.py                    # Entry point and orchestration
├── args.py                    # CLI argument parser
├── config.example.yaml        # Example configuration file
├── pyproject.toml             # Package configuration
├── Dockerfile                 # Docker support
├── Makefile                   # Test, skill sync, and UI shortcuts
├── AGENTS.md                  # Agent runbook and live-action policy
├── bot/
│   ├── __init__.py
│   ├── bot.py                 # Core RedditBot class
│   ├── config.py              # BotConfig dataclass with YAML/env support
│   ├── database.py            # SQLite action log, queue, leases, schedules, quotas
│   ├── action_schema.py       # Machine-readable reddit-tool action schema
│   ├── agentctl.py            # Agent-safe control plane CLI
│   ├── tool_cli.py            # Human-friendly reddit-tool CLI and JSON envelope
│   ├── skills_sync.py         # .claude -> .codex skill mirror utility
│   ├── ghost_logger.py        # Legacy no-op logger
│   ├── reporting.py           # Summary, durable structured logging, webhooks
│   ├── actions/               # Plugin-based action system
│   │   ├── base.py            # BaseAction ABC and ActionResult
│   │   ├── registry.py        # Action name -> class mapping
│   │   ├── search.py          # Human search and search_upvote flows
│   │   ├── vote.py            # Upvote/downvote
│   │   ├── comment.py         # Comment on post
│   │   ├── community.py       # Join/leave subreddit
│   │   ├── save_hide.py       # Save/hide post
│   │   ├── post.py            # Text/link/image post, crosspost
│   │   ├── dm.py              # Direct messages
│   │   ├── follow.py          # Follow/unfollow users
│   │   └── profile.py         # Update bio
│   └── utils/                 # Shared utilities
│       ├── chrome_extension_bridge.py # Reddit healer extension bridge
│       ├── chromedriver.py    # ChromeDriver resolution helper
│       ├── clock.py           # UTC timestamp helpers
│       ├── timeouts.py        # Randomized delays
│       ├── retry.py           # Exponential backoff decorator
│       ├── mouse.py           # Bezier curve mouse movement
│       ├── self_healing.py    # Runtime selector healing
│       ├── visible_vote.py    # Visible vote control diagnostics/clicking
│       ├── user_agents.py     # UA string rotation
│       ├── credentials.py     # Account parsing and encryption
│       ├── input_parser.py    # Action file parsing
│       ├── validators.py      # URL validation
│       └── proxy.py           # Proxy loading and rotation
│   └── web/                   # Localhost-only dashboard server
├── chrome_extension/          # Reddit healer Chrome extension
├── docs/                      # Agent operations, scheduling, UI, and maintenance docs
├── scripts/                   # Thin CLI launchers and diagnostics
├── tests/                     # Unit and API test suite
├── web/                       # Zero-build dashboard frontend
└── .github/
    └── workflows/
        └── ci.yml             # GitHub Actions CI pipeline
```

### Adding Custom Actions

Create a new action by extending `BaseAction`:

```python
# bot/actions/my_action.py
from bot.actions.base import BaseAction, ActionResult

class MyCustomAction(BaseAction):
    name = "my_action"

    def execute(self, link="", **kwargs):
        self.logger.info(f"Running my action on {link}")
        if self.config.dry_run:
            return ActionResult(success=True, action="my_action", link=link, message="Dry run")

        # Your Selenium logic here
        self._navigate(link)
        element = self._find_with_fallbacks(
            (By.CSS_SELECTOR, "button.my-button"),
            (By.XPATH, "//button[text()='Click Me']"),
        )
        self._click(element)

        return ActionResult(success=True, action="my_action", link=link, message="Done")
```

Register it in `bot/actions/registry.py`:

```python
from .my_action import MyCustomAction

# In ActionRegistry._action_map:
"my_action": MyCustomAction,
```

---

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/new-action`)
3. Write tests for any new functionality
4. Run the test suite (`pytest tests/ -v`)
5. Commit your changes
6. Push to your branch
7. Open a Pull Request

---

## License

MIT License - see [LICENSE](LICENSE) for details.
