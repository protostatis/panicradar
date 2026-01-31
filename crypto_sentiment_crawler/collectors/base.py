"""Base collector class for all data sources."""

from abc import ABC, abstractmethod
from datetime import datetime

from ..logging_config import logger
from ..storage.db import Database


class BaseCollector(ABC):
    """Abstract base class for data collectors."""

    name: str = "base"

    def __init__(self, db: Database):
        self.db = db
        self.logger = logger

    @abstractmethod
    async def collect(self) -> None:
        """Collect data from the source and store it."""
        pass

    async def run(self) -> None:
        """Run the collector with error handling."""
        self.logger.info(f"[{self.name}] Starting collection...")
        start = datetime.now()
        try:
            await self.collect()
            elapsed = (datetime.now() - start).total_seconds()
            self.logger.info(f"[{self.name}] Collection complete in {elapsed:.2f}s")
        except Exception as e:
            self.logger.error(f"[{self.name}] Collection failed: {e}")
            raise
