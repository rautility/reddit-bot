"""Tests for rendered vote-control fallback helpers."""

from bot.utils.visible_vote import (
    FIND_VISIBLE_VOTE_CONTROL_SCRIPT,
    click_visible_vote_control,
    find_visible_vote_control,
)


def test_find_visible_vote_control_uses_rendered_dom_script(mocker):
    driver = mocker.Mock()
    driver.execute_script.return_value = {"ok": True}

    result = find_visible_vote_control(driver, "downvote", "https://reddit.com/r/test/comments/abc")

    assert result == {"ok": True}
    script, intent, url = driver.execute_script.call_args.args
    assert script == FIND_VISIBLE_VOTE_CONTROL_SCRIPT
    assert intent == "downvote"
    assert url == "https://reddit.com/r/test/comments/abc"
    assert "getBoundingClientRect" in script
    assert "shadowRoot" in script
    assert "vote-pill-geometry" in script
    assert "descendantIconNames" in script
    assert "combinedVotePill" in script
    assert "containsOnlyOppositeIcon" in script


def test_click_visible_vote_control_dispatches_cdp_click_and_screenshot(mocker, tmp_path):
    driver = mocker.Mock()
    driver.current_url = "https://reddit.com/r/test/comments/abc"
    before = {
        "ok": True,
        "candidate": {
            "source": "vote-pill-geometry",
            "click": {"x": 359, "y": 369},
            "pressed": False,
        },
    }
    after = {
        "ok": True,
        "candidate": {
            "source": "vote-pill-geometry",
            "click": {"x": 359, "y": 369},
            "pressed": True,
        },
    }
    driver.execute_script.side_effect = [before, after]
    screenshot_path = tmp_path / "vote.png"
    sleep = mocker.patch("bot.utils.visible_vote.time.sleep")

    result = click_visible_vote_control(
        driver,
        intent="downvote",
        url="https://reddit.com/r/test/comments/abc",
        screenshot_path=str(screenshot_path),
    )

    assert result["ok"] is True
    assert result["clicked"] is True
    assert result["confirmed"] is True
    assert result["click"] == {"x": 359, "y": 369}
    assert driver.execute_cdp_cmd.call_count == 3
    driver.get.assert_called_once_with("https://reddit.com/r/test/comments/abc")
    driver.save_screenshot.assert_called_once_with(str(screenshot_path))
    sleep.assert_called_once_with(2.0)


def test_click_visible_vote_control_reports_missing_candidate(mocker):
    driver = mocker.Mock()
    driver.execute_script.return_value = {"ok": False, "candidate": None}

    result = click_visible_vote_control(
        driver,
        intent="upvote",
        url="https://reddit.com/r/test/comments/abc",
    )

    assert result["ok"] is False
    assert result["clicked"] is False
    assert "No visible vote control" in result["error"]
    driver.execute_cdp_cmd.assert_not_called()
