"""Self-healing browser element lookup for Reddit's changing UI."""

from __future__ import annotations

import json
import re
import time
import contextlib
from pathlib import Path
from typing import Any, Iterable, Optional

from selenium.common.exceptions import NoSuchElementException, WebDriverException


class SelfHealingLocator:
    """Find UI controls by intent, then cache selectors discovered at runtime."""

    CACHE_VERSION = 1

    def __init__(self, driver, config, logger=None):
        self.driver = driver
        self.config = config
        self.logger = logger
        self.cache_path = Path(
            getattr(config, "selector_cache_path", ".selector-healing/reddit_selectors.json")
        )
        self.diagnostics_dir = Path(
            getattr(config, "selector_diagnostics_dir", ".selector-healing/diagnostics")
        )

    def find(
        self,
        intent: str,
        labels: Iterable[str],
        *,
        legacy_locators: Iterable[tuple[str, str]] = (),
        reject_labels: Iterable[str] = (),
    ):
        labels = [label.lower() for label in labels]
        reject_labels = [label.lower() for label in reject_labels]

        element = self._find_cached(intent)
        if element is not None:
            self._log_info(f"Using healed selector for {intent}")
            return element

        response = self._run_console_probe(intent, labels, reject_labels)
        element = response.get("element") if isinstance(response, dict) else None
        if element is not None:
            self._persist_healed_selector(intent, labels, response)
            return element

        element = self._find_legacy(legacy_locators)
        if element is not None:
            return element

        if isinstance(response, dict):
            self._write_diagnostics(intent, response)
        return None

    def _find_cached(self, intent: str):
        cache = self._load_cache()
        selector = cache.get("selectors", {}).get(intent, {}).get("selector")
        if not selector:
            return None

        try:
            return self.driver.execute_script(self._deep_query_script(), selector)
        except WebDriverException:
            return None

    def _run_console_probe(
        self,
        intent: str,
        labels: list[str],
        reject_labels: list[str],
    ) -> dict[str, Any]:
        try:
            response = self.driver.execute_script(
                self._probe_script(),
                {"intent": intent, "labels": labels, "rejectLabels": reject_labels},
            )
            if isinstance(response, dict):
                return response
        except WebDriverException as exc:
            return {"intent": intent, "error": str(exc).splitlines()[0], "candidates": []}
        return {"intent": intent, "error": "Probe returned no structured response", "candidates": []}

    def _find_legacy(self, legacy_locators: Iterable[tuple[str, str]]):
        if not legacy_locators:
            return None

        restore_wait = getattr(self.config, "selenium_implicit_wait", 20)
        fallback_wait = getattr(self.config, "selector_fallback_wait", 1)
        try:
            self.driver.implicitly_wait(fallback_wait)
            for by, value in legacy_locators:
                try:
                    return self.driver.find_element(by, value)
                except NoSuchElementException:
                    continue
        finally:
            with contextlib.suppress(WebDriverException):
                self.driver.implicitly_wait(restore_wait)
        return None

    def _persist_healed_selector(
        self,
        intent: str,
        labels: list[str],
        response: dict[str, Any],
    ) -> None:
        selector = response.get("selector")
        if not selector:
            return

        cache = self._load_cache()
        cache.setdefault("version", self.CACHE_VERSION)
        cache.setdefault("selectors", {})
        cache["selectors"][intent] = {
            "selector": selector,
            "labels": labels,
            "evidence": response.get("evidence", {}),
            "updated_at": int(time.time()),
        }

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True))
        self._log_info(f"Healed selector for {intent}: {selector}")

    def _write_diagnostics(self, intent: str, response: dict[str, Any]) -> None:
        safe_intent = re.sub(r"[^a-zA-Z0-9_.-]+", "_", intent)
        path = self.diagnostics_dir / f"{int(time.time())}_{safe_intent}.json"
        payload = {
            "intent": intent,
            "url": response.get("url"),
            "error": response.get("error"),
            "candidates": response.get("candidates", [])[:20],
        }

        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        self._log_info(f"Wrote selector diagnostics for {intent}: {path}")

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {"version": self.CACHE_VERSION, "selectors": {}}
        try:
            data = json.loads(self.cache_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {"version": self.CACHE_VERSION, "selectors": {}}
        if not isinstance(data, dict):
            return {"version": self.CACHE_VERSION, "selectors": {}}
        data.setdefault("version", self.CACHE_VERSION)
        data.setdefault("selectors", {})
        return data

    def _log_info(self, message: str) -> None:
        if self.logger:
            self.logger.info(message)

    @staticmethod
    def _deep_query_script() -> str:
        return """
            const selector = arguments[0];

            function visible(element) {
                if (!element) {
                    return false;
                }
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.visibility !== 'hidden' &&
                    style.display !== 'none' &&
                    rect.width > 0 &&
                    rect.height > 0;
            }

            function search(root) {
                if (!root || !root.querySelectorAll) {
                    return null;
                }

                for (const element of root.querySelectorAll(selector)) {
                    if (visible(element)) {
                        return element;
                    }
                }

                for (const element of root.querySelectorAll('*')) {
                    if (element.shadowRoot) {
                        const found = search(element.shadowRoot);
                        if (found) {
                            return found;
                        }
                    }
                }

                return null;
            }

            return search(document);
        """

    @staticmethod
    def _probe_script() -> str:
        return """
            const request = arguments[0] || {};
            const intent = String(request.intent || '');
            const labels = (request.labels || []).map(label => String(label).toLowerCase());
            const rejectLabels = (request.rejectLabels || []).map(label => String(label).toLowerCase());
            const clickableSelector = 'button,[role="button"],a';
            const candidateSelector = [
                'button',
                '[role="button"]',
                '[aria-label]',
                '[id]',
                '[data-testid]',
                '[data-action-bar-action]',
                '[slot]',
                '[noun]',
                '[upvote]',
                '[downvote]',
                'faceplate-tracker',
                'shreddit-post'
            ].join(',');

            function cssEscape(value) {
                if (window.CSS && CSS.escape) {
                    return CSS.escape(value);
                }
                return String(value).replace(/["\\\\]/g, '\\\\$&');
            }

            function textFor(element) {
                return [
                    element.getAttribute('aria-label'),
                    element.getAttribute('id'),
                    element.getAttribute('data-testid'),
                    element.getAttribute('data-action-bar-action'),
                    element.getAttribute('slot'),
                    element.getAttribute('noun'),
                    element.getAttribute('title'),
                    element.textContent
                ]
                    .filter(Boolean)
                    .join(' ')
                    .replace(/\\s+/g, ' ')
                    .trim()
                    .toLowerCase();
            }

            function visible(element) {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.visibility !== 'hidden' &&
                    style.display !== 'none' &&
                    rect.width > 0 &&
                    rect.height > 0;
            }

            function closestClickable(element) {
                return element.closest(clickableSelector) || element;
            }

            function selectorFor(element, matchedLabel) {
                const tag = element.tagName.toLowerCase();
                const attrs = ['data-action-bar-action', 'data-testid', 'aria-label', 'slot', 'noun', 'id'];
                for (const attr of attrs) {
                    const value = element.getAttribute(attr);
                    if (value) {
                        return `${tag}[${attr}="${cssEscape(value)}"]`;
                    }
                }
                if (matchedLabel && element.hasAttribute(matchedLabel)) {
                    return `${tag}[${cssEscape(matchedLabel)}]`;
                }
                return null;
            }

            function scoreFor(element) {
                const text = textFor(element);
                if (!text || !visible(element)) {
                    return null;
                }

                for (const rejected of rejectLabels) {
                    if (text.includes(rejected)) {
                        return null;
                    }
                }

                let score = 0;
                let matchedLabel = '';
                for (const label of labels) {
                    if (!label) {
                        continue;
                    }
                    if (text === label) {
                        score += 100;
                        matchedLabel = label;
                    } else if (text.includes(label)) {
                        score += 50;
                        matchedLabel = label;
                    }
                }

                if (score === 0) {
                    return null;
                }

                const clickable = closestClickable(element);
                if (clickable.tagName.toLowerCase() === 'button') {
                    score += 10;
                }
                if (clickable.getAttribute('role') === 'button') {
                    score += 8;
                }

                return {element, clickable, score, matchedLabel, text};
            }

            const candidates = [];
            function search(root) {
                if (!root || !root.querySelectorAll) {
                    return;
                }

                for (const element of root.querySelectorAll(candidateSelector)) {
                    const scored = scoreFor(element);
                    if (scored) {
                        candidates.push(scored);
                    }
                }

                for (const element of root.querySelectorAll('*')) {
                    if (element.shadowRoot) {
                        search(element.shadowRoot);
                    }
                }
            }

            search(document);
            candidates.sort((left, right) => right.score - left.score);
            const best = candidates[0] || null;
            const response = {
                intent,
                url: window.location.href,
                selector: best ? selectorFor(best.clickable, best.matchedLabel) : null,
                evidence: best ? {
                    score: best.score,
                    matchedLabel: best.matchedLabel,
                    text: best.text.slice(0, 160)
                } : null,
                candidates: candidates.slice(0, 20).map(candidate => ({
                    score: candidate.score,
                    text: candidate.text.slice(0, 160),
                    tag: candidate.clickable.tagName.toLowerCase(),
                    selector: selectorFor(candidate.clickable, candidate.matchedLabel)
                }))
            };

            console.info('reddit-bot:self-healing', JSON.stringify(response));
            return Object.assign(response, {element: best ? best.clickable : null});
        """
