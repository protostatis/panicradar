"""Source configuration loading from YAML files."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class EndpointConfig:
    """Configuration for a crawl endpoint."""

    name: str
    path: str
    method: str = "article"  # 'article', 'listing', 'feed'
    selectors: dict = field(default_factory=dict)


@dataclass
class SourceConfig:
    """Configuration for a crawl source."""

    name: str
    base_url: str
    source_type: str  # 'news', 'social', 'forum', 'search'
    endpoints: list[EndpointConfig] = field(default_factory=list)
    selectors: dict = field(default_factory=dict)
    rate_limit: float = 1.0
    headers: dict = field(default_factory=dict)
    enabled: bool = True

    # Bayesian priors
    prior_adjustment: float = 0.0  # Added to baseline informativeness

    def get_url(self, endpoint_name: str | None = None) -> str:
        """Get full URL for an endpoint."""
        if not endpoint_name:
            return self.base_url

        for ep in self.endpoints:
            if ep.name == endpoint_name:
                return f"{self.base_url.rstrip('/')}{ep.path}"

        return self.base_url

    def get_selectors(self, endpoint_name: str | None = None) -> dict:
        """Get selectors, merging endpoint-specific with source defaults."""
        selectors = dict(self.selectors)

        if endpoint_name:
            for ep in self.endpoints:
                if ep.name == endpoint_name:
                    selectors.update(ep.selectors)
                    break

        return selectors


def load_source_config(path: str | Path) -> SourceConfig:
    """Load source configuration from YAML file."""
    path = Path(path)

    with open(path) as f:
        data = yaml.safe_load(f)

    # Parse endpoints
    endpoints = []
    for ep_data in data.get("endpoints", []):
        endpoints.append(EndpointConfig(
            name=ep_data.get("name", "default"),
            path=ep_data.get("path", "/"),
            method=ep_data.get("method", "article"),
            selectors=ep_data.get("selectors", {}),
        ))

    return SourceConfig(
        name=data["name"],
        base_url=data["base_url"],
        source_type=data.get("type", "unknown"),
        endpoints=endpoints,
        selectors=data.get("selectors", {}),
        rate_limit=data.get("rate_limit", 1.0),
        headers=data.get("headers", {}),
        enabled=data.get("enabled", True),
        prior_adjustment=data.get("prior_adjustment", 0.0),
    )


def load_all_sources(directory: str | Path) -> dict[str, SourceConfig]:
    """Load all source configs from a directory."""
    directory = Path(directory)
    sources = {}

    if not directory.exists():
        return sources

    for path in directory.glob("*.yaml"):
        try:
            config = load_source_config(path)
            sources[config.name] = config
        except Exception as e:
            print(f"Error loading {path}: {e}")

    for path in directory.glob("*.yml"):
        try:
            config = load_source_config(path)
            sources[config.name] = config
        except Exception as e:
            print(f"Error loading {path}: {e}")

    return sources


# Default source configs (can be overridden by YAML files or discovery)
DEFAULT_SOURCES = {
    "reddit_cryptocurrency": SourceConfig(
        name="reddit_cryptocurrency",
        base_url="https://old.reddit.com",
        source_type="social",
        endpoints=[
            EndpointConfig(name="hot", path="/r/cryptocurrency/hot/"),
            EndpointConfig(name="new", path="/r/cryptocurrency/new/"),
            EndpointConfig(name="rising", path="/r/cryptocurrency/rising/"),
        ],
        rate_limit=0.5,
        prior_adjustment=0.0,
    ),
    "reddit_bitcoin": SourceConfig(
        name="reddit_bitcoin",
        base_url="https://old.reddit.com",
        source_type="social",
        endpoints=[
            EndpointConfig(name="hot", path="/r/bitcoin/hot/"),
        ],
        rate_limit=0.5,
        prior_adjustment=0.0,
    ),
    "reddit_ethereum": SourceConfig(
        name="reddit_ethereum",
        base_url="https://old.reddit.com",
        source_type="social",
        endpoints=[
            EndpointConfig(name="hot", path="/r/ethereum/hot/"),
        ],
        rate_limit=0.5,
        prior_adjustment=0.0,
    ),
    "reddit_solana": SourceConfig(
        name="reddit_solana",
        base_url="https://old.reddit.com",
        source_type="social",
        endpoints=[
            EndpointConfig(name="hot", path="/r/solana/hot/"),
        ],
        rate_limit=0.5,
        prior_adjustment=0.0,
    ),
    "reddit_altcoin": SourceConfig(
        name="reddit_altcoin",
        base_url="https://old.reddit.com",
        source_type="social",
        endpoints=[
            EndpointConfig(name="hot", path="/r/altcoin/hot/"),
        ],
        rate_limit=0.5,
        prior_adjustment=-0.1,  # Often lower quality
    ),
}


def load_discovered_sources(state_path: str = "data/discovery_state.json") -> dict[str, SourceConfig]:
    """
    Load sources from discovery state file.
    Returns active sources as SourceConfig objects.
    """
    import json
    from pathlib import Path

    path = Path(state_path)
    if not path.exists():
        return {}

    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return {}

    sources = {}
    for key, source_data in data.get("sources", {}).items():
        if source_data.get("status") != "active":
            continue

        if source_data.get("source_type") == "reddit":
            subreddit = source_data.get("subreddit", key.replace("reddit_", ""))
            sources[key] = SourceConfig(
                name=key,
                base_url="https://old.reddit.com",
                source_type="social",
                endpoints=[
                    EndpointConfig(name="new", path=f"/r/{subreddit}/new/"),
                ],
                rate_limit=0.5,
                prior_adjustment=0.0,
            )

    return sources


def get_all_sources(include_discovered: bool = True) -> dict[str, SourceConfig]:
    """
    Get all available sources, including discovered ones.
    Discovered sources override defaults with the same name.
    """
    sources = dict(DEFAULT_SOURCES)

    if include_discovered:
        discovered = load_discovered_sources()
        sources.update(discovered)

    return sources

# News sources (require JS, disabled for now)
# TODO: Add RSS feed support or use playwright for these
NEWS_SOURCES_DISABLED = {
    "coindesk": SourceConfig(
        name="coindesk",
        base_url="https://www.coindesk.com",
        source_type="news",
        selectors={
            "title": "h1",
            "content": "article",
            "timestamp": "time[datetime]",
            "author": ".author-name",
        },
        rate_limit=1.0,
        prior_adjustment=0.3,
        enabled=False,
    ),
    "cointelegraph": SourceConfig(
        name="cointelegraph",
        base_url="https://cointelegraph.com",
        source_type="news",
        selectors={
            "title": "h1",
            "content": "article",
            "timestamp": "time",
        },
        rate_limit=1.0,
        prior_adjustment=0.3,
        enabled=False,
    ),
}
