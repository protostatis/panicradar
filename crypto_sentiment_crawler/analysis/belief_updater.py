"""
Update Bayesian beliefs based on observed prediction performance.

Computes accuracy for each source and updates the orchestrator's
belief priors accordingly.

Uses user_sentiment_scores.final_score which is filtered sentiment
(excludes bot messages, scam warnings, and other noise).
"""

import asyncio
import copy
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy import stats

from ..logging_config import logger
from ..state_lock import StateFileLock
from ..storage.db import Database


# Minimum samples needed before updating beliefs
MIN_SAMPLES = 20

# Prediction lag (hours) for accuracy measurement
PREDICTION_LAG = 4


async def _find_ghost_sources(db: "Database", beliefs: dict) -> list[str]:
    """
    Find ghost sources in beliefs that have zero rows in sentiment_raw.

    A source is a ghost if:
    - It does NOT start with "reddit_" (Reddit sources are always valid)
    - It has zero rows in the sentiment_raw table

    Source names are normalized to lowercase for database comparisons. The
    original belief keys are returned so callers can remove them safely even
    if a legacy state file used mixed casing.
    """
    if not beliefs:
        return []

    candidates = [
        source for source in beliefs
        if not source.lower().startswith("reddit_")
    ]
    if not candidates:
        return []

    normalized_sources = {source.lower() for source in candidates}
    placeholders = ", ".join("?" for _ in normalized_sources)
    cursor = await db.conn.execute(
        f"""
        SELECT DISTINCT LOWER(source)
        FROM sentiment_raw
        WHERE LOWER(source) IN ({placeholders})
        """,
        tuple(normalized_sources),
    )
    existing_sources = {row[0] for row in await cursor.fetchall()}
    return [source for source in candidates if source.lower() not in existing_sources]


