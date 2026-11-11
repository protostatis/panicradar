"""Regression tests for canonical source keys.

Belief keys, weight-table keys, and ``sentiment_raw.source`` must agree on one
spelling per source. Older discovery and backfill code built the key from a
subreddit's display name (``reddit_CryptoCurrency``), which produced a second
belief that never matched any database row and stayed frozen forever.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crypto_sentiment_crawler.bayesian.beliefs import SourceBeliefStore
from crypto_sentiment_crawler.crawler.sources import load_discovered_sources
from crypto_sentiment_crawler.source_names import canonical_source_name, reddit_source_key


class TestCanonicalSourceName:
    def test_lowercases_and_strips(self):
        assert canonical_source_name("  Reddit_CryptoCurrency ") == "reddit_cryptocurrency"

    def test_reddit_key_from_bare_name(self):
        assert reddit_source_key("CryptoCurrency") == "reddit_cryptocurrency"

    def test_reddit_key_is_idempotent(self):
        assert reddit_source_key("reddit_CryptoCurrency") == "reddit_cryptocurrency"
        assert reddit_source_key(reddit_source_key("CryptoCurrency")) == "reddit_cryptocurrency"

    def test_reddit_key_preserves_underscores(self):
        assert reddit_source_key("Crypto_General") == "reddit_crypto_general"


def _belief(source: str, *, alpha: float, beta: float, last_updated: datetime, **extra):
    payload = {
        "source": source,
        "alpha": alpha,
        "beta": beta,
        "last_updated": last_updated.isoformat(),
        "status": "active",
    }
    payload.update(extra)
    return payload


class TestBeliefStoreNormalization:
    def test_case_variants_merge_into_one_belief(self):
        stale = datetime(2026, 2, 3, tzinfo=timezone.utc)
        fresh = datetime(2026, 11, 10, tzinfo=timezone.utc)
        store = SourceBeliefStore.from_dict(
            {
                "reddit_cryptocurrency": _belief(
                    "reddit_cryptocurrency", alpha=70.0, beta=58.0, last_updated=fresh
                ),
                "reddit_CryptoCurrency": _belief(
                    "reddit_CryptoCurrency", alpha=68.0, beta=57.0, last_updated=stale
                ),
            }
        )

        assert list(store.beliefs) == ["reddit_cryptocurrency"]
        belief = store.beliefs["reddit_cryptocurrency"]
        # The lowercase entry is the one the crawler and database use, so its
        # posterior is authoritative; counts must not be summed.
        assert (belief.alpha, belief.beta) == (70.0, 58.0)
        assert belief.last_updated == fresh
        assert belief.source == "reddit_cryptocurrency"

    def test_merge_is_order_independent(self):
        stale = datetime(2026, 2, 3, tzinfo=timezone.utc)
        fresh = datetime(2026, 11, 10, tzinfo=timezone.utc)
        store = SourceBeliefStore.from_dict(
            {
                "reddit_CryptoCurrency": _belief(
                    "reddit_CryptoCurrency", alpha=68.0, beta=57.0, last_updated=stale
                ),
                "reddit_cryptocurrency": _belief(
                    "reddit_cryptocurrency", alpha=70.0, beta=58.0, last_updated=fresh
                ),
            }
        )

        assert list(store.beliefs) == ["reddit_cryptocurrency"]
        belief = store.beliefs["reddit_cryptocurrency"]
        assert (belief.alpha, belief.beta) == (70.0, 58.0)

    def test_merge_carries_crawl_clock_from_duplicate(self):
        now = datetime.now(timezone.utc)
        last_crawl = now - timedelta(hours=3)
        store = SourceBeliefStore.from_dict(
            {
                "reddit_cryptomarkets": _belief(
                    "reddit_cryptomarkets", alpha=5.0, beta=5.0, last_updated=now
                ),
                "reddit_CryptoMarkets": _belief(
                    "reddit_CryptoMarkets",
                    alpha=9.0,
                    beta=9.0,
                    last_updated=now,
                    last_crawl_at=last_crawl.isoformat(),
                ),
            }
        )

        assert list(store.beliefs) == ["reddit_cryptomarkets"]
        belief = store.beliefs["reddit_cryptomarkets"]
        assert belief.last_crawl_at == last_crawl
        assert (belief.alpha, belief.beta) == (5.0, 5.0)

    def test_get_normalizes_lookup_key(self):
        store = SourceBeliefStore()
        canonical = store.get("reddit_cryptotax")
        assert store.get("reddit_CryptoTax") is canonical
        assert list(store.beliefs) == ["reddit_cryptotax"]

    def test_to_dict_has_no_mixed_case_keys(self):
        store = SourceBeliefStore.from_dict(
            {
                "reddit_CryptoTechnology": _belief(
                    "reddit_CryptoTechnology",
                    alpha=2.0,
                    beta=2.0,
                    last_updated=datetime.now(timezone.utc),
                )
            }
        )
        assert list(store.to_dict()) == ["reddit_cryptotechnology"]


class TestDiscoveryStateLoading:
    def test_mixed_case_discovery_entry_becomes_one_canonical_source(self, tmp_path: Path):
        state = {
            "sources": {
                "reddit_CryptoMarkets": {
                    "name": "reddit_CryptoMarkets",
                    "source_type": "reddit",
                    "subreddit": "CryptoMarkets",
                    "status": "active",
                }
            },
            "rejected": [],
        }
        path = tmp_path / "discovery_state.json"
        path.write_text(json.dumps(state))

        sources = load_discovered_sources(str(path))

        assert list(sources) == ["reddit_cryptomarkets"]
        assert sources["reddit_cryptomarkets"].name == "reddit_cryptomarkets"
        assert sources["reddit_cryptomarkets"].endpoints[0].path == "/r/cryptomarkets/new/"
