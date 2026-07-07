"""Human-like Reddit search action."""

from __future__ import annotations

import random
import sys
import time
from typing import Any
from urllib.parse import quote_plus, urlparse

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from .base import BaseAction, ActionResult
from bot.utils.timeouts import Timeouts


class HumanSearchAction(BaseAction):
    """Search Reddit, skim results, and open one eligible organic post."""

    name = "human_search"

    def execute(
        self,
        link: str = "",
        query: str = "",
        subreddit: str = "",
        **kwargs: Any,
    ) -> ActionResult:
        search_query = (query or link or kwargs.get("body") or kwargs.get("title") or "").strip()
        if not search_query:
            return ActionResult(
                success=False,
                action=self.name,
                link=link,
                message="Search query is required",
            )

        if self.config.dry_run:
            return ActionResult(
                success=True,
                action=self.name,
                link=search_query,
                message="Dry run",
            )

        try:
            self._open_search(search_query, subreddit=subreddit)
            self._skim_results()
            candidate, source = self._find_search_candidate(search_query)
            if not candidate:
                return ActionResult(
                    success=False,
                    action=self.name,
                    link=search_query,
                    message="No eligible non-promoted, non-archived Reddit post found",
                )
            element = candidate.get("element")
            if element is None:
                return ActionResult(
                    success=False,
                    action=self.name,
                    link=candidate.get("url", search_query),
                    message="Eligible search result could not be reselected",
                )
            self._click(element)
            Timeouts.med()
            selected_url = self.driver.current_url or candidate.get("url", "")
            return ActionResult(
                success=True,
                action=self.name,
                link=selected_url,
                message=(
                    f"Opened {source} search result: "
                    f"{candidate.get('title') or candidate.get('url')}"
                ),
            )
        except WebDriverException as exc:
            detail = str(exc).splitlines()[0]
            return ActionResult(
                success=False,
                action=self.name,
                link=search_query,
                message=f"Search failed: {detail}",
            )

    def _open_search(self, query: str, *, subreddit: str = "") -> None:
        if self._looks_like_url(query):
            self._navigate(query)
            Timeouts.med()
            return

        sub = subreddit.strip().strip("/")
        if sub.lower().startswith("r/"):
            sub = sub[2:]
        base = f"https://www.reddit.com/r/{sub}/search/" if sub else "https://www.reddit.com/search/"
        # Land on the subreddit's own page first so the in-page search box is
        # scoped to it ("Search in r/<sub>") instead of searching all of Reddit.
        home = f"https://www.reddit.com/r/{sub}/" if sub else "https://www.reddit.com/"
        self._navigate(home)
        Timeouts.med()

        search_box = self._find_search_box()
        if search_box is None:
            self.logger.info("Search input not found; falling back to direct Reddit search URL")
            self._navigate(f"{base}?q={quote_plus(query)}&type=link")
            Timeouts.med()
            return

        self._click(search_box)
        self._type_search_query_like_human(search_box, query)
        Timeouts.med()

        if "search" not in self.driver.current_url:
            self._navigate(f"{base}?q={quote_plus(query)}&type=link")
            Timeouts.med()

    def _find_search_box(self):
        locators = [
            (By.CSS_SELECTOR, "reddit-search-large"),
            (By.CSS_SELECTOR, "form[action*='search']"),
            (By.CSS_SELECTOR, "input[type='search']"),
            (By.CSS_SELECTOR, "input[name='q']"),
            (By.CSS_SELECTOR, "reddit-search-large input"),
            (By.CSS_SELECTOR, "input[placeholder*='Search']"),
            (By.CSS_SELECTOR, "input[aria-label*='Search']"),
        ]
        for locator in locators:
            try:
                element = self.driver.find_element(*locator)
                if element.is_displayed() and element.is_enabled():
                    return element
            except WebDriverException:
                continue
        return self._find_search_box_deep()

    def _find_search_box_deep(self):
        try:
            return self.driver.execute_script(
                """
                const selectors = [
                  'input[type="search"]',
                  'input[name="q"]',
                  'input[placeholder*="Search"]',
                  'input[aria-label*="Search"]',
                  'input[data-testid*="search" i]',
                  'textarea[placeholder*="Search"]',
                  '[contenteditable="true"][aria-label*="Search"]',
                  'reddit-search-large',
                  'form[action*="search"]'
                ];

                function visible(element) {
                  if (!element || !element.getBoundingClientRect) {
                    return false;
                  }
                  const style = window.getComputedStyle(element);
                  const rect = element.getBoundingClientRect();
                  return style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    rect.width > 80 &&
                    rect.height > 12 &&
                    !element.disabled &&
                    element.getAttribute('aria-disabled') !== 'true';
                }

                function collectRoots(root, output) {
                  if (!root || !root.querySelectorAll) {
                    return;
                  }
                  output.push(root);
                  for (const element of root.querySelectorAll('*')) {
                    if (element.shadowRoot) {
                      collectRoots(element.shadowRoot, output);
                    }
                  }
                }

                const roots = [];
                collectRoots(document, roots);
                const matches = [];
                for (const root of roots) {
                  for (const selector of selectors) {
                    for (const element of root.querySelectorAll(selector)) {
                      if (visible(element)) {
                        matches.push(element);
                      }
                    }
                  }
                }
                matches.sort((left, right) => {
                  const leftRect = left.getBoundingClientRect();
                  const rightRect = right.getBoundingClientRect();
                  return (leftRect.top - rightRect.top) || (rightRect.width - leftRect.width);
                });
                return matches[0] || null;
                """
            )
        except WebDriverException:
            return None

    def _type_search_query_like_human(self, element, query: str) -> None:
        """Focus, pause, type the search query in bursts, then submit."""
        Timeouts.custom(1.2, 2.4)
        target = self._focus_search_input(element) or element
        with_context_clear = random.random() < 0.65
        if with_context_clear:
            select_modifier = Keys.COMMAND if sys.platform == "darwin" else Keys.CONTROL
            self._send_search_keys(target, select_modifier, "a")
            Timeouts.custom(0.15, 0.45)
            self._send_search_keys(target, Keys.BACKSPACE)
            Timeouts.custom(0.35, 0.9)

        words = query.split(" ")
        for word_index, word in enumerate(words):
            for char_index, ch in enumerate(word):
                self._send_search_keys(target, ch)
                if char_index and random.random() < 0.12:
                    Timeouts.custom(0.25, 0.75)
                else:
                    time.sleep(random.uniform(0.06, 0.22))
            if word_index < len(words) - 1:
                self._send_search_keys(target, " ")
                Timeouts.custom(0.12, 0.45)
            if random.random() < 0.35:
                Timeouts.custom(0.45, 1.25)

        Timeouts.custom(1.4, 2.8)
        self._send_search_keys(target, Keys.ENTER)
        Timeouts.custom(0.5, 1.2)

    def _focus_search_input(self, element) -> None:
        with_script = """
            const root = arguments[0];
            const selectors = [
              'input[name="q"]',
              'input[type="search"]',
              'input[placeholder*="Find"]',
              'input[placeholder*="Search"]',
              'textarea[placeholder*="Search"]',
              '[contenteditable="true"]'
            ];
            function findInput(scope) {
              if (!scope) {
                return null;
              }
              for (const selector of selectors) {
                const found = scope.matches && scope.matches(selector) ? scope : scope.querySelector && scope.querySelector(selector);
                if (found) {
                  return found;
                }
              }
              if (scope.shadowRoot) {
                const found = findInput(scope.shadowRoot);
                if (found) {
                  return found;
                }
              }
              if (scope.querySelectorAll) {
                for (const child of scope.querySelectorAll('*')) {
                  if (child.shadowRoot) {
                    const found = findInput(child.shadowRoot);
                    if (found) {
                      return found;
                    }
                  }
                }
              }
              return null;
            }
            const input = findInput(root) || findInput(document);
            if (!input) {
              return null;
            }
            const hostRect = root && root.getBoundingClientRect ? root.getBoundingClientRect() : null;
            const inputRect = input.getBoundingClientRect();
            if (
              hostRect &&
              hostRect.width > 80 &&
              hostRect.height > 12 &&
              (inputRect.width < 40 || inputRect.height < 10)
            ) {
              const form = input.closest('form');
              if (form) {
                form.style.position = 'absolute';
                form.style.inset = '0';
                form.style.width = '100%';
                form.style.height = '100%';
                form.style.display = 'flex';
                form.style.alignItems = 'center';
                form.style.opacity = '1';
                form.style.pointerEvents = 'auto';
              }
              input.style.display = 'block';
              input.style.visibility = 'visible';
              input.style.opacity = '1';
              input.style.width = `${Math.max(160, Math.floor(hostRect.width - 48))}px`;
              input.style.height = `${Math.max(24, Math.floor(hostRect.height - 12))}px`;
              input.style.margin = '6px 16px';
              input.style.padding = '0 12px';
              input.style.textAlign = 'left';
              input.style.pointerEvents = 'auto';
            }
            const styledRect = input.getBoundingClientRect();
            if (
              hostRect &&
              hostRect.width > 80 &&
              hostRect.height > 12 &&
              (styledRect.width < 40 || styledRect.height < 10)
            ) {
              let overlay = document.querySelector('input[data-reddit-bot-search-overlay="true"]');
              if (!overlay) {
                overlay = document.createElement('input');
                overlay.setAttribute('data-reddit-bot-search-overlay', 'true');
                overlay.setAttribute('name', 'q');
                overlay.setAttribute('type', 'text');
                overlay.setAttribute('autocomplete', 'off');
                overlay.setAttribute('aria-label', 'Search Reddit');
                document.body.appendChild(overlay);
              }
              overlay.value = '';
              overlay.placeholder = input.getAttribute('placeholder') || 'Search Reddit';
              overlay.style.position = 'fixed';
              overlay.style.left = `${Math.round(hostRect.left + 16)}px`;
              overlay.style.top = `${Math.round(hostRect.top + 6)}px`;
              overlay.style.width = `${Math.max(160, Math.floor(hostRect.width - 48))}px`;
              overlay.style.height = `${Math.max(24, Math.floor(hostRect.height - 12))}px`;
              overlay.style.zIndex = '2147483647';
              overlay.style.display = 'block';
              overlay.style.visibility = 'visible';
              overlay.style.opacity = '1';
              overlay.style.background = 'var(--color-neutral-background, #fff)';
              overlay.style.color = 'var(--color-neutral-content-strong, #111)';
              overlay.style.border = '1px solid var(--color-neutral-border, #d7d7d7)';
              overlay.style.borderRadius = '999px';
              overlay.style.padding = '0 14px';
              overlay.style.font = '14px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
              overlay.style.outline = '2px solid transparent';
              overlay.style.pointerEvents = 'auto';
              overlay.addEventListener('input', () => {
                input.value = overlay.value;
                input.dispatchEvent(new Event('input', {bubbles: true}));
              });
              overlay.focus({preventScroll: true});
              return overlay;
            }
            input.focus({preventScroll: true});
            input.dispatchEvent(new Event('focus', {bubbles: true}));
            return input;
        """
        try:
            return self.driver.execute_script(with_script, element)
        except WebDriverException:
            return None

    def _send_search_keys(self, element, *keys: str) -> None:
        if self._send_overlay_keys(element, *keys):
            return
        try:
            element.send_keys(*keys)
            return
        except WebDriverException:
            self._send_active_keys(*keys)

    def _send_overlay_keys(self, element, *keys: str) -> bool:
        try:
            return bool(
                self.driver.execute_script(
                    """
                    const element = arguments[0];
                    const keys = Array.from(arguments).slice(1);
                    if (
                      !element ||
                      !element.matches ||
                      !element.matches('input[data-reddit-bot-search-overlay="true"]')
                    ) {
                      return false;
                    }
                    const realInput = document.querySelector('input[name="q"]:not([data-reddit-bot-search-overlay="true"])');
                    function sync() {
                      element.dispatchEvent(new Event('input', {bubbles: true}));
                      if (realInput) {
                        realInput.value = element.value;
                        realInput.dispatchEvent(new Event('input', {bubbles: true}));
                      }
                    }
                    if (keys.length === 2 && (keys[0] === '\\uE03D' || keys[0] === '\\uE009') && String(keys[1]).toLowerCase() === 'a') {
                      element.value = '';
                      sync();
                      return true;
                    }
                    for (const key of keys) {
                      if (key === '\\uE003') {
                        element.value = element.value.slice(0, -1);
                      } else if (key === '\\uE007') {
                        element.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
                        element.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter', bubbles: true}));
                      } else {
                        element.value += key;
                      }
                      sync();
                    }
                    return true;
                    """,
                    element,
                    *keys,
                )
            )
        except WebDriverException:
            return False

    def _send_active_keys(self, *keys: str) -> None:
        actions = ActionChains(self.driver)
        if len(keys) == 2 and keys[0] in (Keys.COMMAND, Keys.CONTROL):
            actions.key_down(keys[0]).send_keys(keys[1]).key_up(keys[0]).perform()
            return
        actions.send_keys(*keys).perform()

    def _skim_results(self) -> None:
        from bot.utils.mouse import human_reading_scroll

        human_reading_scroll(self.driver)
        for _ in range(random.randint(1, 3)):
            self.driver.execute_script(
                "window.scrollBy({top: arguments[0], left: 0, behavior: 'smooth'});",
                random.randint(260, 620),
            )
            Timeouts.custom(0.4, 1.2)
        self.driver.execute_script(
            "window.scrollBy({top: arguments[0], left: 0, behavior: 'smooth'});",
            -random.randint(120, 380),
        )
        Timeouts.custom(0.3, 0.9)

    def _find_search_candidate(self, query: str) -> tuple[dict[str, Any] | None, str]:
        candidate = self._find_extension_search_candidate(query)
        if candidate:
            return candidate, "extension"
        candidate = self._find_dom_search_candidate()
        if candidate:
            return candidate, "dom"
        return None, ""

    def collect_candidates(
        self,
        query: str,
        *,
        subreddit: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Run a human-like search and return a ranked list of organic post URLs.

        Unlike :meth:`execute`, this does not open a post — it returns the ranked
        candidate URLs so the caller (``search_upvote``) can fall through to the
        next result when a selected post turns out deleted, removed, or archived.
        """
        limit = max(1, int(limit))
        pool_size = max(limit * 3, limit)
        self._open_search(query, subreddit=subreddit)
        self._skim_results()
        candidates = self._collect_extension_candidates(query, pool_size)
        if not candidates:
            candidates = self._collect_dom_candidates(pool_size)
        candidates = self._augment_and_rank(candidates)
        return candidates[:limit]

    def _augment_and_rank(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Attach each candidate's post age (read from the live search cards) and
        move likely-archived (old) posts to the back so the votable ones are tried
        first. Reordering only — no candidate is dropped, so fall-through still
        covers every result.
        """
        if not candidates:
            return candidates
        age_map: Any = None
        try:
            age_map = self.driver.execute_script(self._age_map_script())
        except WebDriverException:
            age_map = None
        if isinstance(age_map, dict):
            for candidate in candidates:
                path = urlparse(candidate.get("url", "")).path.rstrip("/").lower()
                age = age_map.get(path)
                candidate["age_days"] = int(age) if isinstance(age, (int, float)) else None
        recent_days = max(1, int(getattr(self.config, "search_upvote_recent_days", 365)))

        def is_old(candidate: dict[str, Any]) -> int:
            age = candidate.get("age_days")
            return 1 if (isinstance(age, int) and age > recent_days) else 0

        # Stable sort keeps the confidence order within the recent/old groups.
        candidates.sort(key=is_old)
        return candidates

    @staticmethod
    def _age_map_script() -> str:
        return """
            function ageDaysFor(card) {
              const el = card.querySelector && (
                card.querySelector('time[datetime]') ||
                card.querySelector('faceplate-timeago[ts]') ||
                card.querySelector('[data-testid="post_timestamp"]')
              );
              let ms = null;
              if (el) {
                const iso = el.getAttribute('datetime') || el.getAttribute('ts');
                const parsed = iso ? Date.parse(iso) : NaN;
                if (!isNaN(parsed)) ms = parsed;
              }
              if (ms === null) {
                const text = String((card.textContent || '')).toLowerCase();
                const m = text.match(/(\\d+)\\s*(yr|year|years|mo|month|months|wk|week|weeks|day|days|hr|hour|hours|min|minute|minutes)\\b/);
                if (!m) return null;
                const n = parseInt(m[1], 10);
                const unit = m[2];
                if (/yr|year/.test(unit)) return n * 365;
                if (/mo|month/.test(unit)) return n * 30;
                if (/wk|week/.test(unit)) return n * 7;
                if (/day/.test(unit)) return n;
                return 0;
              }
              return Math.max(0, Math.round((Date.now() - ms) / 86400000));
            }
            const out = {};
            for (const anchor of document.querySelectorAll('a[href*="/comments/"]')) {
              const card = anchor.closest('shreddit-post, article, [data-testid="post-container"], search-telemetry-tracker') || anchor;
              let path;
              try { path = new URL(anchor.getAttribute('href'), window.location.href).pathname; }
              catch (_e) { continue; }
              const key = path.replace(/\\/+$/, '').toLowerCase();
              if (key in out) continue;
              const age = ageDaysFor(card);
              if (age !== null) out[key] = age;
            }
            return out;
        """

    def _collect_extension_candidates(self, query: str, limit: int) -> list[dict[str, Any]]:
        if not getattr(self.config, "chrome_extension_healer_enabled", False):
            return []

        from bot.utils.chrome_extension_bridge import ChromeExtensionBridge

        bridge = ChromeExtensionBridge(
            self.driver,
            timeout_ms=getattr(self.config, "chrome_extension_bridge_timeout_ms", 1500),
        )
        result = bridge.find_search_result(query, max_results=max(limit * 3, 15))
        if not result.ok:
            if result.error:
                self.logger.info(f"Chrome extension search healer unavailable: {result.error}")
            return []

        min_confidence = 0.62
        collected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in result.candidates:  # already sorted by confidence desc
            if candidate is None or not candidate.url:
                continue
            if candidate.confidence < min_confidence:
                continue
            state = candidate.state or {}
            if (
                state.get("promoted")
                or state.get("archived")
                or state.get("deleted")
                or state.get("removed")
            ):
                continue
            key = candidate.url.rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            collected.append(
                {
                    "url": candidate.url,
                    "title": candidate.title,
                    "confidence": candidate.confidence,
                    "subreddit": candidate.subreddit,
                    "source": "extension",
                }
            )
            if len(collected) >= limit:
                break
        return collected

    def _collect_dom_candidates(self, limit: int) -> list[dict[str, Any]]:
        payload = self.driver.execute_script(
            """
            const limit = Number(arguments[0]) || 5;
            function visible(element) {
              if (!element || !element.getBoundingClientRect) return false;
              const style = window.getComputedStyle(element);
              const rect = element.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' &&
                rect.width > 0 && rect.height > 0;
            }
            function text(element) {
              return String((element && element.textContent) || '').replace(/\\s+/g, ' ').trim();
            }
            function attrs(element) {
              if (!element || !element.getAttribute) return '';
              return ['aria-label', 'data-testid', 'data-adclicklocation', 'data-promoted', 'class']
                .map(attr => element.getAttribute(attr)).filter(Boolean).join(' ');
            }
            function rejected(card) {
              const joined = `${text(card)} ${attrs(card)}`.toLowerCase();
              return /\\b(promoted|sponsored|advertise|advertisement|ad)\\b/.test(joined) ||
                /\\b(archived|this post is archived)\\b/.test(joined) ||
                /\\b(deleted by user|\\[deleted\\]|removed by moderators|removed post|\\[removed\\])\\b/.test(joined);
            }
            const anchors = Array.from(document.querySelectorAll('a[href*="/comments/"]'));
            const out = [];
            const seen = new Set();
            for (const anchor of anchors) {
              if (!visible(anchor)) continue;
              const card = anchor.closest('shreddit-post, article, [data-testid="post-container"], search-telemetry-tracker') || anchor;
              if (!visible(card) || rejected(card)) continue;
              const href = new URL(anchor.getAttribute('href'), window.location.href).href;
              const key = href.replace(/\\/+$/, '').toLowerCase();
              if (seen.has(key)) continue;
              seen.add(key);
              out.push({url: href, title: text(anchor) || text(card)});
              if (out.length >= limit) break;
            }
            return out;
            """,
            limit,
        )
        if not isinstance(payload, list):
            return []
        collected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not url:
                continue
            key = str(url).rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            collected.append(
                {
                    "url": url,
                    "title": item.get("title") or url,
                    "confidence": None,
                    "source": "dom",
                }
            )
            if len(collected) >= limit:
                break
        return collected

    def _find_extension_search_candidate(self, query: str) -> dict[str, Any] | None:
        if not getattr(self.config, "chrome_extension_healer_enabled", False):
            return None

        from bot.utils.chrome_extension_bridge import ChromeExtensionBridge

        bridge = ChromeExtensionBridge(
            self.driver,
            timeout_ms=getattr(self.config, "chrome_extension_bridge_timeout_ms", 1500),
        )
        result = bridge.find_search_result(query)
        candidate = result.best_candidate
        min_confidence = 0.62
        if not result.ok or candidate is None or candidate.confidence < min_confidence:
            if result.error:
                self.logger.info(f"Chrome extension search healer unavailable: {result.error}")
            return None
        if (
            candidate.state.get("promoted") or
            candidate.state.get("archived") or
            candidate.state.get("deleted") or
            candidate.state.get("removed")
        ):
            return None

        element = bridge.element_for_search_result(candidate)
        if element is None:
            return None
        return {
            "element": element,
            "url": candidate.url,
            "title": candidate.title,
            "confidence": candidate.confidence,
            "evidence": candidate.evidence,
        }

    def _find_dom_search_candidate(self) -> dict[str, Any] | None:
        payload = self.driver.execute_script(
            """
            function visible(element) {
              if (!element || !element.getBoundingClientRect) return false;
              const style = window.getComputedStyle(element);
              const rect = element.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' &&
                rect.width > 0 && rect.height > 0;
            }
            function text(element) {
              return String((element && element.textContent) || '').replace(/\\s+/g, ' ').trim();
            }
            function attrs(element) {
              if (!element || !element.getAttribute) return '';
              return ['aria-label', 'data-testid', 'data-adclicklocation', 'data-promoted', 'class']
                .map(attr => element.getAttribute(attr)).filter(Boolean).join(' ');
            }
            function rejected(card) {
              const joined = `${text(card)} ${attrs(card)}`.toLowerCase();
              return /\\b(promoted|sponsored|advertise|advertisement|ad)\\b/.test(joined) ||
                /\\b(archived|this post is archived)\\b/.test(joined) ||
                /\\b(deleted by user|\\[deleted\\]|removed by moderators|removed post|\\[removed\\])\\b/.test(joined);
            }
            const anchors = Array.from(document.querySelectorAll('a[href*="/comments/"]'));
            for (const anchor of anchors) {
              if (!visible(anchor)) continue;
              const card = anchor.closest('shreddit-post, article, [data-testid="post-container"], search-telemetry-tracker') || anchor;
              if (!visible(card) || rejected(card)) continue;
              const href = new URL(anchor.getAttribute('href'), window.location.href).href;
              const selector = anchor.id ? `a#${CSS.escape(anchor.id)}` : '';
              return {url: href, title: text(anchor) || text(card), selector};
            }
            return null;
            """
        )
        if not isinstance(payload, dict) or not payload.get("url"):
            return None
        element = self._element_for_url(payload["url"], payload.get("selector") or "")
        if element is None:
            return None
        return {
            "element": element,
            "url": payload["url"],
            "title": payload.get("title") or payload["url"],
        }

    def _element_for_url(self, url: str, selector: str = ""):
        try:
            if selector:
                element = self.driver.find_element(By.CSS_SELECTOR, selector)
                if element.is_displayed():
                    return element
        except WebDriverException:
            pass

        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        try:
            return self.driver.find_element(By.CSS_SELECTOR, f'a[href*="{path}"]')
        except WebDriverException:
            return None

    @staticmethod
    def _looks_like_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)


