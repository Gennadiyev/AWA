"""
RSS Watcher - Monitors RSS feeds for new entries
Sends notifications with LLM-curated digest of relevant entries

Version 0.1.0 (c) Kunologist & Claude Opus 4.1
"""

import asyncio
import hashlib
from typing import Any, Coroutine, Optional

import feedparser
from loguru import logger

from notifier import Notifier
from plugins.llm import query as llm_query


# Default configuration values
DEFAULT_INTERVAL_SECONDS = 3600  # Check every hour
DEFAULT_DIGEST_PROMPT = (
    "Review the following RSS feed entries and select the most important and relevant ones. "
    "Return a concise digest with entry titles and links. "
    "If no entries are relevant, respond with 'No relevant entries found.'"
)


class RSSFeed:
    """Represents a single RSS feed to monitor."""

    def __init__(self, feed_config: dict):
        """
        Initialize an RSS feed monitor.

        Args:
            feed_config: Configuration dict for this specific feed
        """
        self.url = feed_config["url"]
        self.name = feed_config.get("name", self.url)
        self.enabled = feed_config.get("enabled", True)

        # Digest configuration
        self.enable_digest = feed_config.get("enable_digest", True)
        digest_config = feed_config.get("digest", {})
        self.digest_prompt = digest_config.get("prompt", DEFAULT_DIGEST_PROMPT)
        self.digest_model = digest_config.get("model_name")

        # Track seen entry IDs to avoid duplicates
        self.seen_entry_ids: set[str] = set()

        # First run flag - don't notify on first check to avoid spam
        self.first_run = True

    def __str__(self) -> str:
        """String representation of the feed."""
        return f"{self.name} ({self.url})"

    def get_entry_id(self, entry: dict) -> str:
        """
        Get unique ID for an RSS entry.

        Args:
            entry: Feed entry dict from feedparser

        Returns:
            Unique ID string for the entry
        """
        # Try to use entry's id/guid first
        if hasattr(entry, "id"):
            return entry.id
        if hasattr(entry, "guid"):
            return entry.guid

        # Fall back to hash of link + title
        link = getattr(entry, "link", "")
        title = getattr(entry, "title", "")
        content = f"{link}:{title}"
        return hashlib.md5(content.encode()).hexdigest()

    async def fetch_feed(self) -> Optional[feedparser.FeedParserDict]:
        """
        Fetch and parse the RSS feed.

        Returns:
            Parsed feed object or None if failed
        """
        try:
            logger.debug(f"Fetching RSS feed: {self}")
            # Use asyncio.to_thread for blocking feedparser call
            feed = await asyncio.to_thread(feedparser.parse, self.url)

            # Check for feed errors
            if hasattr(feed, "bozo") and feed.bozo:
                if hasattr(feed, "bozo_exception"):
                    logger.warning(
                        f"Feed parse warning for {self}: {feed.bozo_exception}"
                    )

            # Check if feed has entries
            if not hasattr(feed, "entries"):
                logger.warning(f"No entries found in feed: {self}")
                return None

            return feed

        except Exception as e:
            logger.error(f"Failed to fetch feed {self}: {e}", exc_info=True)
            return None

    async def get_new_entries(self) -> list[dict[str, Any]]:
        """
        Fetch feed and return new entries.

        Returns:
            List of new entry dictionaries
        """
        feed = await self.fetch_feed()
        if not feed:
            return []

        total_entries = len(feed.entries)
        new_entries = []

        for entry in feed.entries:
            entry_id = self.get_entry_id(entry)

            # Skip if already seen
            if entry_id in self.seen_entry_ids:
                continue

            self.seen_entry_ids.add(entry_id)

            # Extract entry data
            entry_data = {
                "id": entry_id,
                "title": getattr(entry, "title", "No Title"),
                "link": getattr(entry, "link", ""),
                "summary": getattr(entry, "summary", ""),
                "published": getattr(entry, "published", "Unknown"),
                "author": getattr(entry, "author", "Unknown"),
            }

            new_entries.append(entry_data)

        # Always log the results for visibility
        if new_entries:
            logger.info(f"Found {len(new_entries)} new entries (out of {total_entries} total) in {self}")
        else:
            logger.debug(f"No new entries found (checked {total_entries} entries) in {self}")

        return new_entries

    def format_entries_for_llm(self, entries: list[dict[str, Any]]) -> str:
        """
        Format entries for LLM processing.

        Args:
            entries: List of entry dictionaries

        Returns:
            Formatted string for LLM
        """
        formatted = []
        for i, entry in enumerate(entries, 1):
            formatted.append(
                f"## {i}. {entry['title']}\n"
                f"[Link]({entry['link']})\n"
                f"From {entry['published']}\n"
                f"{entry['summary']}\n"  # Include full summary for LLM analysis
            )
        return "\n---\n".join(formatted)


