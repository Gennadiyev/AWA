
<img src="docs/awa.gif" alt="AWA Logo Animated" width="300" style="display: block; margin: auto;" />

AWA (AtomicWatcherAquarium) is a passive monitoring system that watches various sources (emails, RSS feeds, system resources) and pushes notifications through multiple channels.

With AWA, you can easily:

1. Build your own watchers to monitor processes, services, or data
2. Notify you via console, ntfy, or custom notifiers (e.g. webhooks)
3. Ask LLMs to curate your personal digest of updates wherever you want

## Highlights

**Hackable** - Simple plugin architecture. Drop a Python file in `watchers/` and it's automatically discovered. Write custom notifiers by inheriting from `BaseNotifier`.

**Asynchronous** - Built on asyncio from the ground up. All watchers run concurrently without blocking each other. Efficient I/O handling for monitoring multiple sources.

**Modular** - Clean separation of concerns. Notifiers, watchers, and LLM integrations are independent modules. Mix and match components as needed.

## Start Hacking!

```bash
pip install -e . && cp config.example.yaml config.yaml && python main.py
```

Edit `config.yaml` and `plugins/configs` to configure your watchers, plugins and notifiers, then run again. That's it! Happy hacking!

## Project Structure

```
AtomicWatcherAquarium/
├── main.py                  # Entry point, discovers and runs watchers
├── notifier.py                
├── watchers/                  
│   ├── imap_watcher.py      # Email monitoring
│   ├── rss_watcher.py       # RSS feed monitoring
│   └── ...                  # Your custom watchers here. Created watchers will automatically load upon next run!
├── plugins/
│   ├── llm.py                 
│   └── ...                  # Your plugins here
├── config.yaml              # Your configuration
└── config.example.yaml      # Configuration template
```

## Configuration

AWA uses a single `config.yaml` file. Here's a quick example:

```yaml
notifier:
  console:
    enabled: true
    enable_rich_markdown_formatting: true
  ntfy:
    enabled: true
    url: "http://127.0.0.1:23301"
    topic: "awa"

watchers:
  system_watcher:
    enabled: true
    interval_seconds: 2
    cpu_threshold: 95
    ram_threshold: 95
    cooldown_seconds: 60
```

See `config.example.yaml` for configuration options for built-in watchers and notifiers.
These options are passed to each watcher's `init()` function for custom behavior.

Additionally, plugins can have their own configuration sections under `plugins/configs`.
See `plugins/configs-examples/` for examples.

## Credits

Born from KunBot, which successfully monitored production systems before the QQ platform restrictions. AWA inherits KunBot's battle-tested, modular design with a fresh focus on extensibility to push notifications elegantly.

## License

MIT License - See LICENSE file for details

---

**Happy Monitoring!** If you build something cool with AWA, let us know!
