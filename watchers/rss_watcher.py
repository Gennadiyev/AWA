"""
RSS Watcher - Monitors RSS feeds for new entries
Sends notifications with LLM-curated digest of relevant entries

Version 0.2.0 - Refactored with StateDiff plugin for persistent state tracking
"""

import asyncio
import hashlib
import re
from collections.abc import Coroutine

import aiohttp
import feedparser
import requests
from loguru import logger

from notifier import Notifier
from plugins.llm import query as llm_query
from plugins.state_diff import StateDiff, JsonSerializable


# Default configuration values
DEFAULT_INTERVAL_SECONDS = 3600  # Check every hour
DEFAULT_DIGEST_PROMPT = (
    "Review the following RSS feed entries and select the most important and relevant ones. "
    "Return a concise digest with entry titles and links. "
    "If no entries are relevant, respond with 'No relevant entries found.'"
)
DEFAULT_LLM_FILTER_PROMPT = (
    "Evaluate the recommendation score of the following RSS feed entry to current events. "
    "The score ranges from 0 (not relevant) to 5 (highly relevant). "
    "Respond with only the score in the format: \\boxed{score}."
)

type EntryData = dict[str, str]
type ConfigDict = dict[str, str | int | bool | dict[str, str]]


class RSSFeed:
    """Represents a single RSS feed to monitor with persistent state tracking."""

    def __init__(self, feed_config: ConfigDict, cache_id: str = "") -> None:
        """
        Initialize an RSS feed monitor.

        Args:
            feed_config: Configuration dict for this specific feed
            cache_id: Unique identifier for the user/instance to separate caches
        """
        self.url: str = feed_config["url"]
        self.name: str = feed_config.get("name", self.url)
        self.enabled: bool = feed_config.get("enabled", True)

        # Proxy configuration
        proxy_config = feed_config.get("proxy", "")
        self.proxy: str = str(proxy_config) if proxy_config else ""
        self._session: aiohttp.ClientSession | None = None

        # Digest configuration
        self.enable_digest: bool = bool(feed_config.get("enable_digest", True))
        digest_config = feed_config.get("digest", {})
        digest_dict: dict[str, str] = digest_config if isinstance(digest_config, dict) else {}
        self.digest_prompt: str = str(digest_dict.get("prompt", DEFAULT_DIGEST_PROMPT))
        digest_model_name = digest_dict.get("model_name")
        self.digest_model: str = str(digest_model_name) if digest_model_name else ""

        # LLM Filter configuration
        self.enable_llm_filter: bool = bool(feed_config.get("enable_llm_filter", False))
        llm_filter_config = feed_config.get("llm_filter", {})
        llm_filter_dict: dict[str, str] = llm_filter_config if isinstance(llm_filter_config, dict) else {}
        self.llm_filter_prompt: str = str(llm_filter_dict.get("prompt", DEFAULT_LLM_FILTER_PROMPT))
        llm_filter_model_name = llm_filter_dict.get("model_name")
        self.llm_filter_model: str = str(llm_filter_model_name) if llm_filter_model_name else ""
        self.max_concurrent_llm_filter_queries: int = int(llm_filter_dict.get("max_concurrent_queries", 50))

        # Initialize StateDiff for persistent state tracking
        # Use hash of URL combined with cache_id to ensure uniqueness per user per feed
        feed_hash = hashlib.md5(self.url.encode()).hexdigest()
        # Combine cache_id and feed_hash to create user-specific cache files
        state_user_id = f"{cache_id}-{feed_hash}" if cache_id else feed_hash
        self.state_diff: StateDiff = StateDiff(
            app_id="rss_watcher",
            user_id=state_user_id,
            maximum_entries=1000  # Keep up to 1000 recent entries
        )

    def __str__(self) -> str:
        """String representation of the feed."""
        return f"{self.name} ({self.url})"

    def get_entry_id(self, entry: feedparser.FeedParserDict) -> str:
        """
        Get unique ID for an RSS entry.

        Args:
            entry: Feed entry dict from feedparser

        Returns:
            Unique ID string for the entry
        """
        # Try to use entry's id/guid first
        if hasattr(entry, "id") and entry.id:  # type: ignore[attr-defined]
            return str(entry.id)  # type: ignore[attr-defined]
        if hasattr(entry, "guid") and entry.guid:  # type: ignore[attr-defined]
            return str(entry.guid)  # type: ignore[attr-defined]

        # Fall back to hash of link + title
        link = str(getattr(entry, "link", ""))
        title = str(getattr(entry, "title", ""))
        content = f"{link}:{title}"
        return hashlib.md5(content.encode()).hexdigest()

    def _fetch_feed_sync(self) -> feedparser.FeedParserDict:
        """
        Synchronous helper to fetch and parse RSS feed.
        Supports optional proxy configuration.

        Returns:
            Parsed feed object from feedparser
        """
        if self.proxy:
            # Use requests with proxy, then parse the content
            proxies = {
                "http": self.proxy,
                "https": self.proxy,
            }
            response = requests.get(self.url, proxies=proxies, timeout=30)
            response.raise_for_status()
            return feedparser.parse(response.content)
        else:
            # Direct feedparser fetch without proxy
            return feedparser.parse(self.url)

    async def _fetch_feed_aiohttp(self) -> feedparser.FeedParserDict:
        """
        Asynchronous helper to fetch and parse RSS feed using aiohttp.
        Supports optional proxy configuration.

        Returns:
            Parsed feed object from feedparser
        """
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()

        try:
            async with self._session.get(self.url, proxy=self.proxy, timeout=30) as response:
                response.raise_for_status()
                content = await response.read()
                return feedparser.parse(content)
        except Exception as e:
            logger.error(f"Error fetching feed {self} with aiohttp: {e}", exc_info=True)
            return feedparser.FeedParserDict()

    async def fetch_feed(self) -> feedparser.FeedParserDict | None:
        """
        Fetch and parse the RSS feed.

        Returns:
            Parsed feed object or None if failed
        """
        try:
            proxy_info = f" (via proxy {self.proxy})" if self.proxy else ""
            logger.warning(f"Fetching RSS feed: {self}{proxy_info}")
            feed: feedparser.FeedParserDict = await self._fetch_feed_aiohttp()

            # Check for feed errors
            if hasattr(feed, "bozo") and feed.bozo:  # type: ignore[attr-defined]
                if hasattr(feed, "bozo_exception"):
                    logger.warning(
                        f"Feed parse warning for {self}: {feed.bozo_exception}"  # type: ignore[attr-defined]
                    )

            # Check if feed has entries
            if not hasattr(feed, "entries"):
                logger.warning(f"No entries found in feed: {self}")
                return None

            return feed

        except Exception as e:
            logger.error(f"Failed to fetch feed {self}: {e}", exc_info=True)
            return None

    def extract_entry_data(self, entry: feedparser.FeedParserDict) -> EntryData:
        """
        Extract relevant data from a feed entry.

        Args:
            entry: Feed entry from feedparser

        Returns:
            Dictionary with entry data
        """
        return {
            "id": self.get_entry_id(entry),
            "title": str(getattr(entry, "title", "No Title")),
            "link": str(getattr(entry, "link", "")),
            "summary": str(getattr(entry, "summary", "")),
            "published": str(getattr(entry, "published", "Unknown")),
            "author": str(getattr(entry, "author", "Unknown")),
        }

    async def get_new_entries(self) -> list[EntryData]:
        """
        Fetch feed and return new entries using StateDiff.

        Returns:
            List of new entry dictionaries
        """
        feed = await self.fetch_feed()
        if not feed:
            return []

        total_entries = len(feed.entries)  # type: ignore[attr-defined]
        if total_entries == 0:
            logger.debug("There is no entries in the fetched feed!")

        # Extract all current entries
        current_entries: list[JsonSerializable] = [
            self.extract_entry_data(entry) for entry in feed.entries  # type: ignore[attr-defined]
        ]

        # Use StateDiff to get only new entries
        new_entries_raw = await self.state_diff.diff(
            current_entries, mode="incremental"
        )

        # Cast back to EntryData list
        new_entries: list[EntryData] = [
            entry for entry in new_entries_raw if isinstance(entry, dict)
        ]

        # Log the results for visibility
        if new_entries:
            logger.info(
                f"Found {len(new_entries)} new entries (out of {total_entries} total) in {self}"
            )
        else:
            logger.debug(
                f"No new entries found (checked {total_entries} entries) in {self}"
            )

        return new_entries

    def format_entries_for_llm(self, entries: list[EntryData]) -> str:
        """
        Format entries for LLM processing.

        Args:
            entries: List of entry dictionaries

        Returns:
            Formatted string for LLM
        """
        formatted: list[str] = []
        for i, entry in enumerate(entries, 1):
            formatted.append(
                f"## {i}. {entry['title']}\n" +
                f"[Link]({entry['link']})\n" +
                f"From {entry['published']}\n" +
                f"{entry['summary']}\n"  # Include full summary for LLM analysis
            )
        return "\n---\n".join(formatted)


