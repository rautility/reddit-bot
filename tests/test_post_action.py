"""Unit tests for post submission actions (mocked WebDriver, no live Reddit)."""

from selenium.common.exceptions import NoSuchElementException

from bot.actions.post import CrosspostAction, PostImageAction, PostLinkAction, PostTextAction
from bot.config import BotConfig


def _post_action(cls, mocker, *, dry_run: bool = False):
    driver = mocker.Mock()
    action = cls(driver, BotConfig(dry_run=dry_run), mocker.Mock())
    action._navigate = mocker.Mock()
    action._click = mocker.Mock()
    action._type_like_human = mocker.Mock()
    action._find_with_fallbacks = mocker.Mock()
    mocker.patch("bot.actions.post.Timeouts.lng")
    mocker.patch("bot.actions.post.Timeouts.med")
    mocker.patch("bot.actions.post.Timeouts.srt")
    return action, driver


# --- PostTextAction ---


def test_post_text_dry_run(mocker):
    action, _ = _post_action(PostTextAction, mocker, dry_run=True)

    result = action.execute(subreddit="test", title="Hello")

    assert result.success is True
    assert result.action == "post_text"
    assert "Dry run" in result.message
    action._navigate.assert_not_called()


def test_post_text_fails_without_title(mocker):
    action, _ = _post_action(PostTextAction, mocker)

    result = action.execute(subreddit="test", title="")

    assert result.success is False
    assert result.action == "post_text"
    assert "No title provided" in result.message
    action._navigate.assert_not_called()


def test_post_text_happy_path(mocker):
    action, _ = _post_action(PostTextAction, mocker)
    text_tab = mocker.Mock()
    title_field = mocker.Mock()
    body_field = mocker.Mock()
    submit_btn = mocker.Mock()
    action._find_with_fallbacks.side_effect = [text_tab, title_field, body_field, submit_btn]

    result = action.execute(
        subreddit="excel",
        title="My post",
        body="Post body text",
    )

    assert result.success is True
    assert result.action == "post_text"
    assert result.link == "excel"
    assert "Text post 'My post' created" in result.message
    action._navigate.assert_called_once_with("https://www.reddit.com/r/excel/submit")
    action._type_like_human.assert_any_call(title_field, "My post")
    action._type_like_human.assert_any_call(body_field, "Post body text")
    action._click.assert_any_call(submit_btn)


def test_post_text_fails_when_controls_missing(mocker):
    action, _ = _post_action(PostTextAction, mocker)
    action._find_with_fallbacks.side_effect = NoSuchElementException("no title field")

    result = action.execute(subreddit="test", title="Hello")

    assert result.success is False
    assert result.action == "post_text"
    assert "no title field" in result.message


# --- PostLinkAction ---


def test_post_link_fails_without_title_or_url(mocker):
    action, _ = _post_action(PostLinkAction, mocker)

    result = action.execute(subreddit="test", title="Only title", body="")

    assert result.success is False
    assert result.action == "post_link"
    assert "Title and URL" in result.message
    action._navigate.assert_not_called()


def test_post_link_happy_path(mocker):
    action, _ = _post_action(PostLinkAction, mocker)
    link_tab = mocker.Mock()
    title_field = mocker.Mock()
    url_field = mocker.Mock()
    submit_btn = mocker.Mock()
    action._find_with_fallbacks.side_effect = [link_tab, title_field, url_field, submit_btn]

    result = action.execute(
        subreddit="news",
        title="Cool link",
        body="https://example.com/article",
    )

    assert result.success is True
    assert result.action == "post_link"
    assert result.link == "news"
    assert "Link post 'Cool link' created" in result.message
    action._navigate.assert_called_once_with("https://www.reddit.com/r/news/submit")
    action._type_like_human.assert_any_call(title_field, "Cool link")
    action._type_like_human.assert_any_call(url_field, "https://example.com/article")
    action._click.assert_any_call(submit_btn)


def test_post_link_fails_when_controls_missing(mocker):
    action, _ = _post_action(PostLinkAction, mocker)
    action._find_with_fallbacks.side_effect = NoSuchElementException("no link tab")

    result = action.execute(subreddit="test", title="T", body="https://example.com")

    assert result.success is False
    assert result.action == "post_link"
    assert "no link tab" in result.message


# --- PostImageAction ---


def test_post_image_fails_without_title_or_path(mocker):
    action, _ = _post_action(PostImageAction, mocker)

    result = action.execute(subreddit="pics", title="", body="/tmp/img.png")

    assert result.success is False
    assert result.action == "post_image"
    assert "Title and image path" in result.message


def test_post_image_happy_path(mocker):
    action, driver = _post_action(PostImageAction, mocker)
    image_tab = mocker.Mock()
    title_field = mocker.Mock()
    file_input = mocker.Mock()
    submit_btn = mocker.Mock()
    action._find_with_fallbacks.side_effect = [image_tab, title_field, submit_btn]
    driver.find_element.return_value = file_input

    result = action.execute(
        subreddit="pics",
        title="Sunset",
        body="/tmp/sunset.png",
    )

    assert result.success is True
    assert result.action == "post_image"
    assert result.link == "pics"
    assert "Image post 'Sunset' created" in result.message
    action._navigate.assert_called_once_with("https://www.reddit.com/r/pics/submit")
    action._type_like_human.assert_any_call(title_field, "Sunset")
    file_input.send_keys.assert_called_once_with("/tmp/sunset.png")
    action._click.assert_any_call(submit_btn)


def test_post_image_fails_when_file_input_missing(mocker):
    action, driver = _post_action(PostImageAction, mocker)
    image_tab = mocker.Mock()
    title_field = mocker.Mock()
    action._find_with_fallbacks.side_effect = [image_tab, title_field]
    driver.find_element.side_effect = NoSuchElementException("no file input")

    result = action.execute(subreddit="pics", title="Sunset", body="/tmp/sunset.png")

    assert result.success is False
    assert result.action == "post_image"
    assert "no file input" in result.message


# --- CrosspostAction (same module; light coverage) ---


def test_crosspost_fails_without_subreddit(mocker):
    action, _ = _post_action(CrosspostAction, mocker)

    result = action.execute(link="https://www.reddit.com/r/a/comments/x/", subreddit="")

    assert result.success is False
    assert result.action == "crosspost"
    assert "Target subreddit required" in result.message
    action._navigate.assert_not_called()


def test_crosspost_happy_path(mocker):
    action, driver = _post_action(CrosspostAction, mocker)
    share_btn = mocker.Mock()
    crosspost_btn = mocker.Mock()
    sub_field = mocker.Mock()
    sub_option = mocker.Mock()
    submit_btn = mocker.Mock()
    action._find_with_fallbacks.side_effect = [share_btn, crosspost_btn, sub_field, submit_btn]
    driver.find_element.return_value = sub_option
    link = "https://www.reddit.com/r/a/comments/abc/slug/"

    result = action.execute(link=link, subreddit="b")

    assert result.success is True
    assert result.action == "crosspost"
    assert "Crossposted to r/b" in result.message
    action._navigate.assert_called_once_with(link)
    action._type_like_human.assert_any_call(sub_field, "b")
    action._click.assert_any_call(submit_btn)