class SearchUpvoteAction(BaseAction):
    """Search Reddit and upvote the post selected by the search action."""

    name = "search_upvote"

    def execute(
        self,
        link: str = "",
        query: str = "",
        subreddit: str = "",
        **kwargs: Any,
    ) -> ActionResult:
        search_query = (query or link or kwargs.get("body") or kwargs.get("title") or "").strip()
        if not search_query:
            return ActionResult(
                success=False,
                action=self.name,
                link=link,
                message="Search query is required",
            )

        if self.config.dry_run:
            return ActionResult(
                success=True,
                action=self.name,
                link=search_query,
                message="Dry run: would search Reddit and upvote the selected post",
            )

        max_candidates = max(1, int(getattr(self.config, "search_upvote_max_candidates", 5)))
        searcher = HumanSearchAction(self.driver, self.config, self.logger)
        try:
            candidates = searcher.collect_candidates(
                search_query,
                subreddit=subreddit,
                limit=max_candidates,
            )
        except WebDriverException as exc:
            return ActionResult(
                success=False,
                action=self.name,
                link=search_query,
                message=f"Search failed: {str(exc).splitlines()[0]}",
            )

        if not candidates:
            return ActionResult(
                success=False,
                action=self.name,
                link=search_query,
                message="No eligible non-promoted, non-archived Reddit post found",
            )

        from .vote import VoteAction

        skipped: list[str] = []          # human-readable skip trace, e.g. "[1] archived"
        attempts_detail: list[str] = []  # full messages for the failure summary
        last_screenshot: str | None = None
        total = len(candidates)
        # Global budget of extra attempts for transient (probably-recoverable)
        # failures. Bounds total vote attempts to total + retry_budget.
        retry_budget = max(0, int(getattr(self.config, "search_upvote_transient_retries", 1)))
        for index, candidate in enumerate(candidates, start=1):
            url = (candidate.get("url") or "").strip()
            if not url:
                continue
            title = candidate.get("title") or url
            source = candidate.get("source") or "search"
            age_days = candidate.get("age_days")

            attempts_here = 0
            while True:
                vote_result = VoteAction(self.driver, self.config, self.logger).execute(
                    link=url, upvote=True
                )
                attempts_here += 1
                last_screenshot = vote_result.screenshot_path or last_screenshot
                if (
                    vote_result.success
                    or self._is_definitive_failure(vote_result.message)
                    or retry_budget <= 0
                ):
                    break
                # Transient failure and budget available: retry the same post.
                retry_budget -= 1
                self.logger.info(
                    f"search_upvote candidate {index}/{total} transient failure, "
                    f"retrying same post: {vote_result.message}"
                )
                Timeouts.med()

            if vote_result.success:
                retry_note = f" (retried {attempts_here - 1}x)" if attempts_here > 1 else ""
                skip_note = f" after skipping {', '.join(skipped)}" if skipped else ""
                return ActionResult(
                    success=True,
                    action=self.name,
                    link=url,
                    message=(
                        f"Upvoted {source} search result {index}/{total} "
                        f"({title}); {vote_result.message}{retry_note}{skip_note}"
                    ),
                    screenshot_path=vote_result.screenshot_path,
                )

            reason = self._short_reason(vote_result.message)
            kind = "definitive" if self._is_definitive_failure(vote_result.message) else "transient"
            self.logger.info(
                f"search_upvote candidate {index}/{total} {kind} skip "
                f"(age_days={age_days}, attempts={attempts_here}, {url}): {vote_result.message}"
            )
            skipped.append(f"[{index}] {reason}")
            attempts_detail.append(f"[{index}] {url}: {vote_result.message}")
            if index < total:
                Timeouts.med()

        return ActionResult(
            success=False,
            action=self.name,
            link=(candidates[0].get("url") or search_query),
            message=(
                f"Upvote failed after trying {len(attempts_detail)} search result(s) "
                f"[{'; '.join(skipped)}]: " + " | ".join(attempts_detail)
            ),
            screenshot_path=last_screenshot,
        )

    @staticmethod
    def _is_definitive_failure(message: str) -> bool:
        """True when the post genuinely cannot be voted (skip to the next candidate).

        Everything else — vote button not found, click did not register, could not
        open the post — is treated as transient and worth one retry, because the
        post itself is probably still votable. Matching is anchored on VoteAction's
        certainty phrases so a hedged transient message ("post may be unavailable
        or Reddit layout changed") is NOT misread as definitive.
        """
        text = (message or "").lower()
        return "voting was not attempted" in text or "control is disabled" in text

    @staticmethod
    def _short_reason(message: str) -> str:
        """Condense a vote failure message into a one-word skip reason."""
        text = (message or "").lower()
        for key in (
            "deleted",
            "removed",
            "archived",
            "unavailable",
            "disabled",
            "not found",
            "could not open",
        ):
            if key in text:
                return key
        return ((message or "").split(";")[0].strip()[:48]) or "unknown"
