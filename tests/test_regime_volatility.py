"""Tests for the RegimeCollector volatility calculation.

The previous implementation relied on CryptoCompare's histohour endpoint,
which now requires an API key (HTTP 401) and produced NULL / "N/A" in
production. These tests verify the new key-free path (CoinGecko primary,
Coinbase fallback) and the corrected realized-volatility formula.
"""

import math

import httpx

from crypto_sentiment_crawler.confounders.regime import RegimeCollector


class _FakeResponse:
    def __init__(self, status_code: int, json_data):
        self.status_code = status_code
        self._json = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=None, response=self
            )

    def json(self):
        return self._json


class _SequentialClient:
    """Returns queued responses in order for each GET call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params))
        return self._responses.pop(0)

    async def aclose(self):
        pass


def _coingecko_prices(closes):
    # CoinGecko returns [[ts_ms, price], ...] oldest -> newest.
    return {"prices": [[i * 3600_000, p] for i, p in enumerate(closes)]}


def _coinbase_candles(closes):
    # Coinbase returns [ts, low, high, open, close, volume] newest -> oldest.
    return [[i, 0, 0, 0, p, 0] for i, p in reversed(list(enumerate(closes)))]


def _make_closes(n=25, start=60000.0, hourly_std=0.002):
    """Synthesize a gentle random-ish walk with a known per-hour std."""
    closes = [start]
    step = start * hourly_std
    for i in range(1, n):
        # Deterministic oscillation so std is non-zero and reproducible.
        delta = step * math.sin(i / 3.0)
        closes.append(closes[-1] + delta)
    return closes


async def _run_with_client(responses, **kwargs):
    collector = RegimeCollector()
    collector.client = _SequentialClient(responses)
    try:
        return await collector.calculate_volatility(**kwargs)
    finally:
        await collector.close()


class TestCalculateVolatility:
    async def test_coingecko_primary_returns_volatility(self):
        closes = _make_closes(25)
        resp = _FakeResponse(200, _coingecko_prices(closes))
        result = await _run_with_client([resp])

        assert "error" not in result
        assert result["volatility_24h"] is not None
        # 24h realized vol should be a small positive percentage (single digits).
        assert 0 < result["volatility_24h"] < 20
        assert result["current_price"] == closes[-1]

    async def test_coinbase_fallback_used_when_coingecko_fails(self):
        closes = _make_closes(25)
        coingecko_err = _FakeResponse(429, {"error": "rate limit"})
        coinbase_ok = _FakeResponse(200, _coinbase_candles(closes))
        result = await _run_with_client([coingecko_err, coinbase_ok])

        assert "error" not in result
        assert result["volatility_24h"] is not None
        assert result["current_price"] == closes[-1]

    async def test_both_sources_fail_returns_error(self):
        coingecko_err = _FakeResponse(401, {"error": "unauthorized"})
        coinbase_err = _FakeResponse(503, {"error": "unavailable"})
        result = await _run_with_client([coingecko_err, coinbase_err])

        assert "error" in result
        assert result.get("volatility_24h") is None

    async def test_insufficient_data_returns_error(self):
        # Only a single price point -> not enough for returns.
        resp = _FakeResponse(200, _coingecko_prices([60000.0]))
        result = await _run_with_client([resp])

        assert "error" in result

    async def test_formula_scale_is_window_realized_vol(self):
        # Build closes with a known constant hourly return.
        base = 100.0
        hourly_ret = 0.01  # 1% per hour
        closes = [base * (1 + hourly_ret) ** i for i in range(25)]
        resp = _FakeResponse(200, _coingecko_prices(closes))
        result = await _run_with_client([resp])

        # With constant 1% hourly returns, std of returns = 0, so vol = 0.
        # Perturb slightly to confirm it tracks the window-scaled std.
        closes2 = [base * (1 + hourly_ret + 0.001 * (i % 2)) ** i for i in range(25)]
        resp2 = _FakeResponse(200, _coingecko_prices(closes2))
        result2 = await _run_with_client([resp2])

        assert result["volatility_24h"] == 0.0 or abs(result["volatility_24h"]) < 1e-9
        assert result2["volatility_24h"] is not None
        # Sanity: not the old ~90x annualized inflation.
        assert result2["volatility_24h"] < 50
