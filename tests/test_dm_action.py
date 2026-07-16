"""Unit tests for DirectMessageAction (mocked WebDriver, no live Reddit)."""

from selenium.common.exceptions import NoSuchElementException

from bot.actions.dm import DirectMessageAction
from bot.config import BotConfig


def _dm_action(mocker, *, dry_run: bool = False):
    driver = mocker.Mock()
    action = DirectMessageAction(driver, BotConfig(dry_run=dry_run), mocker.Mock())
    action._navigate = mocker.Mock()
    action._click = mocker.Mock()
    action._type_like_human = mocker.Mock()
    action._find_with_fallbacks = mocker.Mock()
    mocker.patch("bot.actions.dm.Timeouts.lng")
    mocker.patch("bot.actions.dm.Timeouts.med")
    mocker.patch("bot.actions.dm.Timeouts.srt")
    return action, driver


def test_dm_action_dry_run_skips_browser(mocker):
    action, _ = _dm_action(mocker, dry_run=True)

    result = action.execute(recipient="someuser", message="hello")

    assert result.success is True
    assert result.action == "dm"
    assert result.message == "Dry run"
    action._navigate.assert_not_called()


def test_dm_action_fails_without_message(mocker):
    action, _ = _dm_action(mocker)

    result = action.execute(recipient="someuser", message="")

    assert result.success is False
    assert result.action == "dm"
    assert "No message provided" in result.message
    action._navigate.assert_not_called()


def test_dm_action_happy_path_with_recipient(mocker):
    action, _ = _dm_action(mocker)
    subject = mocker.Mock()
    body = mocker.Mock()
    send_btn = mocker.Mock()
    action._find_with_fallbacks.side_effect = [subject, body, send_btn]

    result = action.execute(
        recipient="u/Particular-Arm2102",
        title="Hi",
        message="Hello there",
    )

    assert result.success is True
    assert result.action == "dm"
    assert result.link == "u/Particular-Arm2102"
    assert result.message == "Message sent"
    action._navigate.assert_called_once_with(
        "https://www.reddit.com/message/compose/?to=u/Particular-Arm2102"
    )
    action._type_like_human.assert_any_call(subject, "Hi")
    action._type_like_human.assert_any_call(body, "Hello there")
    action._click.assert_any_call(body)
    action._click.assert_any_call(send_btn)


def test_dm_action_fills_to_field_from_link_when_no_recipient(mocker):
    action, _ = _dm_action(mocker)
    to_field = mocker.Mock()
    body = mocker.Mock()
    send_btn = mocker.Mock()
    action._find_with_fallbacks.side_effect = [to_field, body, send_btn]

    result = action.execute(link="targetuser", message="ping")

    assert result.success is True
    assert result.link == "targetuser"
    action._navigate.assert_called_once_with("https://www.reddit.com/message/compose")
    action._type_like_human.assert_any_call(to_field, "targetuser")


def test_dm_action_fails_when_controls_missing(mocker):
    action, _ = _dm_action(mocker)
    action._find_with_fallbacks.side_effect = NoSuchElementException("no message field")

    result = action.execute(recipient="someuser", message="hello")

    assert result.success is False
    assert result.action == "dm"
    assert "no message field" in result.message
    action._navigate.assert_called_once()
