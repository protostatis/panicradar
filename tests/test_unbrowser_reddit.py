"""Tests for the cookie-refreshing Unbrowser Reddit transport."""

import pytest

from crypto_sentiment_crawler.crawler.unbrowser_reddit import UnbrowserRedditTransport


class FakeClient:
    def __init__(self, statuses: list[int], bodies: list[str] | None = None):
        self.statuses = iter(statuses)
        self.bodies = iter(bodies or ["<html>Reddit</html>"])
        self.cookies_set_calls: list[tuple[list[dict], str | None]] = []
        self.closed = False

    def navigate(self, _url: str) -> dict:
        return {"status": next(self.statuses), "headers": {"set-cookie": "secret", "x-safe": "yes"}}

    def body(self) -> str:
        return next(self.bodies)

    def cookies_set(self, cookies: list[dict], url: str | None = None) -> None:
        self.cookies_set_calls.append((cookies, url))

    def cookies_clear(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_transport_refreshes_once_after_forbidden_response(monkeypatch) -> None:
    client = FakeClient([403, 200])
    transport = UnbrowserRedditTransport(
        "http://solver.test",
        client_factory=lambda: client,
    )
    monkeypatch.setattr(
        transport,
        "_request_cookies",
        lambda _url: [{"name": "session", "value": "value", "domain": ".reddit.com", "path": "/"}],
    )

    response = transport.fetch("https://old.reddit.com/r/bitcoin/new/")

    assert response.status_code == 200
    assert response.content == "<html>Reddit</html>"
    assert response.headers == {"x-safe": "yes"}
    assert len(client.cookies_set_calls) == 1


def test_transport_replaces_the_anonymously_blocked_client(monkeypatch) -> None:
    anonymous_client = FakeClient([403])
    session_client = FakeClient([200])
    clients = iter([anonymous_client, session_client])
    transport = UnbrowserRedditTransport(
        "http://solver.test",
        client_factory=lambda: next(clients),
    )
    monkeypatch.setattr(
        transport,
        "_request_cookies",
        lambda _url: [{"name": "session", "value": "value", "domain": ".reddit.com"}],
    )

    response = transport.fetch("https://old.reddit.com/r/bitcoin/new/")

    assert response.status_code == 200
    assert anonymous_client.closed
    assert len(session_client.cookies_set_calls) == 1


def test_transport_does_not_refresh_cookies_for_rate_limit(monkeypatch) -> None:
    client = FakeClient([429])
    transport = UnbrowserRedditTransport(
        "http://solver.test",
        client_factory=lambda: client,
    )
    monkeypatch.setattr(
        transport,
        "_request_cookies",
        lambda _url: (_ for _ in ()).throw(AssertionError),
    )

    response = transport.fetch("https://old.reddit.com/r/bitcoin/new/")

    assert response.status_code == 429
    assert client.cookies_set_calls == []


def test_transport_honors_rate_limit_cooldown(monkeypatch) -> None:
    client = FakeClient([429])
    transport = UnbrowserRedditTransport(
        "http://solver.test",
        client_factory=lambda: client,
    )
    monkeypatch.setattr(
        transport,
        "_request_cookies",
        lambda _url: (_ for _ in ()).throw(AssertionError),
    )

    first = transport.fetch("https://old.reddit.com/r/bitcoin/new/")
    second = transport.fetch("https://old.reddit.com/r/bitcoin/new/")

    assert first.status_code == 429
    assert second.status_code == 429
    assert second.error == "Reddit rate limit cooldown is active"


def test_transport_refreshes_after_a_blocked_html_response(monkeypatch) -> None:
    client = FakeClient(
        [200, 200],
        ["<html><title>Blocked</title></html>", "<html>Reddit</html>"],
    )
    transport = UnbrowserRedditTransport(
        "http://solver.test",
        client_factory=lambda: client,
    )
    monkeypatch.setattr(
        transport,
        "_request_cookies",
        lambda _url: [{"name": "session", "value": "value", "domain": ".reddit.com"}],
    )

    response = transport.fetch("https://old.reddit.com/r/bitcoin/new/")

    assert response.status_code == 200
    assert response.content == "<html>Reddit</html>"
    assert len(client.cookies_set_calls) == 1


def test_transport_refreshes_after_a_welcome_page_response(monkeypatch) -> None:
    client = FakeClient(
        [200, 200],
        ["<html><title>Welcome to Reddit</title></html>", "<html>Reddit</html>"],
    )
    transport = UnbrowserRedditTransport(
        "http://solver.test",
        client_factory=lambda: client,
    )
    monkeypatch.setattr(
        transport,
        "_request_cookies",
        lambda _url: [{"name": "session", "value": "value", "domain": ".reddit.com"}],
    )

    response = transport.fetch("https://old.reddit.com/r/bitcoin/new/")

    assert response.status_code == 200
    assert response.content == "<html>Reddit</html>"
    assert len(client.cookies_set_calls) == 1


def test_transport_rejects_a_blocked_html_response_after_refresh(monkeypatch) -> None:
    client = FakeClient(
        [200, 200],
        ["<html><title>Blocked</title></html>", "<html><title>Blocked</title></html>"],
    )
    transport = UnbrowserRedditTransport(
        "http://solver.test",
        client_factory=lambda: client,
    )
    monkeypatch.setattr(
        transport,
        "_request_cookies",
        lambda _url: [{"name": "session", "value": "value", "domain": ".reddit.com"}],
    )

    response = transport.fetch("https://old.reddit.com/r/bitcoin/new/")

    assert response.status_code == 403
    assert response.content == ""
    assert response.error == "Reddit response remained unusable after cookie refresh"


def test_transport_requires_a_solver_token() -> None:
    transport = UnbrowserRedditTransport("http://solver.test")

    with pytest.raises(RuntimeError, match="token is not configured"):
        transport._request_cookies("https://old.reddit.com/r/bitcoin/new/")
