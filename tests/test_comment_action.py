"""Tests for comment action."""

import pytest
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By

from bot.actions.comment import CommentAction
from bot.config import BotConfig


LINK = "https://www.reddit.com/r/test/comments/abc/slug/"


def _comment_action(mocker):
    driver = mocker.Mock()
    action = CommentAction(driver, BotConfig(), mocker.Mock())
    action._navigate = mocker.Mock()
    action._handle_nsfw = mocker.Mock()
    action._click = mocker.Mock()
    action._type_like_human = mocker.Mock()
    mocker.patch("bot.actions.comment.Timeouts.med")
    mocker.patch("bot.actions.comment.Timeouts.srt")
    return action, driver


def test_comment_action_returns_failure_when_text_missing(mocker):
    action, _ = _comment_action(mocker)

    result = action.execute(link=LINK, text="")

    assert result.success is False
    assert result.action == "comment"
    assert result.link == LINK
    assert "No comment text provided" in result.message
    action._navigate.assert_not_called()


def test_comment_action_happy_path_posts_comment(mocker):
    action, driver = _comment_action(mocker)
    body = mocker.Mock()
    textbox = mocker.Mock()
    submit = mocker.Mock()
    driver.find_element.return_value = body
    action._find_with_fallbacks = mocker.Mock(side_effect=[textbox, submit])

    result = action.execute(link=LINK, text="Hello from unit tests")

    assert result.success is True
    assert result.action == "comment"
    assert result.link == LINK
    assert result.message == "Comment posted"
    action._navigate.assert_called_once_with(LINK)
    action._handle_nsfw.assert_called_once_with()
    driver.find_element.assert_called_once_with(By.TAG_NAME, "body")
    body.send_keys.assert_called_once()
    action._click.assert_any_call(textbox)
    action._type_like_human.assert_called_once_with(textbox, "Hello from unit tests")
    action._click.assert_any_call(submit)
    assert action._find_with_fallbacks.call_count == 2


def test_comment_action_dry_run_skips_browser(mocker):
    action, driver = _comment_action(mocker)
    action.config.dry_run = True

    result = action.execute(link=LINK, text="Would comment this")

    assert result.success is True
    assert result.action == "comment"
    assert "Dry run" in result.message
    action._navigate.assert_not_called()
    driver.find_element.assert_not_called()


def test_comment_action_propagates_missing_textbox(mocker):
    action, driver = _comment_action(mocker)
    body = mocker.Mock()
    driver.find_element.return_value = body
    action._find_with_fallbacks = mocker.Mock(
        side_effect=NoSuchElementException("no textbox")
    )

    with pytest.raises(NoSuchElementException):
        action.execute(link=LINK, text="hello")

    action._navigate.assert_called_once_with(LINK)
    action._type_like_human.assert_not_called()


def test_comment_action_propagates_navigate_error(mocker):
    action, _ = _comment_action(mocker)
    action._navigate = mocker.Mock(side_effect=WebDriverException("nav failed"))

    with pytest.raises(WebDriverException):
        action.execute(link=LINK, text="hello")