class RSSMonitor:
    """Monitors multiple RSS feeds and sends notifications for new entries."""

    def __init__(self, notifier: Notifier, config: dict):
        """
        Initialize the RSS monitor.

        Args:
            notifier: Notifier instance for sending alerts
            config: Configuration dictionary for the RSS watcher
        """
        self.notifier = notifier
        self.config = config

        # Load configuration with defaults
        self.interval = config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)

        # Initialize RSS feeds
        self.feeds: list[RSSFeed] = []
        watching_configs = config.get("watching", [])

        for feed_config in watching_configs:
            if not feed_config.get("enabled", True):
                continue

            feed = RSSFeed(feed_config)
            self.feeds.append(feed)
            logger.info(f"Added feed to watch: {feed}")

    async def process_entries(
        self, feed: RSSFeed, entries: list[dict[str, Any]]
    ) -> None:
        """
        Process new entries and send notification.

        Args:
            feed: RSSFeed that has new entries
            entries: List of new entry dictionaries
        """
        if not entries:
            return

        # Skip notifications on first run to avoid spam
        if feed.first_run:
            logger.info(
                f"First run for {feed}, skipping notification for {len(entries)} entries"
            )
            feed.first_run = False
            return

        feed.first_run = False

        # Format entries for LLM
        entries_text = feed.format_entries_for_llm(entries)

        if feed.enable_digest:
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
                logger.error(f"Failed to generate digest: {e}")
                # Fallback to simple list
                markdown_content = self.format_simple_list_markdown(feed, entries)
        else:
            # Simple notification without LLM
            markdown_content = self.format_simple_list_markdown(feed, entries)

        # Send notification
        await self.notifier.send(markdown_content)

    def format_simple_list_markdown(
        self, feed: RSSFeed, entries: list[dict[str, Any]]
    ) -> str:
        """
        Format entries as simple markdown list without LLM.

        Args:
            feed: RSSFeed instance
            entries: List of entry dictionaries

        Returns:
            Formatted markdown string
        """
        lines = ["# 📰 New RSS Entries\n\n"]
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
            f"Starting RSS watcher | "
            f"Interval: {self.interval}s | "
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


async def watch_rss(notifier: Notifier, config: dict) -> None:
    """
    Monitor RSS feeds for new entries.

    Args:
        notifier: Notifier instance for sending alerts
        config: Configuration dictionary for RSS watcher
    """
    monitor = RSSMonitor(notifier, config)
    await monitor.monitor_loop()


def init(notifier: Notifier, config: dict) -> Optional[Coroutine[Any, Any, None]]:
    """
    Initialize the RSS watcher.

    Args:
        notifier: Notifier instance for sending notifications
        config: Configuration dictionary for this watcher

    Returns:
        Async coroutine or None if disabled
    """
    if not config:
        logger.info("RSS watcher is not configured")
        return None

    if not config.get("enabled", False):
        logger.info("RSS watcher is disabled")
        return None

    return watch_rss(notifier, config)
