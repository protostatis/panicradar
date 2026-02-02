# Crypto Sentiment Crawler - Backend Services
# Supports: crawler, api, backfill modes

FROM python:3.13-slim AS base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock* roadmap.md ./

# Install dependencies (non-editable for production)
RUN uv sync --frozen --no-dev --no-editable 2>/dev/null || uv sync --no-dev --no-editable

# Copy application code
COPY crypto_sentiment_crawler/ ./crypto_sentiment_crawler/

# Create data directory for SQLite and state
RUN mkdir -p /app/data /app/logs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DATABASE_PATH=/app/data/sentiment.db

# Default command (can be overridden in docker-compose)
CMD ["uv", "run", "crawler", "background"]

# ============================================
# API Server Target
# ============================================
FROM base AS api

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "crypto_sentiment_crawler.signals.api:app", "--host", "0.0.0.0", "--port", "8000"]

# ============================================
# Crawler Target (default)
# ============================================
FROM base AS crawler

CMD ["uv", "run", "crawler", "background"]

# ============================================
# Backfill Target
# ============================================
FROM base AS backfill

CMD ["uv", "run", "python", "-m", "crypto_sentiment_crawler.backfill"]
