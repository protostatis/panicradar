"""
Main confounder data collector.

Orchestrates all confounder collectors and stores data.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .news import NewsCollector
from .macro import MacroCollector
from .regime import RegimeCollector
from .models import ConfounderSnapshot
from ..logging_config import logger


class ConfounderCollector:
    """
    Main collector that orchestrates all confounder data collection.

    Collects:
    - News proxies (CryptoPanic)
    - Macro proxies (Yahoo Finance)
    - Regime proxies (Fear & Greed, CoinGecko, Binance)
    """

    def __init__(self, db_path: str = "data/sentiment.db"):
        self.db_path = db_path
        self.news_collector = NewsCollector()
        self.macro_collector = MacroCollector()
        self.regime_collector = RegimeCollector()

    async def start(self) -> None:
        """Initialize all collectors."""
        await self.news_collector.start()
        await self.macro_collector.start()
        await self.regime_collector.start()

        # Ensure database table exists
        self._init_db()

        logger.info("Confounder collector initialized")

    async def close(self) -> None:
        """Close all collectors."""
        await self.news_collector.close()
        await self.macro_collector.close()
        await self.regime_collector.close()
        logger.info("Confounder collector closed")

    def _init_db(self) -> None:
        """Initialize database table for confounders."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS confounders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,

                -- News proxies
                news_count_1h INTEGER,
                news_sentiment_avg REAL,
                news_has_btc INTEGER,
                news_has_eth INTEGER,
                news_categories TEXT,

                -- Macro proxies
                vix_level REAL,
                dxy_value REAL,
                dxy_change_24h REAL,
                sp500_price REAL,
                sp500_change_1h REAL,
                fed_event_today INTEGER,
                cpi_release_today INTEGER,

                -- Regime proxies
                fear_greed_index INTEGER,
                btc_dominance REAL,
                total_market_cap REAL,
                btc_trend_7d REAL,
                volatility_24h REAL,
                funding_rate_btc REAL,
                funding_rate_eth REAL,

                -- On-chain proxies
                exchange_inflow_btc REAL,
                exchange_outflow_btc REAL,
                large_tx_count INTEGER,

                -- Social proxies
                reddit_post_volume_1h INTEGER,
                reddit_unique_authors_1h INTEGER,
                reddit_avg_score REAL,

                -- Metadata
                collection_errors TEXT,

                UNIQUE(timestamp)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_confounders_timestamp
            ON confounders(timestamp)
        """)
        conn.commit()
        conn.close()

    async def collect_all(self) -> ConfounderSnapshot:
        """
        Collect all confounder data.

        Returns:
            ConfounderSnapshot with all proxy variables.
        """
        timestamp = datetime.now(timezone.utc)
        errors = []

        # Collect from all sources in parallel
        news_task = self.news_collector.collect()
        macro_task = self.macro_collector.collect()
        regime_task = self.regime_collector.collect()

        news_data, macro_data, regime_data = await asyncio.gather(
            news_task, macro_task, regime_task,
            return_exceptions=True
        )

        # Handle exceptions
        if isinstance(news_data, Exception):
            errors.append(f"News: {news_data}")
            news_data = {}
        elif news_data.get("error"):
            errors.append(f"News: {news_data['error']}")

        if isinstance(macro_data, Exception):
            errors.append(f"Macro: {macro_data}")
            macro_data = {}
        elif macro_data.get("errors"):
            errors.extend(macro_data["errors"])

        if isinstance(regime_data, Exception):
            errors.append(f"Regime: {regime_data}")
            regime_data = {}
        elif regime_data.get("errors"):
            errors.extend(regime_data["errors"])

        # Build snapshot
        snapshot = ConfounderSnapshot(
            timestamp=timestamp,
            # News
            news_count_1h=news_data.get("news_count_1h"),
            news_sentiment_avg=news_data.get("news_sentiment_avg"),
            news_has_btc=news_data.get("news_has_btc"),
            news_has_eth=news_data.get("news_has_eth"),
            news_categories=news_data.get("news_categories", []),
            # Macro
            vix_level=macro_data.get("vix_level"),
            dxy_value=macro_data.get("dxy_value"),
            dxy_change_24h=macro_data.get("dxy_change_24h"),
            sp500_price=macro_data.get("sp500_price"),
            sp500_change_1h=macro_data.get("sp500_change_1h"),
            fed_event_today=macro_data.get("fed_event_today", False),
            cpi_release_today=macro_data.get("cpi_release_today", False),
            # Regime
            fear_greed_index=regime_data.get("fear_greed_index"),
            btc_dominance=regime_data.get("btc_dominance"),
            total_market_cap=regime_data.get("total_market_cap"),
            btc_trend_7d=regime_data.get("btc_trend_7d"),
            volatility_24h=regime_data.get("volatility_24h"),
            funding_rate_btc=regime_data.get("funding_rate_btc"),
            funding_rate_eth=regime_data.get("funding_rate_eth"),
            # Errors
            collection_errors=errors,
        )

        return snapshot

    def store_snapshot(self, snapshot: ConfounderSnapshot) -> None:
        """Store a confounder snapshot to database."""
        conn = sqlite3.connect(self.db_path)

        try:
            conn.execute("""
                INSERT OR REPLACE INTO confounders (
                    timestamp,
                    news_count_1h, news_sentiment_avg, news_has_btc, news_has_eth, news_categories,
                    vix_level, dxy_value, dxy_change_24h, sp500_price, sp500_change_1h,
                    fed_event_today, cpi_release_today,
                    fear_greed_index, btc_dominance, total_market_cap, btc_trend_7d,
                    volatility_24h, funding_rate_btc, funding_rate_eth,
                    exchange_inflow_btc, exchange_outflow_btc, large_tx_count,
                    reddit_post_volume_1h, reddit_unique_authors_1h, reddit_avg_score,
                    collection_errors
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.timestamp.isoformat(),
                snapshot.news_count_1h,
                snapshot.news_sentiment_avg,
                1 if snapshot.news_has_btc else 0,
                1 if snapshot.news_has_eth else 0,
                json.dumps(snapshot.news_categories),
                snapshot.vix_level,
                snapshot.dxy_value,
                snapshot.dxy_change_24h,
                snapshot.sp500_price,
                snapshot.sp500_change_1h,
                1 if snapshot.fed_event_today else 0,
                1 if snapshot.cpi_release_today else 0,
                snapshot.fear_greed_index,
                snapshot.btc_dominance,
                snapshot.total_market_cap,
                snapshot.btc_trend_7d,
                snapshot.volatility_24h,
                snapshot.funding_rate_btc,
                snapshot.funding_rate_eth,
                snapshot.exchange_inflow_btc,
                snapshot.exchange_outflow_btc,
                snapshot.large_tx_count,
                snapshot.reddit_post_volume_1h,
                snapshot.reddit_unique_authors_1h,
                snapshot.reddit_avg_score,
                json.dumps(snapshot.collection_errors) if snapshot.collection_errors else None,
            ))
            conn.commit()
        finally:
            conn.close()

    async def collect_and_store(self) -> ConfounderSnapshot:
        """Collect all confounders and store to database."""
        snapshot = await self.collect_all()
        self.store_snapshot(snapshot)

        vix_str = f"{snapshot.vix_level:.1f}" if snapshot.vix_level else "N/A"
        logger.info(
            f"Collected confounders: FNG={snapshot.fear_greed_index}, "
            f"VIX={vix_str}, "
            f"News={snapshot.news_count_1h}, "
            f"Errors={len(snapshot.collection_errors)}"
        )

        return snapshot


