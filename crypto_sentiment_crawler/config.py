"""Configuration management using pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Reddit API
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "crypto_sentiment_crawler/1.0"

    # Whale Alert
    whale_alert_api_key: str = ""

    # Etherscan
    etherscan_api_key: str = ""

    # Twitter/X API (optional - for reliable access)
    twitter_bearer_token: str = ""

    # OpenRouter (embeddings + optional LLM scoring)
    openrouter_api_key: str = ""

    # Embedding backend for sentiment scoring.
    #   backend="local"        → uses EMBEDDING_MODEL via sentence-transformers
    #   backend="openrouter"   → calls OpenRouter /embeddings (needs OPENROUTER_API_KEY)
    embedding_backend: str = "openrouter"
    embedding_model: str = "qwen/qwen3-embedding-8b"

    # Database
    database_path: str = "data/sentiment.db"

    # Tracked coins
    tracked_coins: str = "BTC,ETH,SOL,BNB,XRP,ADA,DOGE,AVAX,DOT,LINK"

    # Collector intervals (seconds)
    price_interval: int = 300
    reddit_interval: int = 600
    onchain_interval: int = 120
    fear_greed_interval: int = 14400

    # Logging
    log_level: str = "INFO"

    @property
    def coins_list(self) -> list[str]:
        """Get tracked coins as a list."""
        return [c.strip().upper() for c in self.tracked_coins.split(",")]

    @property
    def db_path(self) -> Path:
        """Get database path as Path object."""
        return Path(self.database_path)


settings = Settings()
