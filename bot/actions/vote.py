"""Vote action — upvote or downvote a post."""

from __future__ import annotations

import contextlib
from typing import Any

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from .base import BaseAction, ActionResult
from bot.utils.timeouts import Timeouts


class VoteAction(BaseAction):
    name = "vote"

    def execute(self, link: str = "", upvote: bool = True, **kwargs: Any) -> ActionResult:
        vote_type = "upvote" if upvote else "downvote"
        self.logger.info(f"{'Upvoting' if upvote else 'Downvoting'} {link}")

        if self.config.dry_run:
            return ActionResult(success=True, action=vote_type, link=link, message="Dry run")

        self._navigate(link)
        Timeouts.med()
        self._handle_nsfw()

        label = "upvote" if upvote else "downvote"
        try:
            button = self.driver.find_element(
                By.CSS_SELECTOR, f"button[aria-label='{label}']"
            )
        except NoSuchElementException:
            index = 1 if upvote else 2
            button = self.driver.find_element(By.XPATH,
                f"/html/body/div[1]/div/div[2]/div[2]/div/div/div/div[2]/div[3]/div[1]/div[3]/div[1]/div/div[1]/div/button[{index}]"
            )

        self._click(button)
        Timeouts.med()

        # Verify action
        try:
            aria_pressed = button.get_attribute("aria-pressed")
            if aria_pressed == "true":
                return ActionResult(success=True, action=vote_type, link=link, message="Vote registered")
        except Exception:
            pass

        return ActionResult(success=True, action=vote_type, link=link, message="Vote clicked")

    def _handle_nsfw(self) -> None:
        with contextlib.suppress(NoSuchElementException):
            btn = self.driver.find_element(
                By.CSS_SELECTOR, "button.nsfw-gate-btn, button[name='over18']"
            )
            btn.click()
            Timeouts.srt()
        with contextlib.suppress(NoSuchElementException):
            btn = self.driver.find_element(By.XPATH,
                "/html/body/div[1]/div/div[2]/div[2]/div/div/div[1]/div/div/div[2]/button"
            )
            btn.click()
            Timeouts.srt()
