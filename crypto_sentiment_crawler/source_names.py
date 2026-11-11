"""Canonical source-key helpers.

A source key appears in three places that must agree: the belief store, the
published weight tables, and ``sentiment_raw.source``. Every write path stores
lowercase names, so keys that differ only by case are the same source.

Mixed-case keys were persisted by older discovery code that built the key from
the subreddit's display name (``reddit_CryptoCurrency``). Because the database
lookups are case-sensitive, those duplicates never received any accuracy data
and stayed frozen in the belief store, while their lowercase twins were crawled
normally.
"""

REDDIT_PREFIX = "reddit_"


def canonical_source_name(source: str) -> str:
    """Return the lowercase form used for all source identity comparisons."""

    return source.strip().lower()


def reddit_source_key(subreddit: str) -> str:
    """Build the canonical source key for a subreddit name.

    Accepts either ``cryptocurrency`` or ``reddit_cryptocurrency`` and returns
    ``reddit_cryptocurrency``. Reddit resolves subreddit names case-insensitively,
    so ``r/CryptoCurrency`` and ``r/cryptocurrency`` must map to one source key.
    """

    name = canonical_source_name(subreddit)
    if name.startswith(REDDIT_PREFIX):
        return name
    return f"{REDDIT_PREFIX}{name}"
