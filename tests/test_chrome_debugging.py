"""Tests for attaching to an existing Chrome debugger."""

from urllib.error import URLError

import pytest

from bot.bot import RedditBot
from bot.config import BotConfig


def test_constructor_closes_database_when_driver_init_fails(mocker):
    database = mocker.Mock()
    mocker.patch("bot.bot.BotDatabase", return_value=database)
    mocker.patch.object(RedditBot, "_init_driver", side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        RedditBot()

    database.close.assert_called_once()


def test_chrome_debugger_probe_normalizes_http_address(mocker):
    response = mocker.MagicMock()
    response.status = 200
    response.read.return_value = b"{}"
    response.__enter__.return_value = response
    urlopen = mocker.patch("bot.bot.urlopen", return_value=response)

    address = RedditBot._ensure_chrome_debugger_reachable("http://127.0.0.1:9222")

    assert address == "127.0.0.1:9222"
    urlopen.assert_called_once_with(
        "http://127.0.0.1:9222/json/version",
        timeout=2.0,
    )
    response.read.assert_called_once_with(256)


def test_chrome_debugger_probe_raises_actionable_error(mocker):
    mocker.patch("bot.bot.urlopen", side_effect=URLError("connection refused"))

    with pytest.raises(RuntimeError) as exc_info:
        RedditBot._ensure_chrome_debugger_reachable("127.0.0.1:9222")

    message = str(exc_info.value)
    assert "Chrome debugger is not reachable at 127.0.0.1:9222" in message
    assert "--remote-debugging-port=9222" in message
    assert "--user-data-dir=/tmp/reddit-bot-chrome-debug" in message


def test_reddit_authenticated_username_requires_api_username(mocker):
    bot = RedditBot.__new__(RedditBot)
    bot.logger = mocker.Mock()
    bot.dv = mocker.Mock()
    bot.dv.current_url = "https://www.reddit.com/"
    bot.dv.execute_async_script.return_value = {
        "ok": True,
        "status": 200,
        "name": "reddit_user",
    }

    assert bot._reddit_authenticated_username() == "reddit_user"


def test_existing_chrome_login_rejects_anonymous_reddit_homepage(mocker):
    bot = RedditBot.__new__(RedditBot)
    bot.config = BotConfig()
    bot.logger = mocker.Mock()
    bot.dv = mocker.Mock()
    bot.dv.current_url = "https://www.reddit.com/"
    bot.dv.execute_async_script.return_value = {
        "ok": False,
        "status": 401,
        "name": None,
    }
    bot.dv.get_cookies.return_value = []
    bot._popup_handler = mocker.Mock()
    bot._cookies_handler = mocker.Mock()

    assert bot.login_with_existing_chrome("expected_user") is False
    bot._popup_handler.assert_not_called()
    bot._cookies_handler.assert_not_called()


def test_reddit_authenticated_username_accepts_session_cookie(mocker):
    bot = RedditBot.__new__(RedditBot)
    bot.logger = mocker.Mock()
    bot.dv = mocker.Mock()
    bot.dv.execute_async_script.return_value = {
        "ok": False,
        "status": 401,
        "name": None,
    }
    bot.dv.get_cookies.return_value = [{"name": "reddit_session"}]

    assert bot._reddit_authenticated_username() == "Reddit session cookie (reddit_session)"


def test_wait_for_reddit_authentication_polls_until_username(mocker):
    bot = RedditBot.__new__(RedditBot)
    bot.dv = mocker.Mock()
    bot.logger = mocker.Mock()
    bot._reddit_authenticated_username = mocker.Mock(side_effect=[None, "reddit_user"])
    mocker.patch("bot.bot.Timeouts.srt")
    sleep = mocker.patch("bot.bot.time.sleep")

    assert bot._wait_for_reddit_authentication("expected_user") == "reddit_user"
    bot.dv.get.assert_called_once()
    sleep.assert_called_once_with(2.0)
