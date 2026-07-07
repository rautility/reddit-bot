#!/usr/bin/env python3
"""Utilities for saved Reddit debug Chrome profiles."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from bot.utils.chrome_extension_bridge import ChromeExtensionBridge
from bot.utils.chromedriver import install_chromedriver
from bot.config import BotConfig
from bot.actions.search import HumanSearchAction
from bot.reporting import setup_structured_logger


REPO_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = REPO_ROOT / "chrome_extension/reddit_healer"
DEFAULT_PROFILE_NAME = "Chrome Reddit Bot Debug Profile"
DEFAULT_PROFILE_DIR = Path.home() / f"Library/Application Support/{DEFAULT_PROFILE_NAME}"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9222
DEFAULT_DEBUG_ADDRESS = f"{DEFAULT_HOST}:{DEFAULT_PORT}"
DEBUG_LOG_FILE = "reddit-healer-debug.log"


def _setup_script_logger() -> logging.Logger:
    return setup_structured_logger(
        "reddit-bot.debug",
        level=logging.INFO,
        log_dir=REPO_ROOT / "logs",
        log_file=DEBUG_LOG_FILE,
        console=False,
        file_level=logging.INFO,
    )


def _profile_dir(args: argparse.Namespace) -> Path:
    if getattr(args, "profile_dir", ""):
        return Path(args.profile_dir).expanduser()
    return Path.home() / f"Library/Application Support/{args.profile_name}"


def _debug_address(args: argparse.Namespace) -> str:
    if getattr(args, "debug_address", ""):
        return args.debug_address
    return f"{args.host}:{args.port}"


def _debug_host_port(args: argparse.Namespace) -> tuple[str, int]:
    address = _debug_address(args)
    if ":" not in address:
        raise ValueError(f"Debug address must be host:port, got {address!r}")
    host, port_text = address.rsplit(":", 1)
    return host, int(port_text)


def _extension_dir(args: argparse.Namespace) -> Path:
    return Path(args.extension_path).expanduser()


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def add_debug_profile_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile-name",
        default=DEFAULT_PROFILE_NAME,
        help=(
            "Saved Chrome profile name. Defaults to "
            f"{DEFAULT_PROFILE_NAME!r}."
        ),
    )
    parser.add_argument(
        "--profile-dir",
        default="",
        help=(
            "Full Chrome user-data-dir path. Overrides --profile-name. "
            "Use this when the saved profile does not live under "
            "~/Library/Application Support/."
        ),
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="DevTools bind host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="DevTools port.")
    parser.add_argument(
        "--debug-address",
        default="",
        help="Existing DevTools address. Overrides --host/--port for attach commands.",
    )
    parser.add_argument(
        "--extension-path",
        default=str(EXTENSION_DIR),
        help="Path to the unpacked Reddit Bot Healer extension.",
    )


def open_profile(args: argparse.Namespace) -> None:
    profile_dir = _profile_dir(args)
    profile_dir.mkdir(parents=True, exist_ok=True)
    host, port = _debug_host_port(args)
    command = [
        "open",
        "-na",
        "Google Chrome",
        "--args",
        f"--remote-debugging-port={port}",
        f"--remote-debugging-address={host}",
        f"--user-data-dir={profile_dir}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if args.load_extension:
        command.append(f"--load-extension={_extension_dir(args)}")
    command.append(args.url)
    subprocess.run(command, check=True)
    print(f"Opened debug Chrome profile name: {args.profile_name}")
    print(f"Profile path: {profile_dir}")
    print(f"DevTools address: {host}:{port}")
    if args.load_extension:
        print(f"Healer extension path: {_extension_dir(args)}")


def attached_driver(args: argparse.Namespace):
    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", _debug_address(args))
    service = Service(install_chromedriver())
    return webdriver.Chrome(service=service, options=options)


def ping_bridge(args: argparse.Namespace) -> None:
    driver = attached_driver(args)
    try:
        response = ChromeExtensionBridge(driver, timeout_ms=5000).request("ping", {})
        print(json.dumps(response, indent=2, sort_keys=True))
    finally:
        driver.quit()


def find_control(args: argparse.Namespace) -> None:
    driver = attached_driver(args)
    try:
        if args.url:
            driver.get(args.url)
        bridge = ChromeExtensionBridge(driver, timeout_ms=5000)
        result = bridge.find_control(
            args.intent,
            post_url=args.url or driver.current_url,
            min_confidence=args.min_confidence,
        )
        payload = result.raw
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        driver.quit()


def human_search(args: argparse.Namespace) -> None:
    driver = attached_driver(args)
    try:
        config = BotConfig(
            verbose=args.verbose,
            human_mouse=True,
            chrome_extension_healer_enabled=True,
            chrome_extension_bridge_timeout_ms=args.timeout_ms,
            chrome_extension_min_confidence=args.min_confidence,
            log_dir=str(REPO_ROOT / "logs"),
        )
        action = HumanSearchAction(driver, config, logging.getLogger("reddit-bot.debug"))
        result = action.execute(query=args.query, subreddit=args.subreddit)
        payload = {
            "success": result.success,
            "action": result.action,
            "link": result.link,
            "message": result.message,
            "currentUrl": driver.current_url,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        driver.quit()


def find_search_result(args: argparse.Namespace) -> None:
    driver = attached_driver(args)
    try:
        if args.url:
            driver.get(args.url)
        bridge = ChromeExtensionBridge(driver, timeout_ms=args.timeout_ms)
        result = bridge.find_search_result(
            args.query,
            min_confidence=args.min_confidence,
            max_results=args.max_results,
        )
        print(json.dumps(result.raw, indent=2, sort_keys=True))
    finally:
        driver.quit()


def print_bot_command(args: argparse.Namespace) -> None:
    links_path = Path(args.links).resolve()
    debug_address = _debug_address(args)
    print(
        " ".join(
            [
                ".venv/bin/python",
                "main.py",
                "-a",
                _quote(args.accounts),
                "-l",
                _quote(str(links_path)),
                "--verbose",
                "--use-existing-chrome",
                "--chrome-debugging-address",
                debug_address,
                "--chrome-extension-healer",
            ]
        )
    )


def profile_info(args: argparse.Namespace) -> None:
    profile_dir = _profile_dir(args)
    debug_address = _debug_address(args)
    open_command = " ".join(
        [
            ".venv/bin/python",
            "scripts/reddit_healer_debug.py",
            "open-profile",
            "--profile-name",
            _quote(args.profile_name),
            "--profile-dir",
            _quote(str(profile_dir)),
            "--debug-address",
            debug_address,
            "--url",
            _quote(args.url),
        ]
    )
    bot_command = " ".join(
        [
            ".venv/bin/python",
            "main.py",
            "-a",
            _quote(args.accounts),
            "-l",
            _quote(args.links),
            "--verbose",
            "--use-existing-chrome",
            "--chrome-debugging-address",
            debug_address,
            "--chrome-extension-healer",
        ]
    )
    payload = {
        "profileName": args.profile_name,
        "profilePath": str(profile_dir),
        "debugAddress": debug_address,
        "healerExtensionPath": str(_extension_dir(args)),
        "openCommand": open_command,
        "botCommand": bot_command,
        "loginRule": "Log in manually in Chrome; do not script Reddit login.",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    open_parser = subparsers.add_parser("open-profile")
    add_debug_profile_args(open_parser)
    open_parser.add_argument("--url", default="https://www.reddit.com/")
    open_parser.add_argument(
        "--no-load-extension",
        dest="load_extension",
        action="store_false",
        default=True,
        help="Do not pass --load-extension when opening Chrome.",
    )
    open_parser.set_defaults(func=open_profile)

    ping_parser = subparsers.add_parser("ping-bridge")
    add_debug_profile_args(ping_parser)
    ping_parser.set_defaults(func=ping_bridge)

    find_parser = subparsers.add_parser("find-control")
    add_debug_profile_args(find_parser)
    find_parser.add_argument("--intent", required=True, choices=["upvote", "downvote"])
    find_parser.add_argument("--url", default="")
    find_parser.add_argument("--min-confidence", type=float, default=0.72)
    find_parser.set_defaults(func=find_control)

    search_find_parser = subparsers.add_parser("find-search-result")
    add_debug_profile_args(search_find_parser)
    search_find_parser.add_argument("--query", required=True)
    search_find_parser.add_argument("--url", default="")
    search_find_parser.add_argument("--min-confidence", type=float, default=0.62)
    search_find_parser.add_argument("--max-results", type=int, default=30)
    search_find_parser.add_argument("--timeout-ms", type=int, default=5000)
    search_find_parser.set_defaults(func=find_search_result)

    human_search_parser = subparsers.add_parser("human-search")
    add_debug_profile_args(human_search_parser)
    human_search_parser.add_argument("--query", required=True)
    human_search_parser.add_argument("--subreddit", default="")
    human_search_parser.add_argument("--min-confidence", type=float, default=0.62)
    human_search_parser.add_argument("--timeout-ms", type=int, default=5000)
    human_search_parser.add_argument("--verbose", action="store_true")
    human_search_parser.set_defaults(func=human_search)

    command_parser = subparsers.add_parser("print-bot-command")
    add_debug_profile_args(command_parser)
    command_parser.add_argument("--accounts", default="accounts.txt")
    command_parser.add_argument("--links", default="links.txt")
    command_parser.set_defaults(func=print_bot_command)

    info_parser = subparsers.add_parser("profile-info")
    add_debug_profile_args(info_parser)
    info_parser.add_argument("--accounts", default="accounts.txt")
    info_parser.add_argument("--links", default="links.txt")
    info_parser.add_argument("--url", default="https://www.reddit.com/login/")
    info_parser.set_defaults(func=profile_info)

    args = parser.parse_args()
    logger = _setup_script_logger()
    logger.info(f"Running reddit_healer_debug command: {args.command}")
    try:
        args.func(args)
    except Exception:
        logger.exception(f"reddit_healer_debug command failed: {args.command}")
        raise


if __name__ == "__main__":
    main()
