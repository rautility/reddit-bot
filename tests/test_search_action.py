"""Tests for human-like Reddit search action helpers."""

from bot.actions.base import ActionResult
from bot.actions.search import HumanSearchAction, SearchUpvoteAction
from bot.config import BotConfig
from selenium.common.exceptions import WebDriverException


def test_find_search_box_uses_deep_shadow_dom_fallback(mocker):
    driver = mocker.Mock()
    element = mocker.Mock()
    driver.find_element.side_effect = WebDriverException("missing")
    driver.execute_script.return_value = element
    action = HumanSearchAction(driver, BotConfig())

    assert action._find_search_box() is element
    assert "collectRoots(document, roots)" in driver.execute_script.call_args.args[0]


def test_open_search_types_query_when_search_box_found(mocker):
    driver = mocker.Mock()
    search_box = mocker.Mock()
    driver.current_url = "https://www.reddit.com/search/?q=Google"
    action = HumanSearchAction(driver, BotConfig())
    navigate = mocker.patch.object(action, "_navigate")
    mocker.patch.object(action, "_find_search_box", return_value=search_box)
    click = mocker.patch.object(action, "_click")
    type_query = mocker.patch.object(action, "_type_search_query_like_human")
    mocker.patch("bot.actions.search.Timeouts.med")

    action._open_search("Google Form automation")

    navigate.assert_called_once_with("https://www.reddit.com/")
    click.assert_called_once_with(search_box)
    type_query.assert_called_once_with(search_box, "Google Form automation")


def test_type_search_query_focuses_nested_input_and_types_with_actions(mocker):
    driver = mocker.Mock()
    element = mocker.Mock()
    target = mocker.Mock()
    driver.execute_script.side_effect = [target, False, False, False, False, False, False, False]
    action = HumanSearchAction(driver, BotConfig())
    mocker.patch("bot.actions.search.Timeouts.custom")
    mocker.patch("bot.actions.search.random.random", return_value=0.9)
    mocker.patch("bot.actions.search.random.uniform", return_value=0.01)
    sleep = mocker.patch("bot.actions.search.time.sleep")

    action._type_search_query_like_human(element, "ab cd")

    scripts = [call.args[0] for call in driver.execute_script.call_args_list]
    assert any("input[name=\"q\"]" in script for script in scripts)
    assert any("data-reddit-bot-search-overlay" in script for script in scripts)
    assert driver.execute_script.call_args_list[0].args[1] is element
    assert target.send_keys.call_count >= 6
    sleep.assert_called()


def test_send_search_keys_updates_overlay_with_js(mocker):
    driver = mocker.Mock()
    driver.execute_script.return_value = True
    element = mocker.Mock()
    action = HumanSearchAction(driver, BotConfig())

    action._send_search_keys(element, "x")

    element.send_keys.assert_not_called()
    assert "data-reddit-bot-search-overlay" in driver.execute_script.call_args.args[0]
    assert driver.execute_script.call_args.args[1] is element
    assert driver.execute_script.call_args.args[2] == "x"


def test_search_upvote_collects_then_votes_first_candidate(mocker):
    driver = mocker.Mock()
    config = BotConfig()
    selected_url = "https://www.reddit.com/r/excel/comments/abc/title/"
    search_cls = mocker.patch("bot.actions.search.HumanSearchAction")
    search_cls.return_value.collect_candidates.return_value = [
        {"url": selected_url, "title": "title", "source": "extension", "confidence": 0.9},
    ]
    vote_cls = mocker.patch("bot.actions.vote.VoteAction")
    vote_cls.return_value.execute.return_value = ActionResult(
        success=True,
        action="upvote",
        link=selected_url,
        message="Vote registered",
    )

    result = SearchUpvoteAction(driver, config).execute(link="best Excel tips")

    assert result.success is True
    assert result.action == "search_upvote"
    assert result.link == selected_url
    assert "Vote registered" in result.message
    search_cls.return_value.collect_candidates.assert_called_once_with(
        "best Excel tips",
        subreddit="",
        limit=config.search_upvote_max_candidates,
    )
    vote_cls.return_value.execute.assert_called_once_with(link=selected_url, upvote=True)


