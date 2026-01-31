"""HTML parser using BeautifulSoup with configurable selectors."""

import re
from dataclasses import dataclass
from datetime import datetime

from bs4 import BeautifulSoup


@dataclass
class ParseResult:
    """Result of parsing a page."""

    url: str
    title: str | None
    content: str | None
    author: str | None
    published_at: datetime | None
    links: list[str]
    metadata: dict
    success: bool
    error: str | None = None


class Parser:
    """
    HTML parser with configurable CSS selectors.
    """

    def __init__(self, parser_backend: str = "lxml"):
        """
        Args:
            parser_backend: BeautifulSoup parser ('lxml', 'html.parser', 'html5lib')
        """
        self.parser_backend = parser_backend

    def parse(
        self,
        html: str,
        url: str,
        selectors: dict | None = None,
    ) -> ParseResult:
        """
        Parse HTML content using provided selectors.

        Args:
            html: Raw HTML string
            url: Source URL (for resolving relative links)
            selectors: Dictionary mapping field names to CSS selectors
                      e.g., {"title": "h1.headline", "content": "div.article-body"}

        Returns:
            ParseResult with extracted content
        """
        if not html:
            return ParseResult(
                url=url,
                title=None,
                content=None,
                author=None,
                published_at=None,
                links=[],
                metadata={},
                success=False,
                error="Empty HTML",
            )

        try:
            soup = BeautifulSoup(html, self.parser_backend)
            selectors = selectors or {}

            # Extract fields using selectors
            title = self._extract_text(soup, selectors.get("title", "title"))
            content = self._extract_text(soup, selectors.get("content"))
            author = self._extract_text(soup, selectors.get("author"))
            published_at = self._extract_datetime(soup, selectors.get("timestamp"))

            # Extract all links
            links = self._extract_links(soup, url)

            # Extract metadata
            metadata = self._extract_metadata(soup)

            return ParseResult(
                url=url,
                title=title,
                content=content,
                author=author,
                published_at=published_at,
                links=links,
                metadata=metadata,
                success=True,
            )

        except Exception as e:
            return ParseResult(
                url=url,
                title=None,
                content=None,
                author=None,
                published_at=None,
                links=[],
                metadata={},
                success=False,
                error=str(e),
            )

    def _extract_text(self, soup: BeautifulSoup, selector: str | None) -> str | None:
        """Extract text content from selector."""
        if not selector:
            return None

        # Handle attribute extraction (e.g., "a::attr(href)")
        if "::attr(" in selector:
            base_selector, attr = selector.split("::attr(")
            attr = attr.rstrip(")")
            element = soup.select_one(base_selector)
            return element.get(attr) if element else None

        element = soup.select_one(selector)
        if element:
            return self._clean_text(element.get_text())
        return None

    def _extract_all_text(self, soup: BeautifulSoup, selector: str) -> list[str]:
        """Extract text from all matching elements."""
        elements = soup.select(selector)
        return [self._clean_text(el.get_text()) for el in elements]

    def _extract_datetime(
        self,
        soup: BeautifulSoup,
        selector: str | None,
    ) -> datetime | None:
        """Extract and parse datetime from selector."""
        if not selector:
            # Try common datetime locations
            selectors_to_try = [
                "time[datetime]",
                "meta[property='article:published_time']",
                "meta[name='date']",
            ]
            for sel in selectors_to_try:
                result = self._try_extract_datetime(soup, sel)
                if result:
                    return result
            return None

        return self._try_extract_datetime(soup, selector)

    def _try_extract_datetime(
        self,
        soup: BeautifulSoup,
        selector: str,
    ) -> datetime | None:
        """Try to extract datetime from a specific selector."""
        element = soup.select_one(selector)
        if not element:
            return None

        # Try datetime attribute first
        dt_str = element.get("datetime") or element.get("content") or element.get_text()
        return self._parse_datetime(dt_str)

    def _parse_datetime(self, dt_str: str | None) -> datetime | None:
        """Parse datetime string in various formats."""
        if not dt_str:
            return None

        dt_str = dt_str.strip()

        # Common formats to try
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d %B %Y",
            "%d %b %Y",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue

        return None

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Extract all links from page."""
        links = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                # Resolve relative URLs
                if href.startswith("/"):
                    from urllib.parse import urljoin
                    href = urljoin(base_url, href)
                if href.startswith("http"):
                    links.append(href)
        return list(set(links))  # Deduplicate

    def _extract_metadata(self, soup: BeautifulSoup) -> dict:
        """Extract metadata from meta tags and JSON-LD."""
        metadata = {}

        # OpenGraph tags
        for meta in soup.select("meta[property^='og:']"):
            prop = meta.get("property", "").replace("og:", "")
            metadata[f"og_{prop}"] = meta.get("content")

        # Twitter cards
        for meta in soup.select("meta[name^='twitter:']"):
            name = meta.get("name", "").replace("twitter:", "")
            metadata[f"twitter_{name}"] = meta.get("content")

        # Description
        desc = soup.select_one("meta[name='description']")
        if desc:
            metadata["description"] = desc.get("content")

        # JSON-LD
        for script in soup.select("script[type='application/ld+json']"):
            try:
                import json
                data = json.loads(script.string or "{}")
                if isinstance(data, dict):
                    metadata["json_ld"] = data
                    break
            except (json.JSONDecodeError, TypeError):
                pass

        return metadata

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        if not text:
            return ""
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def extract_article_text(self, soup: BeautifulSoup) -> str:
        """
        Extract main article text using common patterns.

        Falls back to largest text block if no article container found.
        """
        # Common article selectors
        article_selectors = [
            "article",
            "[role='article']",
            ".article-content",
            ".article-body",
            ".post-content",
            ".entry-content",
            ".content-body",
            "main",
        ]

        for selector in article_selectors:
            article = soup.select_one(selector)
            if article:
                # Remove scripts, styles, nav, etc.
                for tag in article.select("script, style, nav, header, footer, aside"):
                    tag.decompose()
                return self._clean_text(article.get_text())

        # Fallback: find largest text block
        paragraphs = soup.select("p")
        if paragraphs:
            texts = [self._clean_text(p.get_text()) for p in paragraphs]
            return " ".join(t for t in texts if len(t) > 50)

        return ""
