"""Community action — join or leave a subreddit."""

from __future__ import annotations

import contextlib
from typing import Any

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from .base import BaseAction, ActionResult
from bot.utils.timeouts import Timeouts


class JoinCommunityAction(BaseAction):
    name = "join_community"

    def execute(self, link: str = "", join: bool = True, **kwargs: Any) -> ActionResult:
        action_name = "join" if join else "leave"
        self.logger.info(f"{'Joining' if join else 'Leaving'} {link}")

        if self.config.dry_run:
            return ActionResult(success=True, action=action_name, link=link, message="Dry run")

        self._navigate(link)
        Timeouts.med()
        self._handle_nsfw()

        join_button = self._find_with_fallbacks(
            (By.CSS_SELECTOR, "button[id*='join-button']"),
            (By.XPATH, "/html/body/div[1]/div/div[2]/div[2]/div/div/div/div[2]/div[1]/div/div[1]/div/div[2]/div/button"),
            (By.XPATH, '//*[@id="AppRouter-main-content"]/div/div/div[2]/div[1]/div/div[1]/div/div[2]/div/button'),
        )

        button_text = join_button.text.lower()

        if (join and button_text == "join") or (not join and button_text == "joined"):
            self._click(join_button)
            Timeouts.med()
            return ActionResult(success=True, action=action_name, link=link, message=f"Successfully {'joined' if join else 'left'}")

        return ActionResult(
            success=True, action=action_name, link=link,
            message=f"Already {'joined' if join else 'left'} (button says '{button_text}')"
        )

    def _handle_nsfw(self) -> None:
        with contextlib.suppress(NoSuchElementException):
            btn = self.driver.find_element(
                By.CSS_SELECTOR, "button.nsfw-gate-btn, button[name='over18']"
            )
            btn.click()
            Timeouts.srt()