def test_search_upvote_passes_subreddit_scope(mocker):
    driver = mocker.Mock()
    config = BotConfig()
    selected_url = "https://www.reddit.com/r/excel/comments/abc/title/"
    search_cls = mocker.patch("bot.actions.search.HumanSearchAction")
    search_cls.return_value.collect_candidates.return_value = [
        {"url": selected_url, "title": "title", "source": "extension"},
    ]
    vote_cls = mocker.patch("bot.actions.vote.VoteAction")
    vote_cls.return_value.execute.return_value = ActionResult(
        success=True, action="upvote", link=selected_url, message="Vote registered",
    )

    SearchUpvoteAction(driver, config).execute(link="excel forms", subreddit="excel")

    search_cls.return_value.collect_candidates.assert_called_once_with(
        "excel forms",
        subreddit="excel",
        limit=config.search_upvote_max_candidates,
    )


def test_augment_and_rank_moves_old_posts_last(mocker):
    driver = mocker.Mock()
    driver.execute_script.return_value = {
        "/r/x/comments/aaa/one": 1000,  # old -> to the back
        "/r/x/comments/bbb/two": 10,    # recent
    }
    action = HumanSearchAction(driver, BotConfig())
    candidates = [
        {"url": "https://www.reddit.com/r/x/comments/aaa/one/", "confidence": 0.9, "source": "extension"},
        {"url": "https://www.reddit.com/r/x/comments/bbb/two/", "confidence": 0.8, "source": "extension"},
        {"url": "https://www.reddit.com/r/x/comments/ccc/three/", "confidence": 0.7, "source": "extension"},
    ]

    ranked = action._augment_and_rank(candidates)

    # Recent + unknown-age keep their confidence order; the old post is tried last.
    assert [c["url"] for c in ranked] == [
        "https://www.reddit.com/r/x/comments/bbb/two/",
        "https://www.reddit.com/r/x/comments/ccc/three/",
        "https://www.reddit.com/r/x/comments/aaa/one/",
    ]
    assert ranked[-1]["age_days"] == 1000
    assert ranked[1]["age_days"] is None  # unknown age is not penalised


def test_augment_and_rank_survives_script_error(mocker):
    from selenium.common.exceptions import WebDriverException

    driver = mocker.Mock()
    driver.execute_script.side_effect = WebDriverException("no bridge")
    action = HumanSearchAction(driver, BotConfig())
    candidates = [
        {"url": "https://www.reddit.com/r/x/comments/aaa/one/", "confidence": 0.9},
        {"url": "https://www.reddit.com/r/x/comments/bbb/two/", "confidence": 0.8},
    ]

    ranked = action._augment_and_rank(candidates)

    assert [c["url"] for c in ranked] == [
        "https://www.reddit.com/r/x/comments/aaa/one/",
        "https://www.reddit.com/r/x/comments/bbb/two/",
    ]


def test_search_upvote_falls_through_unvotable_candidate(mocker):
    driver = mocker.Mock()
    config = BotConfig()
    deleted_url = "https://www.reddit.com/r/x/comments/aaa/deleted/"
    votable_url = "https://www.reddit.com/r/x/comments/bbb/votable/"
    search_cls = mocker.patch("bot.actions.search.HumanSearchAction")
    search_cls.return_value.collect_candidates.return_value = [
        {"url": deleted_url, "title": "deleted", "source": "extension"},
        {"url": votable_url, "title": "votable", "source": "extension"},
    ]
    mocker.patch("bot.actions.search.Timeouts.med")
    vote_cls = mocker.patch("bot.actions.vote.VoteAction")
    vote_cls.return_value.execute.side_effect = [
        ActionResult(
            success=False,
            action="upvote",
            link=deleted_url,
            message="Post is deleted; voting was not attempted.",
        ),
        ActionResult(
            success=True,
            action="upvote",
            link=votable_url,
            message="Vote registered",
        ),
    ]

    result = SearchUpvoteAction(driver, config).execute(link="google forms for doctors")

    assert result.success is True
    assert result.link == votable_url
    assert "2/2" in result.message
    assert "after skipping [1] deleted" in result.message  # observability trace
    assert vote_cls.return_value.execute.call_count == 2
    vote_cls.return_value.execute.assert_any_call(link=deleted_url, upvote=True)
    vote_cls.return_value.execute.assert_any_call(link=votable_url, upvote=True)


