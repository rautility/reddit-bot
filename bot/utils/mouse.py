"""Browser pointer click helpers."""

from __future__ import annotations

import random
import time
from importlib.util import find_spec
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

HAS_BEZIER = find_spec("bezier") is not None and find_spec("numpy") is not None


def _bezier_curve_points(
    start: tuple[int, int],
    end: tuple[int, int],
    num_points: int = 20,
) -> list[tuple[int, int]]:
    """Generate points along a non-linear path between start and end."""
    if num_points <= 1:
        return [tuple(start), tuple(end)]

    if HAS_BEZIER:
        try:
            import bezier
            import numpy as np
        except ImportError:
            pass
        else:
            # Add random control points for natural movement.
            ctrl1 = (
                start[0] + random.randint(-50, 50) + (end[0] - start[0]) // 3,
                start[1] + random.randint(-50, 50) + (end[1] - start[1]) // 3,
            )
            ctrl2 = (
                start[0] + random.randint(-50, 50) + 2 * (end[0] - start[0]) // 3,
                start[1] + random.randint(-50, 50) + 2 * (end[1] - start[1]) // 3,
            )

            nodes = np.asfortranarray(
                [
                    [start[0], ctrl1[0], ctrl2[0], end[0]],
                    [start[1], ctrl1[1], ctrl2[1], end[1]],
                ],
                dtype=float,
            )
            curve = bezier.Curve(nodes, degree=3)
            t_values = np.linspace(0.0, 1.0, num_points)
            points = curve.evaluate_multi(t_values)
            return [(int(points[0, i]), int(points[1, i])) for i in range(num_points)]

    ctrl1 = (
        start[0] + random.randint(-50, 50) + (end[0] - start[0]) // 3,
        start[1] + random.randint(-50, 50) + (end[1] - start[1]) // 3,
    )
    ctrl2 = (
        start[0] + random.randint(-50, 50) + 2 * (end[0] - start[0]) // 3,
        start[1] + random.randint(-50, 50) + 2 * (end[1] - start[1]) // 3,
    )

    points: list[tuple[int, int]] = []
    for step in range(num_points):
        t = step / (num_points - 1)
        inverse_t = 1.0 - t
        x = (
            (inverse_t**3) * start[0]
            + 3 * (inverse_t**2) * t * ctrl1[0]
            + 3 * inverse_t * (t**2) * ctrl2[0]
            + (t**3) * end[0]
        )
        y = (
            (inverse_t**3) * start[1]
            + 3 * (inverse_t**2) * t * ctrl1[1]
            + 3 * inverse_t * (t**2) * ctrl2[1]
            + (t**3) * end[1]
        )
        points.append((int(x), int(y)))

    return points


def _cdp_mouse_event(
    driver: WebDriver,
    event_type: str,
    x: int,
    y: int,
    *,
    button: str = "left",
    buttons: int = 0,
    click_count: int = 1,
) -> None:
    driver.execute_cdp_cmd(
        "Input.dispatchMouseEvent",
        {
            "type": event_type,
            "x": x,
            "y": y,
            "button": button,
            "buttons": buttons,
            "clickCount": click_count,
        },
    )


def _cdp_mouse_path_click(
    driver: WebDriver,
    points: list[tuple[int, int]],
    *,
    move_pause_min: float = 0.005,
    move_pause_max: float = 0.03,
    press_pause_min: float = 0.03,
    press_pause_max: float = 0.12,
    release_pause_min: float = 0.01,
    release_pause_max: float = 0.05,
) -> None:
    """Move with CDP mouse events then click with human-like timing."""
    if not points:
        return

    for index, (x, y) in enumerate(points):
        _cdp_mouse_event(
            driver,
            "mouseMoved",
            x,
            y,
            button="none",
            buttons=0,
            click_count=0,
        )
        if index + 1 < len(points):
            time.sleep(random.uniform(move_pause_min, move_pause_max))

    x, y = points[-1]
    time.sleep(random.uniform(press_pause_min, press_pause_max))
    _cdp_mouse_event(driver, "mousePressed", x, y, button="left", buttons=1, click_count=1)
    time.sleep(random.uniform(release_pause_min, release_pause_max))
    _cdp_mouse_event(driver, "mouseReleased", x, y, button="left", buttons=0, click_count=1)


def _driver_supports_cdp(driver: WebDriver) -> bool:
    return callable(getattr(type(driver), "execute_cdp_cmd", None))


