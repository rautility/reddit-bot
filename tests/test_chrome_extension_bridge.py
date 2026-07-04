"""Tests for the Reddit healer Chrome extension bridge client."""

from selenium.common.exceptions import WebDriverException

from bot.utils.chrome_extension_bridge import (
    ChromeControlCandidate,
    ChromeControlResult,
    ChromeExtensionBridge,
)


def test_control_candidate_from_dict_normalizes_fields():
    candidate = ChromeControlCandidate.from_dict(
        {
            "id": "control-1",
            "intent": "downvote",
            "selector": "button[aria-label=\"Downvote\"]",
            "confidence": 0.91,
            "text": "downvote",
            "attributes": {"aria-pressed": "false"},
            "boundingBox": {"x": 10, "y": 20, "width": 30, "height": 40},
            "state": {"pressed": False},
            "evidence": ["contains label: downvote"],
        }
    )

    assert candidate.id == "control-1"
    assert candidate.intent == "downvote"
    assert candidate.confidence == 0.91
    assert candidate.bounding_box["width"] == 30
    assert candidate.state["pressed"] is False


def test_control_result_uses_best_candidate_from_response():
    result = ChromeControlResult.from_dict(
        {
            "ok": True,
            "intent": "downvote",
            "bestCandidate": {"id": "best", "confidence": 0.95},
            "candidates": [{"id": "other", "confidence": 0.7}],
            "nearMisses": [{"id": "near", "confidence": 0.0}],
            "events": [{"type": "found_control"}],
            "meetsMinConfidence": True,
            "scanPass": 2,
            "scanPasses": 3,
        }
    )

    assert result.ok is True
    assert result.best_candidate.id == "best"
    assert result.candidates[0].id == "other"
    assert result.near_misses[0].id == "near"
    assert result.events == [{"type": "found_control"}]
    assert result.meets_min_confidence is True
    assert result.scan_pass == 2
    assert result.scan_passes == 3


def test_bridge_find_control_sends_structured_request(mocker):
    driver = mocker.Mock()
    driver.execute_async_script.return_value = {
        "ok": True,
        "intent": "downvote",
        "bestCandidate": {
            "id": "control-1",
            "selector": "button[aria-label=\"Downvote\"]",
            "confidence": 0.93,
        },
        "candidates": [],
    }
    bridge = ChromeExtensionBridge(driver, timeout_ms=1234)

    result = bridge.find_control(
        "downvote",
        post_url="https://www.reddit.com/r/test/comments/abc/title",
        min_confidence=0.8,
    )

    assert result.ok is True
    assert result.best_candidate.selector == "button[aria-label=\"Downvote\"]"
    call = driver.execute_async_script.call_args
    assert call.args[1] == "find_control"
    assert call.args[2]["intent"] == "downvote"
    assert call.args[2]["postUrl"] == "https://www.reddit.com/r/test/comments/abc/title"
    assert call.args[2]["minConfidence"] == 0.8
    assert call.args[3] == 1234


def test_bridge_returns_error_when_execute_async_script_fails(mocker):
    driver = mocker.Mock()
    driver.execute_async_script.side_effect = WebDriverException("boom")

    response = ChromeExtensionBridge(driver).request("ping", {})

    assert response["ok"] is False
    assert response["command"] == "ping"
    assert "boom" in response["error"]


def test_element_for_candidate_uses_deep_selector_query(mocker):
    element = mocker.Mock()
    driver = mocker.Mock()
    driver.execute_script.return_value = element
    candidate = ChromeControlCandidate(
        selector="button[aria-label=\"Downvote\"]",
        bounding_box={"x": 10, "y": 20, "width": 30, "height": 40},
    )

    found = ChromeExtensionBridge(driver).element_for_candidate(
        candidate,
        post_url="https://www.reddit.com/r/test/comments/abc/title",
    )

    assert found is element
    call = driver.execute_script.call_args
    assert "querySelectorAll(selector)" in call.args[0]
    assert "postScope(postUrl)" in call.args[0]
    assert call.args[1] == "button[aria-label=\"Downvote\"]"
    assert call.args[2] == {"x": 10, "y": 20, "width": 30, "height": 40}
    assert call.args[3] == "https://www.reddit.com/r/test/comments/abc/title"
