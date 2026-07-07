"""Source-level regressions for the unpacked Reddit healer extension."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_page_bridge_does_not_monkeypatch_fetch_or_xhr():
    source = (REPO_ROOT / "chrome_extension/reddit_healer/page_bridge.js").read_text()

    assert "patchedFetch" not in source
    assert "window.fetch =" not in source
    assert "XMLHttpRequest.prototype" not in source
    assert "PerformanceObserver" in source


def test_content_scanner_requires_actionable_candidate_for_threshold():
    source = (REPO_ROOT / "chrome_extension/reddit_healer/content.js").read_text()

    assert "if (!isClickableElement(clickable))" in source
    assert "function hasSpecificIntentAttribute" in source
    assert "directPositive && directReject && !specificIntentAttribute" in source
    assert "function candidateMeetsActionableThreshold" in source
    assert "candidate.actionable" in source
    assert "candidateMeetsActionableThreshold(result.bestCandidate, minConfidence)" in source
    assert "scopeInfo.name !== 'document-fallback'" in source


def test_content_scanner_supports_human_search_results():
    source = (REPO_ROOT / "chrome_extension/reddit_healer/content.js").read_text()

    assert "function findSearchResult" in source
    assert "find_search_result" in source
    assert "function pageShape" in source
    assert "promoted" in source
    assert "archived" in source
    assert "deleted" in source
    assert "removed" in source
    assert "!state.deleted && !state.removed" in source
    assert "a[href*=\"/comments/\"]" in source
