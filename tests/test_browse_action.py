"""Tests for non-mutating browsing actions."""

from bot.actions.browse import HumanScrollAction
from bot.config import BotConfig


def test_human_scroll_opens_reddit_url_and_scrolls(mocker):
    driver = mocker.Mock()
    driver.current_url = "https://www.reddit.com/r/test/comments/abc/title/"
    action = HumanScrollAction(driver, BotConfig())
    navigate = mocker.patch.object(action, "_navigate")
    scroll = mocker.patch("bot.utils.mouse.human_reading_scroll", return_value=[{"delta": 320}])

    result = action.execute(link="https://www.reddit.com/r/test/comments/abc/title/")

    assert result.success is True
    assert result.action == "human_scroll"
    assert result.link == driver.current_url
    assert result.details["scrollMovements"] == [{"delta": 320}]
    navigate.assert_called_once_with("https://www.reddit.com/r/test/comments/abc/title/")
    scroll.assert_called_once_with(driver)


def test_human_scroll_rejects_non_reddit_url(mocker):
    action = HumanScrollAction(mocker.Mock(), BotConfig())

    result = action.execute(link="https://example.com/")

    assert result.success is False
    assert "reddit.com" in result.message
