"""Base action class — all bot actions inherit from this."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

    from bot.config import BotConfig


@dataclass
class ActionResult:
    success: bool
    action: str
    link: str
    message: str = ""
    screenshot_path: str | None = None
    # Optional machine-readable diagnostics (JSON-serializable dict). Flows into
    # the queue job's result_json via dataclasses.asdict, so external callers can
    # read structured detail instead of parsing the message string.
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        status = "OK" if self.success else "FAIL"
        return f"[{status}] {self.action} -> {self.link}: {self.message}"


class BaseAction(ABC):
    """Base class for all bot actions."""

    name: str = "base"

    def __init__(self, driver: WebDriver, config: BotConfig, logger: logging.Logger | None = None):
        self.driver = driver
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

    @abstractmethod
    def execute(self, **kwargs: Any) -> ActionResult:
        """Execute the action. Must be implemented by subclasses."""
        ...

    def _navigate(self, url: str) -> None:
        """Navigate to a URL."""
        from selenium.common.exceptions import WebDriverException

        from bot.utils.timeouts import Timeouts

        attempts = 2
        last_error = None
        for attempt in range(attempts):
            try:
                self.driver.get(url)
                return
            except WebDriverException as exc:
                last_error = exc
                if attempt == 0:
                    self.logger.warning(f"Primary navigation failed (attempt {attempt + 1}/{attempts}); retrying with JS navigation.")
                    self.driver.execute_script("window.location.href = arguments[0];", url)
                    Timeouts.med()
                else:
                    break
        raise last_error

    def _find_with_fallbacks(self, *locators):
        """Try multiple locator strategies, return the first match."""
        from selenium.common.exceptions import NoSuchElementException

        for locator in locators[:-1]:
            try:
                return self.driver.find_element(*locator)
            except NoSuchElementException:
                continue
        return self.driver.find_element(*locators[-1])

    def _find_self_healing(
        self,
        intent: str,
        labels: list[str],
        *,
        legacy_locators=(),
        reject_labels=(),
    ):
        """Find a Reddit UI element using cached selectors and runtime healing."""
        from bot.utils.self_healing import SelfHealingLocator

        return SelfHealingLocator(self.driver, self.config, self.logger).find(
            intent,
            labels,
            legacy_locators=legacy_locators,
            reject_labels=reject_labels,
        )

    def _click(self, element) -> dict:
        """Click an element, using browser pointer actions, and return diagnostics."""
        from bot.utils.mouse import human_click

        return human_click(self.driver, element, enabled=self.config.human_mouse)

    def _type_like_human(self, element, text: str) -> None:
        """Type text character by character with random delays."""
        from bot.utils.timeouts import Timeouts

        for ch in text:
            element.send_keys(ch)
            Timeouts.srt()
