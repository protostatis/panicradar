"""Cookie-refreshing Unbrowser transport for Reddit HTML."""

import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import httpx

SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization", "set-cookie"}
UNUSABLE_TITLES = ("<title>blocked</title>", "<title>welcome to reddit</title>")


@dataclass(frozen=True)
class RedditTransportResponse:
    """A Reddit response returned without exposing browser session cookies."""

    status_code: int
    content: str
    headers: dict[str, str]
    elapsed_seconds: float
    error: str | None = None


def _default_client_factory() -> Any:
    from unbrowser import Client

    return Client()


class UnbrowserRedditTransport:
    """Fetch Reddit in Unbrowser and refresh cookies after an unusable response."""

    def __init__(
        self,
        cookie_service_url: str,
        *,
        cookie_service_socket: str = "",
        cookie_service_token: str = "",
        client_factory: Callable[[], Any] = _default_client_factory,
        cookie_timeout_seconds: float = 90.0,
        refresh_cooldown_seconds: float = 600.0,
    ):
        self.cookie_service_url = cookie_service_url.rstrip("/")
        self.cookie_service_socket = cookie_service_socket
        self.cookie_service_token = cookie_service_token
        self.client_factory = client_factory
        self.cookie_timeout_seconds = cookie_timeout_seconds
        self.refresh_cooldown_seconds = refresh_cooldown_seconds
        self._client: Any | None = None
        self._refresh_blocked_until = 0.0
        self._rate_limited_until = 0.0

    def fetch(self, url: str) -> RedditTransportResponse:
        started_at = time.monotonic()
        try:
            if started_at < self._rate_limited_until:
                return RedditTransportResponse(
                    status_code=429,
                    content="",
                    headers={},
                    elapsed_seconds=0.0,
                    error="Reddit rate limit cooldown is active",
                )
            response = self._navigate(url)
            if self._is_blocked(response) and (
                self.cookie_service_url or self.cookie_service_socket
            ):
                now = time.monotonic()
                if now < self._refresh_blocked_until:
                    return RedditTransportResponse(
                        status_code=403,
                        content="",
                        headers=response.headers,
                        elapsed_seconds=time.monotonic() - started_at,
                        error="Reddit cookie refresh circuit is open",
                    )

                try:
                    cookies = self._request_cookies(url)
                    # A client that has already received Reddit's anonymous
                    # block response can remain unusable after cookies are
                    # injected. Retry from a fresh browser context with the
                    # dedicated-session cookie set before its first request.
                    self._discard_client()
                    self._client_or_create().cookies_set(cookies, url)
                except Exception as error:
                    self._refresh_blocked_until = now + self.refresh_cooldown_seconds
                    return RedditTransportResponse(
                        status_code=0,
                        content="",
                        headers={},
                        elapsed_seconds=time.monotonic() - started_at,
                        error=f"Reddit cookie refresh failed: {type(error).__name__}",
                    )

                response = self._navigate(url)
                if self._is_blocked(response):
                    self._refresh_blocked_until = now + self.refresh_cooldown_seconds
                    response = RedditTransportResponse(
                        status_code=403,
                        content="",
                        headers=response.headers,
                        elapsed_seconds=time.monotonic() - started_at,
                        error="Reddit response remained unusable after cookie refresh",
                    )

            elif self._is_blocked(response):
                response = RedditTransportResponse(
                    status_code=403,
                    content="",
                    headers=response.headers,
                    elapsed_seconds=time.monotonic() - started_at,
                    error="Reddit response is unusable",
                )

            if response.status_code == 429:
                retry_after = self._retry_after_seconds(response.headers)
                self._rate_limited_until = time.monotonic() + retry_after

            return RedditTransportResponse(
                status_code=response.status_code,
                content=response.content,
                headers=response.headers,
                elapsed_seconds=time.monotonic() - started_at,
                error=response.error,
            )
        except Exception as error:
            return RedditTransportResponse(
                status_code=0,
                content="",
                headers={},
                elapsed_seconds=time.monotonic() - started_at,
                error=f"Unbrowser Reddit transport failed: {type(error).__name__}",
            )

    def close(self) -> None:
        self._discard_client()

    def _discard_client(self) -> None:
        if self._client is None:
            return
        try:
            self._client.cookies_clear()
        finally:
            self._client.close()
            self._client = None

    def _client_or_create(self) -> Any:
        if self._client is None:
            self._client = self.client_factory()
        return self._client

    def _navigate(self, url: str) -> RedditTransportResponse:
        result = self._client_or_create().navigate(url)
        status_code = int(result.get("status", 0))
        headers = {
            str(name).lower(): str(value)
            for name, value in (result.get("headers") or {}).items()
            if str(name).lower() not in SENSITIVE_HEADERS
        }
        content = self._client_or_create().body() if status_code == 200 else ""
        return RedditTransportResponse(
            status_code=status_code,
            content=content,
            headers=headers,
            elapsed_seconds=0.0,
            error=None if status_code == 200 else f"HTTP {status_code}",
        )

    def _request_cookies(self, url: str) -> list[dict[str, Any]]:
        if not self.cookie_service_token:
            raise RuntimeError("cookie solver token is not configured")
        if self.cookie_service_socket:
            raw = self._request_cookies_over_socket(url)
        else:
            raw = self._request_cookies_over_http(url)

        if len(raw) > 64 * 1024:
            raise RuntimeError("cookie solver response exceeded limit")
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise RuntimeError("cookie solver returned invalid JSON") from error

        cookies = (
            payload.get("cookies")
            if isinstance(payload, dict) and payload.get("ok")
            else None
        )
        if not isinstance(cookies, list):
            raise RuntimeError("cookie solver returned no cookies")

        normalized = [self._normalize_cookie(cookie) for cookie in cookies]
        normalized = [cookie for cookie in normalized if cookie]
        if not normalized:
            raise RuntimeError("cookie solver returned no valid Reddit cookies")
        return normalized

    def _request_cookies_over_socket(self, url: str) -> bytes:
        transport = httpx.HTTPTransport(uds=self.cookie_service_socket)
        try:
            with httpx.Client(transport=transport, timeout=self.cookie_timeout_seconds) as client:
                response = client.post(
                    "http://solver/solve",
                    json={"url": url},
                    headers={
                        "Cache-Control": "no-store",
                        "X-Reddit-Solver-Token": self.cookie_service_token,
                    },
                )
                response.raise_for_status()
                return response.content
        except httpx.HTTPError as error:
            raise RuntimeError("cookie solver request failed") from error

    def _request_cookies_over_http(self, url: str) -> bytes:
        request = Request(
            f"{self.cookie_service_url}/solve",
            data=json.dumps({"url": url}).encode(),
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
                "X-Reddit-Solver-Token": self.cookie_service_token,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.cookie_timeout_seconds) as response:
                raw = response.read(64 * 1024 + 1)
        except (HTTPError, URLError, TimeoutError) as error:
            raise RuntimeError("cookie solver request failed") from error
        return raw

    @staticmethod
    def _is_blocked(response: RedditTransportResponse) -> bool:
        return response.status_code == 403 or (
            response.status_code == 200
            and any(title in response.content[:500].casefold() for title in UNUSABLE_TITLES)
        )

    @staticmethod
    def _normalize_cookie(cookie: Any) -> dict[str, Any] | None:
        if not isinstance(cookie, dict):
            return None
        name = cookie.get("name")
        value = cookie.get("value")
        domain = str(cookie.get("domain", "")).lower().lstrip(".")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(value, str)
            or not value
            or not (domain == "reddit.com" or domain.endswith(".reddit.com"))
        ):
            return None
        return {
            "name": name,
            "value": value,
            "domain": f".{domain}",
            "path": str(cookie.get("path") or "/"),
            "secure": bool(cookie.get("secure", True)),
            "http_only": bool(cookie.get("http_only", cookie.get("httpOnly", False))),
        }

    @staticmethod
    def _retry_after_seconds(headers: dict[str, str]) -> float:
        try:
            return min(max(float(headers.get("retry-after", "60")), 15.0), 600.0)
        except ValueError:
            return 60.0
