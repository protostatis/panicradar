"""Tests for Reddit proxy routing."""

import httpx
import pytest

from crypto_sentiment_crawler.crawler.fetcher import Fetcher


def test_reddit_domains_require_proxy() -> None:
    fetcher = Fetcher()

    assert fetcher._needs_proxy("https://reddit.com/r/bitcoin/")
    assert fetcher._needs_proxy("https://www.reddit.com/r/bitcoin/")
    assert fetcher._needs_proxy("https://old.reddit.com/r/bitcoin/new/")


def test_non_reddit_domains_do_not_require_proxy() -> None:
    fetcher = Fetcher()

    assert not fetcher._needs_proxy("https://notreddit.com/r/bitcoin/")
    assert not fetcher._needs_proxy("https://old.reddit.com.evil.example/")
    assert not fetcher._needs_proxy("https://example.com/")


def test_proxy_url_environment_configures_proxy(monkeypatch) -> None:
    monkeypatch.setenv("PROXY_URL", "http://user:pass@proxy.example:8080")

    fetcher = Fetcher()

    assert fetcher.proxies == ["http://user:pass@proxy.example:8080"]


@pytest.mark.asyncio
async def test_reddit_fetch_uses_configured_proxy(monkeypatch) -> None:
    calls: list[bool] = []

    async def fake_fetch(
        url: str,
        headers: dict,
        use_proxy: bool = False,
    ) -> httpx.Response:
        calls.append(use_proxy)
        return httpx.Response(200, text="<html></html>")

    async with Fetcher(
        proxy_url="http://user:pass@proxy.example:8080",
        randomize_delay=False,
    ) as fetcher:
        monkeypatch.setattr(fetcher, "_fetch_with_retry", fake_fetch)
        result = await fetcher.fetch("https://old.reddit.com/r/bitcoin/new/")

    assert result.success
    assert calls == [True]