async def compute_source_accuracy(
    db: Database,
    lag_hours: int = PREDICTION_LAG,
    lookback_days: int = 90,
) -> dict:
    """
    Compute prediction accuracy for each source.

    Aggregates sentiment by source-hour (mean final_score) to avoid counting
    thousands of posts as independent observations. Applies a neutral deadband
    (|mean_score| < 0.05) treated as abstention.

    Returns dict of source -> {accuracy, correct, incorrect, abstained, total,
    correlation, coverage, is_contrarian, type_label, credible_interval_lower,
    credible_interval_upper, effective_n}
    """
    # Compute start date from lookback_days (Change 6)
    start_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime('%Y-%m-%d')

    # Get sentiment scores from user_sentiment_scores (filtered scores)
    cursor = await db.conn.execute("""
        SELECT uss.timestamp, up.source, uss.final_score
        FROM user_sentiment_scores uss
        JOIN user_profiles up ON uss.user_id = up.user_id
        WHERE uss.timestamp >= ?
        ORDER BY uss.timestamp
    """, (start_date,))
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
        if price is None:
            continue
        ts = datetime.fromisoformat(ts_str).replace(tzinfo=None)
        hour_key = ts.replace(minute=0, second=0, microsecond=0)
        if hour_key not in price_by_hour:
            price_by_hour[hour_key] = []
        price_by_hour[hour_key].append(price)
    price_by_hour = {h: np.mean(p) for h, p in price_by_hour.items()}

    # Change 1: Group sentiment by (source, hour_key) and compute mean score
    source_hour_scores = defaultdict(list)
    for ts_str, source, score in sent_rows:
        ts = datetime.fromisoformat(ts_str).replace(tzinfo=None)
        hour_key = ts.replace(minute=0, second=0, microsecond=0)
        source_hour_scores[(source, hour_key)].append(score)

    # Evaluate each source-hour against price change
    source_data = defaultdict(lambda: {
        'correct': 0, 'incorrect': 0, 'abstained': 0,
        'total': 0, 'sents': [], 'changes': [],
    })

    for (source, hour_key), scores in source_hour_scores.items():
        # Filter out None/NULL scores that can appear in mixed
        # embedding-provider contexts (older schema rows may lack
        # scores computed by a different provider version).
        valid_scores = [s for s in scores if isinstance(s, (int, float)) and not (isinstance(s, float) and np.isnan(s))]
        if not valid_scores:
            continue
        mean_score = float(np.mean(valid_scores))
        future_hour = hour_key + timedelta(hours=lag_hours)

        if hour_key in price_by_hour and future_hour in price_by_hour:
            price_now = price_by_hour[hour_key]
            price_future = price_by_hour[future_hour]
            if price_now is None or price_future is None:
                continue
            if price_now == 0:
                continue
            price_change = (price_future - price_now) / price_now

            d = source_data[source]
            d['total'] += 1
            d['sents'].append(mean_score)
            d['changes'].append(price_change * 100)

            # Change 2: Neutral deadband — |mean_score| < 0.05 is abstention
            if abs(mean_score) < 0.05:
                d['abstained'] += 1
            else:
                # Defensive: guard against non-numeric price_change
                try:
                    correct = (mean_score > 0 and price_change > 0) or (mean_score < 0 and price_change < 0)
                except TypeError:
                    continue
                if correct:
                    d['correct'] += 1
                else:
                    d['incorrect'] += 1

    # Compute final metrics
    results = {}
    for source, data in source_data.items():
        effective_n = data['correct'] + data['incorrect']
        if effective_n < MIN_SAMPLES:
            continue

        accuracy = data['correct'] / effective_n if effective_n > 0 else 0.5

        # Change 2: Coverage — fraction of non-abstained observations
        coverage = (data['total'] - data['abstained']) / data['total'] if data['total'] > 0 else 0.0

        # Calculate correlation — guard against empty/bad data
        corr = 0
        if len(data['sents']) >= 5:
            try:
                corr, _ = stats.pearsonr(data['sents'], data['changes'])
                if np.isnan(corr):
                    corr = 0
            except Exception:
                corr = 0

        # Change 4: Compute 95% Beta credible interval
        alpha_post = 1 + data['correct']
        beta_post = 1 + data['incorrect']
        ci_lower = float(stats.beta.ppf(0.025, alpha_post, beta_post))
        ci_upper = float(stats.beta.ppf(0.975, alpha_post, beta_post))

        # Change 4: Fail-closed contrarian classification
        if effective_n < 100:
            is_contrarian = False
            type_label = "insufficient_data"
        elif ci_upper < 0.50:
            is_contrarian = True
            type_label = "contrarian"
        elif ci_lower > 0.50:
            is_contrarian = False
            type_label = "momentum"
        else:
            is_contrarian = False
            type_label = "neutral"

        results[source] = {
            'accuracy': round(accuracy, 4),
            'correct': data['correct'],
            'incorrect': data['incorrect'],
            'abstained': data['abstained'],
            'total': data['total'],
            'correlation': round(corr, 4),
            'coverage': round(coverage, 4),
            'is_contrarian': is_contrarian,
            'type_label': type_label,
            'credible_interval_lower': round(ci_lower, 4),
            'credible_interval_upper': round(ci_upper, 4),
            'effective_n': effective_n,
        }

    return results


