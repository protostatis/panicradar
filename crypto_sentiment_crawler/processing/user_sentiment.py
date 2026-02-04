"""User-centric sentiment scoring with hierarchical aggregation and multi-dimensional signals."""

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import numpy as np

from .semantic_sentiment import SemanticSentimentAnalyzer

logger = logging.getLogger("crypto_sentiment")

# Minimum human comments required for a post to be saved/scored
MIN_HUMAN_COMMENTS = 4

# Bot authors to filter out from comment scoring
# Note: Authors ending with 'bot' (case-insensitive) are also filtered automatically
BOT_AUTHORS = {
    # Reddit system bots
    'AutoModerator',
    'RemindMeBot',
    'sneakpeekbot',
    'WikiSummarizerBot',
    'RepostSleuthBot',
    'ImagesOfNetwork',
    'TweetPoster',
    'bot',  # Generic bot username
    # Crypto-specific bots
    'donut-bot',
    'coinfeeds-bot',
    'Bitty_Bot',
    'ModToolBot',
    'MoonsModBot',
    'moons_bot',
    'lntipbot',
    'Banano_Tipbot',
    'changetip',
    'TipBotLite',
    'pepetipbot',
    'dca-bot',
    # Content bots
    'WikiTextBot',
    'haikusbot',
    'Shakespeare-Bot',
    'alphabet_order_bot',
    'wikipedia_answer_bot',
    'GoodBot_BadBot',
    'totes_meta_bot',
    'timee_bot',
    'the_timezone_bot',
}


def count_human_comments(metadata: dict) -> int:
    """Count non-bot comments in post metadata.

    Args:
        metadata: Post metadata dict containing 'comments' list

    Returns:
        Number of human (non-bot) comments
    """
    comments = metadata.get('comments', [])
    if not comments:
        return 0

    return sum(
        1 for c in comments
        if c.get('author') not in BOT_AUTHORS
        and c.get('body')
        and not (c.get('author') or '').lower().endswith('bot')
    )


class SegmentCategory(str, Enum):
    """Category for segment classification."""
    FILTER = "FILTER"           # Bot messages, automod - exclude from sentiment
    ACTIVITY = "ACTIVITY"       # Scam warnings - indicates market activity, not sentiment
    TRUE_BEARISH = "TRUE_BEARISH"  # Actual losses, fear, capitulation
    EUPHORIA = "EUPHORIA"       # Moon talk, FOMO - contrarian sell signal
    STANDARD = "STANDARD"       # Regular content - use for sentiment


# Pattern definitions for segment categorization
FILTER_PATTERNS = [
    r'\bi am a bot\b',
    r'\bautomod(erator)?\b',
    r'\bperformed automatically\b',
    r'\bcontact the moderators\b',
    r'^⚠️?\s*WARNING',
    r'^WARNING:?\s*(IMPORTANT)?',
    r'^PSA.*SCAM',
    r'Please read.*wiki',
    r'NEWBIES GUIDE',
    r'PROJECT CATALYST',
    r'This comment\s+logs the Pay2Post',
]

ACTIVITY_PATTERNS = [
    r'\bscam(mer)?s?\b',
    r'\bprotect your (crypto|funds|wallet)\b',
    r'\bstay safe\b',
    r'\bphishing\b',
    r'\brug\s?pull(ed)?\b',
    r'\bfraud(ulent)?\b',
    r'\bsuspicious\b',
    r'\bdo not trust\b',
    r'\bnever (give|share|send)\b',
]

BEARISH_PATTERNS = [
    r'\bi lost \$?\d+',
    r'\blost (my |all |everything)',
    r'\bgot (rekt|liquidated|rugged|scammed)',
    r'\bgoing to zero\b',
    r'\bdone with crypto\b',
    r'\bshould have sold\b',
    r'\bpanic sell',
    r'\bbleeding (out|money)',
    r'\bwiped out\b',
    r'\bcapitulat',
    r'\bgive up\b',
    r'\bregret (buying|holding)',
]

EUPHORIA_PATTERNS = [
    r'\bto the moon\b',
    r'\b\d+x (incoming|guaranteed|easy)',
    r'\bcan\'t lose\b',
    r'\blast chance\b',
    r'\bgoing all in\b',
    r'\btook out (a )?loan\b',
    r'\blambo\b',
    r'\bmillionaire\b',
    r'\beasy money\b',
    r'\bfree money\b',
    r'\bnot financial advice but\b',
    r'\btrust me\b',
    r'\bguaranteed\b',
]


