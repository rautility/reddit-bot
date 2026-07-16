"""Non-mutating Reddit browsing actions."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from selenium.common.exceptions import WebDriverException

from .base import ActionResult, BaseAction


class HumanScrollAction(BaseAction):
    """Open a Reddit URL and perform a human-like reading scroll."""

    name = "human_scroll"

    def execute(
        self,
        link: str = "",
        **kwargs: Any,
    ) -> ActionResult:
        url = (link or kwargs.get("body") or "").strip()
        if not url:
            return ActionResult(
                success=False,
                action=self.name,
                link=link,
                message="Reddit URL is required",
            )
        if not self._is_reddit_url(url):
            return ActionResult(
                success=False,
                action=self.name,
                link=url,
                message="human_scroll requires a reddit.com URL",
            )

        if self.config.dry_run:
            return ActionResult(
                success=True,
                action=self.name,
                link=url,
                message="Dry run: would open the Reddit URL and perform a human-like reading scroll",
            )

        try:
            self._navigate(url)
            from bot.utils.mouse import human_reading_scroll

            movements = human_reading_scroll(self.driver)
            final_url = self.driver.current_url or url
            return ActionResult(
                success=True,
                action=self.name,
                link=final_url,
                message=f"Opened Reddit URL and completed {len(movements)} reading scroll movement(s)",
                details={"requestedUrl": url, "finalUrl": final_url, "scrollMovements": movements},
            )
        except WebDriverException as exc:
            return ActionResult(
                success=False,
                action=self.name,
                link=url,
                message=f"Scroll failed: {str(exc).splitlines()[0]}",
            )

    @staticmethod
    def _is_reddit_url(url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return parsed.scheme in ("http", "https") and (host == "reddit.com" or host.endswith(".reddit.com"))
