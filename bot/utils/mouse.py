"""Human-like mouse movement using Bezier curves."""

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


def human_click(driver: "WebDriver", element: "WebElement", enabled: bool = True) -> None:
    """Click an element with optional human-like mouse movement.

    If bezier/numpy are not installed or enabled=False, falls back to a direct click.
    """
    if not enabled or not HAS_BEZIER:
        element.click()
        return

    from selenium.webdriver.common.action_chains import ActionChains

    # Get current mouse position (approximate center of viewport)
    viewport_w = driver.execute_script("return window.innerWidth;")
    viewport_h = driver.execute_script("return window.innerHeight;")
    start = (viewport_w // 2, viewport_h // 2)

    # Get element center
    loc = element.location
    size = element.size
    end = (loc["x"] + size["width"] // 2, loc["y"] + size["height"] // 2)

    points = _bezier_curve_points(start, end, num_points=random.randint(15, 30))

    actions = ActionChains(driver)
    for i, (x, y) in enumerate(points):
        if i == 0:
            continue
        dx = x - points[i - 1][0]
        dy = y - points[i - 1][1]
        actions.move_by_offset(dx, dy)
        actions.pause(random.uniform(0.005, 0.03))

    actions.perform()
    time.sleep(random.uniform(0.05, 0.2))
    element.click()
