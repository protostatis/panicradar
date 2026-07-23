#!/usr/bin/env python3
"""Run a local-only Reddit cookie solver backed by an existing Chrome profile."""

import argparse
import hmac
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

MAX_BODY_BYTES = 4096
solve_lock = threading.Lock()


def is_reddit_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "reddit.com" or host.endswith(".reddit.com"))


class RedditCookieSolver:
    def __init__(
        self,
        profile: str,
        cdp_port: int,
        allowed_cookie_names: set[str],
        use_existing_profile: bool = False,
        headless: bool = True,
    ):
        self.profile = profile
        self.cdp_port = str(cdp_port)
        self.allowed_cookie_names = allowed_cookie_names
        self.use_existing_profile = use_existing_profile
        self.headless = headless

    def _run(self, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["unchained", "--port", self.cdp_port, "--json", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def solve(self, url: str) -> list[dict]:
        if not is_reddit_url(url):
            raise ValueError("only https Reddit URLs are allowed")

        try:
            launch_args = ["launch", "--profile", self.profile]
            if self.use_existing_profile:
                launch_args.append("--use-profile")
            if self.headless:
                launch_args.append("--headless")
            launch_args.extend(["--stealth", "https://old.reddit.com/r/Bitcoin/new/"])
            self._run(*launch_args)
            time.sleep(2)
            raw = self._run(
                "cookies", "get", "--urls", "https://www.reddit.com", "https://old.reddit.com"
            ).stdout
            payload = json.loads(raw or "[]")
            source = self._cookie_source(payload)
            cookies = self._select_cookies(source, self.allowed_cookie_names)
            if not cookies:
                raise RuntimeError("Chrome supplied no allowlisted Reddit cookies")
            return cookies
        finally:
            subprocess.run(
                ["unchained", "--port", self.cdp_port, "kill"],
                capture_output=True,
                text=True,
                timeout=15,
            )

    @staticmethod
    def _cookie_source(payload: object) -> object:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return payload.get("cookies", payload.get("result", []))
        return []

    @staticmethod
    def _select_cookies(source: object, allowed_cookie_names: set[str]) -> list[dict]:
        if not isinstance(source, list):
            return []

        cookies = []
        for item in source:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            domain = str(item.get("domain", "")).lower().lstrip(".")
            if (
                not isinstance(name, str)
                or name not in allowed_cookie_names
                or not isinstance(value, str)
                or not value
                or not (domain == "reddit.com" or domain.endswith(".reddit.com"))
            ):
                continue
            cookies.append(
                {
                    "name": name,
                    "value": value,
                    "domain": f".{domain}",
                    "path": item.get("path", "/"),
                    "secure": bool(item.get("secure", False)),
                    "http_only": bool(item.get("httpOnly", item.get("http_only", False))),
                }
            )
        return cookies


def make_handler(solver: RedditCookieSolver, token: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._json(200, {"ok": True})
                return
            self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:
            if self.path != "/solve":
                self._json(404, {"ok": False, "error": "not found"})
                return
            supplied_token = self.headers.get("X-Reddit-Solver-Token", "")
            if not hmac.compare_digest(supplied_token, token):
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("content-length", "0"))
                if not 0 < length <= MAX_BODY_BYTES:
                    raise ValueError("invalid request length")
                payload = json.loads(self.rfile.read(length))
                with solve_lock:
                    cookies = solver.solve(str(payload.get("url", "")))
                # Cookie values are returned only to the local socket peer and are never logged.
                self._json(200, {"ok": True, "cookies": cookies})
            except Exception as error:
                self._json(502, {"ok": False, "error": type(error).__name__})

        def _json(self, status: int, payload: dict) -> None:
            raw = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("cache-control", "no-store")
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, _format: str, *_args) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--cdp-port", type=int, default=9444)
    parser.add_argument(
        "--profile",
        required=True,
        help="Dedicated Unchained profile name (sandboxed unless --use-existing-profile is set)",
    )
    parser.add_argument(
        "--use-existing-profile",
        action="store_true",
        help="Use a reviewed dedicated Chrome profile instead of an Unchained sandbox",
    )
    parser.add_argument(
        "--headed",
        action="store_false",
        dest="headless",
        help="Show Chrome for diagnostics (headless is the default)",
    )
    parser.add_argument(
        "--cookie-name",
        action="append",
        required=True,
        help="Reddit cookie name to export; repeat only for the minimum verified set",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("REDDIT_COOKIE_SOLVER_TOKEN", ""),
        help="Solver token (defaults to REDDIT_COOKIE_SOLVER_TOKEN)",
    )
    args = parser.parse_args()

    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("the solver must bind to loopback")
    if len(args.token) < 32:
        parser.error("set a random REDDIT_COOKIE_SOLVER_TOKEN with at least 32 characters")

    solver = RedditCookieSolver(
        args.profile,
        args.cdp_port,
        set(args.cookie_name),
        use_existing_profile=args.use_existing_profile,
        headless=args.headless,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(solver, args.token))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
