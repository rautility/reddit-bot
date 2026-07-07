"""Proxy management — loading, rotation, and validation."""

from __future__ import annotations

import itertools
from dataclasses import dataclass


@dataclass
class Proxy:
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def chrome_arg(self) -> str:
        return f"--proxy-server={self.host}:{self.port}"

    @classmethod
    def from_string(cls, s: str) -> Proxy:
        """Parse proxy from string format: host:port or host:port:user:pass."""
        parts = s.strip().split(":")
        if len(parts) == 2:
            return cls(host=parts[0], port=int(parts[1]))
        elif len(parts) == 4:
            return cls(
                host=parts[0],
                port=int(parts[1]),
                username=parts[2],
                password=parts[3],
            )
        raise ValueError(f"Invalid proxy format: {s}")


_proxy_cycle: itertools.cycle | None = None
_proxies: list[Proxy] = []


def load_proxies(path: str) -> list[Proxy]:
    """Load proxies from a file (one per line: host:port or host:port:user:pass)."""
    global _proxy_cycle, _proxies
    with open(path) as f:
        lines = [line.strip() for line in f if line.strip()]
    _proxies = [Proxy.from_string(line) for line in lines]
    _proxy_cycle = itertools.cycle(_proxies)
    return _proxies


def get_next_proxy() -> Proxy | None:
    """Get the next proxy in rotation. Returns None if no proxies loaded."""
    if _proxy_cycle is None:
        return None
    return next(_proxy_cycle)


def get_all_proxies() -> list[Proxy]:
    """Return all loaded proxies."""
    return _proxies