def click_target_diagnostics(
    driver: WebDriver,
    element: WebElement,
    *,
    scroll: bool = True,
) -> dict:
    """Return center-point hit-test details for a candidate click target."""
    return driver.execute_script(
        """
        const element = arguments[0];
        const shouldScroll = Boolean(arguments[1]);
        if (!element || !element.getBoundingClientRect) {
            return {ok: false, error: 'missing element'};
        }

        if (shouldScroll) {
            element.scrollIntoView({block: 'center', inline: 'center'});
        }
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
        scroll,
    )


def _element_view_metrics(driver: WebDriver, element: WebElement) -> dict:
    return driver.execute_script(
        """
        const element = arguments[0];
        const rect = element.getBoundingClientRect();
        return {
            center: {
                x: Math.round(rect.left + rect.width / 2),
                y: Math.round(rect.top + rect.height / 2)
            },
            rect: {
                top: Math.round(rect.top),
                bottom: Math.round(rect.bottom),
                height: Math.round(rect.height)
            },
            viewport: {
                width: window.innerWidth,
                height: window.innerHeight
            }
        };
        """,
        element,
    )


def _wheel_scroll(driver: WebDriver, y_amount: int, pause_seconds: float) -> None:
    driver.execute_script("window.scrollBy({top: arguments[0], behavior: 'auto'});", y_amount)
    time.sleep(pause_seconds)


def _scroll_position(driver: WebDriver) -> dict:
    return driver.execute_script(
        """
        return {
            y: Math.round(window.scrollY),
            viewportHeight: window.innerHeight,
            documentHeight: Math.max(
                document.body ? document.body.scrollHeight : 0,
                document.documentElement ? document.documentElement.scrollHeight : 0
            )
        };
        """
    )


def _clamp_point_to_viewport(
    point: tuple[int, int],
    viewport_w: int,
    viewport_h: int,
) -> tuple[int, int]:
    x, y = point
    return (
        max(0, min(viewport_w - 1, x)),
        max(0, min(viewport_h - 1, y)),
    )


def _element_viewport_center(driver: WebDriver, element: WebElement) -> tuple[int, int]:
    center = driver.execute_script(
        """
        const rect = arguments[0].getBoundingClientRect();
        return {
            x: Math.round(rect.left + rect.width / 2),
            y: Math.round(rect.top + rect.height / 2)
        };
        """,
        element,
    )
    return int(center["x"]), int(center["y"])


def _uses_attached_chrome_debugger(driver: WebDriver) -> bool:
    capabilities = getattr(driver, "capabilities", {}) or {}
    chrome_options = capabilities.get("goog:chromeOptions", {}) or {}
    return bool(chrome_options.get("debuggerAddress"))


def _dom_mouse_path_click(
    driver: WebDriver,
    element: WebElement,
    points: list[tuple[int, int]],
) -> None:
    if not points:
        return

    move_pause_min = 0.005
    move_pause_max = 0.03
    press_pause_min = 0.03
    press_pause_max = 0.12
    release_pause_min = 0.01
    release_pause_max = 0.05

    move_script = """
        const element = arguments[0];
        const point = arguments[1];
        const eventInit = {
            bubbles: true,
            cancelable: true,
            composed: true,
            clientX: point.x,
            clientY: point.y,
            screenX: point.x,
            screenY: point.y,
            button: 0,
            buttons: 0,
            pointerId: 1,
            pointerType: 'mouse',
            isPrimary: true
        };
        const eventCtor = window.PointerEvent ? window.PointerEvent : window.MouseEvent;
        const target = document.elementFromPoint(point.x, point.y) || element;
        if (!target || !target.dispatchEvent) {
            return false;
        }
        target.dispatchEvent(new eventCtor('pointermove', eventInit));
        target.dispatchEvent(new MouseEvent('mousemove', {
            bubbles: true,
            cancelable: true,
            clientX: point.x,
            clientY: point.y
        }));
        return true;
        """
    for index, point in enumerate(points):
        driver.execute_script(move_script, element, {"x": point[0], "y": point[1]})
        if index + 1 < len(points):
            time.sleep(random.uniform(move_pause_min, move_pause_max))

    end = points[-1]
    end_script = """
        const element = arguments[0];
        const point = arguments[1];
        const dispatch = (type, point, button, buttons) => {
            const eventInit = {
                bubbles: true,
                cancelable: true,
                composed: true,
                clientX: point.x,
                clientY: point.y,
                screenX: point.x,
                screenY: point.y,
                button: button,
                buttons: buttons,
                pointerId: 1,
                pointerType: 'mouse',
                isPrimary: true
            };
            const eventCtor = type.startsWith('pointer') && window.PointerEvent
                ? window.PointerEvent
                : window.MouseEvent;
            const target = document.elementFromPoint(point.x, point.y) || element;
            if (!target || !target.dispatchEvent) {
                return false;
            }
            target.dispatchEvent(new eventCtor(type, eventInit));
            return true;
        };
        dispatch('pointerover', point, 0, 0);
        dispatch('mouseover', point, 0, 0);
        dispatch('pointerdown', point, 0, 1);
        dispatch('mousedown', point, 0, 1);
        dispatch('pointerup', point, 0, 0);
        dispatch('mouseup', point, 0, 0);
        dispatch('click', point, 0, 0);
        return true;
        """
    time.sleep(random.uniform(press_pause_min, press_pause_max))
    driver.execute_script(end_script, element, {"x": end[0], "y": end[1]})
    time.sleep(random.uniform(release_pause_min, release_pause_max))


def human_scroll_to_element(
    driver: WebDriver,
    element: WebElement,
    *,
    max_steps: int = 16,
) -> list[dict]:
    """Use wheel-like scroll steps to bring an element into the viewport."""
    history = []
    for _ in range(max_steps):
        metrics = _element_view_metrics(driver, element)
        history.append(metrics)

        rect = metrics["rect"]
        viewport_h = metrics["viewport"]["height"]
        top_margin = min(120, max(40, viewport_h // 6))
        bottom_margin = min(140, max(50, viewport_h // 5))
        if rect["top"] >= top_margin and rect["bottom"] <= viewport_h - bottom_margin:
            break

        desired_y = int(viewport_h * random.uniform(0.42, 0.58))
        distance = metrics["center"]["y"] - desired_y
        if abs(distance) < 30:
            break

        y_amount = int(distance * random.uniform(0.45, 0.75))
        if 0 < abs(y_amount) < 80:
            y_amount = 80 if y_amount > 0 else -80
        y_amount = max(-650, min(650, y_amount))
        _wheel_scroll(driver, y_amount, random.uniform(0.04, 0.18))

    return history


def human_reading_scroll(driver: WebDriver) -> list[int]:
    """Skim a little below the current view, then drift back before targeting."""
    start = _scroll_position(driver)
    viewport_h = int(start.get("viewportHeight") or 0)
    document_h = int(start.get("documentHeight") or 0)
    start_y = int(start.get("y") or 0)
    if viewport_h <= 0 or document_h <= viewport_h + 80:
        return []

    max_down = max(0, document_h - viewport_h - start_y)
    if max_down < 120:
        return []

    movements = []
    down_steps = random.randint(1, 3)
    for _ in range(down_steps):
        amount = min(
            max_down,
            random.randint(max(90, viewport_h // 5), max(140, viewport_h // 2)),
        )
        if amount <= 0:
            break
        _wheel_scroll(driver, amount, random.uniform(0.35, 1.15))
        movements.append(amount)
        max_down -= amount

    back_steps = random.randint(1, max(1, len(movements)))
    for amount in reversed(movements[-back_steps:]):
        back_amount = -int(amount * random.uniform(0.55, 0.95))
        _wheel_scroll(driver, back_amount, random.uniform(0.25, 0.8))
        movements.append(back_amount)

    return movements


def _pointer_click(driver: WebDriver, element: WebElement, pause_seconds: float) -> None:
    from selenium.webdriver.common.action_chains import ActionChains

    ActionChains(driver).move_to_element(element).pause(pause_seconds).click().perform()


def _pointer_click_current_position(driver: WebDriver, pause_seconds: float) -> None:
    from selenium.webdriver.common.action_chains import ActionChains

    ActionChains(driver).pause(pause_seconds).click().perform()


def human_click(driver: WebDriver, element: WebElement, enabled: bool = True) -> dict:
    """Click an element through WebDriver pointer actions and return hit-test diagnostics."""
    if enabled:
        human_reading_scroll(driver)
        human_scroll_to_element(driver, element)
    diagnostics = click_target_diagnostics(driver, element, scroll=not enabled)
    if not enabled:
        _pointer_click(driver, element, 0.05)
        return diagnostics

    from selenium.webdriver.common.action_chains import ActionChains

    viewport_w = driver.execute_script("return window.innerWidth;")
    viewport_h = driver.execute_script("return window.innerHeight;")
    start = (viewport_w // 2, viewport_h // 2)
    end = _element_viewport_center(driver, element)
    points = [
        _clamp_point_to_viewport(point, viewport_w, viewport_h)
        for point in _bezier_curve_points(start, end, num_points=random.randint(15, 30))
    ]

    if _driver_supports_cdp(driver):
        _cdp_mouse_path_click(driver, points)
        return diagnostics

    if _uses_attached_chrome_debugger(driver):
        _dom_mouse_path_click(driver, element, points)
        return diagnostics

    actions = ActionChains(driver)
    pointer = actions.w3c_actions.pointer_action
    for x, y in points:
        pointer.move_to_location(x, y)
        actions.pause(random.uniform(0.005, 0.03))

    actions.perform()
    time.sleep(random.uniform(0.05, 0.2))
    _pointer_click_current_position(driver, random.uniform(0.03, 0.12))
    return diagnostics
