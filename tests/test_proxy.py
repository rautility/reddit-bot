"""Tests for proxy management."""

import pytest

from bot.utils.proxy import Proxy, get_next_proxy, load_proxies


class TestProxy:
    def test_from_string_host_port(self):
        p = Proxy.from_string("127.0.0.1:8080")
        assert p.host == "127.0.0.1"
        assert p.port == 8080
        assert p.username is None

    def test_from_string_with_auth(self):
        p = Proxy.from_string("127.0.0.1:8080:user:pass")
        assert p.host == "127.0.0.1"
        assert p.port == 8080
        assert p.username == "user"
        assert p.password == "pass"

    def test_chrome_arg(self):
        p = Proxy(host="127.0.0.1", port=8080)
        assert p.chrome_arg == "--proxy-server=127.0.0.1:8080"

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            Proxy.from_string("invalid")


class TestProxyRotation:
    def test_load_and_rotate(self, tmp_path):
        f = tmp_path / "proxies.txt"
        f.write_text("127.0.0.1:8080\n127.0.0.1:8081\n127.0.0.1:8082\n")

        proxies = load_proxies(str(f))
        assert len(proxies) == 3

        p1 = get_next_proxy()
        p2 = get_next_proxy()
        p3 = get_next_proxy()
        p4 = get_next_proxy()  # Should cycle back

        assert p1.port == 8080
        assert p2.port == 8081
        assert p3.port == 8082
        assert p4.port == 8080  # Cycled
