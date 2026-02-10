# Crypto Sentiment Crawler - Backend Services
# Supports: api (lean, no torch), crawler, backfill, base (ML)

# Global ARG — must be before first FROM to be usable in later FROM lines
ARG TORCH_BASE_IMAGE=ghcr.io/protostatis/crypto-sentiment-torch-base:latest

# ============================================
# API stages (lean — no torch dependency)
# Evaluated first so `--target api` never pulls torch-base
# ============================================
FROM python:3.13-slim AS api-base

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Use the minimal API pyproject (no torch/transformers)
COPY pyproject-api.toml ./pyproject.toml
COPY roadmap.md ./

RUN uv sync --no-dev --no-editable

COPY crypto_sentiment_crawler/ ./crypto_sentiment_crawler/
COPY scripts/ ./scripts/

RUN mkdir -p /app/data /app/logs

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DATABASE_PATH=/app/data/sentiment.db

# ---- API target ----
FROM api-base AS api

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uv", "run", "uvicorn", "crypto_sentiment_crawler.signals.api:app", "--host", "0.0.0.0", "--port", "8000"]

# ============================================
# ML stages (torch + transformers via pre-baked base)
# ============================================
FROM ${TORCH_BASE_IMAGE} AS ml-base

# Refresh dependency files (may have non-ML changes since base was built)
COPY pyproject.toml uv.lock* roadmap.md ./

# Re-run sync — torch is already installed, so this only installs the delta
RUN uv sync --frozen --no-dev --no-editable --extra-index-url https://download.pytorch.org/whl/cpu 2>/dev/null || \
    uv sync --no-dev --no-editable --extra-index-url https://download.pytorch.org/whl/cpu

COPY crypto_sentiment_crawler/ ./crypto_sentiment_crawler/
COPY scripts/ ./scripts/

RUN mkdir -p /app/data /app/logs

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DATABASE_PATH=/app/data/sentiment.db

# ---- base target (used by signals, belief-auto, etc.) ----
FROM ml-base AS base

CMD ["uv", "run", "crawler", "background"]

# ---- Crawler target ----
FROM ml-base AS crawler

CMD ["uv", "run", "crawler", "background"]

# ---- Backfill target ----
FROM ml-base AS backfill

CMD ["uv", "run", "python", "-m", "crypto_sentiment_crawler.backfill"]
