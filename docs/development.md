# Development Guide

> [!TIP]
> The entire page is written by Claude Opus 4.1. Use at your own discretion. This document may be useful for coding agents, though.

## Developing Extensions

### Creating a Custom Watcher

Watchers are auto-discovered from the `watchers/` directory. Here's a simple "Hello World" watcher that sends a greeting every minute:

**File: `watchers/hello_watcher.py`**

```python
import asyncio
from datetime import datetime
from typing import Optional, Coroutine, Any

from loguru import logger
from notifier import Notifier


async def hello_loop(notifier: Notifier, config: dict) -> None:
    """Send a hello notification every minute."""
    interval = config.get("interval_seconds", 60)

    logger.info(f"Hello watcher started (interval: {interval}s)")

    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            markdown_content = f"""# 👋 Hello from AWA!

Current time: **{now}**

This is a demo notification from the hello watcher.
"""
            await notifier.send(markdown_content)
            await asyncio.sleep(interval)

        except asyncio.CancelledError:
            logger.info("Hello watcher cancelled")
            break
        except Exception as e:
            logger.error(f"Error in hello watcher: {e}", exc_info=True)
            await asyncio.sleep(interval)


def init(notifier: Notifier, config: dict) -> Optional[Coroutine[Any, Any, None]]:
    if not config:
        logger.info("Hello watcher is not configured")
        return None

    if not config.get("enabled", False):
        logger.info("Hello watcher is disabled")
        return None

    return hello_loop(notifier, config)
```

**Configuration in `config.yaml`:**

```yaml
watchers:
  hello_watcher:
    enabled: true
    interval_seconds: 60
```

That's it! The watcher will be automatically discovered and loaded on next run.

### Adding Notification Providers

AWA supports multiple notification backends:

**Console Notifier** - Rich markdown rendering in your terminal
**Ntfy Notifier** - Push notifications to [ntfy.sh](https://ntfy.sh) (self-hosted or public)

More notifiers can be added by extending `BaseNotifier`.

Notifiers inherit from `BaseNotifier` and implement the `send()` method. Here's a simple webhook notifier example:

**File: `notifier.py` (add to existing file)**

```python
import httpx


class WebhookNotifier(BaseNotifier):
    """Webhook notifier that POSTs to a URL."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.webhook_url = config.get("webhook_url")
        self.headers = config.get("headers", {})
        logger.info(f"Webhook notifier initialized: {self.webhook_url}")

    async def send(self, markdown_content: str) -> None:
        """
        Send notification to webhook endpoint.

        Args:
            markdown_content: The notification content in markdown format
        """
        if not self.enabled:
            return

        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "content": markdown_content,
                    "timestamp": datetime.now().isoformat()
                }
                response = await client.post(
                    self.webhook_url,
                    json=payload,
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()
                logger.debug(f"Webhook notification sent: {response.status_code}")

        except Exception as e:
            logger.error(f"Error sending webhook notification: {e}", exc_info=True)
```

**Register in `Notifier.__init__()` (in `notifier.py`):**

```python
# Initialize webhook notifier if configured
webhook_config = config.get("webhook", {})
if webhook_config.get("enabled", False):
    self.notifiers.append(WebhookNotifier(webhook_config))
```

**Configuration in `config.yaml`:**

```yaml
notifier:
  webhook:
    enabled: true
    webhook_url: "https://your-server.com/webhook"
    headers:
      Authorization: "Bearer your-token"
```

## Built-in Watchers

### IMAP Email Watcher

Monitors email accounts via IMAP with optional LLM-powered summarization.

**Features:**
- Multi-account support
- Automatic reconnection on errors
- LLM summarization for email content
- Duplicate detection

**Example configuration:**

```yaml
watchers:
  imap_watcher:
    enabled: true
    interval_seconds: 60
    watching:
      - server: "mail.example.com"
        enabled: true
        username: "user@example.com"
        password: "your-password"
        enable_summary: true
        summary:
          model_name: "gpt-4o-mini"
          prompt: "Summarize this email in one sentence."
```

### RSS Feed Watcher

Monitors RSS/Atom feeds with AI-powered content filtering.

**Features:**
- Multiple feed support
- LLM-based digest generation
- Duplicate entry detection
- First-run spam prevention

**Example configuration:**

```yaml
watchers:
  rss_watcher:
    enabled: true
    interval_seconds: 3600
    watching:
      - url: "https://example.com/feed.xml"
        name: "Example Blog"
        enabled: true
        enable_digest: true
        digest:
          model_name: "gpt-4o-mini"
          prompt: "Select the 3 most interesting articles."
```

### System Resource Watcher

Monitors CPU and RAM usage with configurable thresholds.

**Features:**
- Real-time resource monitoring
- Configurable alert thresholds
- Cooldown periods to prevent spam
- Detailed system metrics in alerts

**Example configuration:**

```yaml
watchers:
  system_watcher:
    enabled: true
    interval_seconds: 2
    cpu_threshold: 95
    ram_threshold: 95
    cooldown_seconds: 60
```

## Development Guidelines

### Project Principles

- **Async-first**: All I/O operations use asyncio
- **Type hints**: Function signatures include type information
- **Error handling**: Comprehensive try-catch with proper logging
- **Modular design**: Easy to extend and customize

### Logging

AWA uses [loguru](https://github.com/Delgan/loguru) for structured logging.

**File Logging**: All logs are written to `./logs/awa.log` with automatic rotation (10 MB) and 7-day retention with compression.

**Console Logging**: By default, console output is clean (only rich notifications). Use `python main.py --verbose` to enable detailed logging to console.

```bash
# Clean mode (default) - only notifications shown
python main.py

# Verbose mode - see all logs in console
python main.py --verbose
python main.py -v
```

