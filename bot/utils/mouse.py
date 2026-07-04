"""Browser pointer click helpers."""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from selenium.webdriver.remote.webelement import WebElement
    from selenium.webdriver.remote.webdriver import WebDriver

try:
    import numpy as np
    import bezier

    def _bezier_curve_points(
        start: tuple[int, int],
        end: tuple[int, int],
        num_points: int = 20,
    ) -> list[tuple[int, int]]:
        """Generate points along a Bezier curve between start and end."""
        # Add 1-2 random control points for natural movement
        ctrl1 = (
            start[0] + random.randint(-50, 50) + (end[0] - start[0]) // 3,
            start[1] + random.randint(-50, 50) + (end[1] - start[1]) // 3,
        )
        ctrl2 = (
            start[0] + random.randint(-50, 50) + 2 * (end[0] - start[0]) // 3,
            start[1] + random.randint(-50, 50) + 2 * (end[1] - start[1]) // 3,
        )

        nodes = np.asfortranarray([
            [start[0], ctrl1[0], ctrl2[0], end[0]],
            [start[1], ctrl1[1], ctrl2[1], end[1]],
        ], dtype=float)
        curve = bezier.Curve(nodes, degree=3)

        t_values = np.linspace(0.0, 1.0, num_points)
        points = curve.evaluate_multi(t_values)
        return [(int(points[0, i]), int(points[1, i])) for i in range(num_points)]

    HAS_BEZIER = True
except ImportError:
    HAS_BEZIER = False


def click_target_diagnostics(driver: "WebDriver", element: "WebElement") -> dict:
    """Return center-point hit-test details for a candidate click target."""
    return driver.execute_script(
        """
        const element = arguments[0];
        if (!element || !element.getBoundingClientRect) {
            return {ok: false, error: 'missing element'};
        }

        element.scrollIntoView({block: 'center', inline: 'center'});
        const rect = element.getBoundingClientRect();
        const x = Math.round(rect.left + rect.width / 2);
        const y = Math.round(rect.top + rect.height / 2);
        const inViewport =
            x >= 0 && y >= 0 &&
            x <= window.innerWidth &&
            y <= window.innerHeight;
        function rootElementFromPoint(root, x, y) {
            if (!root) {
                return null;
            }
            if (typeof root.elementFromPoint === 'function') {
                const found = root.elementFromPoint(x, y);
                if (found) {
                    return found;
                }
            }
            if (!root.querySelectorAll) {
                return null;
            }

            let best = null;
            let bestRank = Number.POSITIVE_INFINITY;
            let bestArea = Number.POSITIVE_INFINITY;
            for (const candidate of root.querySelectorAll('*')) {
                if (!candidate.getBoundingClientRect) {
                    continue;
                }
                const candidateRect = candidate.getBoundingClientRect();
                if (
                    candidateRect.width <= 0 ||
                    candidateRect.height <= 0 ||
                    x < candidateRect.left ||
                    x > candidateRect.right ||
                    y < candidateRect.top ||
                    y > candidateRect.bottom
                ) {
                    continue;
                }
                const style = window.getComputedStyle(candidate);
                if (style.visibility === 'hidden' || style.display === 'none') {
                    continue;
                }
                const rank = candidate.matches(
                    'button,[role="button"],a,[data-action-bar-action],[tabindex]'
                ) ? 0 : 1;
                const area = candidateRect.width * candidateRect.height;
                if (rank < bestRank || (rank === bestRank && area <= bestArea)) {
                    best = candidate;
                    bestRank = rank;
                    bestArea = area;
                }
            }
            return best;
        }

        function deepElementFromPoint(x, y) {
            let current = document.elementFromPoint(x, y);
            let depth = 0;
            while (current && current.shadowRoot && depth < 8) {
                const inner = rootElementFromPoint(current.shadowRoot, x, y);
                if (!inner || inner === current) {
                    break;
                }
                current = inner;
                depth += 1;
            }
            return current;
        }

        const top = inViewport ? document.elementFromPoint(x, y) : null;
        const deepTop = inViewport ? deepElementFromPoint(x, y) : null;

        function attrsFor(target) {
            if (!target || !target.getAttribute) {
                return {};
            }
            const attrs = {};
            for (const attr of [
                'aria-label',
                'aria-pressed',
                'aria-selected',
                'data-action-bar-action',
                'data-state',
                'data-testid',
                'id',
                'class'
            ]) {
                const value = target.getAttribute(attr);
                if (value !== null) {
                    attrs[attr] = value;
                }
            }
            return attrs;
        }

        return {
            ok: true,
            center: {x, y},
            rect: {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                top: Math.round(rect.top),
                right: Math.round(rect.right),
                bottom: Math.round(rect.bottom),
                left: Math.round(rect.left)
            },
            viewport: {
                width: window.innerWidth,
                height: window.innerHeight
            },
            inViewport,
            topmostMatches: Boolean(
                deepTop &&
                (deepTop === element || element.contains(deepTop) || deepTop.contains(element))
            ),
            element: {
                tag: element.tagName ? element.tagName.toLowerCase() : '',
                attrs: attrsFor(element)
            },
            topmost: top ? {
                tag: top.tagName ? top.tagName.toLowerCase() : '',
                text: String(top.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 120),
                attrs: attrsFor(top)
            } : null,
            deepTopmost: deepTop ? {
                tag: deepTop.tagName ? deepTop.tagName.toLowerCase() : '',
                text: String(deepTop.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 120),
                attrs: attrsFor(deepTop)
            } : null
        };
        """,
        element,
    )


def _pointer_click(driver: "WebDriver", element: "WebElement", pause_seconds: float) -> None:
    from selenium.webdriver.common.action_chains import ActionChains

    ActionChains(driver).move_to_element(element).pause(pause_seconds).click().perform()


def human_click(driver: "WebDriver", element: "WebElement", enabled: bool = True) -> dict:
    """Click an element through WebDriver pointer actions and return hit-test diagnostics."""
    diagnostics = click_target_diagnostics(driver, element)
    if not enabled or not HAS_BEZIER:
        _pointer_click(driver, element, 0.05)
        return diagnostics

    # Keep the optional legacy cursor movement, then use a real pointer click at the element.
    from selenium.webdriver.common.action_chains import ActionChains

    viewport_w = driver.execute_script("return window.innerWidth;")
    viewport_h = driver.execute_script("return window.innerHeight;")
    start = (viewport_w // 2, viewport_h // 2)
    loc = element.location
    size = element.size
    end = (loc["x"] + size["width"] // 2, loc["y"] + size["height"] // 2)
    points = _bezier_curve_points(start, end, num_points=random.randint(15, 30))

    actions = ActionChains(driver)
    pointer = actions.w3c_actions.pointer_action
    for x, y in points:
        pointer.move_to_location(x, y)
        actions.pause(random.uniform(0.005, 0.03))

    actions.perform()
    time.sleep(random.uniform(0.05, 0.2))
    _pointer_click(driver, element, random.uniform(0.03, 0.12))
    return diagnostics
