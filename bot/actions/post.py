"""Post submission actions — text, link, image, and crosspost."""

from __future__ import annotations

from typing import Any

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from bot.utils.timeouts import Timeouts

from .base import ActionResult, BaseAction


class PostTextAction(BaseAction):
    name = "post_text"

    def execute(
        self,
        link: str = "",
        subreddit: str = "",
        title: str = "",
        body: str = "",
        flair: str = "",
        **kwargs: Any,
    ) -> ActionResult:
        target = subreddit or link
        self.logger.info(f"Creating text post in {target}")

        if self.config.dry_run:
            return ActionResult(success=True, action="post_text", link=target, message=f"Dry run: '{title}'")

        if not title:
            return ActionResult(success=False, action="post_text", link=target, message="No title provided")

        submit_url = f"https://www.reddit.com/r/{subreddit}/submit" if subreddit else f"{link.rstrip('/')}/submit"
        self._navigate(submit_url)
        Timeouts.lng()

        try:
            # Select text post tab
            text_tab = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "button[role='tab']:first-child"),
                (By.XPATH, "//button[contains(text(), 'Post')]"),
            )
            self._click(text_tab)
            Timeouts.srt()

            # Title
            title_field = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "textarea[placeholder*='Title'], textarea[name='title']"),
                (
                    By.XPATH,
                    "//textarea[contains(@placeholder, 'title') or contains(@placeholder, 'Title')]",
                ),
            )
            self._type_like_human(title_field, title)
            Timeouts.srt()

            # Body
            if body:
                body_field = self._find_with_fallbacks(
                    (By.CSS_SELECTOR, "div[contenteditable='true'][role='textbox']"),
                    (By.CSS_SELECTOR, "textarea[name='body']"),
                )
                self._click(body_field)
                self._type_like_human(body_field, body)
                Timeouts.srt()

            # Flair
            if flair:
                self._select_flair(flair)

            # Submit
            submit_btn = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(text(), 'Post')]"),
            )
            self._click(submit_btn)
            Timeouts.lng()

            return ActionResult(
                success=True,
                action="post_text",
                link=target,
                message=f"Text post '{title}' created",
            )
        except NoSuchElementException as e:
            return ActionResult(success=False, action="post_text", link=target, message=str(e))

    def _select_flair(self, flair: str) -> None:
        try:
            flair_btn = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "button[aria-label*='flair'], button[aria-label*='Flair']"),
                (By.XPATH, "//button[contains(text(), 'Flair')]"),
            )
            self._click(flair_btn)
            Timeouts.srt()

            flair_option = self.driver.find_element(By.XPATH, f"//div[contains(text(), '{flair}')]")
            self._click(flair_option)
            Timeouts.srt()

            apply_btn = self._find_with_fallbacks(
                (By.XPATH, "//button[contains(text(), 'Apply')]"),
                (By.CSS_SELECTOR, "button[type='submit']"),
            )
            self._click(apply_btn)
            Timeouts.srt()
        except NoSuchElementException:
            self.logger.warning(f"Could not select flair: {flair}")


class PostLinkAction(BaseAction):
    name = "post_link"

    def execute(
        self,
        link: str = "",
        subreddit: str = "",
        title: str = "",
        body: str = "",
        **kwargs: Any,
    ) -> ActionResult:
        """body is used as the URL to submit."""
        target = subreddit or link
        self.logger.info(f"Creating link post in {target}")

        if self.config.dry_run:
            return ActionResult(success=True, action="post_link", link=target, message=f"Dry run: '{title}'")

        if not title or not body:
            return ActionResult(
                success=False,
                action="post_link",
                link=target,
                message="Title and URL (body) required",
            )

        submit_url = f"https://www.reddit.com/r/{subreddit}/submit" if subreddit else f"{link.rstrip('/')}/submit"
        self._navigate(submit_url)
        Timeouts.lng()

        try:
            link_tab = self._find_with_fallbacks(
                (By.XPATH, "//button[contains(text(), 'Link')]"),
                (By.CSS_SELECTOR, "button[role='tab']:nth-child(2)"),
            )
            self._click(link_tab)
            Timeouts.srt()

            title_field = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "textarea[placeholder*='Title'], textarea[name='title']"),
                (
                    By.XPATH,
                    "//textarea[contains(@placeholder, 'title') or contains(@placeholder, 'Title')]",
                ),
            )
            self._type_like_human(title_field, title)
            Timeouts.srt()

            url_field = self._find_with_fallbacks(
                (
                    By.CSS_SELECTOR,
                    "input[placeholder*='Url'], input[name='url'], textarea[placeholder*='Url']",
                ),
                (
                    By.XPATH,
                    "//input[contains(@placeholder, 'url') or contains(@placeholder, 'Url')]",
                ),
            )
            self._type_like_human(url_field, body)
            Timeouts.srt()

            submit_btn = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(text(), 'Post')]"),
            )
            self._click(submit_btn)
            Timeouts.lng()

            return ActionResult(
                success=True,
                action="post_link",
                link=target,
                message=f"Link post '{title}' created",
            )
        except NoSuchElementException as e:
            return ActionResult(success=False, action="post_link", link=target, message=str(e))


