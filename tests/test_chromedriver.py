"""Tests for ChromeDriver cache resolution helpers."""

from pathlib import Path

from bot.utils import chromedriver


def test_chromedriver_cache_dir_defaults_to_repo_local_cache(mocker):
    mocker.patch.dict("os.environ", {}, clear=False)

    cache_dir = chromedriver.chromedriver_cache_dir()

    assert cache_dir == Path("/Users/raulvecchione/MEGA/rvScripts/reddit-bot/.webdriver")


def test_chromedriver_cache_dir_honors_env_override(tmp_path, mocker):
    override = tmp_path / "custom-wdm"
    mocker.patch.dict("os.environ", {"REDDIT_BOT_WDM_CACHE": str(override)}, clear=False)

    cache_dir = chromedriver.chromedriver_cache_dir()

    assert cache_dir == override


def test_install_chromedriver_uses_driver_cache_manager_root(mocker, tmp_path):
    cache_dir = tmp_path / "wdm-cache"
    manager = mocker.Mock()
    manager.install.return_value = "/tmp/chromedriver"
    cache_manager = mocker.patch("bot.utils.chromedriver.DriverCacheManager", return_value=object())
    manager_cls = mocker.patch("bot.utils.chromedriver.ChromeDriverManager", return_value=manager)
    mocker.patch("bot.utils.chromedriver.chromedriver_cache_dir", return_value=cache_dir)

    path = chromedriver.install_chromedriver()

    assert path == "/tmp/chromedriver"
    assert cache_dir.is_dir()
    cache_manager.assert_called_once_with(root_dir=str(cache_dir))
    manager_cls.assert_called_once_with(cache_manager=cache_manager.return_value)
    manager.install.assert_called_once_with()
