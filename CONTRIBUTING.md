# Contributing to AtomicWatcherAquarium

Thank you for your interest in contributing to AtomicWatcherAquarium (AWA)! We welcome contributions from the community.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/atomic-watcher-aquarium.git`
3. Install dependencies: `pip install -e .`
4. Copy the example config: `cp config.example.yaml config.yaml`
5. Make your changes
6. Test your changes thoroughly

## Branch Naming Convention

To keep the repository organized, please follow these branch naming conventions:

- **Bug fixes/Patches**: `<your_name>-fix-<patch_name>`
  - Example: `john-fix-imap-reconnect`
  - Example: `alice-fix-notification-timeout`

- **New Watchers**: `<your_name>-watcher-<watcher_name>`
  - Example: `bob-watcher-telegram`
  - Example: `sarah-watcher-github`

- **New Notifiers**: `<your_name>-notifier-<notifier_name>`
  - Example: `jane-notifier-webhook`
  - Example: `mike-notifier-discord`

- **New Plugins**: `<your_name>-plugin-<plugin_name>`
  - Example: `alex-plugin-sentiment-analysis`
  - Example: `chris-plugin-translation`

- **Features/Enhancements**: `<your_name>-feature-<feature_name>`
  - Example: `emily-feature-config-validation`
  - Example: `david-feature-metrics-dashboard`

- **Documentation**: `<your_name>-docs-<doc_topic>`
  - Example: `tom-docs-deployment-guide`
  - Example: `lisa-docs-api-reference`

## Development Guidelines

### Code Style

- Follow PEP 8 style guidelines
- Use type hints where appropriate
- Write descriptive docstrings for functions and classes
- Keep functions focused and modular

### Async Best Practices

- All I/O operations should be async
- Use `asyncio.to_thread()` for blocking operations
- Handle `asyncio.CancelledError` for graceful shutdown
- Avoid blocking calls in async functions

### Adding a New Watcher

1. Create a new file in `watchers/` directory (e.g., `watchers/my_watcher.py`)
2. Implement the `init(notifier, config)` function that returns a coroutine or None
3. Add configuration example to `config.example.yaml`
4. Update README.md with documentation for your watcher
5. Test thoroughly with various configurations

Example watcher structure:
```python
from typing import Optional, Coroutine, Any
from loguru import logger
from notifier import Notifier

async def watch_something(notifier: Notifier, config: dict) -> None:
    """Main watcher loop"""
    # Your implementation here
    pass

def init(notifier: Notifier, config: Dict) -> Optional[Coroutine[Any, Any, None]]:
    """Initialize the watcher"""
    if not config or not config.get("enabled", False):
        logger.info("My watcher is disabled")
        return None
    return watch_something(notifier, config)
```

### Adding a New Notifier

1. Create a class that inherits from `BaseNotifier` in `notifier.py`
2. Implement the `send(markdown_content)` async method
3. Register the notifier in `Notifier.__init__()`
4. Add configuration example to `config.example.yaml`
5. Update README.md with documentation

Example notifier structure:
```python
class MyNotifier(BaseNotifier):
    """My custom notifier"""

    def __init__(self, config: dict):
        super().__init__(config)
        # Your initialization here

    async def send(self, markdown_content: str) -> None:
        """Send notification"""
        if not self.enabled:
            return
        # Your implementation here
```

### Adding a New Plugin

1. Create a new file in `plugins/` directory (e.g., `plugins/my_plugin.py`)
2. Implement clear async interfaces
3. Add any required configuration to `config.example.yaml`
4. Document usage in README.md or plugin docstrings
5. Handle errors gracefully

### Testing

- Test your changes with real configurations
- Verify error handling works correctly
- Check that logging is informative and appropriate
- Ensure graceful shutdown (Ctrl+C) works properly
- Test with both minimal and complex configurations

## Pull Request Process

1. Create a new branch following the naming convention above
2. Commit your changes with clear, descriptive messages
   - Use present tense: "Add feature" not "Added feature"
   - Reference issue numbers when applicable: "Fix #123"
3. Push to your fork: `git push origin <branch-name>`
4. Open a Pull Request with:
   - Clear description of changes
   - Why the changes are needed
   - Any relevant issue numbers
   - Testing performed
   - Screenshots/logs if applicable

### PR Title Format

- `[Watcher] Add <name> watcher`
- `[Notifier] Add <name> notifier`
- `[Fix] Fix <issue description>`
- `[Feature] Add <feature description>`
- `[Docs] Update <documentation topic>`

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers and help them learn
- Focus on constructive feedback
- Keep discussions professional and on-topic

## Reporting Issues

When reporting issues, please include:
- AWA version
- Python version
- Operating system
- Configuration (redact sensitive info)
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs

## Questions?

If you have questions or need help, feel free to:
- Open an issue for discussion
- Ask in your pull request
- Check existing issues and discussions

Thank you for contributing to AWA!
