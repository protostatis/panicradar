#!/usr/bin/env python3
"""CLI wrapper for the reusable spec-driven price gap patch tooling."""

# ruff: noqa: E402, I001

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # noqa: E402

from crypto_sentiment_crawler.maintenance.price_gap_patch import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
