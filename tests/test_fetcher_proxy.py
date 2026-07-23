"""Tests for Reddit transport routing."""

import httpx
import pytest

from crypto_sentiment_crawler.crawler.fetcher import Fetcher
from crypto_sentiment_crawler.crawler.unbrowser_reddit import RedditTransportResponse


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


@pytest.mark.asyncio
async def test_reddit_fetch_uses_unbrowser_transport_when_enabled(monkeypatch) -> None:
    class FakeTransport:
        def __init__(self):
            self.urls: list[str] = []

        def fetch(self, url: str) -> RedditTransportResponse:
            self.urls.append(url)
            return RedditTransportResponse(
                status_code=200,
                content="<html></html>",
                headers={},
                elapsed_seconds=0.01,
            )

        def close(self) -> None:
            pass

    monkeypatch.setenv("REDDIT_FETCH_MODE", "unbrowser")
    transport = FakeTransport()
    async with Fetcher(
        randomize_delay=False,
        reddit_transport=transport,  # type: ignore[arg-type]
    ) as fetcher:
        result = await fetcher.fetch("https://old.reddit.com/r/bitcoin/new/")

    assert result.success
    assert transport.urls == ["https://old.reddit.com/r/bitcoin/new/"]


@pytest.mark.asyncio
async def test_unbrowser_transport_receives_the_solver_token(monkeypatch) -> None:
    monkeypatch.setenv("REDDIT_FETCH_MODE", "unbrowser")
    monkeypatch.setenv("UNBROWSER_COOKIE_SERVICE_SOCKET", "/run/reddit-solver.sock")
    monkeypatch.setenv("UNBROWSER_COOKIE_SERVICE_TOKEN", "solver-token")

    async with Fetcher(randomize_delay=False) as fetcher:
        assert fetcher.reddit_transport is not None
        assert fetcher.reddit_transport.cookie_service_socket == "/run/reddit-solver.sock"
        assert fetcher.reddit_transport.cookie_service_token == "solver-token"
