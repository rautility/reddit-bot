"""Rendered Reddit vote-control fallback helpers."""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any, Literal

from bot.utils.mouse import _bezier_curve_points, _cdp_mouse_path_click, _clamp_point_to_viewport, _driver_supports_cdp

VoteIntent = Literal["upvote", "downvote"]


FIND_VISIBLE_VOTE_CONTROL_SCRIPT = r"""
const intent = String(arguments[0] || '').toLowerCase();
const expectedPostUrl = String(arguments[1] || '');

function rectPayload(element) {
  const rect = element.getBoundingClientRect();
  return {
    x: Math.round(rect.x),
    y: Math.round(rect.y),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
    centerX: Math.round(rect.x + rect.width / 2),
    centerY: Math.round(rect.y + rect.height / 2)
  };
}

function isVisible(element) {
  if (!element || !element.getBoundingClientRect) return false;
  const rect = element.getBoundingClientRect();
  const style = getComputedStyle(element);
  return rect.width > 0 &&
    rect.height > 0 &&
    rect.bottom >= 0 &&
    rect.right >= 0 &&
    rect.top <= window.innerHeight &&
    rect.left <= window.innerWidth &&
    style.visibility !== 'hidden' &&
    style.display !== 'none' &&
    Number(style.opacity || '1') > 0.05;
}

function statePayload(element) {
  if (!element || !element.getAttribute) return {};
  const style = getComputedStyle(element);
  return {
    ariaPressed: element.getAttribute('aria-pressed'),
    ariaSelected: element.getAttribute('aria-selected'),
    dataState: element.getAttribute('data-state'),
    dataVoteState: element.getAttribute('data-vote-state'),
    ariaLabel: element.getAttribute('aria-label'),
    className: String(element.getAttribute('class') || ''),
    color: style.color,
    backgroundColor: style.backgroundColor
  };
}

function isPressed(element, label) {
  const state = statePayload(element);
  const classText = String(state.className || '').toLowerCase();
  const ariaLabel = String(state.ariaLabel || '').toLowerCase();
  const dataState = String(state.dataState || '').toLowerCase();
  const dataVoteState = String(state.dataVoteState || '').toLowerCase();
  if (state.ariaPressed === 'true' || state.ariaSelected === 'true') return true;
  if (['active', 'selected', 'checked', 'on', 'true'].includes(dataState)) return true;
  if (label === 'upvote') {
    return ariaLabel.includes('upvoted') ||
      ['up', 'upvote'].includes(dataVoteState) ||
      classText.includes('upvote-fill') ||
      classText.includes('text-upvote') ||
      classText.includes('bg-upvote') ||
      classText.includes('vote-state-up');
  }
  return ariaLabel.includes('downvoted') ||
    ['down', 'downvote'].includes(dataVoteState) ||
    classText.includes('downvote-fill') ||
    classText.includes('text-downvote') ||
    classText.includes('bg-downvote') ||
    classText.includes('vote-state-down');
}

function deepElements(root = document, out = []) {
  for (const element of root.querySelectorAll('*')) {
    out.push(element);
    if (element.shadowRoot) deepElements(element.shadowRoot, out);
  }
  return out;
}

function deepElementFromPoint(x, y, root = document) {
  let element = root.elementFromPoint(x, y);
  for (let depth = 0; element && element.shadowRoot && depth < 8; depth += 1) {
    const nested = element.shadowRoot.elementFromPoint(x, y);
    if (!nested || nested === element) break;
    element = nested;
  }
  return element;
}

function postIdFromUrl(value) {
  const match = String(value || '').match(/\/comments\/([^/]+)/);
  return match ? match[1] : '';
}

function scoreFromText(text) {
  const match = String(text || '').match(/\b(-?\d+)\b/);
  return match ? Number(match[1]) : null;
}

const expectedPostId = postIdFromUrl(expectedPostUrl);
const posts = deepElements().filter((element) => {
  const tag = element.tagName && element.tagName.toLowerCase();
  if (tag !== 'shreddit-post') return false;
  if (!expectedPostId) return true;
  return String(element.getAttribute('id') || '').includes(expectedPostId) ||
    String(element.getAttribute('permalink') || '').includes(expectedPostId);
});
const post = posts[0] || document.querySelector('shreddit-post') || document;
const elements = deepElements(post.shadowRoot || post);
const candidates = [];

for (const element of elements) {
  if (!isVisible(element)) continue;
  const text = String(element.innerText || element.textContent || '').trim();
  const descendantIconNames = [...element.querySelectorAll('svg[icon-name]')]
    .map((icon) => icon.getAttribute('icon-name'))
    .filter(Boolean)
    .join(' ');
  const haystack = [
    text,
    element.getAttribute('aria-label'),
    element.getAttribute('data-testid'),
    element.getAttribute('data-click-id'),
    element.getAttribute('data-action-bar-action'),
    element.getAttribute('icon-name'),
    descendantIconNames,
    element.getAttribute('class')
  ].filter(Boolean).join(' ').toLowerCase();

  const isControl = element.matches('button,[role="button"],faceplate-tracker') ||
    element.querySelector('svg[icon-name]');
  const combinedVotePill = /\bupvote\b/i.test(text) && /\bdownvote\b/i.test(text);
  const iconNames = descendantIconNames.toLowerCase().split(/\s+/).filter(Boolean);
  const containsOnlyOppositeIcon = iconNames.length > 0 &&
    iconNames.every((iconName) => iconName.includes(intent === 'upvote' ? 'downvote' : 'upvote'));
  if (combinedVotePill || containsOnlyOppositeIcon) continue;
  if (!isControl || !haystack.includes(intent)) continue;

  const rect = rectPayload(element);
  candidates.push({
    source: 'direct-control',
    tag: element.tagName.toLowerCase(),
    text: text.slice(0, 120),
    rect,
    click: {x: rect.centerX, y: rect.centerY},
    state: statePayload(element),
    pressed: isPressed(element, intent),
    topmostTag: (deepElementFromPoint(rect.centerX, rect.centerY) || {}).tagName || null
  });
}

if (!candidates.length) {
  for (const element of elements) {
    if (!isVisible(element)) continue;
    const text = String(element.innerText || element.textContent || '').trim();
    if (!/\bupvote\b/i.test(text) || !/\bdownvote\b/i.test(text)) continue;
    const rect = rectPayload(element);
    if (rect.width < 40 || rect.height < 20) continue;
    const clickX = intent === 'upvote'
      ? Math.round(rect.x + rect.width * 0.2)
      : Math.round(rect.x + rect.width * 0.8);
    const clickY = rect.centerY;
    candidates.push({
      source: 'vote-pill-geometry',
      tag: element.tagName.toLowerCase(),
      text: text.slice(0, 120),
      rect,
      click: {x: clickX, y: clickY},
      state: statePayload(element),
      pressed: isPressed(element, intent),
      score: scoreFromText(text),
      topmostTag: (deepElementFromPoint(clickX, clickY) || {}).tagName || null
    });
  }
}

candidates.sort((left, right) => {
  if (left.pressed !== right.pressed) return left.pressed ? -1 : 1;
  if (left.source !== right.source) return left.source === 'direct-control' ? -1 : 1;
  return (left.rect.y - right.rect.y) || (left.rect.x - right.rect.x);
});

const candidate = candidates[0] || null;
return {
  ok: Boolean(candidate),
  intent,
  url: location.href,
  title: document.title,
  expectedPostId,
  candidate,
  candidates: candidates.slice(0, 8)
};
"""


