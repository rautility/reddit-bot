"""Vote action — upvote or downvote a post."""

from __future__ import annotations

import contextlib
from typing import Any

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, WebDriverException

from .base import BaseAction, ActionResult
from bot.utils.timeouts import Timeouts


class VoteAction(BaseAction):
    name = "vote"

    def execute(self, link: str = "", upvote: bool = True, **kwargs: Any) -> ActionResult:
        vote_type = "upvote" if upvote else "downvote"
        self.logger.info(f"{'Upvoting' if upvote else 'Downvoting'} {link}")

        if self.config.dry_run:
            return ActionResult(success=True, action=vote_type, link=link, message="Dry run")

        try:
            self._navigate(link)
            Timeouts.med()
            self._handle_nsfw()
        except WebDriverException as exc:
            return ActionResult(
                success=False,
                action=vote_type,
                link=link,
                message=self._short_error("Could not open post", exc),
            )

        label = "upvote" if upvote else "downvote"
        self._last_extension_vote_candidate = None
        self._last_extension_disabled_vote_candidate = None
        self._last_extension_confirm_response = None
        self._last_click_diagnostics = None
        button = self._find_extension_vote_button(label, link)
        if button is None and self._last_extension_disabled_vote_candidate is not None:
            return ActionResult(
                success=False,
                action=vote_type,
                link=link,
                message=f"{label.title()} control is disabled; post may be archived or voting is unavailable",
            )
        if button is None:
            button = self._find_vote_button(label, upvote)
        if button is None:
            return ActionResult(
                success=False,
                action=vote_type,
                link=link,
                message=(
                    f"Could not find {label} button; post may be unavailable "
                    "or Reddit layout changed"
                ),
            )

        try:
            self._last_click_diagnostics = self._click(button)
            Timeouts.med()
        except WebDriverException as exc:
            return ActionResult(
                success=False,
                action=vote_type,
                link=link,
                message=self._short_error("Could not click vote button", exc),
            )

        if self._extension_vote_is_registered(label, link) or self._vote_is_registered(button, label):
            return ActionResult(success=True, action=vote_type, link=link, message="Vote registered")

        return ActionResult(
            success=False,
            action=vote_type,
            link=link,
            message=self._vote_failure_message(label),
        )

    def _find_vote_button(self, label: str, upvote: bool):
        uppercase = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        lowercase = "abcdefghijklmnopqrstuvwxyz"
        aria_label = f"translate(@aria-label, '{uppercase}', '{lowercase}')"
        element_id = f"translate(@id, '{uppercase}', '{lowercase}')"
        test_id = f"translate(@data-testid, '{uppercase}', '{lowercase}')"
        index = 1 if upvote else 2

        locators = [
            (By.CSS_SELECTOR, f"button[aria-label='{label}']"),
            (By.XPATH, f"//button[contains({aria_label}, '{label}')]"),
            (By.XPATH, f"//shreddit-post//button[contains({aria_label}, '{label}')]"),
            (By.XPATH, f"//button[contains({element_id}, '{label}')]"),
            (By.XPATH, f"//button[contains({test_id}, '{label}')]"),
            (
                By.XPATH,
                f"/html/body/div[1]/div/div[2]/div[2]/div/div/div/div[2]/div[3]/div[1]/div[3]/div[1]/div/div[1]/div/button[{index}]",
            ),
        ]

        return self._find_self_healing(
            label,
            [label],
            legacy_locators=locators,
            reject_labels=["downvote" if upvote else "upvote"],
        )

    def _find_extension_vote_button(self, label: str, link: str):
        if not getattr(self.config, "chrome_extension_healer_enabled", False):
            return None

        from bot.utils.chrome_extension_bridge import ChromeExtensionBridge

        bridge = ChromeExtensionBridge(
            self.driver,
            timeout_ms=getattr(self.config, "chrome_extension_bridge_timeout_ms", 1500),
        )
        result = bridge.find_control(
            label,
            post_url=link,
            min_confidence=getattr(self.config, "chrome_extension_min_confidence", 0.72),
        )
        candidate = result.best_candidate
        if not result.ok or candidate is None:
            if result.error:
                self.logger.info(f"Chrome extension healer unavailable for {label}: {result.error}")
            return None

        min_confidence = getattr(self.config, "chrome_extension_min_confidence", 0.72)
        if candidate.confidence < min_confidence:
            self.logger.info(
                f"Chrome extension healer skipped low-confidence {label} candidate "
                f"({candidate.confidence:.2f} < {min_confidence:.2f})"
            )
            return None
        if candidate.state.get("disabled"):
            self._last_extension_disabled_vote_candidate = candidate
            self.logger.info(
                f"Chrome extension healer found {label} control but it is disabled"
            )
            return None

        element = bridge.element_for_candidate(candidate, post_url=link)
        if element is None:
            self.logger.info(
                f"Chrome extension healer found {label} candidate but Selenium could not reselect it"
            )
            return None

        self._last_extension_vote_candidate = (bridge, candidate)
        self.logger.info(
            f"Chrome extension healer selected {label} control "
            f"({candidate.confidence:.2f} confidence)"
        )
        return element

    def _extension_vote_is_registered(self, label: str, link: str) -> bool:
        bridge_candidate = getattr(self, "_last_extension_vote_candidate", None)
        if not bridge_candidate:
            return False

        bridge, candidate = bridge_candidate
        response = bridge.confirm_control_state(
            label,
            selector=candidate.selector,
            candidate_id=candidate.id,
            post_url=link,
            expected_pressed=True,
        )
        self._last_extension_confirm_response = response
        if response.get("ok") and response.get("confirmed"):
            return True
        if response.get("error"):
            self.logger.info(f"Chrome extension healer could not confirm {label}: {response['error']}")
        return False

    @staticmethod
    def _short_error(prefix: str, exc: Exception) -> str:
        detail = str(exc).splitlines()[0]
        return f"{prefix}: {detail}" if detail else prefix

    def _vote_is_registered(self, button, label: str) -> bool:
        with contextlib.suppress(Exception):
            if button.get_attribute("aria-pressed") == "true":
                return True

        with contextlib.suppress(WebDriverException):
            return bool(
                self.driver.execute_script(
                    """
                    const button = arguments[0];
                    const label = arguments[1].toLowerCase();
                    if (!button) {
                        return false;
                    }

                    function attributeText(element) {
                        if (!element || !element.getAttribute) {
                            return '';
                        }
                        return [
                            element.getAttribute('aria-pressed'),
                            element.getAttribute('aria-selected'),
                            element.getAttribute('data-state'),
                            element.getAttribute('data-vote-state'),
                            element.getAttribute('class'),
                            element.getAttribute('aria-label'),
                            element.getAttribute('data-action-bar-action')
                        ].filter(Boolean).join(' ').toLowerCase();
                    }

                    function isPressed(text) {
                        if (text.includes('true') || text.includes('active') || text.includes('selected')) {
                            return true;
                        }
                        if (label === 'upvote') {
                            return text.includes('upvoted') ||
                                text.includes('text-upvote') ||
                                text.includes('bg-upvote') ||
                                text.includes('vote-state-up');
                        }

                        return text.includes('downvoted') ||
                            text.includes('text-downvote') ||
                            text.includes('bg-downvote') ||
                            text.includes('vote-state-down');
                    }

                    const targets = [];
                    let current = button;
                    for (let depth = 0; current && depth < 6; depth += 1) {
                        targets.push(current);
                        current = current.parentElement;
                    }
                    if (button.querySelectorAll) {
                        for (const child of button.querySelectorAll('[aria-pressed],[aria-selected],[data-state],[data-vote-state],[class]')) {
                            targets.push(child);
                        }
                    }

                    return targets.some(target => isPressed(attributeText(target)));
                    """,
                    button,
                    label,
                )
            )
        return False

    def _vote_failure_message(self, label: str) -> str:
        message = f"Vote click did not register as active {label}"

        diagnostics = getattr(self, "_last_click_diagnostics", None)
        if isinstance(diagnostics, dict):
            topmost = diagnostics.get("deepTopmost") or diagnostics.get("topmost") or {}
            center = diagnostics.get("center") or {}
            topmost_attrs = topmost.get("attrs") or {}
            topmost_action = topmost_attrs.get("data-action-bar-action") or topmost_attrs.get("aria-label")
            message += (
                f"; click center=({center.get('x')},{center.get('y')}) "
                f"topmostMatches={diagnostics.get('topmostMatches')}"
            )
            if topmost.get("tag"):
                message += f" topmost={topmost.get('tag')}"
            if topmost_action:
                message += f"[{topmost_action}]"

        response = getattr(self, "_last_extension_confirm_response", None)
        if isinstance(response, dict):
            state = response.get("state") or {}
            message += (
                f"; healerConfirmed={response.get('confirmed')} "
                f"ariaPressed={state.get('ariaPressed')} dataState={state.get('dataState')}"
            )

        return message

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
