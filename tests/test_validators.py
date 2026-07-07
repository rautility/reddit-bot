"""Tests for URL validation utilities."""

from bot.utils.validators import (
    validate_reddit_url,
    is_post_url,
    is_share_url,
    is_subreddit_url,
    is_user_url,
)


class TestValidateRedditUrl:
    def test_valid_urls(self):
        assert validate_reddit_url("https://www.reddit.com/r/python") is True
        assert validate_reddit_url("https://reddit.com/r/python") is True
        assert validate_reddit_url("https://old.reddit.com/r/python") is True
        assert validate_reddit_url("https://new.reddit.com/r/python") is True

    def test_invalid_urls(self):
        assert validate_reddit_url("https://google.com") is False
        assert validate_reddit_url("not a url") is False
        assert validate_reddit_url("") is False
        assert validate_reddit_url("ftp://reddit.com/r/python") is False


class TestIsPostUrl:
    def test_valid_post(self):
        assert is_post_url("https://www.reddit.com/r/ProgrammerHumor/comments/abc123/title") is True

    def test_invalid_post(self):
        assert is_post_url("https://www.reddit.com/r/python") is False
        assert is_post_url("https://google.com") is False


class TestIsShareUrl:
    def test_valid_share_url(self):
        assert is_share_url("https://www.reddit.com/r/excel/s/Ipw1C8yg0P") is True

    def test_invalid_share_url(self):
        assert is_share_url("https://www.reddit.com/r/excel/comments/abc123/title") is False


class TestIsSubredditUrl:
    def test_valid_subreddit(self):
        assert is_subreddit_url("https://www.reddit.com/r/python") is True
        assert is_subreddit_url("https://www.reddit.com/r/python/") is True

    def test_invalid_subreddit(self):
        assert is_subreddit_url("https://www.reddit.com/r/python/comments/abc") is False


class TestIsUserUrl:
    def test_valid_user(self):
        assert is_user_url("https://www.reddit.com/user/testuser") is True
        assert is_user_url("https://www.reddit.com/u/testuser") is True

    def test_invalid_user(self):
        assert is_user_url("https://www.reddit.com/r/python") is False