def update_belief_priors(
    current_beliefs: dict,
    source_accuracy: dict,
) -> dict:
    """
    Rebuild belief priors deterministically from observed accuracy.

    Starts from neutral prior (alpha=1, beta=1) and adds observed
    correct/incorrect source-hours. No blending with previous beliefs
    — the function recomputes alpha/beta from raw counts every time.
    """
    updated_beliefs = {}
    now = datetime.now(timezone.utc).isoformat()

    for source, belief in current_beliefs.items():
        updated = belief.copy()

        if source in source_accuracy:
            obs = source_accuracy[source]

            # Change 3: Deterministic rebuild from neutral prior (no PRIOR_STRENGTH blending)
            new_alpha = 1 + obs['correct']
            new_beta = 1 + obs['incorrect']

            updated['alpha'] = round(new_alpha, 2)
            updated['beta'] = round(new_beta, 2)
            updated['total_crawls'] = obs['total']
            updated['accuracy'] = round(obs['accuracy'], 4)
            updated['correlation'] = round(obs['correlation'], 4)
            updated['is_contrarian'] = obs['is_contrarian']
            updated['type_label'] = obs['type_label']
            updated['credible_interval_lower'] = obs['credible_interval_lower']
            updated['credible_interval_upper'] = obs['credible_interval_upper']
            updated['effective_n'] = obs['effective_n']
            updated['coverage'] = round(obs['coverage'], 4)
            updated['last_updated'] = now

            logger.info(
                f"Updated {source}: accuracy={obs['accuracy']:.1%}, "
                f"Beta({updated['alpha']:.1f}, {updated['beta']:.1f}), "
                f"type={obs['type_label']}"
            )

        updated_beliefs[source] = updated

    # Add new sources not in current beliefs
    for source, obs in source_accuracy.items():
        source_lower = source.lower()
        if source_lower not in updated_beliefs:
            updated_beliefs[source_lower] = {
                'source': source_lower,
                'alpha': 1 + obs['correct'],
                'beta': 1 + obs['incorrect'],
                'granger_pvalue': None,
                'lead_time_hours': None,
                'total_crawls': obs['total'],
                'accuracy': round(obs['accuracy'], 4),
                'correlation': round(obs['correlation'], 4),
                'is_contrarian': obs['is_contrarian'],
                'type_label': obs['type_label'],
                'credible_interval_lower': obs['credible_interval_lower'],
                'credible_interval_upper': obs['credible_interval_upper'],
                'effective_n': obs['effective_n'],
                'coverage': round(obs['coverage'], 4),
                'last_updated': now,
            }
            logger.info(f"Added new source {source_lower}: accuracy={obs['accuracy']:.1%}, type={obs['type_label']}")

    return updated_beliefs


async def update_orchestrator_beliefs(
    state_path: str = "data/orchestrator_state.json",
    db_path: str = "data/sentiment.db",
    lookback_days: int = 90,
    *,
    base_beliefs: dict | None = None,
    persist_state: bool = True,
) -> dict:
    """
    Main function to update orchestrator beliefs based on observed performance.

    Args:
        state_path: Path to orchestrator state JSON.
        db_path: Path to SQLite database.
        lookback_days: Number of days of history to consider (default 90).
        base_beliefs: Live snapshot to use in compute-only mode.
        persist_state: Write JSON state for CLI/legacy use. Scheduler-driven
            updates set this to False and let CrawlerOrchestrator persist.
    """
    logger.info("=" * 60)
    logger.info("UPDATING BAYESIAN BELIEFS")
    logger.info("=" * 60)

    if base_beliefs is not None and persist_state:
        raise ValueError("base_beliefs requires persist_state=False")

    # Legacy CLI runs must not overwrite a live orchestrator's state.
    state_file = Path(state_path)
    state_lock = StateFileLock(state_file) if persist_state else None
    if state_lock:
        state_lock.acquire(blocking=False)

    try:
        # Load current state only for the legacy CLI/write path.
        if persist_state and state_file.exists():
            with open(state_file) as f:
                state = json.load(f)
        else:
            state = {"beliefs": {}, "baseline_informativeness": 0.5, "total_crawls": 0}

        if not persist_state and base_beliefs is None:
            raise ValueError("base_beliefs is required when persist_state=False")

        current_beliefs = copy.deepcopy(
            base_beliefs if base_beliefs is not None else state.get("beliefs", {})
        )
    except Exception:
        if state_lock:
            state_lock.release()
        raise
    logger.info(f"Loaded {len(current_beliefs)} existing beliefs")

    # Connect to database
    db = Database(Path(db_path))
    try:
        await db.connect()
    except Exception:
        if state_lock:
            state_lock.release()
        raise

    try:
        # ── Filter out ghost sources (non-Reddit with zero sentiment_raw rows) ──
        ghost_sources = await _find_ghost_sources(db, current_beliefs)
        if ghost_sources:
            logger.warning(
                "Removing %d ghost source(s) with zero raw posts: %s",
                len(ghost_sources),
                ", ".join(ghost_sources),
            )
            for src in ghost_sources:
                current_beliefs.pop(src, None)

        # Compute source accuracy
        source_accuracy = await compute_source_accuracy(db, lookback_days=lookback_days)
        logger.info(f"Computed accuracy for {len(source_accuracy)} sources")

        # Update beliefs
        updated_beliefs = update_belief_priors(current_beliefs, source_accuracy)

        if persist_state:
            state["belief_version"] = state.get("belief_version", 0) + 1
            state["belief_revision"] = state.get(
                "belief_revision",
                state["belief_version"] - 1,
            ) + 1
            state["beliefs"] = updated_beliefs
            state["last_belief_update"] = datetime.now(timezone.utc).isoformat()

            from .source_weights import (
                compute_weights_from_beliefs,
                print_weights_table,
                save_weights_to_db,
            )

            weights = compute_weights_from_beliefs(updated_beliefs)
            await save_weights_to_db(
                db,
                weights,
                belief_version=state["belief_version"],
                publish=False,
            )
            await _refit_gp_from_state(state, db, updated_beliefs)

            tmp_path = state_file.with_suffix(".tmp")
            with open(tmp_path, "w") as f:
                json.dump(state, f, indent=4)
            os.replace(tmp_path, state_file)
            logger.info(
                "Saved %d updated beliefs (version %d)",
                len(updated_beliefs),
                state["belief_version"],
            )
            await save_weights_to_db(
                db,
                weights,
                belief_version=state["belief_version"],
                publish=True,
            )
            logger.info(
                "Updated %d source weights from belief version %d",
                len(weights),
                state["belief_version"],
            )

        # Print summary
        print("\n" + "=" * 60)
        print("BELIEF UPDATE SUMMARY")
        print("=" * 60)
        print(f"\n{'Source':<28} {'Accuracy':<10} {'Alpha':<8} {'Beta':<8} {'Mean':<8} {'Type':<18} {'Coverage':<10}")
        print("-" * 92)

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
            type_label = belief.get('type_label', 'unknown')
            coverage = belief.get('coverage', 1.0)
            print(f"{source:<28} {acc:>6.1%}     {alpha:>6.1f}   {beta:>6.1f}   {mean:>6.3f}   {type_label:<18} {coverage:>6.1%}")

        print("=" * 60)

        if persist_state:
            print_weights_table(weights)

        return updated_beliefs

    finally:
        await db.close()
        if state_lock:
            state_lock.release()


