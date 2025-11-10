"""
AtomicWatcherAquarium (AWA) - Hackable, asynchronous, modular monitoring system
Entry point that discovers and runs all watchers
"""

import argparse
import asyncio
import importlib
import os
import re
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger

from notifier import Notifier


def expand_env_vars(config):
    """
    Recursively expand environment variables in config.
    Supports ${VAR_NAME} and ${VAR_NAME:-default_value} syntax.

    Args:
        config: Configuration dictionary, list, or string value

    Returns:
        Configuration with environment variables expanded
    """
    if isinstance(config, dict):
        return {key: expand_env_vars(value) for key, value in config.items()}
    elif isinstance(config, list):
        return [expand_env_vars(item) for item in config]
    elif isinstance(config, str):
        # Pattern to match ${VAR_NAME} or ${VAR_NAME:-default_value}
        pattern = r"\$\{([^}:]+)(?::-(.*?))?\}"

        def replace_env_var(match):
            var_name = match.group(1)
            default_value = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default_value)

        return re.sub(pattern, replace_env_var, config)
    else:
        return config


# Setup loguru logging
def setup_logging(enable_console_logging: bool = False):
    """
    Setup logging configuration.

    Args:
        enable_console_logging: If True, logs will be written to console.
                               If False, only file logging is enabled for cleaner UX.
    """
    logger.remove()  # Remove default handler

    # Add console logging only if enabled
    if enable_console_logging:
        logger.add(
            sys.stdout,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
            colorize=True,
        )

    # Ensure logs directory exists
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Always log to file
    logger.add(
        logs_dir / "awa.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="INFO",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
    )


async def discover_watchers():
    """Dynamically discover and load all watcher modules from watchers/ directory"""
    watchers_dir = Path(__file__).parent / "watchers"
    watcher_modules = []

    if not watchers_dir.exists():
        logger.error(f"Watchers directory not found: {watchers_dir}")
        return watcher_modules

    for file in watchers_dir.glob("*.py"):
        if file.name.startswith("_"):
            continue

        module_name = f"watchers.{file.stem}"
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "init"):
                watcher_modules.append(module)
                logger.info(f"Discovered watcher: {module_name}")
            else:
                logger.warning(f"Module {module_name} has no init() function")
        except Exception as e:
            logger.error(f"Failed to load watcher {module_name}: {e}", exc_info=True)

    return watcher_modules


async def main(verbose: bool = False, config_file: str = "config.yaml"):
    """Main entry point"""
    # Load .env file from the project root directory
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.debug(f"Loaded environment variables from {env_path}")

    # Setup logging based on verbose flag
    setup_logging(enable_console_logging=verbose)

    # Load configuration
    config_path = (
        Path(config_file)
        if Path(config_file).is_absolute()
        else Path(__file__).parent / config_file
    )
    if not config_path.exists():
        logger.error(
            f"{config_file} not found! Please create it from config.example.yaml"
        )
        sys.exit(1)

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        # Expand environment variables in the config
        config = expand_env_vars(config)
    except Exception as e:
        logger.error(f"Failed to load {config_file}: {e}")
        sys.exit(1)

    logger.info("AtomicWatcherAquarium starting")

    # Initialize notifier
    notifier_config = config.get("notifier", {})
    notifier = Notifier(notifier_config)

    # Discover and initialize watchers
    watcher_modules = await discover_watchers()

    if not watcher_modules:
        logger.warning("No watchers found!")
        return

    # Initialize all watchers and collect their tasks
    tasks: list[asyncio.Task] = []
    watchers_config = config.get("watchers", {})

    for module in watcher_modules:
        try:
            # Extract module name from "watchers.module_name" -> "module_name"
            module_name = module.__name__.split(".")[-1]

            # Get the specific config for this watcher module
            # This allows watchers/imap_watcher.py to use config key "imap_watcher"
            watcher_config = watchers_config.get(module_name, {})

            # Pass only this watcher's config directly to its init function
            coro = module.init(notifier, watcher_config)
            if coro:
                task_obj = asyncio.create_task(coro, name=f"watcher_{module_name}")
                tasks.append(task_obj)
                logger.info(f"Started watcher: {module_name}")
        except Exception as e:
            logger.error(f"Failed to initialize {module.__name__}: {e}", exc_info=True)

    if not tasks:
        logger.error("No watcher tasks started!")
        return

    logger.info(f"Running {len(tasks)} watcher(s)...")
    logger.info("Press Ctrl+C to stop...")

    # Send startup notification
    active_watchers = [t.get_name().replace("watcher_", "") for t in tasks]
    startup_markdown = """# 🚀 AtomicWatcherAquarium Started!

System initialized successfully!

## Active Watchers

""" + "\n".join(f"- `{name}`" for name in active_watchers)

    await notifier.send(startup_markdown)
    logger.info("Startup notification sent")

    # Run all tasks and handle graceful shutdown
    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("Shutdown signal received, stopping watchers...")
    finally:
        # Cancel all tasks
        for task in tasks:
            if not task.done():
                task.cancel()

        # Wait for all tasks to complete cancellation
        await asyncio.gather(*tasks, return_exceptions=True)

        # Clean up notifier
        await notifier.close()

        logger.info("All watchers stopped. AWA terminated.")


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="AtomicWatcherAquarium - Hackable, asynchronous, modular monitoring system"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose console logging (logs also go to ./logs/awa.log)",
    )
    parser.add_argument(
        "--config_file",
        "-c",
        type=str,
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(main(verbose=args.verbose, config_file=args.config_file))
    except KeyboardInterrupt:
        logger.info("AWA terminated by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
