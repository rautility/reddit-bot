"""Follow/unfollow actions for Reddit users."""

from __future__ import annotations

from typing import Any

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from .base import BaseAction, ActionResult
from bot.utils.timeouts import Timeouts


class FollowAction(BaseAction):
    name = "follow"

    def execute(self, link: str = "", **kwargs: Any) -> ActionResult:
        self.logger.info(f"Following user {link}")

        if self.config.dry_run:
            return ActionResult(success=True, action="follow", link=link, message="Dry run")

        self._navigate(link)
        Timeouts.med()

        try:
            follow_btn = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "button[id*='follow-button']"),
                (By.XPATH, "//button[contains(text(), 'Follow')]"),
            )

            btn_text = follow_btn.text.lower()
            if btn_text == "follow":
                self._click(follow_btn)
                Timeouts.med()
                return ActionResult(success=True, action="follow", link=link, message="User followed")
            else:
                return ActionResult(success=True, action="follow", link=link, message="Already following")
        except NoSuchElementException as e:
            return ActionResult(success=False, action="follow", link=link, message=str(e))


class UnfollowAction(BaseAction):
    name = "unfollow"

    def execute(self, link: str = "", **kwargs: Any) -> ActionResult:
        self.logger.info(f"Unfollowing user {link}")

        if self.config.dry_run:
            return ActionResult(success=True, action="unfollow", link=link, message="Dry run")

        self._navigate(link)
        Timeouts.med()

        try:
            follow_btn = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "button[id*='follow-button']"),
                (By.XPATH, "//button[contains(text(), 'Following')]"),
                (By.XPATH, "//button[contains(text(), 'Unfollow')]"),
            )

            btn_text = follow_btn.text.lower()
            if btn_text in ("following", "unfollow"):
                self._click(follow_btn)
                Timeouts.med()
                return ActionResult(success=True, action="unfollow", link=link, message="User unfollowed")
            else:
                return ActionResult(success=True, action="unfollow", link=link, message="Not following")
        except NoSuchElementException as e:
            return ActionResult(success=False, action="unfollow", link=link, message=str(e))
