"""Unit tests for UpdateBioAction (mocked WebDriver, no live Reddit)."""

from selenium.common.exceptions import NoSuchElementException

from bot.actions.profile import UpdateBioAction
from bot.config import BotConfig


def _profile_action(mocker, *, dry_run: bool = False):
    driver = mocker.Mock()
    action = UpdateBioAction(driver, BotConfig(dry_run=dry_run), mocker.Mock())
    action._navigate = mocker.Mock()
    action._click = mocker.Mock()
    action._type_like_human = mocker.Mock()
    action._find_with_fallbacks = mocker.Mock()
    mocker.patch("bot.actions.profile.Timeouts.lng")
    mocker.patch("bot.actions.profile.Timeouts.med")
    mocker.patch("bot.actions.profile.Timeouts.srt")
    return action, driver


def test_update_bio_dry_run(mocker):
    action, _ = _profile_action(mocker, dry_run=True)

    result = action.execute(body="New bio text for profile")

    assert result.success is True
    assert result.action == "update_bio"
    assert result.link == "profile"
    assert "Dry run" in result.message
    action._navigate.assert_not_called()


def test_update_bio_fails_without_body(mocker):
    action, _ = _profile_action(mocker)

    result = action.execute(body="")

    assert result.success is False
    assert result.action == "update_bio"
    assert "No bio text provided" in result.message
    action._navigate.assert_not_called()


def test_update_bio_happy_path(mocker):
    action, _ = _profile_action(mocker)
    bio_field = mocker.Mock()
    save_btn = mocker.Mock()
    action._find_with_fallbacks.side_effect = [bio_field, save_btn]

    result = action.execute(body="I like spreadsheets and coffee.")

    assert result.success is True
    assert result.action == "update_bio"
    assert result.link == "profile"
    assert result.message == "Bio updated"
    action._navigate.assert_called_once_with("https://www.reddit.com/settings/profile")
    bio_field.clear.assert_called_once()
    action._type_like_human.assert_called_once_with(bio_field, "I like spreadsheets and coffee.")
    action._click.assert_called_once_with(save_btn)


def test_update_bio_fails_when_controls_missing(mocker):
    action, _ = _profile_action(mocker)
    action._find_with_fallbacks.side_effect = NoSuchElementException("no bio textarea")

    result = action.execute(body="Something interesting")

    assert result.success is False
    assert result.action == "update_bio"
    assert "no bio textarea" in result.message
    action._navigate.assert_called_once()