@dataclass
class SegmentScore:
    """Score for an individual segment (sentence/paragraph)."""
    text: str
    score: float
    char_length: int
    category: SegmentCategory = SegmentCategory.STANDARD
    included: bool = True  # Whether included in sentiment calculation


@dataclass
class PostScore:
    """Hierarchical score for a post with multi-dimensional signals."""
    raw_id: int
    timestamp: str
    coin: Optional[str]
    username: str
    source: str
    title: str
    title_score: Optional[float]
    body_score: float
    segment_scores: list[SegmentScore]
    final_score: float  # Filtered sentiment for Bayesian
    aggregation_method: str
    pos_count: int
    neg_count: int
    neu_count: int
    # Multi-dimensional signals
    activity_level: float = 0.0      # 0-1, scam/warning activity
    fear_index: float = 0.0          # 0-1, loss/panic mentions
    euphoria_index: float = 0.0      # 0-1, moon/fomo mentions
    segments_total: int = 0
    segments_filtered: int = 0
    segments_scored: int = 0


@dataclass
class UserProfile:
    """Aggregated user sentiment profile."""
    user_id: int
    username: str
    source: str
    total_posts: int
    avg_sentiment: float
    sentiment_stddev: float
    bullish_pct: float
    bearish_pct: float
    tendency: str
    accuracy_score: Optional[float]
    credibility_weight: float
    first_seen: str
    last_seen: str


def categorize_segment(text: str) -> SegmentCategory:
    """Categorize a segment based on content patterns."""
    text_lower = text.lower()

    # Check FILTER patterns first (highest priority)
    for pattern in FILTER_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return SegmentCategory.FILTER

    # Check ACTIVITY patterns (scam discussions)
    for pattern in ACTIVITY_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return SegmentCategory.ACTIVITY

    # Check TRUE_BEARISH patterns (actual losses/fear)
    for pattern in BEARISH_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return SegmentCategory.TRUE_BEARISH

    # Check EUPHORIA patterns (FOMO/moon)
    for pattern in EUPHORIA_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return SegmentCategory.EUPHORIA

    return SegmentCategory.STANDARD


