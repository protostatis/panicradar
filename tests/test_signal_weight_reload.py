"""Regression tests for live source-weight reloads."""

from unittest.mock import AsyncMock, Mock

from crypto_sentiment_crawler.signals.service import SignalService


async def test_check_signals_reloads_weights_before_reading_data(tmp_path):
    service = SignalService(db_path=str(tmp_path / "sentiment.db"))
    service._load_source_weights = Mock()
    service._load_data = AsyncMock(return_value=([], [], {}))

    await service.check_signals()

    service._load_source_weights.assert_called_once()


async def test_market_summary_reloads_weights_before_reading_data(tmp_path):
    service = SignalService(db_path=str(tmp_path / "sentiment.db"))
    service._load_source_weights = Mock()
    service._load_data = AsyncMock(return_value=([], [], {}))

    summary = await service.get_market_summary()

    service._load_source_weights.assert_called_once()
    assert summary == {"error": "Insufficient data"}
