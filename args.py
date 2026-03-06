"""Command-line argument parser with all supported flags."""

from argparse import ArgumentParser


def cmdline_args() -> dict:
    parser = ArgumentParser(
        prog="reddit-bot",
        description="A feature-rich Reddit automation bot using Selenium.",
    )

    # ─── Required inputs ─────────────────────────────────────
    parser.add_argument(
        "-a", "--accounts",
        dest="accounts",
        help="Path to file containing account credentials (pipe-delimited, CSV, or JSON).",
    )
    parser.add_argument(
        "-l", "--links",
        dest="links",
        help="Path to file containing links and actions (pipe-delimited, CSV, or JSON).",
    )

    # ─── Config file ─────────────────────────────────────────
    parser.add_argument(
        "-c", "--config",
        dest="config",
        help="Path to YAML configuration file.",
    )

    # ─── Modes ───────────────────────────────────────────────
    parser.add_argument(
        "-v", "--verbose",
        dest="verbose",
        action="store_true",
        help="Enable verbose logging to stdout.",
    )
    parser.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        help="Run browser in headless mode (no visible window).",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Log actions without executing them.",
    )

    # ─── Anti-detection ──────────────────────────────────────
    parser.add_argument(
        "--proxy-list",
        dest="proxy_list",
        help="Path to file containing proxies (host:port per line).",
    )
    parser.add_argument(
        "--rotate-ua",
        dest="rotate_user_agent",
        action="store_true",
        help="Randomize browser User-Agent per session.",
    )
    parser.add_argument(
        "--randomize-actions",
        dest="randomize_actions",
        action="store_true",
        help="Shuffle action order per account.",
    )
    parser.add_argument(
        "--human-mouse",
        dest="human_mouse",
        action="store_true",
        help="Use human-like Bezier curve mouse movements.",
    )

    # ─── Orchestration ───────────────────────────────────────
    parser.add_argument(
        "--parallel",
        dest="parallel",
        type=int,
        default=None,
        help="Number of parallel browser instances.",
    )
    parser.add_argument(
        "--schedule",
        dest="schedule",
        help="Cron expression for scheduled execution (e.g., '0 */6 * * *').",
    )
    parser.add_argument(
        "--session-persistence",
        dest="session_persistence",
        action="store_true",
        help="Save and restore browser sessions between runs.",
    )

    # ─── Credentials ─────────────────────────────────────────
    parser.add_argument(
        "--encrypt-credentials",
        dest="encrypt_credentials",
        action="store_true",
        help="Accounts file is encrypted (requires REDDIT_BOT_KEY env var).",
    )

    # ─── Reporting ───────────────────────────────────────────
    parser.add_argument(
        "--screenshot-on-failure",
        dest="screenshot_on_failure",
        action="store_true",
        help="Capture screenshots when actions fail.",
    )
    parser.add_argument(
        "--webhook-url",
        dest="webhook_url",
        help="Webhook URL for completion/failure notifications (Discord, Slack, or generic).",
    )

    return vars(parser.parse_args())
