"""Save and Hide actions for Reddit posts."""

from __future__ import annotations

from typing import Any

from selenium.webdriver.common.by import By

from bot.utils.timeouts import Timeouts

from .base import ActionResult, BaseAction


class SaveAction(BaseAction):
    name = "save"

    def execute(self, link: str = "", **kwargs: Any) -> ActionResult:
        self.logger.info(f"Saving post {link}")

        if self.config.dry_run:
            return ActionResult(success=True, action="save", link=link, message="Dry run")

        self._navigate(link)
        Timeouts.med()

        more_button = self._find_self_healing(
            "more_options",
            ["more options", "more"],
            legacy_locators=(
                (By.CSS_SELECTOR, "button[aria-label='more options']"),
                (By.CSS_SELECTOR, "button[id*='post-action-bar']"),
            ),
        )
        if more_button is None:
            return ActionResult(success=False, action="save", link=link, message="Could not find post options menu")

        self._click(more_button)
        Timeouts.srt()

        save_button = self._find_self_healing(
            "save",
            ["save"],
            legacy_locators=(
                (By.CSS_SELECTOR, "li[role='menuitem'] button:has(span)"),
                (By.XPATH, "//button[contains(text(), 'Save')]"),
                (By.XPATH, "//menuitem[contains(text(), 'Save')]"),
            ),
        )
        if save_button is None:
            return ActionResult(success=False, action="save", link=link, message="Could not find Save menu item")

        self._click(save_button)
        Timeouts.med()
        return ActionResult(success=True, action="save", link=link, message="Post saved")


class HideAction(BaseAction):
    name = "hide"

    def execute(self, link: str = "", **kwargs: Any) -> ActionResult:
        self.logger.info(f"Hiding post {link}")

        if self.config.dry_run:
            return ActionResult(success=True, action="hide", link=link, message="Dry run")

        self._navigate(link)
        Timeouts.med()

        more_button = self._find_self_healing(
            "more_options",
            ["more options", "more"],
            legacy_locators=(
                (By.CSS_SELECTOR, "button[aria-label='more options']"),
                (By.CSS_SELECTOR, "button[id*='post-action-bar']"),
            ),
        )
        if more_button is None:
            return ActionResult(success=False, action="hide", link=link, message="Could not find post options menu")

        self._click(more_button)
        Timeouts.srt()

        hide_button = self._find_self_healing(
            "hide",
            ["hide"],
            legacy_locators=(
                (By.XPATH, "//button[contains(text(), 'Hide')]"),
                (By.XPATH, "//menuitem[contains(text(), 'Hide')]"),
            ),
        )
        if hide_button is None:
            return ActionResult(success=False, action="hide", link=link, message="Could not find Hide menu item")

        self._click(hide_button)
        Timeouts.med()
        return ActionResult(success=True, action="hide", link=link, message="Post hidden")
