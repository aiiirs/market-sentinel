# MarketSentinel

MarketSentinel monitors IOPV premiums for selected China-listed ETFs during A-share trading sessions and sends Feishu (Lark) webhook notifications when configured thresholds are met. It can also send periodic premium summaries and health alerts.

> **Disclaimer**
> This project is for information monitoring and technical experimentation only. It is not investment advice. Market data may be delayed, incomplete, or incorrect.

## Features

- Configurable ETF codes, groups, premium thresholds, polling intervals, and cooldowns.
- IOPV premium calculation using AKShare ETF spot data.
- Feishu/Lark interactive-card notifications through incoming Webhooks.
- Periodic group summaries and separate health-alert Webhook support.
- A-share trading-session and exchange-calendar checks.
- Persistent local cooldown state, retries, logs, and unit tests.

## Quick start

```bash
git clone <your-repository-url>
cd MarketSentinel
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.toml config.toml
cp .env.example .env
```

Edit `config.toml` to define your ETFs and thresholds. Edit `.env` locally and set your Feishu Webhook URLs. Do not commit either file.

Run one polling round:

```bash
./run_market_sentinel.sh --once
```

Run continuously:

```bash
./run_market_sentinel.sh
```

## Configuration

`config.toml` controls monitoring behavior. Webhook URLs are read from environment variables named in `[feishu]`. The included `.env.example` uses:

```bash
MARKET_SENTINEL_FEISHU_WEBHOOK=
MARKET_SENTINEL_HEALTH_WEBHOOK=
```

Use a separate health-alert Webhook if possible: the main Webhook cannot reliably report its own outage.

## macOS auto-start

See `launchd/com.marketsentinel.monitor.plist.example`. Replace every `__PROJECT_DIR__` placeholder with the absolute path to your clone, then load it with `launchctl`.

## Development

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Security

Webhook URLs are secrets. Review [SECURITY.md](SECURITY.md) before reporting security issues or publishing a configuration.

## Data source

The monitor uses [AKShare](https://github.com/akfamily/akshare) and therefore depends on publicly available upstream market data. Verify upstream terms and data suitability for your own use.

## License

MIT. See [LICENSE](LICENSE).
