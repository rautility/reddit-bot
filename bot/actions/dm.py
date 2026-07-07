"""Direct message action — send a DM to a Reddit user."""

from __future__ import annotations

from typing import Any

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from bot.utils.timeouts import Timeouts

from .base import ActionResult, BaseAction


class DirectMessageAction(BaseAction):
    name = "dm"

    def execute(
        self,
        link: str = "",
        recipient: str = "",
        title: str = "",
        message: str = "",
        **kwargs: Any,
    ) -> ActionResult:
        target = recipient or link
        self.logger.info(f"Sending DM to {target}")

        if self.config.dry_run:
            return ActionResult(success=True, action="dm", link=target, message="Dry run")

        if not message:
            return ActionResult(success=False, action="dm", link=target, message="No message provided")

        # Navigate to compose message page
        compose_url = "https://www.reddit.com/message/compose"
        if recipient:
            compose_url += f"/?to={recipient}"
        self._navigate(compose_url)
        Timeouts.lng()

        try:
            # Fill recipient if not pre-filled
            if not recipient and link:
                to_field = self._find_with_fallbacks(
                    (By.CSS_SELECTOR, "input[name='to']"),
                    (By.XPATH, "//input[@placeholder='Username']"),
                )
                self._type_like_human(to_field, link)
                Timeouts.srt()

            # Subject
            if title:
                subject_field = self._find_with_fallbacks(
                    (By.CSS_SELECTOR, "input[name='subject']"),
                    (By.XPATH, "//input[@placeholder='Subject']"),
                )
                self._type_like_human(subject_field, title)
                Timeouts.srt()

            # Message body
            msg_field = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "textarea[name='message'], div[contenteditable='true']"),
                (By.XPATH, "//textarea[@name='message']"),
            )
            self._click(msg_field)
            self._type_like_human(msg_field, message)
            Timeouts.srt()

            # Send
            send_btn = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(text(), 'Send')]"),
            )
            self._click(send_btn)
            Timeouts.med()

            return ActionResult(success=True, action="dm", link=target, message="Message sent")
        except NoSuchElementException as e:
            return ActionResult(success=False, action="dm", link=target, message=str(e))