class UserSentimentScorer:
    """Score posts hierarchically with multi-dimensional signals and track by user."""

    def __init__(
        self,
        db_path: str = "data/sentiment.db",
        aggregation_method: str = "title_weighted",
        min_segment_length: int = 20,
    ):
        self.db_path = db_path
        self.aggregation_method = aggregation_method
        self.min_segment_length = min_segment_length
        self.analyzer = SemanticSentimentAnalyzer()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return sqlite3.connect(self.db_path)

    def _split_into_segments(self, text: str) -> list[str]:
        """Split text into meaningful segments."""
        if not text:
            return []
        segments = re.split(r'\n\n+', text)
        return [s.strip() for s in segments if len(s.strip()) >= self.min_segment_length]

    def _aggregate_scores(
        self,
        title_score: Optional[float],
        segment_scores: list[float],
        method: str = "title_weighted",
    ) -> float:
        """Aggregate individual scores using specified method."""
        if not segment_scores and title_score is None:
            return 0.0

        all_scores = ([title_score] if title_score is not None else []) + segment_scores

        if not all_scores:
            return 0.0

        scores_arr = np.array(all_scores)

        if method == "mean":
            return float(np.mean(scores_arr))

        elif method == "title_weighted":
            if title_score is not None and segment_scores:
                seg_mean = np.mean(segment_scores)
                return 0.4 * title_score + 0.6 * seg_mean
            return float(np.mean(scores_arr))

        elif method == "extremes":
            max_pos = max(scores_arr) if max(scores_arr) > 0 else 0
            min_neg = min(scores_arr) if min(scores_arr) < 0 else 0
            return float(max_pos + min_neg)

        elif method == "dominant":
            pos = [s for s in scores_arr if s > 0.1]
            neg = [s for s in scores_arr if s < -0.1]
            if len(pos) > len(neg):
                return float(np.mean(pos))
            elif len(neg) > len(pos):
                return float(np.mean(neg))
            return float(np.mean(scores_arr))

        elif method == "first_last":
            if title_score is not None and segment_scores:
                return 0.4 * title_score + 0.3 * segment_scores[0] + 0.3 * segment_scores[-1]
            return float(np.mean(scores_arr))

        return float(np.mean(scores_arr))

    def _classify_tendency(
        self,
        bullish_pct: float,
        bearish_pct: float,
        stddev: float,
    ) -> str:
        """Classify user's sentiment tendency."""
        if bullish_pct > 0.6:
            return "consistently_bullish"
        elif bearish_pct > 0.6:
            return "consistently_bearish"
        elif stddev > 0.4:
            return "volatile"
        else:
            return "neutral"

    def _extract_user_info(self, raw_data: dict) -> tuple[Optional[str], str, str, int]:
        """Extract username, title, content from raw_data.

        Handles different source formats:
        - Reddit: author, title, content/body + comments from metadata
        - Stocktwits: username, body
        - 4chan: anonymous (use post_id as pseudo-user), thread_subject, text

        Comments are extracted from metadata and filtered to exclude bot authors.

        Returns:
            tuple: (username, title, content, human_comment_count)
        """
        # Try standard username fields
        username = raw_data.get('author') or raw_data.get('username')

        # For anonymous sources like 4chan, use post_id as pseudo-user
        if not username and raw_data.get('post_id'):
            username = f"anon_{raw_data['post_id']}"

        # Title: try standard field, then 4chan's thread_subject
        title = raw_data.get('title') or raw_data.get('thread_subject') or ''

        # Content: try multiple fields (selftext/body only, not comments)
        content = (
            raw_data.get('content') or
            raw_data.get('body') or
            raw_data.get('text') or ''
        )

        # Extract comments from metadata, filtering out bots
        metadata = raw_data.get('metadata', {})
        comments = metadata.get('comments', [])
        human_comment_count = 0

        if comments:
            # Filter out bot comments and extract bodies
            human_comments = [
                c.get('body', '')
                for c in comments
                if c.get('author') not in BOT_AUTHORS
                and c.get('body')
                and not c.get('author', '').lower().endswith('bot')
            ]
            human_comment_count = len(human_comments)

            # Append human comments to content
            if human_comments:
                comment_text = '\n\n'.join(human_comments)
                if content:
                    content = f"{content}\n\n{comment_text}"
                else:
                    content = comment_text

        return username, title, content, human_comment_count

    def score_post(self, raw_data: dict, raw_id: int, timestamp: str, source: str, coin: Optional[str] = None, min_human_comments: int = MIN_HUMAN_COMMENTS) -> Optional[PostScore]:
        """Score a single post with multi-dimensional signals.

        Args:
            raw_data: Raw post data dict
            raw_id: Database ID of raw post
            timestamp: Post timestamp
            source: Source identifier (e.g., 'reddit_bitcoin')
            coin: Optional coin symbol
            min_human_comments: Minimum number of non-bot comments required (default 4)

        Returns:
            PostScore if post meets criteria, None otherwise
        """
        username, title, content, human_comment_count = self._extract_user_info(raw_data)

        if not username:
            return None

        # Skip posts with insufficient engagement (fewer than min_human_comments)
        if human_comment_count < min_human_comments:
            logger.debug(f"Skipping post {raw_id}: only {human_comment_count} human comments (min: {min_human_comments})")
            return None

        # Score title (always included)
        title_score = None
        if title and len(title.strip()) >= 10:
            result = self.analyzer.analyze(title, method="asymmetric")
            title_score = result['score']

        # Split and categorize segments
        segments = self._split_into_segments(content)
        segment_objs = []

        # Counters for multi-dimensional signals
        activity_segments = 0
        fear_segments = 0
        euphoria_segments = 0
        filtered_segments = 0

        # Scores for filtered sentiment (STANDARD + TRUE_BEARISH only)
        scored_segment_values = []

        for seg in segments[:20]:  # Limit segments
            # Get semantic score
            result = self.analyzer.analyze(seg, method="asymmetric")
            score = result['score']

            # Categorize segment
            category = categorize_segment(seg)

            # Determine if included in sentiment calculation
            included = category in (SegmentCategory.STANDARD, SegmentCategory.TRUE_BEARISH)

            # Track category counts
            if category == SegmentCategory.FILTER:
                filtered_segments += 1
            elif category == SegmentCategory.ACTIVITY:
                activity_segments += 1
            elif category == SegmentCategory.TRUE_BEARISH:
                fear_segments += 1
            elif category == SegmentCategory.EUPHORIA:
                euphoria_segments += 1

            # Only include STANDARD and TRUE_BEARISH in sentiment
            if included:
                scored_segment_values.append(score)

            segment_objs.append(SegmentScore(
                text=seg[:100],
                score=score,
                char_length=len(seg),
                category=category,
                included=included,
            ))

        # Calculate body score from scored segments only
        body_score = float(np.mean(scored_segment_values)) if scored_segment_values else 0.0

        # Aggregate final score (filtered)
        final_score = self._aggregate_scores(
            title_score, scored_segment_values, self.aggregation_method
        )

        # Calculate multi-dimensional indices (0-1 scale)
        total_segments = len(segment_objs)
        if total_segments > 0:
            activity_level = activity_segments / total_segments
            fear_index = fear_segments / total_segments
            euphoria_index = euphoria_segments / total_segments
        else:
            activity_level = fear_index = euphoria_index = 0.0

        # Count sentiment distribution from scored segments only
        all_scored = ([title_score] if title_score else []) + scored_segment_values
        pos_count = sum(1 for s in all_scored if s > 0.1)
        neg_count = sum(1 for s in all_scored if s < -0.1)
        neu_count = len(all_scored) - pos_count - neg_count

        return PostScore(
            raw_id=raw_id,
            timestamp=timestamp,
            coin=coin,
            username=username,
            source=source,
            title=title[:200],
            title_score=title_score,
            body_score=body_score,
            segment_scores=segment_objs,
            final_score=final_score,
            aggregation_method=self.aggregation_method,
            pos_count=pos_count,
            neg_count=neg_count,
            neu_count=neu_count,
            activity_level=activity_level,
            fear_index=fear_index,
            euphoria_index=euphoria_index,
            segments_total=total_segments,
            segments_filtered=filtered_segments,
            segments_scored=len(scored_segment_values),
        )

    def get_or_create_user(self, username: str, source: str, timestamp: str) -> int:
        """Get existing user_id or create new user profile."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Try to get existing user
        cursor.execute(
            "SELECT user_id FROM user_profiles WHERE username = ? AND source = ?",
            (username, source)
        )
        row = cursor.fetchone()

        if row:
            user_id = row[0]
            # Update last_seen
            cursor.execute(
                "UPDATE user_profiles SET last_seen = ? WHERE user_id = ?",
                (timestamp, user_id)
            )
        else:
            # Create new user
            cursor.execute(
                """INSERT INTO user_profiles
                   (username, source, first_seen, last_seen, total_posts, credibility_weight)
                   VALUES (?, ?, ?, ?, 0, 1.0)""",
                (username, source, timestamp, timestamp)
            )
            user_id = cursor.lastrowid

        conn.commit()
        conn.close()
        return user_id

    def save_post_score(self, post_score: PostScore, update_existing: bool = False) -> int:
        """Save post score to database and link to user."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Get or create user
        user_id = self.get_or_create_user(
            post_score.username,
            post_score.source,
            post_score.timestamp
        )

        # Check if already scored
        cursor.execute(
            "SELECT id FROM user_sentiment_scores WHERE raw_id = ?",
            (post_score.raw_id,)
        )
        existing = cursor.fetchone()

        if existing:
            if update_existing:
                score_id = existing[0]
                # Update existing record
                segment_json = json.dumps([
                    {
                        "text": s.text,
                        "score": s.score,
                        "len": s.char_length,
                        "category": s.category.value,
                        "included": s.included,
                    }
                    for s in post_score.segment_scores
                ])

                cursor.execute(
                    """UPDATE user_sentiment_scores SET
                       title_score = ?, body_score = ?, segment_scores = ?,
                       final_score = ?, pos_count = ?, neg_count = ?, neu_count = ?,
                       activity_level = ?, fear_index = ?, euphoria_index = ?,
                       segments_filtered = ?, segments_scored = ?
                       WHERE id = ?""",
                    (
                        post_score.title_score,
                        post_score.body_score,
                        segment_json,
                        post_score.final_score,
                        post_score.pos_count,
                        post_score.neg_count,
                        post_score.neu_count,
                        post_score.activity_level,
                        post_score.fear_index,
                        post_score.euphoria_index,
                        post_score.segments_filtered,
                        post_score.segments_scored,
                        score_id,
                    )
                )
                conn.commit()
                conn.close()
                return score_id
            else:
                conn.close()
                return -1  # Already exists

        # Serialize segment scores with categories
        segment_json = json.dumps([
            {
                "text": s.text,
                "score": s.score,
                "len": s.char_length,
                "category": s.category.value,
                "included": s.included,
            }
            for s in post_score.segment_scores
        ])

        # Insert score with new fields
        cursor.execute(
            """INSERT INTO user_sentiment_scores
               (user_id, raw_id, timestamp, coin, title_score, body_score,
                segment_scores, final_score, aggregation_method,
                pos_count, neg_count, neu_count,
                activity_level, fear_index, euphoria_index,
                segments_filtered, segments_scored)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                post_score.raw_id,
                post_score.timestamp,
                post_score.coin,
                post_score.title_score,
                post_score.body_score,
                segment_json,
                post_score.final_score,
                post_score.aggregation_method,
                post_score.pos_count,
                post_score.neg_count,
                post_score.neu_count,
                post_score.activity_level,
                post_score.fear_index,
                post_score.euphoria_index,
                post_score.segments_filtered,
                post_score.segments_scored,
            )
        )
        score_id = cursor.lastrowid

        conn.commit()
        conn.close()

        return score_id

    def update_user_profile(self, user_id: int):
        """Recalculate and update user profile aggregates."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Get all scores for user
        cursor.execute(
            """SELECT final_score, timestamp FROM user_sentiment_scores
               WHERE user_id = ? ORDER BY timestamp""",
            (user_id,)
        )
        rows = cursor.fetchall()

        if not rows:
            conn.close()
            return

        scores = [r[0] for r in rows]
        timestamps = [r[1] for r in rows]

        total_posts = len(scores)
        avg_sentiment = float(np.mean(scores))
        sentiment_stddev = float(np.std(scores)) if len(scores) > 1 else 0.0
        bullish_pct = sum(1 for s in scores if s > 0.1) / total_posts
        bearish_pct = sum(1 for s in scores if s < -0.1) / total_posts
        tendency = self._classify_tendency(bullish_pct, bearish_pct, sentiment_stddev)

        # Update profile
        cursor.execute(
            """UPDATE user_profiles SET
               total_posts = ?,
               avg_sentiment = ?,
               sentiment_stddev = ?,
               bullish_pct = ?,
               bearish_pct = ?,
               tendency = ?,
               first_seen = ?,
               last_seen = ?,
               updated_at = ?
               WHERE user_id = ?""",
            (
                total_posts,
                avg_sentiment,
                sentiment_stddev,
                bullish_pct,
                bearish_pct,
                tendency,
                timestamps[0],
                timestamps[-1],
                datetime.now(timezone.utc).isoformat(),
                user_id,
            )
        )

        conn.commit()
        conn.close()

    def get_user_profile(self, username: str, source: str) -> Optional[UserProfile]:
        """Get user profile by username and source."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """SELECT user_id, username, source, total_posts, avg_sentiment,
                      sentiment_stddev, bullish_pct, bearish_pct, tendency,
                      accuracy_score, credibility_weight, first_seen, last_seen
               FROM user_profiles
               WHERE username = ? AND source = ?""",
            (username, source)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return UserProfile(
            user_id=row[0],
            username=row[1],
            source=row[2],
            total_posts=row[3],
            avg_sentiment=row[4],
            sentiment_stddev=row[5],
            bullish_pct=row[6],
            bearish_pct=row[7],
            tendency=row[8],
            accuracy_score=row[9],
            credibility_weight=row[10],
            first_seen=row[11],
            last_seen=row[12],
        )

    def get_users_by_tendency(self, tendency: str, min_posts: int = 3) -> list[UserProfile]:
        """Get users with a specific sentiment tendency."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """SELECT user_id, username, source, total_posts, avg_sentiment,
                      sentiment_stddev, bullish_pct, bearish_pct, tendency,
                      accuracy_score, credibility_weight, first_seen, last_seen
               FROM user_profiles
               WHERE tendency = ? AND total_posts >= ?
               ORDER BY total_posts DESC""",
            (tendency, min_posts)
        )
        rows = cursor.fetchall()
        conn.close()

        return [
            UserProfile(
                user_id=r[0], username=r[1], source=r[2], total_posts=r[3],
                avg_sentiment=r[4], sentiment_stddev=r[5], bullish_pct=r[6],
                bearish_pct=r[7], tendency=r[8], accuracy_score=r[9],
                credibility_weight=r[10], first_seen=r[11], last_seen=r[12],
            )
            for r in rows
        ]

    def get_weighted_sentiment(
        self,
        coin: Optional[str] = None,
        hours: int = 24,
        weight_by_credibility: bool = True,
    ) -> dict:
        """Get aggregate sentiment weighted by user credibility with multi-dimensional signals."""
        conn = self._get_connection()
        cursor = conn.cursor()

        query = """
            SELECT uss.final_score, up.credibility_weight, up.username, up.tendency,
                   uss.activity_level, uss.fear_index, uss.euphoria_index
            FROM user_sentiment_scores uss
            JOIN user_profiles up ON uss.user_id = up.user_id
            WHERE uss.timestamp >= datetime('now', ?)
        """
        params = [f'-{hours} hours']

        if coin:
            query += " AND uss.coin = ?"
            params.append(coin)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return {
                "weighted_sentiment": 0.0,
                "simple_sentiment": 0.0,
                "activity_level": 0.0,
                "fear_index": 0.0,
                "euphoria_index": 0.0,
                "sample_size": 0,
                "bullish_users": 0,
                "bearish_users": 0,
            }

        scores = [r[0] for r in rows]
        weights = [r[1] for r in rows]
        tendencies = [r[3] for r in rows]
        activities = [r[4] or 0 for r in rows]
        fears = [r[5] or 0 for r in rows]
        euphorias = [r[6] or 0 for r in rows]

        simple_sentiment = float(np.mean(scores))

        if weight_by_credibility:
            weighted_sentiment = float(np.average(scores, weights=weights))
        else:
            weighted_sentiment = simple_sentiment

        return {
            "weighted_sentiment": weighted_sentiment,
            "simple_sentiment": simple_sentiment,
            "activity_level": float(np.mean(activities)),
            "fear_index": float(np.mean(fears)),
            "euphoria_index": float(np.mean(euphorias)),
            "sample_size": len(rows),
            "bullish_users": sum(1 for t in tendencies if t == "consistently_bullish"),
            "bearish_users": sum(1 for t in tendencies if t == "consistently_bearish"),
        }


def backfill_user_scores(db_path: str = "data/sentiment.db", limit: int = None, update_existing: bool = False, sources: list = None):
    """Backfill existing raw data into user sentiment scores with multi-dimensional signals.

    Args:
        db_path: Path to SQLite database
        limit: Max number of posts to process (None for all)
        update_existing: Whether to update already-scored posts
        sources: List of source patterns to include (None for all social sources)
    """
    scorer = UserSentimentScorer(db_path=db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Default to all social media sources
    if sources is None:
        sources = ['reddit%', 'stocktwits', '4chan%', 'bitcointalk%', 'twitter%']

    # Build source filter
    source_conditions = ' OR '.join([f"source LIKE '{s}'" if '%' in s else f"source = '{s}'" for s in sources])

    query = f"""
        SELECT id, source, raw_data, timestamp, coin
        FROM sentiment_raw
        WHERE ({source_conditions})
        ORDER BY timestamp
    """
    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    logger.info(f"Backfilling {len(rows)} posts (update_existing={update_existing})...")

    processed = 0
    updated = 0
    skipped = 0
    errors = 0
    user_ids = set()

    for i, row in enumerate(rows):
        raw_id, source, raw_str, timestamp, coin = row

        try:
            raw_data = json.loads(raw_str) if isinstance(raw_str, str) else raw_str
            if not raw_data:
                skipped += 1
                continue

            post_score = scorer.score_post(raw_data, raw_id, timestamp, source, coin)

            if post_score is None:
                skipped += 1
                continue

            score_id = scorer.save_post_score(post_score, update_existing=update_existing)

            if score_id > 0:
                if update_existing:
                    updated += 1
                else:
                    processed += 1
                # Track user for profile update
                user_id = scorer.get_or_create_user(
                    post_score.username, post_score.source, timestamp
                )
                user_ids.add(user_id)
            else:
                skipped += 1

            if (i + 1) % 500 == 0:
                logger.info(f"Progress: {i+1}/{len(rows)} ({processed} new, {updated} updated, {skipped} skipped)")

        except Exception as e:
            errors += 1
            logger.error(f"Error processing row {raw_id}: {e}")

    # Update all user profiles
    logger.info(f"Updating {len(user_ids)} user profiles...")
    for user_id in user_ids:
        scorer.update_user_profile(user_id)

    logger.info(f"Backfill complete: {processed} new, {updated} updated, {skipped} skipped, {errors} errors")
    return processed, updated, skipped, errors