class PostImageAction(BaseAction):
    name = "post_image"

    def execute(
        self,
        link: str = "",
        subreddit: str = "",
        title: str = "",
        body: str = "",
        **kwargs: Any,
    ) -> ActionResult:
        """body is the path to the image file."""
        target = subreddit or link
        self.logger.info(f"Creating image post in {target}")

        if self.config.dry_run:
            return ActionResult(success=True, action="post_image", link=target, message=f"Dry run: '{title}'")

        if not title or not body:
            return ActionResult(
                success=False,
                action="post_image",
                link=target,
                message="Title and image path (body) required",
            )

        submit_url = f"https://www.reddit.com/r/{subreddit}/submit" if subreddit else f"{link.rstrip('/')}/submit"
        self._navigate(submit_url)
        Timeouts.lng()

        try:
            image_tab = self._find_with_fallbacks(
                (By.XPATH, "//button[contains(text(), 'Image')]"),
                (By.CSS_SELECTOR, "button[role='tab']:nth-child(3)"),
            )
            self._click(image_tab)
            Timeouts.srt()

            title_field = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "textarea[placeholder*='Title'], textarea[name='title']"),
                (
                    By.XPATH,
                    "//textarea[contains(@placeholder, 'title') or contains(@placeholder, 'Title')]",
                ),
            )
            self._type_like_human(title_field, title)
            Timeouts.srt()

            # Upload image via file input
            file_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='file']")
            file_input.send_keys(body)
            Timeouts.lng()

            submit_btn = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(text(), 'Post')]"),
            )
            self._click(submit_btn)
            Timeouts.lng()

            return ActionResult(
                success=True,
                action="post_image",
                link=target,
                message=f"Image post '{title}' created",
            )
        except NoSuchElementException as e:
            return ActionResult(success=False, action="post_image", link=target, message=str(e))


class CrosspostAction(BaseAction):
    name = "crosspost"

    def execute(
        self,
        link: str = "",
        subreddit: str = "",
        title: str = "",
        **kwargs: Any,
    ) -> ActionResult:
        self.logger.info(f"Crossposting {link} to r/{subreddit}")

        if self.config.dry_run:
            return ActionResult(
                success=True,
                action="crosspost",
                link=link,
                message=f"Dry run: crosspost to r/{subreddit}",
            )

        if not subreddit:
            return ActionResult(success=False, action="crosspost", link=link, message="Target subreddit required")

        self._navigate(link)
        Timeouts.med()

        try:
            # Open share menu
            share_btn = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "button[aria-label='Share']"),
                (By.XPATH, "//button[contains(text(), 'Share')]"),
            )
            self._click(share_btn)
            Timeouts.srt()

            crosspost_btn = self._find_with_fallbacks(
                (By.XPATH, "//a[contains(text(), 'Crosspost')]"),
                (By.XPATH, "//button[contains(text(), 'Crosspost')]"),
            )
            self._click(crosspost_btn)
            Timeouts.med()

            # Select subreddit
            sub_field = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "input[placeholder*='subreddit']"),
                (By.CSS_SELECTOR, "input[aria-label*='subreddit']"),
            )
            self._type_like_human(sub_field, subreddit)
            Timeouts.med()

            # Select from dropdown
            sub_option = self.driver.find_element(By.XPATH, f"//div[contains(text(), 'r/{subreddit}')]")
            self._click(sub_option)
            Timeouts.srt()

            if title:
                title_field = self.driver.find_element(By.CSS_SELECTOR, "textarea[placeholder*='Title'], textarea[name='title']")
                title_field.clear()
                self._type_like_human(title_field, title)

            submit_btn = self._find_with_fallbacks(
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(text(), 'Post')]"),
            )
            self._click(submit_btn)
            Timeouts.lng()

            return ActionResult(success=True, action="crosspost", link=link, message=f"Crossposted to r/{subreddit}")
        except NoSuchElementException as e:
            return ActionResult(success=False, action="crosspost", link=link, message=str(e))
