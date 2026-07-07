"""Tests for vote actions."""

from bot.actions.vote import VoteAction
from bot.config import BotConfig
from bot.utils.chrome_extension_bridge import ChromeControlCandidate, ChromeControlResult


def _vote_action(mocker):
    driver = mocker.Mock()
    action = VoteAction(driver, BotConfig(), mocker.Mock())
    action._navigate = mocker.Mock()
    action._handle_nsfw = mocker.Mock()
    action._find_self_healing = mocker.Mock(return_value=None)
    mocker.patch("bot.actions.vote.Timeouts.med")
    return action, driver


def test_vote_action_returns_failure_when_button_missing(mocker):
    action, _ = _vote_action(mocker)
    mocker.patch(
        "bot.actions.vote.click_visible_vote_control",
        return_value={"ok": False, "clicked": False, "confirmed": False},
    )

    result = action.execute("https://www.reddit.com/r/test/comments/abc", upvote=True)

    assert result.success is False
    assert result.action == "upvote"
    assert "Could not find upvote button" in result.message


def test_vote_action_skips_deleted_post_before_clicking(mocker):
    action, driver = _vote_action(mocker)
    action._click = mocker.Mock()
    driver.execute_script.return_value = {
        "available": False,
        "reason": "Post is deleted; voting was not attempted.",
    }
    fallback = mocker.patch("bot.actions.vote.click_visible_vote_control")

    result = action.execute("https://www.reddit.com/r/test/comments/abc/deleted/", upvote=True)

    assert result.success is False
    assert result.action == "upvote"
    assert result.message == "Post is deleted; voting was not attempted."
    action._find_self_healing.assert_not_called()
    action._click.assert_not_called()
    fallback.assert_not_called()


def test_vote_action_uses_visible_vote_fallback_when_button_missing(mocker):
    action, driver = _vote_action(mocker)
    link = "https://www.reddit.com/r/test/comments/abc"
    fallback = mocker.patch(
        "bot.actions.vote.click_visible_vote_control",
        return_value={"ok": True, "clicked": True, "confirmed": True},
    )

    result = action.execute(link, upvote=False)

    assert result.success is True
    assert result.action == "downvote"
    assert result.message == "Vote registered via visible fallback"
    fallback.assert_called_once_with(driver, intent="downvote", url=link)


def test_vote_action_uses_self_healing_locator(mocker):
    action, _ = _vote_action(mocker)
    button = mocker.Mock()
    button.get_attribute.return_value = "true"
    action._find_self_healing.return_value = button
    action._click = mocker.Mock()

    result = action.execute("https://www.reddit.com/r/test/comments/abc", upvote=True)

    assert result.success is True
    action._click.assert_called_once_with(button)
    call = action._find_self_healing.call_args
    assert call.args[0] == "upvote"
    assert call.args[1] == ["upvote"]
    assert call.kwargs["reject_labels"] == ["downvote"]


def test_vote_action_fails_when_click_does_not_register(mocker):
    action, driver = _vote_action(mocker)
    button = mocker.Mock()
    button.get_attribute.return_value = "false"
    action._find_self_healing.return_value = button
    action._click = mocker.Mock()
    driver.execute_script.return_value = False
    mocker.patch(
        "bot.actions.vote.click_visible_vote_control",
        return_value={"ok": False, "clicked": False, "confirmed": False},
    )

    result = action.execute("https://www.reddit.com/r/test/comments/abc", upvote=False)

    assert result.success is False
    assert result.action == "downvote"
    assert "did not register" in result.message


def test_vote_action_uses_visible_vote_fallback_after_click_does_not_register(mocker):
    action, driver = _vote_action(mocker)
    link = "https://www.reddit.com/r/test/comments/abc"
    button = mocker.Mock()
    button.get_attribute.return_value = "false"
    action._find_self_healing.return_value = button
    action._click = mocker.Mock()
    driver.execute_script.return_value = False
    fallback = mocker.patch(
        "bot.actions.vote.click_visible_vote_control",
        return_value={"ok": True, "clicked": True, "confirmed": True},
    )

    result = action.execute(link, upvote=True)

    assert result.success is True
    assert result.action == "upvote"
    assert result.message == "Vote registered via visible fallback"
    fallback.assert_called_once_with(driver, intent="upvote", url=link)


def test_vote_action_uses_visible_vote_fallback_when_click_raises(mocker):
    from selenium.common.exceptions import WebDriverException

    action, driver = _vote_action(mocker)
    link = "https://www.reddit.com/r/test/comments/abc"
    button = mocker.Mock()
    action._find_self_healing.return_value = button
    action._click = mocker.Mock(side_effect=WebDriverException("not clickable"))
    fallback = mocker.patch(
        "bot.actions.vote.click_visible_vote_control",
        return_value={"ok": True, "clicked": True, "confirmed": True},
    )

    result = action.execute(link, upvote=True)

    assert result.success is True
    assert result.action == "upvote"
    assert result.message == "Vote registered via visible fallback"
    fallback.assert_called_once_with(driver, intent="upvote", url=link)


