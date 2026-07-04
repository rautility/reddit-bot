"""Follow/unfollow actions for Reddit users."""

from __future__ import annotations

from typing import Any

from selenium.webdriver.common.by import By
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

        follow_btn = self._find_self_healing(
            "follow",
            ["follow", "following"],
            legacy_locators=(
                (By.CSS_SELECTOR, "button[id*='follow-button']"),
                (By.XPATH, "//button[contains(text(), 'Follow')]"),
            ),
        )
        if follow_btn is None:
            return ActionResult(
                success=False,
                action="follow",
                link=link,
                message="Could not find follow button",
            )

        btn_text = (follow_btn.text or follow_btn.get_attribute("aria-label") or "").lower()
        if "follow" in btn_text and "following" not in btn_text:
            self._click(follow_btn)
            Timeouts.med()
            return ActionResult(success=True, action="follow", link=link, message="User followed")
        return ActionResult(success=True, action="follow", link=link, message="Already following")


class UnfollowAction(BaseAction):
    name = "unfollow"

    def execute(self, link: str = "", **kwargs: Any) -> ActionResult:
        self.logger.info(f"Unfollowing user {link}")

        if self.config.dry_run:
            return ActionResult(success=True, action="unfollow", link=link, message="Dry run")

        self._navigate(link)
        Timeouts.med()

        follow_btn = self._find_self_healing(
            "unfollow",
            ["following", "unfollow", "follow"],
            legacy_locators=(
                (By.CSS_SELECTOR, "button[id*='follow-button']"),
                (By.XPATH, "//button[contains(text(), 'Following')]"),
                (By.XPATH, "//button[contains(text(), 'Unfollow')]"),
            ),
        )
        if follow_btn is None:
            return ActionResult(
                success=False,
                action="unfollow",
                link=link,
                message="Could not find follow/unfollow button",
            )

        btn_text = (follow_btn.text or follow_btn.get_attribute("aria-label") or "").lower()
        if "following" in btn_text or "unfollow" in btn_text:
            self._click(follow_btn)
            Timeouts.med()
            return ActionResult(success=True, action="unfollow", link=link, message="User unfollowed")
        return ActionResult(success=True, action="unfollow", link=link, message="Not following")