class RSSMonitor:
    """Monitors multiple RSS feeds and sends notifications for new entries."""

    def __init__(self, notifier: Notifier, config: ConfigDict) -> None:
        """
        Initialize the RSS monitor.

        Args:
            notifier: Notifier instance for sending alerts
            config: Configuration dictionary for the RSS watcher
        """
        self.notifier: Notifier = notifier
        self.config: ConfigDict = config

        # Load configuration with defaults
        self.interval: int = int(config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS))

        # Get cache_id from injected config name (for user-specific caching)
        # This is automatically injected by main.py from the config filename
        cache_id = str(config.get("_config_name", ""))

        # Initialize RSS feeds
        self.feeds: list[RSSFeed] = []
        watching_configs_raw = config.get("watching", [])
        watching_configs: list[ConfigDict] = (
            watching_configs_raw if isinstance(watching_configs_raw, list) else []
        )

        for feed_config in watching_configs:
            if not feed_config.get("enabled", True):
                continue

            feed = RSSFeed(feed_config, cache_id=cache_id)
            self.feeds.append(feed)
            logger.info(f"Added feed to watch: {feed}")

    async def process_entries(
        self, feed: RSSFeed, entries: list[EntryData]
    ) -> None:
        """
        Process new entries and send notification.

        Args:
            feed: RSSFeed that has new entries
            entries: List of new entry dictionaries
        """
        if not entries:
            return

        if feed.enable_llm_filter and feed.llm_filter_model:
            # Use LLM to filter relevant entries
            logger.info(f"Filtering {len(entries)} entries with LLM for {feed}")
            try:
                filtered_entries = await self.filter_entries_with_llm(
                    feed=feed,
                    entries=entries,
                )

                # Check if no entries were deemed relevant
                if len(filtered_entries) == 0:
                    logger.info(f"No relevant entries found by LLM for {feed}")
                    return

            except Exception as e:
                logger.error(f"Failed to filter entries with LLM: {e}", exc_info=True)
                # Fall back to unfiltered entries
                filtered_entries = entries
        else:
            # All entries without filtering
            filtered_entries = entries

        # Format entries for LLM
        entries_text = feed.format_entries_for_llm(filtered_entries)

        if feed.enable_digest and feed.digest_model:
            # Use LLM to create digest
            logger.info(f"Generating digest for {len(entries)} entries from {feed}")
            try:
                digest = await llm_query(
                    message=f"Feed entries:\n\n{entries_text}",
                    model=feed.digest_model,
                    system_message=feed.digest_prompt,
                )

                # Check if LLM found no relevant entries
                if "no relevant entries" in digest.lower().strip(".\"'"):
                    logger.info(f"No relevant entries found by LLM for {feed}")
                    return

                # Format as markdown with digest
                markdown_content = f"""# 📰 RSS Digest

> Feed: [{feed.name}]({feed.url})

{digest}
"""

            except Exception as e:
                logger.error(f"Failed to generate digest: {e}", exc_info=True)
                # Fallback to simple list
                markdown_content = self.format_simple_list_markdown(feed, filtered_entries)
        else:
            # Simple notification without LLM digest
            markdown_content = self.format_simple_list_markdown(feed, filtered_entries)

        # Send notification
        await self.notifier.send(markdown_content)

    async def filter_entries_with_llm(
        self, feed: RSSFeed, entries: list[EntryData]
    ) -> list[EntryData]:
        """
        Filter entries using LLM based on relevance.

        Args:
            feed: RSSFeed instance
            entries: List of entry dictionaries

        Returns:
            List of relevant entry dictionaries
        """
        filtered_entries: list[EntryData] = []
        semaphore = asyncio.Semaphore(feed.max_concurrent_llm_filter_queries)

        async def is_entry_relevant(entry: EntryData) -> bool:
            """Check if a single entry is relevant using LLM."""
            async with semaphore:
                entry_text = f"Title: {entry['title']}\nSummary: {entry['summary']}"
                response = await llm_query(
                    message=f"Entry:\n\n{entry_text}",
                    model=feed.llm_filter_model,
                    system_message=feed.llm_filter_prompt,
                )
                # Score: \boxed{xxx}
                matches = re.findall(r"\\boxed{\s*(\d+)\s*}", response)
                if matches:
                    score = int(matches[0])
                    return score >= 3
                else:
                    return False

        # Create tasks for all entries
        tasks = [is_entry_relevant(entry) for entry in entries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect relevant entries
        for entry, result in zip(entries, results):
            if isinstance(result, Exception):
                logger.debug(f"Error checking relevance for entry {entry['title']}: {result}", exc_info=True)
                continue
            if result:
                filtered_entries.append(entry)
        return filtered_entries

    def format_simple_list_markdown(
        self, feed: RSSFeed, entries: list[EntryData]
    ) -> str:
        """
        Format entries as simple markdown list without LLM.

        Args:
            feed: RSSFeed instance
            entries: List of entry dictionaries

        Returns:
            Formatted markdown string
        """
        lines: list[str] = ["# 📰 New RSS Entries\n\n"]
        lines.append(f"> Feed: [{feed.name}]({feed.url})\n")
        lines.append(f"{len(entries)} new entries\n\n")

        for entry in entries[:10]:  # Limit to 10 entries
            lines.append(f"- [{entry['title']}]({entry['link']})\n")

        if len(entries) > 10:
            lines.append(f"\n_...and {len(entries) - 10} more entries_")

        return "".join(lines)

    async def check_all_feeds(self) -> None:
        """Check all configured RSS feeds for new entries."""
        for feed in self.feeds:
            try:
                new_entries = await feed.get_new_entries()
                await self.process_entries(feed, new_entries)

            except Exception as e:
                logger.error(f"Error checking feed {feed}: {e}", exc_info=True)

    async def monitor_loop(self) -> None:
        """Main monitoring loop that checks feeds periodically."""
        if not self.feeds:
            logger.warning("No RSS feeds configured to watch")
            return

        logger.info(
            f"Starting RSS watcher | " +
            f"Interval: {self.interval}s | " +
            f"Feeds: {len(self.feeds)}"
        )

        while True:
            try:
                await self.check_all_feeds()
                await asyncio.sleep(self.interval)

            except asyncio.CancelledError:
                logger.info("RSS watcher cancelled")
                break
            except Exception as e:
                logger.error(f"Error in RSS watcher: {e}", exc_info=True)
                await asyncio.sleep(self.interval)

        logger.info("RSS watcher stopped")


async def watch_rss(notifier: Notifier, config: ConfigDict) -> None:
    """
    Monitor RSS feeds for new entries.

    Args:
        notifier: Notifier instance for sending alerts
        config: Configuration dictionary for RSS watcher
    """
    monitor = RSSMonitor(notifier, config)
    await monitor.monitor_loop()


def init(notifier: Notifier, config: ConfigDict) -> Coroutine[None, None, None] | None:
    """
    Initialize the RSS watcher.

    Args:
        notifier: Notifier instance for sending notifications
        config: Configuration dictionary for this watcher

    Returns:
        Async coroutine or None if disabled
    """
    if not config:
        logger.warning("RSS watcher is not configured")
        return None

    if not config.get("enabled", False):
        logger.info("RSS watcher is disabled")
        return None

    return watch_rss(notifier, config)
