"""On-chain metrics collector using free public APIs.

Data sources:
- Blockchain.info: BTC hash rate, difficulty, mempool size
- Mempool.space: BTC fees, block data
- Etherscan (public): ETH gas prices
- Blockchair: Multi-chain stats
"""

import json
from datetime import datetime, timezone

import httpx

from ..storage.db import Database
from ..storage.models import OnChainMetric
from .base import BaseCollector


class OnChainFreeCollector(BaseCollector):
    """Collector for on-chain metrics using free APIs."""

    name = "onchain_free"

    def __init__(self, db: Database):
        super().__init__(db)
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def collect(self) -> None:
        """Collect on-chain metrics from multiple free sources."""
        timestamp = datetime.now(timezone.utc)

        # Collect from all sources, don't fail on individual errors
        await self._collect_blockchain_info(timestamp)
        await self._collect_mempool_space(timestamp)
        await self._collect_etherscan_gas(timestamp)
        await self._collect_blockchair_stats(timestamp)

    async def _collect_blockchain_info(self, timestamp: datetime) -> None:
        """Collect BTC metrics from Blockchain.info."""
        try:
            # Get stats
            resp = await self.client.get("https://api.blockchain.info/stats")
            resp.raise_for_status()
            stats = resp.json()

            metrics = [
                ("btc_hash_rate", stats.get("hash_rate", 0) / 1e9, "TH/s"),  # Convert to TH/s
                ("btc_difficulty", stats.get("difficulty", 0), ""),
                ("btc_n_tx_24h", stats.get("n_tx", 0), "transactions"),
                ("btc_total_btc_sent_24h", stats.get("total_btc_sent", 0) / 1e8, "BTC"),
                ("btc_miners_revenue_24h", stats.get("miners_revenue_usd", 0), "USD"),
                ("btc_market_price_usd", stats.get("market_price_usd", 0), "USD"),
            ]

            for metric_type, value, unit in metrics:
                if value and value > 0:
                    metric = OnChainMetric(
                        timestamp=timestamp,
                        coin="BTC",
                        metric_type=metric_type,
                        value=float(value),
                        metadata={"unit": unit, "source": "blockchain.info"},
                    )
                    await self.db.insert_on_chain_metric(metric)

            self.logger.info(f"Collected {len(metrics)} BTC metrics from Blockchain.info")

        except Exception as e:
            self.logger.warning(f"Blockchain.info collection failed: {e}")

    async def _collect_mempool_space(self, timestamp: datetime) -> None:
        """Collect BTC mempool and fee data from Mempool.space."""
        try:
            # Get recommended fees
            resp = await self.client.get("https://mempool.space/api/v1/fees/recommended")
            resp.raise_for_status()
            fees = resp.json()

            fee_metrics = [
                ("btc_fee_fastest", fees.get("fastestFee", 0), "sat/vB"),
                ("btc_fee_half_hour", fees.get("halfHourFee", 0), "sat/vB"),
                ("btc_fee_hour", fees.get("hourFee", 0), "sat/vB"),
                ("btc_fee_economy", fees.get("economyFee", 0), "sat/vB"),
                ("btc_fee_minimum", fees.get("minimumFee", 0), "sat/vB"),
            ]

            for metric_type, value, unit in fee_metrics:
                if value and value > 0:
                    metric = OnChainMetric(
                        timestamp=timestamp,
                        coin="BTC",
                        metric_type=metric_type,
                        value=float(value),
                        metadata={"unit": unit, "source": "mempool.space"},
                    )
                    await self.db.insert_on_chain_metric(metric)

            # Get mempool stats
            resp = await self.client.get("https://mempool.space/api/mempool")
            resp.raise_for_status()
            mempool = resp.json()

            mempool_metrics = [
                ("btc_mempool_count", mempool.get("count", 0), "transactions"),
                ("btc_mempool_vsize", mempool.get("vsize", 0), "vbytes"),
                ("btc_mempool_total_fee", mempool.get("total_fee", 0) / 1e8, "BTC"),
            ]

            for metric_type, value, unit in mempool_metrics:
                if value and value > 0:
                    metric = OnChainMetric(
                        timestamp=timestamp,
                        coin="BTC",
                        metric_type=metric_type,
                        value=float(value),
                        metadata={"unit": unit, "source": "mempool.space"},
                    )
                    await self.db.insert_on_chain_metric(metric)

            self.logger.info(f"Collected BTC fee/mempool metrics from Mempool.space")

        except Exception as e:
            self.logger.warning(f"Mempool.space collection failed: {e}")

    async def _collect_etherscan_gas(self, timestamp: datetime) -> None:
        """Collect ETH gas prices from Etherscan public API."""
        try:
            # Public gas oracle endpoint (no API key needed for basic access)
            resp = await self.client.get(
                "https://api.etherscan.io/api",
                params={
                    "module": "gastracker",
                    "action": "gasoracle",
                }
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") == "1" and data.get("result"):
                result = data["result"]

                gas_metrics = [
                    ("eth_gas_safe", float(result.get("SafeGasPrice", 0)), "gwei"),
                    ("eth_gas_propose", float(result.get("ProposeGasPrice", 0)), "gwei"),
                    ("eth_gas_fast", float(result.get("FastGasPrice", 0)), "gwei"),
                ]

                for metric_type, value, unit in gas_metrics:
                    if value and value > 0:
                        metric = OnChainMetric(
                            timestamp=timestamp,
                            coin="ETH",
                            metric_type=metric_type,
                            value=value,
                            metadata={"unit": unit, "source": "etherscan"},
                        )
                        await self.db.insert_on_chain_metric(metric)

                self.logger.info("Collected ETH gas metrics from Etherscan")

        except Exception as e:
            self.logger.warning(f"Etherscan gas collection failed: {e}")

    async def _collect_blockchair_stats(self, timestamp: datetime) -> None:
        """Collect multi-chain stats from Blockchair."""
        try:
            # Bitcoin stats
            resp = await self.client.get("https://api.blockchair.com/bitcoin/stats")
            resp.raise_for_status()
            data = resp.json()

            if data.get("data"):
                stats = data["data"]

                btc_metrics = [
                    ("btc_blocks", stats.get("blocks", 0), "blocks"),
                    ("btc_transactions_24h", stats.get("transactions_24h", 0), "transactions"),
                    ("btc_volume_24h", stats.get("volume_24h", 0) / 1e8, "BTC"),
                    ("btc_average_transaction_fee_24h", stats.get("average_transaction_fee_24h", 0), "USD"),
                    ("btc_mempool_transactions", stats.get("mempool_transactions", 0), "transactions"),
                    ("btc_mempool_size", stats.get("mempool_size", 0), "bytes"),
                    ("btc_suggested_fee", stats.get("suggested_transaction_fee_per_byte_sat", 0), "sat/byte"),
                ]

                for metric_type, value, unit in btc_metrics:
                    if value and value > 0:
                        metric = OnChainMetric(
                            timestamp=timestamp,
                            coin="BTC",
                            metric_type=metric_type,
                            value=float(value),
                            metadata={"unit": unit, "source": "blockchair"},
                        )
                        await self.db.insert_on_chain_metric(metric)

            # Ethereum stats
            resp = await self.client.get("https://api.blockchair.com/ethereum/stats")
            resp.raise_for_status()
            data = resp.json()

            if data.get("data"):
                stats = data["data"]

                def safe_float(val, default=0):
                    """Safely convert to float."""
                    try:
                        return float(val) if val else default
                    except (ValueError, TypeError):
                        return default

                eth_metrics = [
                    ("eth_blocks", safe_float(stats.get("blocks", 0)), "blocks"),
                    ("eth_transactions_24h", safe_float(stats.get("transactions_24h", 0)), "transactions"),
                    ("eth_volume_24h", safe_float(stats.get("volume_24h", 0)) / 1e18, "ETH"),
                    ("eth_average_transaction_fee_24h", safe_float(stats.get("average_transaction_fee_24h", 0)), "USD"),
                    ("eth_mempool_transactions", safe_float(stats.get("mempool_transactions", 0)), "transactions"),
                ]

                for metric_type, value, unit in eth_metrics:
                    if value and value > 0:
                        metric = OnChainMetric(
                            timestamp=timestamp,
                            coin="ETH",
                            metric_type=metric_type,
                            value=float(value),
                            metadata={"unit": unit, "source": "blockchair"},
                        )
                        await self.db.insert_on_chain_metric(metric)

            self.logger.info("Collected chain stats from Blockchair")

        except Exception as e:
            self.logger.warning(f"Blockchair collection failed: {e}")
