"""Compare sentiment scorers backed by different embedding models.

Runs the same anchor-similarity pipeline against two embedding backends and
prints a side-by-side delta. Uses ``data/audit_sample_50.csv`` — a balanced
human-labeled benchmark (10 per class: very_bearish, bearish, neutral, bullish,
very_bullish).

Usage::

    # default: local MiniLM  vs  local BGE-M3 (apples-to-apples encoder)
    python scripts/compare_embedding_models.py

    # custom challenger
    EMBEDDING_MODEL=baai/bge-large-en-v1.5 python scripts/compare_embedding_models.py

The script needs ``OPENROUTER_API_KEY`` in the environment (or ``.env``) when
the challenger is an OpenRouter-hosted model (e.g. ``qwen/qwen3-embedding-8b``).
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_sentiment_crawler.logging_config import logger  # noqa: E402
from crypto_sentiment_crawler.processing.embedding_providers import (  # noqa: E402
    LocalSentenceTransformerProvider,
    OpenRouterEmbeddingProvider,
)
from crypto_sentiment_crawler.processing.semantic_sentiment import (  # noqa: E402
    SemanticSentimentAnalyzer,
)

BENCHMARK_PATH = Path("data/audit_sample_50.csv")

# ── utility ─────────────────────────────────────────────────────────────────


def _label(score: float) -> str:
    if score > 0.15:
        return "bullish"
    if score < -0.15:
        return "bearish"
    return "neutral"


def score_texts(analyzer: SemanticSentimentAnalyzer, texts: list[str]) -> list[float]:
    results = analyzer.analyze_batch(texts)
    return [r["score"] for r in results]


def _provider(model_slug: str) -> LocalSentenceTransformerProvider | OpenRouterEmbeddingProvider:
    """Decide backend from the model slug."""
    if "/" in model_slug and not model_slug.startswith(
        ("all-", "paraphrase-", "sentence-transformers/", "baai/", "BAAI/",
         "intfloat/", "thenlper/", "Snowflake/")
    ):
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            env_path = Path(".env")
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("OPENROUTER_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        os.environ["OPENROUTER_API_KEY"] = api_key
                        break
        if not api_key:
            logger.error("OPENROUTER_API_KEY required for %s", model_slug)
            sys.exit(1)
        return OpenRouterEmbeddingProvider(model=model_slug, api_key=api_key)
    return LocalSentenceTransformerProvider(model_slug)


# ── benchmark parser ────────────────────────────────────────────────────────

BUCKET_ORDER = ["very_bearish", "bearish", "neutral", "bullish", "very_bullish"]
BUCKET_EXPECTED = {
    "very_bearish": (-1.0, -0.3),
    "bearish": (-0.3, -0.05),
    "neutral": (-0.05, 0.05),
    "bullish": (0.05, 0.3),
    "very_bullish": (0.3, 1.0),
}


def load_benchmark(path: Path) -> list[dict[str, str]]:
    """Parse ``audit_sample_50.csv`` into a list of dicts.

    The CSV has multi-line fields (comments with embedded newlines and commas).
    We parse with the stdlib csv module and keep only valid benchmark rows
    (those with a recognised ``bucket`` and non-empty title).
    """
    raw = path.read_text(encoding="utf-8")
    # Remove very long comment continuations that spill across lines
    reader = csv.DictReader(io.StringIO(raw), restval="")
    rows: list[dict[str, str]] = []
    for r in reader:
        bucket = (r.get("bucket") or "").strip()
        title = (r.get("title") or "").strip()
        body = (r.get("body") or "").strip()
        if bucket not in BUCKET_ORDER:
            continue
        # Build the text the same way the original pipeline does.
        title_clean = re.sub(r"\s+", " ", title)
        body_clean = re.sub(r"\s+", " ", body)[:400]
        full_text = f"{title_clean} {body_clean}".strip()[:500]
        if not full_text or len(full_text) < 10:
            continue
        rows.append({"bucket": bucket, "text": full_text, "title": title_clean})
    return rows


# ── comparison functions ────────────────────────────────────────────────────


def compare_benchmark(
    baseline: SemanticSentimentAnalyzer,
    challenger: SemanticSentimentAnalyzer,
    rows: list[dict[str, str]],
) -> None:
    print(f"\n{'=' * 90}")
    print(f"BENCHMARK: {BENCHMARK_PATH}  ({len(rows)} labeled posts)")
    print("=" * 90)

    texts = [r["text"] for r in rows]
    base_scores = score_texts(baseline, texts)
    chal_scores = score_texts(challenger, texts)

    # ── per-class mean score ────────────────────────────────────────────────
    print(f"\n{'bucket':<15} {'count':>6} {'MiniLM mean':>12} {'Chall mean':>12}")
    print("-" * 50)
    for bucket in BUCKET_ORDER:
        idxs = [i for i, r in enumerate(rows) if r["bucket"] == bucket]
        if not idxs:
            continue
        bm = statistics.mean(base_scores[i] for i in idxs)
        cm = statistics.mean(chal_scores[i] for i in idxs)
        print(f"  {bucket:<13} {len(idxs):>6} {bm:>+12.3f} {cm:>+12.3f}")
    print(f"  {'OVERALL':<13} {len(rows):>6} "
          f"{statistics.mean(base_scores):>+12.3f} {statistics.mean(chal_scores):>+12.3f}")

    # ── bucketed accuracy ───────────────────────────────────────────────────
    def bucket_match(score: float, label: str) -> bool:
        lo, hi = BUCKET_EXPECTED[label]
        return lo <= score <= hi

    print(f"\n{'bucket':<15} {'MiniLM acc':>12} {'Chall acc':>12} {'Δ':>8}")
    print("-" * 50)
    b_total = c_total = b_correct = c_correct = 0
    for bucket in BUCKET_ORDER:
        idxs = [i for i, r in enumerate(rows) if r["bucket"] == bucket]
        if not idxs:
            continue
        b_ok = sum(bucket_match(base_scores[i], bucket) for i in idxs)
        c_ok = sum(bucket_match(chal_scores[i], bucket) for i in idxs)
        b_total += len(idxs)
        c_total += len(idxs)
        b_correct += b_ok
        c_correct += c_ok
        print(f"  {bucket:<13} {b_ok}/{len(idxs)} = {100*b_ok/len(idxs):5.1f}%   "
              f"{c_ok}/{len(idxs)} = {100*c_ok/len(idxs):5.1f}%   "
              f"{100*(c_ok-b_ok)/len(idxs):+6.1f}pp")
    print("-" * 50)
    print(f"  {'OVERALL':<13} {b_correct}/{b_total} = {100*b_correct/b_total:5.1f}%   "
          f"{c_correct}/{c_total} = {100*c_correct/c_total:5.1f}%   "
          f"{100*(c_correct-b_correct)/b_total:+6.1f}pp")

    # ── worst disagreements per class ───────────────────────────────────────
    print("\nPER-BUCKET DISAGREEMENTS (top-2 per bucket where models diverge most)")
    for bucket in BUCKET_ORDER:
        idxs = [i for i, r in enumerate(rows) if r["bucket"] == bucket]
        deltas = sorted(idxs, key=lambda i: abs(base_scores[i] - chal_scores[i]), reverse=True)
        for i in deltas[:2]:
            d = chal_scores[i] - base_scores[i]
            s = "→" if abs(d) > 0.1 else "≈"
            print(f"  [{bucket}] {s} "
                  f"{rows[i]['title'][:45]:<46} "
                  f"MiniLM={base_scores[i]:+.3f} Chall={chal_scores[i]:+.3f} Δ={d:+.3f}")


# ── main ────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline-model", default="all-MiniLM-L6-v2")
    ap.add_argument(
        "--challenger-model",
        default=os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3"),
    )
    ap.add_argument("--benchmark", default=str(BENCHMARK_PATH))
    args = ap.parse_args()

    print("Baseline (local):", args.baseline_model)
    baseline = SemanticSentimentAnalyzer(provider=_provider(args.baseline_model))

    print("Challenger:", args.challenger_model)
    challenger = SemanticSentimentAnalyzer(provider=_provider(args.challenger_model))

    # Human-labeled benchmark
    bench_path = Path(args.benchmark)
    if bench_path.exists():
        benchmark_rows = load_benchmark(bench_path)
        compare_benchmark(baseline, challenger, benchmark_rows)
    else:
        print(f"\nBenchmark not found: {bench_path}")


if __name__ == "__main__":
    main()
