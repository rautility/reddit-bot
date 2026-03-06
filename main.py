"""Reddit bot entry point — orchestrates accounts, actions, and reporting."""

from __future__ import annotations

import logging
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from tqdm import tqdm

from args import cmdline_args
from bot import RedditBot, BotConfig, GhostLogger
from bot.reporting import ExecutionSummary, send_webhook, setup_structured_logger
from bot.utils.credentials import read_accounts, read_accounts_from_env, Account
from bot.utils.input_parser import parse_links_file, ActionEntry
from bot.utils.timeouts import Timeouts


def load_config(args: dict) -> BotConfig:
    """Build BotConfig from config file, env vars, and CLI args (in that priority order)."""
    config = BotConfig()

    if args.get("config"):
        config = BotConfig.from_yaml(args["config"])

    config.merge_env_vars()
    config.merge_cli_args(args)

    return config


def load_accounts(config: BotConfig) -> list[Account]:
    """Load accounts from file or environment variables."""
    # Try environment variables first
    env_accounts = read_accounts_from_env()
    if env_accounts:
        return env_accounts

    if not config.accounts_path:
        return []

    return read_accounts(
        config.accounts_path,
        encrypted=config.encrypt_credentials,
        passphrase=os.environ.get(config.credentials_key_env),
    )


def run_account(
    account: Account,
    entries: list[ActionEntry],
    config: BotConfig,
    logger: logging.Logger,
) -> ExecutionSummary:
    """Run all actions for a single account. Used for both sequential and parallel execution."""
    with RedditBot(config=config) as bot:
        # Try session restore first
        if not bot.login_with_session(account.username):
            try:
                bot.login(account.username, account.password)
            except RuntimeError:
                logger.error(f"Login failed for {account.username}")
                return bot.summary

        # Execute actions
        action_list = list(entries)
        if config.randomize_actions:
            random.shuffle(action_list)

        for entry in action_list:
            kwargs = {"link": entry.link}
            if entry.comment:
                kwargs["comment"] = entry.comment
            if entry.title:
                kwargs["title"] = entry.title
            if entry.subreddit:
                kwargs["subreddit"] = entry.subreddit
            if entry.body:
                kwargs["body"] = entry.body
            if entry.flair:
                kwargs["flair"] = entry.flair
            if entry.recipient:
                kwargs["recipient"] = entry.recipient
            if entry.message:
                kwargs["message"] = entry.message

            result = bot.perform_action(entry.action, **kwargs)
            if config.verbose:
                logger.info(str(result))

        return bot.summary


def run_scheduled(config: BotConfig, accounts: list[Account], entries: list[ActionEntry], logger) -> None:
    """Run the bot on a cron schedule."""
    import sched
    import re

    def parse_simple_interval(cron_expr: str) -> int:
        """Parse a simple cron-like interval. Supports '*/N' in hours position."""
        match = re.search(r'\*/(\d+)', cron_expr)
        if match:
            hours = int(match.group(1))
            return hours * 3600
        # Default to 6 hours
        return 6 * 3600

    interval = parse_simple_interval(config.schedule_cron)
    logger.info(f"Scheduled mode: running every {interval // 3600} hours")

    scheduler = sched.scheduler(time.time, time.sleep)

    def scheduled_run():
        logger.info("Starting scheduled run...")
        _execute_run(config, accounts, entries, logger)
        scheduler.enter(interval, 1, scheduled_run)

    scheduler.enter(0, 1, scheduled_run)
    scheduler.run()


def _execute_run(
    config: BotConfig,
    accounts: list[Account],
    entries: list[ActionEntry],
    logger,
) -> ExecutionSummary:
    """Execute the full run (all accounts, all actions)."""
    combined_summary = ExecutionSummary()

    if config.parallel_accounts > 1:
        # Parallel execution
        logger.info(f"Running {len(accounts)} accounts in parallel (max {config.parallel_accounts} workers)")
        with ThreadPoolExecutor(max_workers=config.parallel_accounts) as executor:
            futures = {
                executor.submit(run_account, acc, entries, config, logger): acc
                for acc in accounts
            }
            for future in tqdm(as_completed(futures), total=len(futures), desc="Accounts", disable=not config.verbose):
                account = futures[future]
                try:
                    summary = future.result()
                    for r in summary.results:
                        combined_summary.add(r)
                except Exception as e:
                    logger.error(f"Account {account.username} failed: {e}")
    else:
        # Sequential execution
        for acc in tqdm(accounts, desc="Accounts", disable=not config.verbose):
            summary = run_account(acc, entries, config, logger)
            for r in summary.results:
                combined_summary.add(r)

            # Staggered delay between accounts
            if acc != accounts[-1]:
                Timeouts.custom(
                    config.rate_limit.min_account_delay,
                    config.rate_limit.max_account_delay,
                )

    combined_summary.finalize()
    return combined_summary


def main() -> None:
    args = cmdline_args()
    config = load_config(args)

    # Logger
    logger = GhostLogger()
    if config.verbose:
        logger = setup_structured_logger("reddit-bot", level=logging.INFO)

    # Load accounts
    accounts = load_accounts(config)
    if not accounts:
        logger.error("No accounts provided. Use -a/--accounts or REDDIT_ACCOUNT_N env vars.")
        sys.exit(1)

    # Load actions
    if not config.links_path:
        logger.error("No links file provided. Use -l/--links.")
        sys.exit(1)

    entries = parse_links_file(config.links_path)
    if not entries:
        logger.error("No actions found in links file.")
        sys.exit(1)

    logger.info(f"Loaded {len(accounts)} accounts and {len(entries)} actions")

    if config.dry_run:
        logger.info("DRY RUN MODE — no actions will be executed")

    # Scheduled or one-shot
    if config.schedule_cron:
        run_scheduled(config, accounts, entries, logger)
    else:
        summary = _execute_run(config, accounts, entries, logger)

        # Print summary
        if config.verbose:
            print(summary.print_table())

        # Webhook notification
        if config.webhook.enabled and config.webhook.url:
            success = send_webhook(
                config.webhook.url,
                summary,
                on_completion=config.webhook.on_completion,
                on_failure=config.webhook.on_failure,
            )
            if success:
                logger.info("Webhook notification sent")
            else:
                logger.warning("Webhook notification failed")

        # Exit with error code if any actions failed
        if summary.failed > 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
