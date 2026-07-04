"""Tests for self-healing selector lookup."""

import json

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from bot.config import BotConfig
from bot.utils.self_healing import SelfHealingLocator


def _config(tmp_path):
    return BotConfig(
        selector_cache_path=str(tmp_path / "selectors.json"),
        selector_diagnostics_dir=str(tmp_path / "diagnostics"),
        selector_fallback_wait=1.0,
        selenium_implicit_wait=20,
    )


def test_self_healing_locator_reuses_cached_selector(tmp_path, mocker):
    cache_path = tmp_path / "selectors.json"
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "selectors": {
                    "upvote": {
                        "selector": "button[aria-label=\"Upvote\"]",
                        "labels": ["upvote"],
                    }
                },
            }
        )
    )
    element = mocker.Mock()
    driver = mocker.Mock()
    driver.execute_script.return_value = element

    found = SelfHealingLocator(driver, _config(tmp_path), mocker.Mock()).find(
        "upvote",
        ["upvote"],
    )

    assert found is element
    driver.find_element.assert_not_called()


def test_self_healing_locator_persists_console_probe_selector(tmp_path, mocker):
    element = mocker.Mock()
    driver = mocker.Mock()
    driver.execute_script.return_value = {
        "element": element,
        "selector": "button[aria-label=\"Upvote\"]",
        "evidence": {"score": 110},
        "candidates": [],
    }

    found = SelfHealingLocator(driver, _config(tmp_path), mocker.Mock()).find(
        "upvote",
        ["upvote"],
    )

    assert found is element
    cache = json.loads((tmp_path / "selectors.json").read_text())
    assert cache["selectors"]["upvote"]["selector"] == "button[aria-label=\"Upvote\"]"
    assert cache["selectors"]["upvote"]["evidence"] == {"score": 110}


def test_self_healing_locator_uses_legacy_with_short_wait(tmp_path, mocker):
    element = mocker.Mock()
    driver = mocker.Mock()
    driver.execute_script.return_value = {"element": None, "candidates": []}
    driver.find_element.side_effect = [NoSuchElementException("missing"), element]

    found = SelfHealingLocator(driver, _config(tmp_path), mocker.Mock()).find(
        "upvote",
        ["upvote"],
        legacy_locators=[
            (By.CSS_SELECTOR, "button[aria-label='upvote']"),
            (By.XPATH, "//button[contains(@aria-label, 'upvote')]"),
        ],
    )

    assert found is element
    assert driver.implicitly_wait.call_args_list[0].args == (1.0,)
    assert driver.implicitly_wait.call_args_list[-1].args == (20,)


def test_self_healing_locator_writes_diagnostics_on_failure(tmp_path, mocker):
    driver = mocker.Mock()
    driver.execute_script.return_value = {
        "element": None,
        "url": "https://www.reddit.com/r/test/comments/abc",
        "candidates": [{"score": 1, "text": "near miss"}],
    }

    found = SelfHealingLocator(driver, _config(tmp_path), mocker.Mock()).find(
        "upvote",
        ["upvote"],
    )

    assert found is None
    diagnostics = list((tmp_path / "diagnostics").glob("*_upvote.json"))
    assert len(diagnostics) == 1
    payload = json.loads(diagnostics[0].read_text())
    assert payload["candidates"] == [{"score": 1, "text": "near miss"}]
