"""Tests for Reddit share shortlink resolution (WP-D)."""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from bot import tool_cli
from bot.control.errors import CliError
from bot.control.resolve import resolve_reddit_url
from bot.utils.reddit_urls import classify_reddit_url, follow_http_redirects, resolve_share_url

POST = "https://www.reddit.com/r/excel/comments/abc123/some_title/"
SHARE = "https://www.reddit.com/r/excel/s/Ipw1C8yg0P"
SUB = "https://www.reddit.com/r/excel/"


class TestClassify:
    def test_post(self):
        assert classify_reddit_url(POST) == "post"

    def test_share(self):
        assert classify_reddit_url(SHARE) == "share"

    def test_subreddit(self):
        assert classify_reddit_url(SUB) == "subreddit"

    def test_invalid(self):
        assert classify_reddit_url("https://example.com/x") == "invalid"
        assert classify_reddit_url("") == "invalid"
        assert classify_reddit_url("not-a-url") == "invalid"


class TestFollowRedirects:
    def test_returns_final_url_from_response(self):
        mock_resp = MagicMock()
        mock_resp.geturl.return_value = POST + "?utm=1#frag"
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch("bot.utils.reddit_urls.urllib.request.urlopen", return_value=mock_resp) as open_mock:
            final = follow_http_redirects(SHARE)
            open_mock.assert_called_once()
            request = open_mock.call_args[0][0]
            assert request.full_url == SHARE
            assert "User-Agent" in request.headers or request.get_header("User-agent")

        assert final == "https://www.reddit.com/r/excel/comments/abc123/some_title/"

    def test_resolve_share_rejects_non_share(self):
        with pytest.raises(ValueError, match="Not a Reddit share"):
            resolve_share_url(POST)


class TestResolveRedditUrl:
    def test_canonical_post_passthrough(self):
        result = resolve_reddit_url(POST)
        assert result["input"] == POST
        assert result["output"] == POST
        assert result["resolved"] is False
        assert result["kind"] == "post"

    def test_post_without_trailing_slash(self):
        url = "https://www.reddit.com/r/excel/comments/abc123/title"
        result = resolve_reddit_url(url)
        assert result["resolved"] is False
        assert result["kind"] == "post"
        assert result["output"] == url
        assert result["input"] == url

    def test_share_mocked_redirect_to_post(self):
        with patch(
            "bot.control.resolve.resolve_share_url",
            return_value=POST,
        ) as resolve_mock:
            result = resolve_reddit_url(SHARE)
            resolve_mock.assert_called_once()

        assert result["input"] == SHARE
        assert result["output"] == POST
        assert result["resolved"] is True
        assert result["kind"] == "post"

    def test_share_redirect_not_to_post_errors(self):
        with patch(
            "bot.control.resolve.resolve_share_url",
            return_value="https://www.reddit.com/r/excel/",
        ):
            with pytest.raises(CliError, match="did not redirect to a canonical post"):
                resolve_reddit_url(SHARE)

    def test_share_http_error(self):
        with patch(
            "bot.control.resolve.resolve_share_url",
            side_effect=urllib.error.HTTPError(SHARE, 404, "Not Found", hdrs=None, fp=None),
        ):
            with pytest.raises(CliError, match="HTTP 404"):
                resolve_reddit_url(SHARE)

    def test_share_url_error(self):
        with patch(
            "bot.control.resolve.resolve_share_url",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with pytest.raises(CliError, match="Failed to resolve"):
                resolve_reddit_url(SHARE)

    def test_other_reddit_passthrough(self):
        result = resolve_reddit_url(SUB)
        assert result["resolved"] is False
        assert result["kind"] == "subreddit"
        assert result["input"] == SUB
        assert result["output"] == SUB

    def test_invalid_url_errors(self):
        with pytest.raises(CliError, match="Not a valid Reddit URL"):
            resolve_reddit_url("https://example.com/nope")

    def test_empty_url_errors(self):
        with pytest.raises(CliError, match="non-empty"):
            resolve_reddit_url("   ")


class TestResolveUrlCli:
    def test_cli_json_passthrough_post(self, capsys):
        exit_code = tool_cli.main(
            [
                "--json",
                "resolve-url",
                "--link",
                POST,
            ]
        )
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["command"] == "resolve-url"
        assert payload["data"]["resolved"] is False
        assert payload["data"]["kind"] == "post"
        assert payload["data"]["input"] == POST
        assert "comments" in payload["data"]["output"]

    def test_cli_json_share_resolved(self, capsys):
        with patch(
            "bot.control.resolve.resolve_share_url",
            return_value=POST,
        ):
            exit_code = tool_cli.main(
                [
                    "--json",
                    "resolve-url",
                    "--link",
                    SHARE,
                ]
            )
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["data"]["resolved"] is True
        assert payload["data"]["output"] == POST
        assert payload["data"]["kind"] == "post"

    def test_cli_invalid_fails_cleanly(self, capsys):
        exit_code = tool_cli.main(
            [
                "--json",
                "resolve-url",
                "--link",
                "https://google.com/",
            ]
        )
        assert exit_code == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False
        assert payload["error"]
        assert payload["data"]["resolved"] is False
