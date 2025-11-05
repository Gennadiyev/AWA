"""
System Watcher - Monitors CPU and RAM usage
Sends notifications when usage exceeds thresholds
"""

import asyncio
import time
from typing import Any, Coroutine, Optional

import psutil
from loguru import logger

from notifier import Notifier


# Default configuration values
DEFAULT_INTERVAL_SECONDS = 2
DEFAULT_CPU_THRESHOLD = 95
DEFAULT_RAM_THRESHOLD = 95
DEFAULT_COOLDOWN_SECONDS = 60
STATUS_LOG_INTERVAL_TICKS = (
    150  # Log status every 150 ticks (5 minutes at 2s intervals)
)


class SystemMonitor:
    """Monitors system resources and sends alerts when thresholds are exceeded."""

    def __init__(self, notifier: Notifier, config: dict):
        """
        Initialize the system monitor.

        Args:
            notifier: Notifier instance for sending alerts
            config: Configuration dictionary for the system watcher
        """
        self.notifier = notifier
        self.config = config

        # Load configuration with defaults
        self.interval = config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)
        self.cpu_threshold = config.get("cpu_threshold", DEFAULT_CPU_THRESHOLD)
        self.ram_threshold = config.get("ram_threshold", DEFAULT_RAM_THRESHOLD)
        self.cooldown = config.get("cooldown_seconds", DEFAULT_COOLDOWN_SECONDS)

        # Cooldown tracking
        self.last_cpu_alert_time = 0.0
        self.last_ram_alert_time = 0.0

        # Tick counter for periodic logging
        self.tick_count = 0

    async def initialize_cpu_monitoring(self) -> None:
        """Initialize CPU monitoring (first call returns 0.0, need baseline)."""
        psutil.cpu_percent(interval=None)
        await asyncio.sleep(0.1)

    def get_system_metrics(self) -> tuple[float, float, Any]:
        """
        Get current system metrics.

        Returns:
            Tuple of (cpu_percent, ram_percent, memory_info)
        """
        cpu_percent = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        ram_percent = memory.percent
        return cpu_percent, ram_percent, memory

    def should_send_alert(self, last_alert_time: float) -> bool:
        """
        Check if enough time has passed since the last alert.

        Args:
            last_alert_time: Timestamp of the last alert

        Returns:
            True if cooldown period has elapsed
        """
        current_time = time.time()
        return (current_time - last_alert_time) > self.cooldown

    async def send_cpu_alert(self, cpu_percent: float) -> None:
        """
        Send CPU usage alert notification.

        Args:
            cpu_percent: Current CPU usage percentage
        """
        logger.warning(f"CPU usage high: {cpu_percent:.1f}%")
        markdown_content = f"""# ⚠️ High CPU Usage

**Current Usage:** {cpu_percent:.1f}%
**Threshold:** {self.cpu_threshold}%

CPU usage has exceeded the configured threshold.
"""
        await self.notifier.send(markdown_content)
        self.last_cpu_alert_time = time.time()

    async def send_ram_alert(
        self, ram_percent: float, memory: Any
    ) -> None:
        """
        Send RAM usage alert notification.

        Args:
            ram_percent: Current RAM usage percentage
            memory: Memory information object from psutil
        """
        logger.warning(f"RAM usage high: {ram_percent:.1f}%")

        # Convert memory stats to GB for readability
        total_gb = memory.total / (1024**3)
        used_gb = memory.used / (1024**3)
        available_gb = memory.available / (1024**3)

        markdown_content = f"""# ⚠️ High RAM Usage

**Current Usage:** {ram_percent:.1f}%
**Threshold:** {self.ram_threshold}%

**Used:** {used_gb:.2f} GB / {total_gb:.2f} GB
**Available:** {available_gb:.2f} GB

RAM usage has exceeded the configured threshold.
"""
        await self.notifier.send(markdown_content)
        self.last_ram_alert_time = time.time()

    def log_periodic_status(self, cpu_percent: float, ram_percent: float) -> None:
        """
        Log system status periodically at DEBUG level to avoid log file spam.

        Args:
            cpu_percent: Current CPU usage percentage
            ram_percent: Current RAM usage percentage
        """
        self.tick_count += 1
        if self.tick_count % STATUS_LOG_INTERVAL_TICKS == 0:
            logger.debug(
                f"System status | CPU: {cpu_percent:.1f}% | RAM: {ram_percent:.1f}%"
            )

    async def monitor_loop(self) -> None:
        """Main monitoring loop that checks system resources and sends alerts."""
        logger.info(
            f"Starting system watcher | "
            f"Interval: {self.interval}s | "
            f"CPU threshold: {self.cpu_threshold}% | "
            f"RAM threshold: {self.ram_threshold}% | "
            f"Cooldown: {self.cooldown}s"
        )

        # Initialize CPU monitoring
        await self.initialize_cpu_monitoring()

        while True:
            try:
                # Get current system metrics
                cpu_percent, ram_percent, memory = self.get_system_metrics()

                # Log status periodically (console only)
                self.log_periodic_status(cpu_percent, ram_percent)

                # Check CPU threshold and send alert if needed
                if cpu_percent > self.cpu_threshold:
                    if self.should_send_alert(self.last_cpu_alert_time):
                        await self.send_cpu_alert(cpu_percent)

                # Check RAM threshold and send alert if needed
                if ram_percent > self.ram_threshold:
                    if self.should_send_alert(self.last_ram_alert_time):
                        await self.send_ram_alert(ram_percent, memory)

                await asyncio.sleep(self.interval)

            except asyncio.CancelledError:
                logger.info("System watcher cancelled")
                break
            except Exception as e:
                logger.error(f"Error in system watcher: {e}", exc_info=True)
                await asyncio.sleep(self.interval)

        logger.info("System watcher stopped")


async def watch_system(notifier: Notifier, config: dict) -> None:
    """
    Monitor system CPU and RAM usage.

    Args:
        notifier: Notifier instance for sending alerts
        config: Configuration dictionary for system watcher
    """
    monitor = SystemMonitor(notifier, config)
    await monitor.monitor_loop()


def init(notifier: Notifier, config: dict) -> Optional[Coroutine[Any, Any, None]]:
    """
    Initialize the system watcher.

    Args:
        notifier: Notifier instance for sending notifications
        config: Configuration dictionary for this watcher

    Returns:
        Async coroutine or None if disabled
    """
    if not config:
        logger.info("System watcher is not configured")
        return None

    if not config.get("enabled", False):
        logger.info("System watcher is disabled")
        return None

    return watch_system(notifier, config)
