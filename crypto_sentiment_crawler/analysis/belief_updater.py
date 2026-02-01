"""
Update Bayesian beliefs based on observed prediction performance.

Computes accuracy for each source and updates the orchestrator's
belief priors accordingly.

Uses user_sentiment_scores.final_score which is filtered sentiment
(excludes bot messages, scam warnings, and other noise).
"""

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy import stats

from ..logging_config import logger
from ..storage.db import Database


# Minimum samples needed before updating beliefs
MIN_SAMPLES = 20

# Prediction lag (hours) for accuracy measurement
PREDICTION_LAG = 4

# Prior strength - how much to weight new observations vs existing prior
# Lower = faster adaptation, higher = more stable
PRIOR_STRENGTH = 0.3


async def compute_source_accuracy(db: Database, lag_hours: int = PREDICTION_LAG) -> dict:
    """
    Compute prediction accuracy for each source.

    Uses final_score from user_sentiment_scores which is filtered
    (excludes bot messages, scam warnings, and other noise).

    Returns dict of source -> {accuracy, correct, total, correlation}
    """
    # Get sentiment scores from user_sentiment_scores (filtered scores)
    cursor = await db.conn.execute("""
        SELECT uss.timestamp, up.source, uss.final_score
        FROM user_sentiment_scores uss
        JOIN user_profiles up ON uss.user_id = up.user_id
        WHERE uss.timestamp >= '2026-01-01'
        ORDER BY uss.timestamp
    """)
    sent_rows = await cursor.fetchall()

    # Get prices
    cursor = await db.conn.execute("""
        SELECT timestamp, price_usd
        FROM price_data
        WHERE coin = 'BTC'
        ORDER BY timestamp
    """)
    price_rows = await cursor.fetchall()

    # Build price lookup by hour
    price_by_hour = {}
    for ts_str, price in price_rows:
        ts = datetime.fromisoformat(ts_str).replace(tzinfo=None)
        hour_key = ts.replace(minute=0, second=0, microsecond=0)
        if hour_key not in price_by_hour:
            price_by_hour[hour_key] = []
        price_by_hour[hour_key].append(price)
    price_by_hour = {h: np.mean(p) for h, p in price_by_hour.items()}

    # Track predictions per source
    source_data = defaultdict(lambda: {'correct': 0, 'total': 0, 'sents': [], 'changes': []})

    for ts_str, source, score in sent_rows:
        ts = datetime.fromisoformat(ts_str).replace(tzinfo=None)
        hour_key = ts.replace(minute=0, second=0, microsecond=0)
        future_hour = hour_key + timedelta(hours=lag_hours)

        if hour_key in price_by_hour and future_hour in price_by_hour:
            price_now = price_by_hour[hour_key]
            price_future = price_by_hour[future_hour]
            price_change = (price_future - price_now) / price_now

            # Direction correct?
            correct = (score > 0 and price_change > 0) or (score < 0 and price_change < 0)

            source_data[source]['total'] += 1
            source_data[source]['correct'] += int(correct)
            source_data[source]['sents'].append(score)
            source_data[source]['changes'].append(price_change * 100)

    # Compute final metrics
    results = {}
    for source, data in source_data.items():
        if data['total'] < MIN_SAMPLES:
            continue

        accuracy = data['correct'] / data['total']

        # Correlation
        corr = 0
        if len(data['sents']) >= 5:
            corr, _ = stats.pearsonr(data['sents'], data['changes'])
            if np.isnan(corr):
                corr = 0

        results[source] = {
            'accuracy': accuracy,
            'correct': data['correct'],
            'total': data['total'],
            'correlation': corr,
            'is_contrarian': accuracy < 0.45,  # Worse than random = contrarian signal
        }

    return results