def test_vote_action_failure_includes_visible_vote_fallback_diagnostics(mocker):
    action, driver = _vote_action(mocker)
    link = "https://www.reddit.com/r/test/comments/abc"
    button = mocker.Mock()
    button.get_attribute.return_value = "false"
    action._find_self_healing.return_value = button
    action._click = mocker.Mock()
    driver.execute_script.return_value = False
    fallback = mocker.patch(
        "bot.actions.vote.click_visible_vote_control",
        return_value={
            "ok": True,
            "clicked": True,
            "confirmed": False,
            "source": "vote-pill-geometry",
            "click": {"x": 410, "y": 88},
            "error": "confirmation stayed inactive",
        },
    )

    result = action.execute(link, upvote=False)

    assert result.success is False
    assert result.action == "downvote"
    assert "visibleFallback clicked=True confirmed=False" in result.message
    assert "source=vote-pill-geometry" in result.message
    assert "fallbackClick=(410,88)" in result.message
    assert "error=confirmation stayed inactive" in result.message
    fallback.assert_called_once_with(driver, intent="downvote", url=link)


def test_vote_registration_script_does_not_accept_generic_active_text(mocker):
    action, driver = _vote_action(mocker)
    button = mocker.Mock()
    button.get_attribute.return_value = "false"
    driver.execute_script.return_value = False

    assert action._vote_is_registered(button, "upvote") is False

    script = driver.execute_script.call_args.args[0]
    assert "text.includes('active')" not in script
    assert "text.includes('selected')" not in script
    assert "interactive" not in script


def test_vote_action_failure_includes_click_diagnostics(mocker):
    action, driver = _vote_action(mocker)
    button = mocker.Mock()
    button.get_attribute.return_value = "false"
    action._find_self_healing.return_value = button
    action._click = mocker.Mock(
        return_value={
            "center": {"x": 296, "y": 610},
            "topmostMatches": True,
            "topmost": {
                "tag": "button",
                "attrs": {"data-action-bar-action": "upvote"},
            },
        }
    )
    driver.execute_script.return_value = False
    mocker.patch(
        "bot.actions.vote.click_visible_vote_control",
        return_value={"ok": False, "clicked": False, "confirmed": False},
    )

    result = action.execute("https://www.reddit.com/r/test/comments/abc", upvote=True)

    assert result.success is False
    assert "click center=(296,610)" in result.message
    assert "topmostMatches=True" in result.message
    assert "topmost=button[upvote]" in result.message


def test_vote_action_uses_extension_bridge_candidate(mocker):
    action, _ = _vote_action(mocker)
    action.config.chrome_extension_healer_enabled = True
    action.config.chrome_extension_min_confidence = 0.8
    button = mocker.Mock()
    candidate = ChromeControlCandidate(
        id="control-1",
        intent="downvote",
        selector='button[aria-label="Downvote"]',
        confidence=0.93,
    )
    bridge = mocker.Mock()
    bridge.find_control.return_value = ChromeControlResult(
        ok=True,
        intent="downvote",
        best_candidate=candidate,
        candidates=[candidate],
    )
    bridge.element_for_candidate.return_value = button
    bridge.confirm_control_state.return_value = {"ok": True, "confirmed": True}
    mocker.patch("bot.utils.chrome_extension_bridge.ChromeExtensionBridge", return_value=bridge)
    action._click = mocker.Mock()

    result = action.execute("https://www.reddit.com/r/test/comments/abc", upvote=False)

    assert result.success is True
    action._find_self_healing.assert_not_called()
    action._click.assert_called_once_with(button)
    bridge.find_control.assert_called_once_with(
        "downvote",
        post_url="https://www.reddit.com/r/test/comments/abc",
        min_confidence=0.8,
    )
    bridge.confirm_control_state.assert_called_once()
    bridge.element_for_candidate.assert_called_once_with(
        candidate,
        post_url="https://www.reddit.com/r/test/comments/abc",
    )


def test_vote_action_falls_back_when_extension_confidence_is_low(mocker):
    action, _ = _vote_action(mocker)
    action.config.chrome_extension_healer_enabled = True
    action.config.chrome_extension_min_confidence = 0.8
    legacy_button = mocker.Mock()
    legacy_button.get_attribute.return_value = "true"
    action._find_self_healing.return_value = legacy_button
    action._click = mocker.Mock()
    candidate = ChromeControlCandidate(
        id="control-1",
        intent="upvote",
        selector='button[aria-label="Upvote"]',
        confidence=0.4,
    )
    bridge = mocker.Mock()
    bridge.find_control.return_value = ChromeControlResult(
        ok=True,
        intent="upvote",
        best_candidate=candidate,
        candidates=[candidate],
    )
    mocker.patch("bot.utils.chrome_extension_bridge.ChromeExtensionBridge", return_value=bridge)

    result = action.execute("https://www.reddit.com/r/test/comments/abc", upvote=True)

    assert result.success is True
    action._find_self_healing.assert_called_once()
    action._click.assert_called_once_with(legacy_button)
    bridge.element_for_candidate.assert_not_called()


def test_vote_action_stops_when_extension_candidate_is_disabled(mocker):
    action, _ = _vote_action(mocker)
    action.config.chrome_extension_healer_enabled = True
    action._click = mocker.Mock()
    candidate = ChromeControlCandidate(
        id="control-1",
        intent="upvote",
        selector='button[data-action-bar-action="upvote"]',
        confidence=1.0,
        state={"disabled": True, "pressed": False},
        actionable=False,
    )
    bridge = mocker.Mock()
    bridge.find_control.return_value = ChromeControlResult(
        ok=True,
        intent="upvote",
        best_candidate=candidate,
        candidates=[candidate],
    )
    mocker.patch("bot.utils.chrome_extension_bridge.ChromeExtensionBridge", return_value=bridge)

    result = action.execute("https://www.reddit.com/r/test/comments/abc", upvote=True)

    assert result.success is False
    assert "control is disabled" in result.message
    action._find_self_healing.assert_not_called()
    action._click.assert_not_called()
    bridge.element_for_candidate.assert_not_called()