async def run_confounder_collection():
    """Run a single confounder collection cycle."""
    collector = ConfounderCollector()

    try:
        await collector.start()
        snapshot = await collector.collect_and_store()

        print("\n" + "=" * 60)
        print("CONFOUNDER SNAPSHOT")
        print("=" * 60)
        print(f"\nTimestamp: {snapshot.timestamp}")

        print("\n--- NEWS PROXIES ---")
        print(f"  News Count (1h): {snapshot.news_count_1h}")
        print(f"  News Sentiment: {snapshot.news_sentiment_avg:.3f}" if snapshot.news_sentiment_avg else "  News Sentiment: N/A")
        print(f"  Has BTC News: {snapshot.news_has_btc}")
        print(f"  Has ETH News: {snapshot.news_has_eth}")
        print(f"  Categories: {snapshot.news_categories}")

        print("\n--- MACRO PROXIES ---")
        print(f"  VIX Level: {snapshot.vix_level:.2f}" if snapshot.vix_level else "  VIX Level: N/A")
        print(f"  DXY Value: {snapshot.dxy_value:.2f}" if snapshot.dxy_value else "  DXY Value: N/A")
        print(f"  DXY Change 24h: {snapshot.dxy_change_24h:.2f}%" if snapshot.dxy_change_24h else "  DXY Change 24h: N/A")
        print(f"  S&P500: {snapshot.sp500_price:.2f}" if snapshot.sp500_price else "  S&P500: N/A")
        print(f"  S&P500 Change 1h: {snapshot.sp500_change_1h:.2f}%" if snapshot.sp500_change_1h else "  S&P500 Change 1h: N/A")
        print(f"  Fed Event Today: {snapshot.fed_event_today}")
        print(f"  CPI Release Today: {snapshot.cpi_release_today}")

        print("\n--- REGIME PROXIES ---")
        print(f"  Fear & Greed: {snapshot.fear_greed_index}")
        print(f"  BTC Dominance: {snapshot.btc_dominance:.1f}%" if snapshot.btc_dominance else "  BTC Dominance: N/A")
        print(f"  Total Market Cap: ${snapshot.total_market_cap:,.0f}" if snapshot.total_market_cap else "  Total Market Cap: N/A")
        print(f"  BTC Trend 7d: {snapshot.btc_trend_7d:.1f}%" if snapshot.btc_trend_7d else "  BTC Trend 7d: N/A")
        print(f"  Volatility 24h: {snapshot.volatility_24h:.1f}%" if snapshot.volatility_24h else "  Volatility 24h: N/A")
        print(f"  BTC Funding Rate: {snapshot.funding_rate_btc:.6f}" if snapshot.funding_rate_btc else "  BTC Funding Rate: N/A")
        print(f"  ETH Funding Rate: {snapshot.funding_rate_eth:.6f}" if snapshot.funding_rate_eth else "  ETH Funding Rate: N/A")

        if snapshot.collection_errors:
            print("\n--- ERRORS ---")
            for err in snapshot.collection_errors:
                print(f"  - {err}")

        print("\n" + "=" * 60)

        return snapshot

    finally:
        await collector.close()


if __name__ == "__main__":
    asyncio.run(run_confounder_collection())
