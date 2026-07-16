"""Unit tests for follow/unfollow user actions (mocked WebDriver only)."""

from bot.actions.follow import FollowAction, UnfollowAction
from bot.config import BotConfig

USER_URL = "https://www.reddit.com/user/example/"


def _follow_action(mocker):
    driver = mocker.Mock()
    action = FollowAction(driver, BotConfig(), mocker.Mock())
    action._navigate = mocker.Mock()
    action._find_self_healing = mocker.Mock(return_value=None)
    action._click = mocker.Mock()
    mocker.patch("bot.actions.follow.Timeouts.med")
    return action, driver


def _unfollow_action(mocker):
    driver = mocker.Mock()
    action = UnfollowAction(driver, BotConfig(), mocker.Mock())
    action._navigate = mocker.Mock()
    action._find_self_healing = mocker.Mock(return_value=None)
    action._click = mocker.Mock()
    mocker.patch("bot.actions.follow.Timeouts.med")
    return action, driver


def test_follow_happy_path_clicks_follow_button(mocker):
    action, _ = _follow_action(mocker)
    button = mocker.Mock()
    button.text = "Follow"
    button.get_attribute.return_value = "Follow"
    action._find_self_healing.return_value = button

    result = action.execute(link=USER_URL)

    assert result.success is True
    assert result.action == "follow"
    assert result.link == USER_URL
    assert result.message == "User followed"
    action._navigate.assert_called_once_with(USER_URL)
    action._click.assert_called_once_with(button)
    call = action._find_self_healing.call_args
    assert call.args[0] == "follow"
    assert call.args[1] == ["follow", "following"]


def test_follow_fails_when_button_missing(mocker):
    action, _ = _follow_action(mocker)
    action._find_self_healing.return_value = None

    result = action.execute(link=USER_URL)

    assert result.success is False
    assert result.action == "follow"
    assert result.link == USER_URL
    assert "Could not find follow button" in result.message
    action._click.assert_not_called()


def test_follow_already_following_does_not_click(mocker):
    action, _ = _follow_action(mocker)
    button = mocker.Mock()
    button.text = "Following"
    button.get_attribute.return_value = "Following"
    action._find_self_healing.return_value = button

    result = action.execute(link=USER_URL)

    assert result.success is True
    assert result.action == "follow"
    assert result.message == "Already following"
    action._click.assert_not_called()


def test_follow_dry_run_skips_browser(mocker):
    driver = mocker.Mock()
    config = BotConfig(dry_run=True)
    action = FollowAction(driver, config, mocker.Mock())
    action._navigate = mocker.Mock()
    action._find_self_healing = mocker.Mock()

    result = action.execute(link=USER_URL)

    assert result.success is True
    assert result.action == "follow"
    assert result.message == "Dry run"
    action._navigate.assert_not_called()
    action._find_self_healing.assert_not_called()


def test_unfollow_happy_path_clicks_when_following(mocker):
    action, _ = _unfollow_action(mocker)
    button = mocker.Mock()
    button.text = "Following"
    button.get_attribute.return_value = "Following"
    action._find_self_healing.return_value = button

    result = action.execute(link=USER_URL)

    assert result.success is True
    assert result.action == "unfollow"
    assert result.link == USER_URL
    assert result.message == "User unfollowed"
    action._navigate.assert_called_once_with(USER_URL)
    action._click.assert_called_once_with(button)
    call = action._find_self_healing.call_args
    assert call.args[0] == "unfollow"
    assert call.args[1] == ["following", "unfollow", "follow"]


def test_unfollow_happy_path_with_unfollow_label(mocker):
    action, _ = _unfollow_action(mocker)
    button = mocker.Mock()
    button.text = "Unfollow"
    button.get_attribute.return_value = None
    action._find_self_healing.return_value = button

    result = action.execute(link=USER_URL)

    assert result.success is True
    assert result.action == "unfollow"
    assert result.message == "User unfollowed"
    action._click.assert_called_once_with(button)


def test_unfollow_fails_when_button_missing(mocker):
    action, _ = _unfollow_action(mocker)
    action._find_self_healing.return_value = None

    result = action.execute(link=USER_URL)

    assert result.success is False
    assert result.action == "unfollow"
    assert "Could not find follow/unfollow button" in result.message
    action._click.assert_not_called()


def test_unfollow_not_following_does_not_click(mocker):
    action, _ = _unfollow_action(mocker)
    button = mocker.Mock()
    button.text = "Follow"
    button.get_attribute.return_value = "Follow"
    action._find_self_healing.return_value = button

    result = action.execute(link=USER_URL)

    assert result.success is True
    assert result.action == "unfollow"
    assert result.message == "Not following"
    action._click.assert_not_called()


def test_unfollow_dry_run_skips_browser(mocker):
    driver = mocker.Mock()
    config = BotConfig(dry_run=True)
    action = UnfollowAction(driver, config, mocker.Mock())
    action._navigate = mocker.Mock()
    action._find_self_healing = mocker.Mock()

    result = action.execute(link=USER_URL)

    assert result.success is True
    assert result.action == "unfollow"
    assert result.message == "Dry run"
    action._navigate.assert_not_called()
    action._find_self_healing.assert_not_called()


def test_follow_uses_aria_label_when_text_empty(mocker):
    action, _ = _follow_action(mocker)
    button = mocker.Mock()
    button.text = ""
    button.get_attribute.return_value = "Follow u/example"
    action._find_self_healing.return_value = button

    result = action.execute(link=USER_URL)

    assert result.success is True
    assert result.message == "User followed"
    action._click.assert_called_once_with(button)
    button.get_attribute.assert_called_with("aria-label")
