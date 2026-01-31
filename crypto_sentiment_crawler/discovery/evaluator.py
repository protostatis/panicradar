"""
Source evaluator: Assess quality and suitability of discovered sources.

Evaluation criteria:
1. Activity: Post frequency (posts per hour)
2. Engagement: Average score and comments
3. Freshness: Age of recent posts
4. Relevance: Crypto content ratio
5. Quality: Not spam, meaningful discussion
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..crawler.fetcher import Fetcher
from ..logging_config import logger
from .reddit_discovery import CRYPTO_PATTERNS, DiscoveredSubreddit


@dataclass
class EvaluationResult:
    """Result of evaluating a source."""

    subreddit: str
    posts_per_hour: float
    avg_score: float
    avg_comments: float
    crypto_relevance: float  # 0-1, ratio of crypto-related posts
    freshness_hours: float  # Average age of recent posts
    newest_post_hours: float  # Age of most recent post (key for inference)
    overall_score: float  # Combined suitability score 0-1
    recommendation: str  # "add", "monitor", "reject"
    reason: str


class SourceEvaluator:
    """Evaluate potential data sources for suitability."""

    # Thresholds for recommendation
    # Focus on freshness - do they have posts within our inference window?
    MIN_CRYPTO_RELEVANCE = 0.15  # At least 15% crypto content
    MIN_AVG_SCORE = 2  # Minimum engagement
    MAX_FRESHNESS_HOURS = 24  # Has posts within last day
    MAX_NEWEST_POST_HOURS = 6  # Most recent post should be < 6 hours old

    def __init__(self, fetcher: Fetcher | None = None):
        self.fetcher = fetcher
        self._owns_fetcher = fetcher is None

    async def __aenter__(self):
        if self._owns_fetcher:
            self.fetcher = Fetcher()
            await self.fetcher.start()
        return self

    async def __aexit__(self, *args):
        if self._owns_fetcher and self.fetcher:
            await self.fetcher.close()

    async def evaluate(self, subreddit: str) -> EvaluationResult | None:
        """
        Evaluate a subreddit's suitability as a data source.

        Fetches recent posts and analyzes:
        - Post frequency
        - Engagement levels
        - Crypto relevance
        - Content freshness
        """
        url = f"https://old.reddit.com/r/{subreddit}/new"

        result = await self.fetcher.fetch(url, rate_limit=1.0)
        if not result.success:
            logger.warning(f"Could not fetch r/{subreddit}: {result.error}")
            return None

        soup = BeautifulSoup(result.content, "lxml")
        posts = soup.select("div.thing.link")

        if not posts:
            return EvaluationResult(
                subreddit=subreddit,
                posts_per_hour=0,
                avg_score=0,
                avg_comments=0,
                crypto_relevance=0,
                freshness_hours=999,
                overall_score=0,
                recommendation="reject",
                reason="No posts found or subreddit doesn't exist",
            )

        now = datetime.now(timezone.utc)
        scores = []
        comments = []
        timestamps = []
        crypto_count = 0

        for post in posts[:25]:
            try:
                # Score
                score_elem = post.select_one("div.score.unvoted")
                if score_elem:
                    score_text = score_elem.get_text().replace("•", "0")
                    try:
                        scores.append(int(score_text))
                    except ValueError:
                        scores.append(0)

                # Comments
                comments_elem = post.select_one("a.comments")
                if comments_elem:
                    text = comments_elem.get_text()
                    match = re.search(r"(\d+)", text)
                    if match:
                        comments.append(int(match.group(1)))

                # Timestamp
                ts_attr = post.get("data-timestamp")
                if ts_attr:
                    try:
                        ts = datetime.fromtimestamp(int(ts_attr) / 1000, tz=timezone.utc)
                        timestamps.append(ts)
                    except (ValueError, OSError):
                        pass

                # Crypto relevance
                title = post.select_one("a.title")
                if title:
                    text = title.get_text()
                    if any(p.search(text) for p in CRYPTO_PATTERNS):
                        crypto_count += 1

            except Exception as e:
                logger.debug(f"Error parsing post: {e}")
                continue

        # Compute metrics
        n_posts = len(posts[:25])

        avg_score = sum(scores) / len(scores) if scores else 0
        avg_comments = sum(comments) / len(comments) if comments else 0
        crypto_relevance = crypto_count / n_posts if n_posts > 0 else 0

        # Posts per hour
        if len(timestamps) >= 2:
            timestamps.sort()
            time_span = (timestamps[-1] - timestamps[0]).total_seconds() / 3600
            posts_per_hour = (len(timestamps) - 1) / time_span if time_span > 0 else 0
        else:
            posts_per_hour = 0

        # Freshness (average age of posts and newest post age)
        if timestamps:
            ages = [(now - ts).total_seconds() / 3600 for ts in timestamps]
            freshness_hours = sum(ages) / len(ages)
            newest_post_hours = min(ages)  # Most recent post
        else:
            freshness_hours = 999
            newest_post_hours = 999

        # Compute overall score (weighted)
        overall = self._compute_overall_score(
            posts_per_hour=posts_per_hour,
            avg_score=avg_score,
            avg_comments=avg_comments,
            crypto_relevance=crypto_relevance,
            freshness_hours=freshness_hours,
            newest_post_hours=newest_post_hours,
        )

        # Determine recommendation
        recommendation, reason = self._get_recommendation(
            posts_per_hour=posts_per_hour,
            avg_score=avg_score,
            crypto_relevance=crypto_relevance,
            freshness_hours=freshness_hours,
            newest_post_hours=newest_post_hours,
            overall=overall,
        )

        return EvaluationResult(
            subreddit=subreddit,
            posts_per_hour=posts_per_hour,
            avg_score=avg_score,
            avg_comments=avg_comments,
            crypto_relevance=crypto_relevance,
            freshness_hours=freshness_hours,
            newest_post_hours=newest_post_hours,
            overall_score=overall,
            recommendation=recommendation,
            reason=reason,
        )

    def _compute_overall_score(
        self,
        posts_per_hour: float,
        avg_score: float,
        avg_comments: float,
        crypto_relevance: float,
        freshness_hours: float,
        newest_post_hours: float,
    ) -> float:
        """Compute weighted overall suitability score."""

        # Recent activity score (0-1) - key metric for inference
        # If newest post is < 4 hours old, score = 1.0
        recency = max(0, 1 - (newest_post_hours / 12))

        # Engagement score (0-1)
        engagement = min((avg_score + avg_comments * 2) / 50, 1.0)

        # Weighted combination
        # Recency is most important for inference, then relevance
        overall = (
            recency * 0.40 +
            crypto_relevance * 0.35 +
            engagement * 0.25
        )

        return overall

    def _get_recommendation(
        self,
        posts_per_hour: float,
        avg_score: float,
        crypto_relevance: float,
        freshness_hours: float,
        newest_post_hours: float,
        overall: float,
    ) -> tuple[str, str]:
        """Determine recommendation based on metrics."""

        reasons = []

        # Check hard requirements
        if crypto_relevance < 0.1:
            return "reject", "Too little crypto content (<10%)"

        if newest_post_hours > 48:
            return "reject", "Stale content (newest post >48h old)"

        # Check soft requirements for inference suitability
        if newest_post_hours > self.MAX_NEWEST_POST_HOURS:
            reasons.append(f"newest post {newest_post_hours:.0f}h old")

        if crypto_relevance < self.MIN_CRYPTO_RELEVANCE:
            reasons.append(f"low crypto relevance ({crypto_relevance:.0%})")

        if avg_score < self.MIN_AVG_SCORE:
            reasons.append(f"low engagement (avg score {avg_score:.0f})")

        # Final recommendation - focus on recent activity for inference
        if newest_post_hours <= 4 and crypto_relevance >= 0.15:
            return "add", f"Active source with recent posts ({newest_post_hours:.1f}h old)"
        elif newest_post_hours <= 12 and crypto_relevance >= 0.1:
            reason = "; ".join(reasons) if reasons else "Moderate activity"
            return "monitor", f"Potential source: {reason}"
        elif overall >= 0.4:
            reason = "; ".join(reasons) if reasons else "Good overall score"
            return "monitor", f"Worth monitoring: {reason}"
        else:
            return "reject", "; ".join(reasons) if reasons else "Low overall score"

    async def evaluate_batch(
        self,
        subreddits: list[str | DiscoveredSubreddit],
    ) -> list[EvaluationResult]:
        """Evaluate multiple subreddits."""
        results = []

        for sub in subreddits:
            name = sub.name if isinstance(sub, DiscoveredSubreddit) else sub
            result = await self.evaluate(name)
            if result:
                results.append(result)
                logger.info(
                    f"r/{name}: {result.recommendation} "
                    f"(newest={result.newest_post_hours:.1f}h, "
                    f"crypto={result.crypto_relevance:.0%}, "
                    f"score={result.overall_score:.2f})"
                )

        return results