def test_search_upvote_fails_when_all_candidates_unvotable(mocker):
    driver = mocker.Mock()
    config = BotConfig()
    url1 = "https://www.reddit.com/r/x/comments/aaa/one/"
    url2 = "https://www.reddit.com/r/x/comments/bbb/two/"
    search_cls = mocker.patch("bot.actions.search.HumanSearchAction")
    search_cls.return_value.collect_candidates.return_value = [
        {"url": url1, "title": "one", "source": "extension"},
        {"url": url2, "title": "two", "source": "extension"},
    ]
    mocker.patch("bot.actions.search.Timeouts.med")
    vote_cls = mocker.patch("bot.actions.vote.VoteAction")
    vote_cls.return_value.execute.side_effect = [
        ActionResult(
            success=False,
            action="upvote",
            link=url1,
            message="Post is deleted; voting was not attempted.",
        ),
        ActionResult(
            success=False,
            action="upvote",
            link=url2,
            message="Post is archived; voting was not attempted.",
        ),
    ]

    result = SearchUpvoteAction(driver, config).execute(link="q")

    assert result.success is False
    assert result.link == url1
    assert "Upvote failed after trying 2 search result(s)" in result.message
    assert "[1] deleted" in result.message and "[2] archived" in result.message
    assert vote_cls.return_value.execute.call_count == 2


def test_is_definitive_failure_classification():
    definitive = SearchUpvoteAction._is_definitive_failure
    assert definitive("Post is deleted; voting was not attempted.")
    assert definitive("Post is archived; voting was not attempted.")
    assert definitive("Post does not allow voting; voting was not attempted.")
    assert definitive("Upvote control is disabled; post may be archived or voting is unavailable")
    # Hedged/transient messages must NOT be misread as definitive.
    assert not definitive("Could not find upvote button; post may be unavailable or Reddit layout changed")
    assert not definitive("Vote click did not register as active upvote")
    assert not definitive("Could not open post: timeout")


def test_search_upvote_retries_transient_failure_then_succeeds(mocker):
    driver = mocker.Mock()
    config = BotConfig()  # search_upvote_transient_retries defaults to 1
    url = "https://www.reddit.com/r/x/comments/aaa/one/"
    search_cls = mocker.patch("bot.actions.search.HumanSearchAction")
    search_cls.return_value.collect_candidates.return_value = [
        {"url": url, "title": "one", "source": "extension"},
    ]
    mocker.patch("bot.actions.search.Timeouts.med")
    vote_cls = mocker.patch("bot.actions.vote.VoteAction")
    vote_cls.return_value.execute.side_effect = [
        ActionResult(
            success=False,
            action="upvote",
            link=url,
            message="Vote click did not register as active upvote",
        ),
        ActionResult(success=True, action="upvote", link=url, message="Vote registered"),
    ]

    result = SearchUpvoteAction(driver, config).execute(link="q")

    assert result.success is True
    assert result.link == url
    assert "retried 1x" in result.message
    assert vote_cls.return_value.execute.call_count == 2  # transient failure was retried


def test_search_upvote_transient_budget_exhausts_then_moves_on(mocker):
    driver = mocker.Mock()
    config = BotConfig()  # budget of 1 transient retry for the whole run
    url1 = "https://www.reddit.com/r/x/comments/aaa/one/"
    url2 = "https://www.reddit.com/r/x/comments/bbb/two/"
    search_cls = mocker.patch("bot.actions.search.HumanSearchAction")
    search_cls.return_value.collect_candidates.return_value = [
        {"url": url1, "title": "one", "source": "extension"},
        {"url": url2, "title": "two", "source": "extension"},
    ]
    mocker.patch("bot.actions.search.Timeouts.med")
    vote_cls = mocker.patch("bot.actions.vote.VoteAction")
    vote_cls.return_value.execute.side_effect = [
        # candidate 1, attempt 1 -> transient (consumes the retry budget)
        ActionResult(success=False, action="upvote", link=url1, message="Vote click did not register"),
        # candidate 1, retry -> transient again, budget now exhausted -> move on
        ActionResult(success=False, action="upvote", link=url1, message="Vote click did not register"),
        # candidate 2, attempt 1 -> success, no retry budget left
        ActionResult(success=True, action="upvote", link=url2, message="Vote registered"),
    ]

    result = SearchUpvoteAction(driver, config).execute(link="q")

    assert result.success is True
    assert result.link == url2
    assert "2/2" in result.message
    assert vote_cls.return_value.execute.call_count == 3  # 2 on c1 (attempt+retry), 1 on c2


def test_search_upvote_returns_failure_when_no_candidates(mocker):
    driver = mocker.Mock()
    config = BotConfig()
    search_cls = mocker.patch("bot.actions.search.HumanSearchAction")
    search_cls.return_value.collect_candidates.return_value = []
    vote_cls = mocker.patch("bot.actions.vote.VoteAction")

    result = SearchUpvoteAction(driver, config).execute(link="q")

    assert result.success is False
    assert "No eligible" in result.message
    vote_cls.return_value.execute.assert_not_called()
