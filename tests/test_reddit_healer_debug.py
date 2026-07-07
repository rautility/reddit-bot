"""Tests for saved Chrome debug helper commands."""

from argparse import Namespace

from scripts import reddit_healer_debug


def test_print_bot_command_quotes_accounts_and_links_paths(tmp_path, capsys):
    accounts = tmp_path / "accounts with spaces.txt"
    links = tmp_path / "links with spaces.txt"
    accounts.write_text("user|pass\n")
    links.write_text("https://reddit.com/r/test|upvote\n")

    reddit_healer_debug.print_bot_command(
        Namespace(
            accounts=str(accounts),
            links=str(links),
            debug_address="127.0.0.1:9222",
            host="127.0.0.1",
            port=9222,
        )
    )

    output = capsys.readouterr().out
    assert f"'{accounts}'" in output
    assert f"'{links.resolve()}'" in output


def test_profile_info_quotes_accounts_and_links_paths(tmp_path, capsys):
    accounts = tmp_path / "accounts with spaces.txt"
    links = tmp_path / "links with spaces.txt"

    reddit_healer_debug.profile_info(
        Namespace(
            profile_name="Chrome Reddit Bot Debug Profile",
            profile_dir=str(tmp_path / "profile with spaces"),
            extension_path=str(tmp_path / "extension with spaces"),
            accounts=str(accounts),
            links=str(links),
            url="https://www.reddit.com/login/",
            debug_address="127.0.0.1:9222",
            host="127.0.0.1",
            port=9222,
        )
    )

    output = capsys.readouterr().out
    assert f"'{accounts}'" in output
    assert f"'{links}'" in output


def test_attached_driver_uses_repo_managed_chromedriver(mocker):
    install = mocker.patch(
        "scripts.reddit_healer_debug.install_chromedriver",
        return_value="/tmp/chromedriver",
    )
    chrome = mocker.patch("scripts.reddit_healer_debug.webdriver.Chrome", return_value=object())
    service = mocker.patch("scripts.reddit_healer_debug.Service")

    result = reddit_healer_debug.attached_driver(
        Namespace(
            debug_address="127.0.0.1:9222",
            host="127.0.0.1",
            port=9222,
        )
    )

    assert result is chrome.return_value
    install.assert_called_once_with()
    service.assert_called_once_with("/tmp/chromedriver")
    chrome.assert_called_once()
