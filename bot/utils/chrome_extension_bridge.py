"""Bridge client for the Reddit healer Chrome extension."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from selenium.common.exceptions import WebDriverException


@dataclass
class ChromeControlCandidate:
    """A DOM control candidate returned by the Chrome extension."""

    id: str = ""
    intent: str = ""
    selector: str = ""
    confidence: float = 0.0
    text: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    bounding_box: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChromeControlCandidate":
        return cls(
            id=str(data.get("id") or ""),
            intent=str(data.get("intent") or ""),
            selector=str(data.get("selector") or ""),
            confidence=float(data.get("confidence") or 0.0),
            text=str(data.get("text") or ""),
            attributes=data.get("attributes") if isinstance(data.get("attributes"), dict) else {},
            bounding_box=data.get("boundingBox") if isinstance(data.get("boundingBox"), dict) else {},
            state=data.get("state") if isinstance(data.get("state"), dict) else {},
            evidence=data.get("evidence") if isinstance(data.get("evidence"), list) else [],
        )


@dataclass
class ChromeControlResult:
    """Structured result from a bridge control lookup."""

    ok: bool
    intent: str = ""
    url: str = ""
    error: str = ""
    best_candidate: Optional[ChromeControlCandidate] = None
    candidates: list[ChromeControlCandidate] = field(default_factory=list)
    near_misses: list[ChromeControlCandidate] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    meets_min_confidence: bool = False
    scan_pass: int = 0
    scan_passes: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChromeControlResult":
        candidates = [
            ChromeControlCandidate.from_dict(candidate)
            for candidate in data.get("candidates", [])
            if isinstance(candidate, dict)
        ]
        best = data.get("bestCandidate")
        best_candidate = (
            ChromeControlCandidate.from_dict(best)
            if isinstance(best, dict)
            else candidates[0] if candidates else None
        )
        near_misses = [
            ChromeControlCandidate.from_dict(candidate)
            for candidate in data.get("nearMisses", [])
            if isinstance(candidate, dict)
        ]
        return cls(
            ok=bool(data.get("ok")),
            intent=str(data.get("intent") or ""),
            url=str(data.get("url") or ""),
            error=str(data.get("error") or ""),
            best_candidate=best_candidate,
            candidates=candidates,
            near_misses=near_misses,
            events=data.get("events") if isinstance(data.get("events"), list) else [],
            meets_min_confidence=bool(data.get("meetsMinConfidence")),
            scan_pass=int(data.get("scanPass") or 0),
            scan_passes=int(data.get("scanPasses") or 0),
            raw=data,
        )


class ChromeExtensionBridge:
    """Send structured requests to the content-script bridge."""

    def __init__(self, driver, timeout_ms: int = 1500):
        self.driver = driver
        self.timeout_ms = timeout_ms

    def ping(self) -> bool:
        response = self.request("ping", {})
        return bool(response.get("ok"))

    def find_control(
        self,
        intent: str,
        *,
        post_url: str = "",
        min_confidence: float = 0.72,
    ) -> ChromeControlResult:
        response = self.request(
            "find_control",
            {
                "intent": intent,
                "postUrl": post_url,
                "minConfidence": min_confidence,
            },
        )
        return ChromeControlResult.from_dict(response)

    def confirm_control_state(
        self,
        intent: str,
        *,
        selector: str = "",
        candidate_id: str = "",
        post_url: str = "",
        expected_pressed: bool = True,
    ) -> dict[str, Any]:
        return self.request(
            "confirm_control_state",
            {
                "intent": intent,
                "selector": selector,
                "candidateId": candidate_id,
                "postUrl": post_url,
                "expectedPressed": expected_pressed,
            },
        )

    def element_for_candidate(self, candidate: ChromeControlCandidate, *, post_url: str = ""):
        if not candidate.selector:
            return None
        try:
            return self.driver.execute_script(
                self._deep_query_script(),
                candidate.selector,
                candidate.bounding_box,
                post_url,
            )
        except WebDriverException:
            return None

    def request(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.driver.execute_async_script(
                self._request_script(),
                command,
                payload,
                self.timeout_ms,
            )
        except WebDriverException as exc:
            return {"ok": False, "command": command, "error": str(exc).splitlines()[0]}

        if isinstance(response, dict):
            return response
        return {"ok": False, "command": command, "error": "Bridge returned no structured response"}

    @staticmethod
    def _request_script() -> str:
        return """
            const command = arguments[0];
            const payload = arguments[1] || {};
            const timeoutMs = Number(arguments[2] || 1500);
            const done = arguments[arguments.length - 1];
            const requestId = `reddit-bot-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            const requestChannel = 'reddit-bot-healer:request';
            const responseChannel = 'reddit-bot-healer:response';
            let settled = false;

            function finish(response) {
                if (settled) {
                    return;
                }
                settled = true;
                window.removeEventListener('message', onMessage);
                done(Object.assign({requestId, command}, response || {}));
            }

            function onMessage(event) {
                if (event.source !== window) {
                    return;
                }
                const data = event.data || {};
                if (data.channel !== responseChannel || data.requestId !== requestId) {
                    return;
                }
                finish(data.response || {});
            }

            window.addEventListener('message', onMessage);
            window.postMessage({channel: requestChannel, requestId, command, payload}, '*');
            window.setTimeout(() => finish({
                ok: false,
                error: 'Chrome extension bridge timed out; is the Reddit healer extension loaded?'
            }), timeoutMs);
        """

    @staticmethod
    def _deep_query_script() -> str:
        return """
            const selector = arguments[0];
            const wantedRect = arguments[1] || {};
            const postUrl = arguments[2] || '';

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

            function normalizeUrl(value) {
                try {
                    const url = new URL(value, window.location.href);
                    return `${url.hostname}${url.pathname}`.replace(/\\/+$/, '').toLowerCase();
                } catch (_error) {
                    return String(value || '').replace(/\\/+$/, '').toLowerCase();
                }
            }

            function elementMatchesPostUrl(element, url) {
                if (!url || !element || !element.getAttribute) {
                    return false;
                }
                const wanted = normalizeUrl(url);
                const values = [
                    element.getAttribute('permalink'),
                    element.getAttribute('content-href'),
                    element.getAttribute('href')
                ].filter(Boolean);
                for (const anchor of element.querySelectorAll ? element.querySelectorAll('a[href]') : []) {
                    values.push(anchor.href);
                }
                return values.some(value => {
                    const normalized = normalizeUrl(value);
                    return normalized.includes(wanted) || wanted.includes(normalized);
                });
            }

            function postScope(url) {
                if (!url) {
                    return document;
                }
                const selectors = [
                    'shreddit-post',
                    'article',
                    '[data-testid="post-container"]',
                    '[slot="post"]',
                    '[permalink]',
                    '[content-href]'
                ];
                for (const element of document.querySelectorAll(selectors.join(','))) {
                    if (elementMatchesPostUrl(element, url)) {
                        return element;
                    }
                }
                return document;
            }

            function collectRoots(root, output) {
                if (!root || !root.querySelectorAll) {
                    return;
                }
                output.push(root);
                if (root.shadowRoot) {
                    collectRoots(root.shadowRoot, output);
                }
                for (const element of root.querySelectorAll('*')) {
                    if (element.shadowRoot) {
                        collectRoots(element.shadowRoot, output);
                    }
                }
            }

            function rectDistance(element) {
                if (
                    typeof wantedRect.x !== 'number' ||
                    typeof wantedRect.y !== 'number' ||
                    typeof wantedRect.width !== 'number' ||
                    typeof wantedRect.height !== 'number'
                ) {
                    return 0;
                }
                const rect = element.getBoundingClientRect();
                return Math.abs(Math.round(rect.x) - wantedRect.x) +
                    Math.abs(Math.round(rect.y) - wantedRect.y) +
                    Math.abs(Math.round(rect.width) - wantedRect.width) +
                    Math.abs(Math.round(rect.height) - wantedRect.height);
            }

            function search(root) {
                const roots = [];
                collectRoots(root, roots);
                const matches = [];
                for (const searchRoot of roots) {
                    for (const element of searchRoot.querySelectorAll(selector)) {
                        if (visible(element)) {
                            matches.push(element);
                        }
                    }
                }
                if (!matches.length) {
                    return null;
                }
                matches.sort((left, right) => rectDistance(left) - rectDistance(right));
                return matches[0];
            }

            return search(postScope(postUrl)) || search(document);
        """
