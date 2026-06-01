from crypto_sentiment_crawler.crawler.fetcher import Fetcher


def test_reddit_domains_require_proxy() -> None:
    fetcher = Fetcher()

    assert fetcher._needs_proxy("https://reddit.com/r/bitcoin/")
    assert fetcher._needs_proxy("https://www.reddit.com/r/bitcoin/")
    assert fetcher._needs_proxy("https://old.reddit.com/r/bitcoin/new/")
    assert not fetcher._needs_proxy("https://notreddit.com/r/bitcoin/")
    assert not fetcher._needs_proxy("https://old.reddit.com.evil.example/")


def test_residential_proxy_env_fallback(monkeypatch) -> None:
    monkeypatch.delenv("PROXY_URL", raising=False)
    monkeypatch.setenv("RESIDENTIAL_PROXY", "http://user:pass@proxy.example:8080")

    fetcher = Fetcher()

    assert fetcher.proxies == ["http://user:pass@proxy.example:8080"]


def test_proxy_url_takes_precedence(monkeypatch) -> None:
    monkeypatch.setenv("PROXY_URL", "http://primary.example:8080")
    monkeypatch.setenv("RESIDENTIAL_PROXY", "http://fallback.example:8080")

    fetcher = Fetcher()

    assert fetcher.proxies == ["http://primary.example:8080"]