def find_visible_vote_control(driver: Any, intent: VoteIntent, url: str = "") -> dict[str, Any]:
    """Return the best visible vote control candidate for the current page."""
    return driver.execute_script(FIND_VISIBLE_VOTE_CONTROL_SCRIPT, intent, url)


def _dispatch_cdp_click(driver: Any, x: int, y: int) -> tuple[int, int]:
    """Move in a human-like curved path and click a viewport point."""
    viewport = driver.execute_script("return [window.innerWidth, window.innerHeight];")
    viewport_w = int(viewport[0]) if isinstance(viewport, (list, tuple)) and viewport[0] else 1
    viewport_h = int(viewport[1]) if isinstance(viewport, (list, tuple)) and len(viewport) > 1 and viewport[1] else 1

    start = (viewport_w // 2, viewport_h // 2)
    end = _clamp_point_to_viewport(
        (x + random.randint(-6, 6), y + random.randint(-6, 6)),
        viewport_w,
        viewport_h,
    )
    points = [
        _clamp_point_to_viewport(point, viewport_w, viewport_h)
        for point in _bezier_curve_points(start, end, num_points=random.randint(16, 32))
    ]

    if _driver_supports_cdp(driver):
        _cdp_mouse_path_click(driver, points)
        return end

    for index, (point_x, point_y) in enumerate(points):
        driver.execute_script(
            """
            const pointX = arguments[0];
            const pointY = arguments[1];
            const target = document.elementFromPoint(pointX, pointY) ||
              document.body ||
              document.documentElement;
            if (!target || !target.dispatchEvent) return false;
            target.dispatchEvent(new MouseEvent('mousemove', {
                bubbles: true,
                cancelable: true,
                clientX: pointX,
                clientY: pointY,
                button: 0,
                buttons: 0
            }));
            return true;
            """,
            point_x,
            point_y,
        )
        if index + 1 < len(points):
            time.sleep(random.uniform(0.005, 0.03))

    time.sleep(random.uniform(0.03, 0.11))
    driver.execute_script(
        """
        const x = arguments[0];
        const y = arguments[1];
        const target = document.elementFromPoint(x, y) || document.body || document.documentElement;
        if (!target || !target.dispatchEvent) return false;
        target.dispatchEvent(new MouseEvent('pointerdown', {
          bubbles: true,
          cancelable: true,
          clientX: x,
          clientY: y,
          button: 0,
          buttons: 1
        }));
        target.dispatchEvent(new MouseEvent('mousedown', {
          bubbles: true,
          cancelable: true,
          clientX: x,
          clientY: y,
          button: 0,
          buttons: 1
        }));
        target.dispatchEvent(new MouseEvent('pointerup', {
          bubbles: true,
          cancelable: true,
          clientX: x,
          clientY: y,
          button: 0,
          buttons: 0
        }));
        target.dispatchEvent(new MouseEvent('mouseup', {
          bubbles: true,
          cancelable: true,
          clientX: x,
          clientY: y,
          button: 0,
          buttons: 0
        }));
        target.dispatchEvent(new MouseEvent('click', {
          bubbles: true,
          cancelable: true,
          clientX: x,
          clientY: y,
          button: 0
        }));
        return true;
        """,
        end[0],
        end[1],
    )
    return end


def click_visible_vote_control(
    driver: Any,
    *,
    intent: VoteIntent,
    url: str,
    settle_seconds: float = 2.0,
    screenshot_path: str = "",
) -> dict[str, Any]:
    """Navigate, click a rendered Reddit vote control once, and return diagnostics."""
    if intent not in {"upvote", "downvote"}:
        raise ValueError("intent must be 'upvote' or 'downvote'")

    if url:
        driver.get(url)

    before = find_visible_vote_control(driver, intent, url)
    candidate = before.get("candidate") if isinstance(before, dict) else None
    if not candidate:
        return {
            "ok": False,
            "clicked": False,
            "intent": intent,
            "url": url,
            "error": "No visible vote control candidate found.",
            "before": before,
        }

    click = candidate.get("click") or {}
    x = int(click["x"])
    y = int(click["y"])
    click_x, click_y = _dispatch_cdp_click(driver, x, y)
    if settle_seconds > 0:
        time.sleep(settle_seconds)

    after = find_visible_vote_control(driver, intent, url)
    screenshot = ""
    if screenshot_path:
        path = Path(screenshot_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(str(path))
        screenshot = str(path)

    return {
        "ok": True,
        "clicked": True,
        "intent": intent,
        "url": driver.current_url,
        "click": {"x": click_x, "y": click_y},
        "source": candidate.get("source"),
        "before": before,
        "after": after,
        "confirmed": bool((after.get("candidate") or {}).get("pressed")),
        "screenshotPath": screenshot or None,
    }
