"""Unit tests for join/leave community actions (mocked WebDriver only)."""

from bot.actions.community import JoinCommunityAction
from bot.config import BotConfig

SUBREDDIT_URL = "https://www.reddit.com/r/test/"


def _community_action(mocker):
    driver = mocker.Mock()
    action = JoinCommunityAction(driver, BotConfig(), mocker.Mock())
    action._navigate = mocker.Mock()
    action._handle_nsfw = mocker.Mock()
    action._find_self_healing = mocker.Mock(return_value=None)
    action._click = mocker.Mock()
    mocker.patch("bot.actions.community.Timeouts.med")
    return action, driver


def test_join_happy_path_clicks_join_button(mocker):
    action, _ = _community_action(mocker)
    button = mocker.Mock()
    button.text = "Join"
    button.get_attribute.return_value = "Join community"
    action._find_self_healing.return_value = button

    result = action.execute(link=SUBREDDIT_URL, join=True)

    assert result.success is True
    assert result.action == "join"
    assert result.link == SUBREDDIT_URL
    assert "Successfully joined" in result.message
    action._navigate.assert_called_once_with(SUBREDDIT_URL)
    action._handle_nsfw.assert_called_once()
    action._click.assert_called_once_with(button)
    call = action._find_self_healing.call_args
    assert call.args[0] == "join"
    assert call.args[1] == ["join", "joined", "leave"]


def test_join_fails_when_button_missing(mocker):
    action, _ = _community_action(mocker)
    action._find_self_healing.return_value = None

    result = action.execute(link=SUBREDDIT_URL, join=True)

    assert result.success is False
    assert result.action == "join"
    assert result.link == SUBREDDIT_URL
    assert "Could not find community join/leave button" in result.message
    action._click.assert_not_called()


def test_join_already_joined_does_not_click(mocker):
    action, _ = _community_action(mocker)
    button = mocker.Mock()
    button.text = "Joined"
    button.get_attribute.return_value = "Joined"
    action._find_self_healing.return_value = button

    result = action.execute(link=SUBREDDIT_URL, join=True)

    assert result.success is True
    assert result.action == "join"
    assert "Already joined" in result.message
    action._click.assert_not_called()


def test_leave_happy_path_clicks_when_joined(mocker):
    action, _ = _community_action(mocker)
    button = mocker.Mock()
    button.text = "Joined"
    button.get_attribute.return_value = "Leave community"
    action._find_self_healing.return_value = button

    result = action.execute(link=SUBREDDIT_URL, join=False)

    assert result.success is True
    assert result.action == "leave"
    assert result.link == SUBREDDIT_URL
    assert "Successfully left" in result.message
    action._navigate.assert_called_once_with(SUBREDDIT_URL)
    action._click.assert_called_once_with(button)
    call = action._find_self_healing.call_args
    assert call.args[0] == "leave"
    assert call.args[1] == ["join", "joined", "leave"]


def test_leave_fails_when_button_missing(mocker):
    action, _ = _community_action(mocker)
    action._find_self_healing.return_value = None

    result = action.execute(link=SUBREDDIT_URL, join=False)

    assert result.success is False
    assert result.action == "leave"
    assert "Could not find community join/leave button" in result.message
    action._click.assert_not_called()


def test_leave_already_left_does_not_click(mocker):
    action, _ = _community_action(mocker)
    button = mocker.Mock()
    button.text = "Join"
    button.get_attribute.return_value = "Join"
    action._find_self_healing.return_value = button

    result = action.execute(link=SUBREDDIT_URL, join=False)

    assert result.success is True
    assert result.action == "leave"
    assert "Already left" in result.message
    action._click.assert_not_called()


def test_join_dry_run_skips_browser(mocker):
    driver = mocker.Mock()
    config = BotConfig(dry_run=True)
    action = JoinCommunityAction(driver, config, mocker.Mock())
    action._navigate = mocker.Mock()
    action._find_self_healing = mocker.Mock()

    result = action.execute(link=SUBREDDIT_URL, join=True)

    assert result.success is True
    assert result.action == "join"
    assert result.message == "Dry run"
    action._navigate.assert_not_called()
    action._find_self_healing.assert_not_called()


def test_leave_dry_run_skips_browser(mocker):
    driver = mocker.Mock()
    config = BotConfig(dry_run=True)
    action = JoinCommunityAction(driver, config, mocker.Mock())
    action._navigate = mocker.Mock()

    result = action.execute(link=SUBREDDIT_URL, join=False)

    assert result.success is True
    assert result.action == "leave"
    assert result.message == "Dry run"
    action._navigate.assert_not_called()


def test_join_uses_aria_label_when_text_empty(mocker):
    action, _ = _community_action(mocker)
    button = mocker.Mock()
    button.text = ""
    button.get_attribute.return_value = "Join"
    action._find_self_healing.return_value = button

    result = action.execute(link=SUBREDDIT_URL, join=True)

    assert result.success is True
    assert "Successfully joined" in result.message
    action._click.assert_called_once_with(button)
    button.get_attribute.assert_called_with("aria-label")
