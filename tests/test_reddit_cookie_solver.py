"""Tests for the local Reddit cookie solver's restrictive export filter."""

import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import httpx

from scripts.reddit_cookie_solver import RedditCookieSolver, make_handler


def test_solver_exports_only_allowlisted_reddit_cookies() -> None:
    cookies = RedditCookieSolver._select_cookies(
        [
            {"name": "loid", "value": "safe", "domain": ".reddit.com"},
            {"name": "token_v2", "value": "sensitive", "domain": ".reddit.com"},
            {"name": "loid", "value": "wrong-domain", "domain": ".example.com"},
            {"name": "loid", "value": "", "domain": ".reddit.com"},
        ],
        {"loid"},
    )

    assert cookies == [
        {
            "name": "loid",
            "value": "safe",
            "domain": ".reddit.com",
            "path": "/",
            "secure": False,
            "http_only": False,
        }
    ]


def test_solver_requires_a_token_before_exporting_cookies() -> None:
    class FakeSolver:
        calls = 0

        def solve(self, _url: str) -> list[dict]:
            self.calls += 1
            return [{"name": "loid", "value": "test", "domain": ".reddit.com"}]

    solver = FakeSolver()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(solver, "t" * 32))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/solve"

    try:
        denied = httpx.post(endpoint, json={"url": "https://old.reddit.com/r/bitcoin/new/"})
        allowed = httpx.post(
            endpoint,
            json={"url": "https://old.reddit.com/r/bitcoin/new/"},
            headers={"X-Reddit-Solver-Token": "t" * 32},
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join()

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert solver.calls == 1


def test_solver_launches_headlessly_by_default(monkeypatch) -> None:
    solver = RedditCookieSolver("reddit-crawler", 9444, {"reddit_session"})
    launch_calls: list[tuple[str, ...]] = []

    def fake_run(*args: str, **_kwargs) -> SimpleNamespace:
        launch_calls.append(args)
        if args[0] == "cookies":
            return SimpleNamespace(
                stdout='[{"name":"reddit_session","value":"test","domain":".reddit.com"}]'
            )
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(solver, "_run", fake_run)
    monkeypatch.setattr(
        "scripts.reddit_cookie_solver.subprocess.run",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("scripts.reddit_cookie_solver.time.sleep", lambda _seconds: None)

    cookies = solver.solve("https://old.reddit.com/r/Bitcoin/new/")

    assert cookies[0]["name"] == "reddit_session"
    assert launch_calls[0] == (
        "launch",
        "--profile",
        "reddit-crawler",
        "--headless",
        "--stealth",
        "https://old.reddit.com/r/Bitcoin/new/",
    )
