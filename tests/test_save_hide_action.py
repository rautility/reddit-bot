"""Tests for save and hide actions."""

import pytest
from selenium.common.exceptions import WebDriverException

from bot.actions.save_hide import HideAction, SaveAction
from bot.config import BotConfig

LINK = "https://www.reddit.com/r/test/comments/abc/slug/"


def _save_action(mocker):
    driver = mocker.Mock()
    action = SaveAction(driver, BotConfig(), mocker.Mock())
    action._navigate = mocker.Mock()
    action._find_self_healing = mocker.Mock(return_value=None)
    action._click = mocker.Mock()
    mocker.patch("bot.actions.save_hide.Timeouts.med")
    mocker.patch("bot.actions.save_hide.Timeouts.srt")
    return action, driver


def _hide_action(mocker):
    driver = mocker.Mock()
    action = HideAction(driver, BotConfig(), mocker.Mock())
    action._navigate = mocker.Mock()
    action._find_self_healing = mocker.Mock(return_value=None)
    action._click = mocker.Mock()
    mocker.patch("bot.actions.save_hide.Timeouts.med")
    mocker.patch("bot.actions.save_hide.Timeouts.srt")
    return action, driver


def test_save_action_happy_path(mocker):
    action, _ = _save_action(mocker)
    more_button = mocker.Mock()
    save_button = mocker.Mock()
    action._find_self_healing.side_effect = [more_button, save_button]

    result = action.execute(link=LINK)

    assert result.success is True
    assert result.action == "save"
    assert result.link == LINK
    assert result.message == "Post saved"
    action._navigate.assert_called_once_with(LINK)
    assert action._find_self_healing.call_count == 2
    assert action._find_self_healing.call_args_list[0].args[0] == "more_options"
    assert action._find_self_healing.call_args_list[1].args[0] == "save"
    action._click.assert_any_call(more_button)
    action._click.assert_any_call(save_button)


def test_save_action_fails_when_more_options_missing(mocker):
    action, _ = _save_action(mocker)
    action._find_self_healing.return_value = None

    result = action.execute(link=LINK)

    assert result.success is False
    assert result.action == "save"
    assert "Could not find post options menu" in result.message
    action._click.assert_not_called()


def test_save_action_fails_when_save_menu_item_missing(mocker):
    action, _ = _save_action(mocker)
    more_button = mocker.Mock()
    action._find_self_healing.side_effect = [more_button, None]

    result = action.execute(link=LINK)

    assert result.success is False
    assert result.action == "save"
    assert "Could not find Save menu item" in result.message
    action._click.assert_called_once_with(more_button)


def test_save_action_dry_run_skips_browser(mocker):
    action, _ = _save_action(mocker)
    action.config.dry_run = True

    result = action.execute(link=LINK)

    assert result.success is True
    assert result.message == "Dry run"
    action._navigate.assert_not_called()
    action._find_self_healing.assert_not_called()


def test_save_action_propagates_navigate_error(mocker):
    action, _ = _save_action(mocker)
    action._navigate = mocker.Mock(side_effect=WebDriverException("nav failed"))

    with pytest.raises(WebDriverException):
        action.execute(link=LINK)


def test_hide_action_happy_path(mocker):
    action, _ = _hide_action(mocker)
    more_button = mocker.Mock()
    hide_button = mocker.Mock()
    action._find_self_healing.side_effect = [more_button, hide_button]

    result = action.execute(link=LINK)

    assert result.success is True
    assert result.action == "hide"
    assert result.link == LINK
    assert result.message == "Post hidden"
    action._navigate.assert_called_once_with(LINK)
    assert action._find_self_healing.call_count == 2
    assert action._find_self_healing.call_args_list[0].args[0] == "more_options"
    assert action._find_self_healing.call_args_list[1].args[0] == "hide"
    action._click.assert_any_call(more_button)
    action._click.assert_any_call(hide_button)


def test_hide_action_fails_when_more_options_missing(mocker):
    action, _ = _hide_action(mocker)
    action._find_self_healing.return_value = None

    result = action.execute(link=LINK)

    assert result.success is False
    assert result.action == "hide"
    assert "Could not find post options menu" in result.message
    action._click.assert_not_called()


def test_hide_action_fails_when_hide_menu_item_missing(mocker):
    action, _ = _hide_action(mocker)
    more_button = mocker.Mock()
    action._find_self_healing.side_effect = [more_button, None]

    result = action.execute(link=LINK)

    assert result.success is False
    assert result.action == "hide"
    assert "Could not find Hide menu item" in result.message
    action._click.assert_called_once_with(more_button)


def test_hide_action_dry_run_skips_browser(mocker):
    action, _ = _hide_action(mocker)
    action.config.dry_run = True

    result = action.execute(link=LINK)

    assert result.success is True
    assert result.message == "Dry run"
    action._navigate.assert_not_called()
    action._find_self_healing.assert_not_called()


def test_hide_action_propagates_navigate_error(mocker):
    action, _ = _hide_action(mocker)
    action._navigate = mocker.Mock(side_effect=WebDriverException("nav failed"))

    with pytest.raises(WebDriverException):
        action.execute(link=LINK)