def update_belief_priors(
    current_beliefs: dict,
    source_accuracy: dict,
    prior_strength: float = PRIOR_STRENGTH,
) -> dict:
    """
    Update belief priors based on observed accuracy.

    Uses a weighted combination of:
    - Current prior (for stability)
    - Observed accuracy (for adaptation)
    """
    updated_beliefs = {}
    now = datetime.now(timezone.utc).isoformat()

    for source, belief in current_beliefs.items():
        updated = belief.copy()

        if source in source_accuracy:
            obs = source_accuracy[source]

            # Compute new alpha/beta from observations
            # Scale by prior_strength to control adaptation rate
            obs_alpha = 1 + obs['correct'] * prior_strength
            obs_beta = 1 + (obs['total'] - obs['correct']) * prior_strength

            # Combine with existing prior
            new_alpha = belief.get('alpha', 1.0) * (1 - prior_strength) + obs_alpha
            new_beta = belief.get('beta', 1.0) * (1 - prior_strength) + obs_beta

            updated['alpha'] = round(new_alpha, 2)
            updated['beta'] = round(new_beta, 2)
            updated['total_crawls'] = obs['total']
            updated['accuracy'] = round(obs['accuracy'], 4)
            updated['correlation'] = round(obs['correlation'], 4)
            updated['is_contrarian'] = obs['is_contrarian']
            updated['last_updated'] = now

            logger.info(
                f"Updated {source}: accuracy={obs['accuracy']:.1%}, "
                f"Beta({updated['alpha']:.1f}, {updated['beta']:.1f})"
            )

        updated_beliefs[source] = updated

    # Add new sources not in current beliefs
    for source, obs in source_accuracy.items():
        if source not in updated_beliefs:
            updated_beliefs[source] = {
                'source': source,
                'alpha': 1 + obs['correct'] * prior_strength,
                'beta': 1 + (obs['total'] - obs['correct']) * prior_strength,
                'granger_pvalue': None,
                'lead_time_hours': None,
                'total_crawls': obs['total'],
                'accuracy': round(obs['accuracy'], 4),
                'correlation': round(obs['correlation'], 4),
                'is_contrarian': obs['is_contrarian'],
                'last_updated': now,
            }
            logger.info(f"Added new source {source}: accuracy={obs['accuracy']:.1%}")

    return updated_beliefs


async def update_orchestrator_beliefs(
    state_path: str = "data/orchestrator_state.json",
    db_path: str = "data/sentiment.db",
) -> dict:
    """
    Main function to update orchestrator beliefs based on observed performance.
    """
    logger.info("=" * 60)
    logger.info("UPDATING BAYESIAN BELIEFS")
    logger.info("=" * 60)

    # Load current state
    state_file = Path(state_path)
    if state_file.exists():
        with open(state_file) as f:
            state = json.load(f)
    else:
        state = {"beliefs": {}, "baseline_informativeness": 0.5, "total_crawls": 0}

    current_beliefs = state.get("beliefs", {})
    logger.info(f"Loaded {len(current_beliefs)} existing beliefs")

    # Connect to database
    db = Database(Path(db_path))
    await db.connect()

    try:
        # Compute source accuracy
        source_accuracy = await compute_source_accuracy(db)
        logger.info(f"Computed accuracy for {len(source_accuracy)} sources")

        # Update beliefs
        updated_beliefs = update_belief_priors(current_beliefs, source_accuracy)

        # Save updated state
        state["beliefs"] = updated_beliefs
        state["last_belief_update"] = datetime.now(timezone.utc).isoformat()

        with open(state_file, "w") as f:
            json.dump(state, f, indent=4)

        logger.info(f"Saved {len(updated_beliefs)} updated beliefs")

        # Update source weights for inference
        from .source_weights import (
            compute_weights_from_beliefs,
            save_weights_to_db,
            print_weights_table,
        )

        weights = compute_weights_from_beliefs(updated_beliefs)
        await save_weights_to_db(db, weights)
        logger.info(f"Updated {len(weights)} source weights")

        # Print summary
        print("\n" + "=" * 60)
        print("BELIEF UPDATE SUMMARY")
        print("=" * 60)
        print(f"\n{'Source':<28} {'Accuracy':<10} {'Alpha':<8} {'Beta':<8} {'Mean':<8} {'Type'}")
        print("-" * 75)

        sorted_beliefs = sorted(
            updated_beliefs.items(),
            key=lambda x: x[1].get('accuracy', 0),
            reverse=True
        )

        for source, belief in sorted_beliefs:
            if 'accuracy' not in belief:
                continue
            acc = belief.get('accuracy', 0)
            alpha = belief.get('alpha', 1)
            beta = belief.get('beta', 1)
            mean = alpha / (alpha + beta)
            type_str = "CONTRARIAN" if belief.get('is_contrarian') else "MOMENTUM"
            print(f"{source:<28} {acc:>6.1%}     {alpha:>6.1f}   {beta:>6.1f}   {mean:>6.3f}   {type_str}")

        print("=" * 60)

        # Print weights table
        print_weights_table(weights)

        return updated_beliefs

    finally:
        await db.close()


async def main():
    """Run belief update."""
    await update_orchestrator_beliefs()


if __name__ == "__main__":
    asyncio.run(main())