async def _refit_gp_from_state(
    state: dict,
    db: Database,
    beliefs: dict,
) -> None:
    """Refit GP hyperparameters after belief update if GP state exists."""
    gp_state = state.get("gp_state")
    if not gp_state:
        return

    try:
        from ..bayesian.feature_extraction import SourceFeatureExtractor
        from ..bayesian.gp_model import GPSourceModel
        from ..bayesian.bandit import GPBandit

        hp = gp_state.get("hyperparameters", {})
        gp_model = GPSourceModel(**hp)

        extractor = SourceFeatureExtractor(db_path=str(db.db_path))
        if gp_state.get("scaler_params"):
            extractor.scaler_params = gp_state["scaler_params"]

        raw_features = await extractor.extract_features(db)
        if len(raw_features) < GPBandit.MIN_GP_ELIGIBLE:
            logger.info("Not enough sources for GP refit")
            return

        features = extractor.standardize_features(raw_features)

        # Build alphas/betas from updated beliefs
        eligible = []
        alphas = []
        betas = []
        for source, sf in features.items():
            b = beliefs.get(source, {})
            total = b.get("total_crawls", 0)
            if total >= GPBandit.MIN_OBSERVATIONS:
                eligible.append(sf)
                alphas.append(b.get("alpha", 1.0))
                betas.append(b.get("beta", 1.0))

        if len(eligible) < GPBandit.MIN_GP_ELIGIBLE:
            return

        result = gp_model.optimize_hyperparameters(
            eligible, np.array(alphas), np.array(betas)
        )

        if result.get("converged"):
            state["gp_state"] = {
                "hyperparameters": result["hyperparameters"],
                "scaler_params": extractor.scaler_params,
                "last_gp_fit": datetime.now(timezone.utc).isoformat(),
            }
            logger.info(
                f"GP hyperparameters reoptimized: "
                f"l={result['hyperparameters']['length_scale']:.3f}, "
                f"sf={result['hyperparameters']['signal_variance']:.3f}"
            )
        else:
            logger.info("GP hyperparameter optimization did not converge")

    except Exception as e:
        logger.warning(f"GP refit in belief updater failed: {e}")


async def main():
    """Run belief update."""
    await update_orchestrator_beliefs()


if __name__ == "__main__":
    asyncio.run(main())
