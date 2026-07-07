"""Profile action — update user bio/display name."""

from __future__ import annotations

from typing import Any

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from bot.utils.timeouts import Timeouts

from .base import ActionResult, BaseAction


class UpdateBioAction(BaseAction):
    name = "update_bio"

    def execute(self, link: str = "", body: str = "", **kwargs: Any) -> ActionResult:
        self.logger.info("Updating profile bio")

        if self.config.dry_run:
            return ActionResult(
                success=True,
                action="update_bio",
                link="profile",
                message=f"Dry run: bio='{body[:50]}'",
            )

        if not body:
            return ActionResult(success=False, action="update_bio", link="profile", message="No bio text provided")

        self._navigate("https://www.reddit.com/settings/profile")
        Timeouts.lng()

        try:
            # Find the bio/about textarea
            bio_field = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "textarea[name='about'], textarea[id*='about']"),
                (
                    By.XPATH,
                    "//textarea[contains(@placeholder, 'About') or contains(@placeholder, 'bio')]",
                ),
                (By.CSS_SELECTOR, "textarea"),
            )
            bio_field.clear()
            self._type_like_human(bio_field, body)
            Timeouts.srt()

            save_btn = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(text(), 'Save')]"),
            )
            self._click(save_btn)
            Timeouts.med()

            return ActionResult(success=True, action="update_bio", link="profile", message="Bio updated")
        except NoSuchElementException as e:
            return ActionResult(success=False, action="update_bio", link="profile", message=str(e))
