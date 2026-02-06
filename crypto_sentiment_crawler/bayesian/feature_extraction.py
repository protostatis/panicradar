"""Extract source feature vectors from user_sentiment_scores.

Builds a 7D feature vector per source from the last N days of scored posts:
1. mean_final_score    - sentiment central tendency
2. std_final_score     - sentiment volatility
3. mean_fear_index     - bearish signal strength
4. mean_euphoria_index - bullish signal strength
5. mean_activity_level - scam/warning prevalence
6. polarity_ratio      - pos_count / (pos + neg + 1)
7. log_post_volume     - log(total_posts + 1)

All features are z-scored before kernel evaluation.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from .gp_model import SourceFeatures

# Source type mapping
_SOURCE_TYPE_MAP = {
    "reddit_": "social",
    "4chan": "forum",
    "bitcointalk": "forum",
    "twitter": "social",
    "x_": "social",
    "coindesk": "news",
    "cointelegraph": "news",
    "decrypt": "news",
    "theblock": "news",
    "google_trends": "search",
}


class SourceFeatureExtractor:
    """Extract and standardize source features from the database."""

    def __init__(self, db_path: str = "data/sentiment.db"):
        self.db_path = db_path
        self.scaler_params: dict | None = None  # {mean: ndarray, std: ndarray}

    async def extract_features(
        self,
        db,
        lookback_days: int = 7,
        min_posts: int = 5,
    ) -> dict[str, SourceFeatures]:
        """Extract 7D feature vectors per source from recent sentiment scores.

        Args:
            db: Database instance (with .conn attribute)
            lookback_days: Number of days to look back
            min_posts: Minimum posts required per source

        Returns:
            Dict mapping source name -> SourceFeatures
        """
        since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

        cursor = await db.conn.execute(
            """
            SELECT up.source,
                   uss.final_score,
                   uss.fear_index,
                   uss.euphoria_index,
                   uss.activity_level,
                   uss.pos_count,
                   uss.neg_count
            FROM user_sentiment_scores uss
            JOIN user_profiles up ON uss.user_id = up.user_id
            WHERE uss.timestamp >= ?
            ORDER BY up.source
            """,
            (since,),
        )
        rows = await cursor.fetchall()

        # Group by source
        source_data: dict[str, list] = {}
        for source, final_score, fear, euphoria, activity, pos, neg in rows:
            if source not in source_data:
                source_data[source] = []
            source_data[source].append({
                "final_score": final_score or 0.0,
                "fear_index": fear or 0.0,
                "euphoria_index": euphoria or 0.0,
                "activity_level": activity or 0.0,
                "pos_count": pos or 0,
                "neg_count": neg or 0,
            })

        # Build feature vectors
        result = {}
        for source, records in source_data.items():
            if len(records) < min_posts:
                continue

            scores = np.array([r["final_score"] for r in records])
            fears = np.array([r["fear_index"] for r in records])
            euphorias = np.array([r["euphoria_index"] for r in records])
            activities = np.array([r["activity_level"] for r in records])
            pos_counts = np.array([r["pos_count"] for r in records])
            neg_counts = np.array([r["neg_count"] for r in records])

            total_pos = pos_counts.sum()
            total_neg = neg_counts.sum()

            features = np.array([
                scores.mean(),                              # mean_final_score
                scores.std() if len(scores) > 1 else 0.0,  # std_final_score
                fears.mean(),                               # mean_fear_index
                euphorias.mean(),                           # mean_euphoria_index
                activities.mean(),                          # mean_activity_level
                total_pos / (total_pos + total_neg + 1),    # polarity_ratio
                np.log(len(records) + 1),                   # log_post_volume
            ])

            result[source] = SourceFeatures(
                source=source,
                features=features,
                source_type=self.get_source_type(source),
            )

        return result

    @staticmethod
    def get_source_type(source_name: str) -> str:
        """Map source name to type category."""
        for prefix, stype in _SOURCE_TYPE_MAP.items():
            if source_name.startswith(prefix):
                return stype
        return "social"

    def standardize_features(
        self, features: dict[str, SourceFeatures]
    ) -> dict[str, SourceFeatures]:
        """Z-score all feature vectors. Stores scaler params for serialization.

        Args:
            features: Dict of source -> SourceFeatures (raw)

        Returns:
            Dict of source -> SourceFeatures (standardized)
        """
        if not features:
            return features

        X = np.array([f.features for f in features.values()])
        mean = X.mean(axis=0)
        std = X.std(axis=0)
        std[std < 1e-10] = 1.0  # Avoid division by zero

        self.scaler_params = {"mean": mean.tolist(), "std": std.tolist()}

        result = {}
        for source, sf in features.items():
            standardized = (sf.features - mean) / std
            result[source] = SourceFeatures(
                source=sf.source,
                features=standardized,
                source_type=sf.source_type,
            )
        return result
