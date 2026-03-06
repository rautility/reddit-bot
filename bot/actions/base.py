"""Base action class — all bot actions inherit from this."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from bot.config import BotConfig


@dataclass
class ActionResult:
    success: bool
    action: str
    link: str
    message: str = ""
    screenshot_path: Optional[str] = None

    def __str__(self) -> str:
        status = "OK" if self.success else "FAIL"
        return f"[{status}] {self.action} -> {self.link}: {self.message}"


class BaseAction(ABC):
    """Base class for all bot actions."""

    name: str = "base"

    def __init__(self, driver: "WebDriver", config: "BotConfig", logger: Optional[logging.Logger] = None):
        self.driver = driver
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

    @abstractmethod
    def execute(self, **kwargs: Any) -> ActionResult:
        """Execute the action. Must be implemented by subclasses."""
        ...

    def _navigate(self, url: str) -> None:
        """Navigate to a URL."""
        self.driver.get(url)

    def _find_with_fallbacks(self, *locators):
        """Try multiple locator strategies, return the first match."""
        from selenium.common.exceptions import NoSuchElementException

        for locator in locators[:-1]:
            try:
                return self.driver.find_element(*locator)
            except NoSuchElementException:
                continue
        return self.driver.find_element(*locators[-1])

    def _click(self, element) -> None:
        """Click an element, using human-like movement if configured."""
        from bot.utils.mouse import human_click
        human_click(self.driver, element, enabled=self.config.human_mouse)

    def _type_like_human(self, element, text: str) -> None:
        """Type text character by character with random delays."""
        from bot.utils.timeouts import Timeouts
        for ch in text:
            element.send_keys(ch)
            Timeouts.srt()
