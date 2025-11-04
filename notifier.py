"""
Notifier system - supports multiple notification providers
Provides async interface for sending notifications
"""

import asyncio
from abc import ABC, abstractmethod

from loguru import logger
from rich.console import Console
from rich.markdown import Markdown


class BaseNotifier(ABC):
    """Base class for all notification providers"""

    def __init__(self, config: dict):
        """
        Initialize the notifier.

        Args:
            config: Configuration dictionary for this notifier
        """
        self.config = config
        self.enabled = config.get("enabled", True)

    @abstractmethod
    async def send(self, markdown_content: str) -> None:
        """
        Send a notification with markdown content.

        Args:
            markdown_content: The notification content in markdown format
        """
        raise NotImplementedError


class ConsoleNotifier(BaseNotifier):
    """Console notifier that logs to terminal using rich"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.console = Console()
        self.enable_rich = config.get("enable_rich_markdown_formatting", True)
        logger.info("Console notifier initialized")

    async def send(self, markdown_content: str) -> None:
        """
        Send notification to console.

        Args:
            markdown_content: The notification content in markdown format
        """
        if not self.enabled:
            return

        try:
            if self.enable_rich:
                md = Markdown(markdown_content)
                self.console.print(md)
            else:
                print(markdown_content)
        except Exception as e:
            logger.error(f"Error sending console notification: {e}", exc_info=True)


class NtfyNotifier(BaseNotifier):
    """Ntfy notifier that sends to ntfy server"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.url = config.get("url", "https://ntfy.sh")
        self.topic = config.get("topic", "reborn")

        # Import here to avoid dependency if not using ntfy
        from python_ntfy import NtfyClient

        self.client = NtfyClient(topic=self.topic, server=self.url)
        logger.info(f"Ntfy notifier initialized: {self.url}/{self.topic}")

    async def send(self, markdown_content: str) -> None:
        """
        Send notification to ntfy server.

        Args:
            markdown_content: The notification content in markdown format
        """
        if not self.enabled:
            return

        try:
            # Send as plain text (ntfy will handle markdown rendering)
            await asyncio.to_thread(
                self.client.send, message=markdown_content, format_as_markdown=True
            )
            logger.debug(f"Ntfy notification sent: {markdown_content[:100]}...")
        except Exception as e:
            logger.error(f"Error sending ntfy notification: {e}", exc_info=True)


class Notifier:
    """Main notifier class that manages multiple notification providers. This class handles the configuration file and initializes the appropriate notifier instances based on the provided settings."""

    def __init__(self, config: dict):
        """
        Initialize the notifier system.

        Args:
            config: Configuration dictionary with notifier settings
        """
        self.notifiers: list[BaseNotifier] = []

        # Initialize console notifier if configured
        console_config = config.get("console", {})
        if console_config.get("enabled", False):
            self.notifiers.append(ConsoleNotifier(console_config))

        # Initialize ntfy notifier if configured
        ntfy_config = config.get("ntfy", {})
        if ntfy_config.get("enabled", False):
            self.notifiers.append(NtfyNotifier(ntfy_config))

        logger.info(
            f"Notifier system initialized with {len(self.notifiers)} provider(s)"
        )

    async def send(self, markdown_content: str) -> None:
        """
        Send notification to all configured providers.

        Args:
            markdown_content: The notification content in markdown format
        """
        if not self.notifiers:
            logger.warning("No notifiers configured, skipping notification")
            return

        # Send to all notifiers concurrently
        await asyncio.gather(
            *[notifier.send(markdown_content) for notifier in self.notifiers],
            return_exceptions=True,
        )

    async def close(self):
        """Close/cleanup all notifiers"""
        logger.info("Notifier system closed")
