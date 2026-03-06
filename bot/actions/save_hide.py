"""Save and Hide actions for Reddit posts."""

from __future__ import annotations

import contextlib
from typing import Any

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from .base import BaseAction, ActionResult
from bot.utils.timeouts import Timeouts


class SaveAction(BaseAction):
    name = "save"

    def execute(self, link: str = "", **kwargs: Any) -> ActionResult:
        self.logger.info(f"Saving post {link}")

        if self.config.dry_run:
            return ActionResult(success=True, action="save", link=link, message="Dry run")

        self._navigate(link)
        Timeouts.med()

        try:
            # Try the more options menu first
            more_button = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "button[aria-label='more options']"),
                (By.CSS_SELECTOR, "button[id*='post-action-bar']"),
            )
            self._click(more_button)
            Timeouts.srt()

            save_button = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "li[role='menuitem'] button:has(span)"),
                (By.XPATH, "//button[contains(text(), 'Save')]"),
                (By.XPATH, "//menuitem[contains(text(), 'Save')]"),
            )
            self._click(save_button)
            Timeouts.med()
            return ActionResult(success=True, action="save", link=link, message="Post saved")
        except NoSuchElementException as e:
            return ActionResult(success=False, action="save", link=link, message=str(e))


class HideAction(BaseAction):
    name = "hide"

    def execute(self, link: str = "", **kwargs: Any) -> ActionResult:
        self.logger.info(f"Hiding post {link}")

        if self.config.dry_run:
            return ActionResult(success=True, action="hide", link=link, message="Dry run")

        self._navigate(link)
        Timeouts.med()

        try:
            more_button = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "button[aria-label='more options']"),
                (By.CSS_SELECTOR, "button[id*='post-action-bar']"),
            )
            self._click(more_button)
            Timeouts.srt()

            hide_button = self._find_with_fallbacks(
                (By.XPATH, "//button[contains(text(), 'Hide')]"),
                (By.XPATH, "//menuitem[contains(text(), 'Hide')]"),
            )
            self._click(hide_button)
            Timeouts.med()
            return ActionResult(success=True, action="hide", link=link, message="Post hidden")
        except NoSuchElementException as e:
            return ActionResult(success=False, action="hide", link=link, message=str(e))
