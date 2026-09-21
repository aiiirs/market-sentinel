# MarketSentinel

[English](README.md) | [简体中文](README.zh-CN.md)

MarketSentinel monitors the IOPV premium of selected China-listed ETFs during A-share trading sessions. It fetches ETF spot data through AKShare and sends Feishu (Lark) incoming-Webhook notifications when a configured premium threshold is met.

> **Disclaimer**
> This project is for information monitoring and technical experimentation only. It is not investment advice. Public market data may be delayed, incomplete, unavailable, or incorrect. Do not use this project for trading automation.

## What it does

For every polling round, MarketSentinel:

1. Checks whether the current time is within the Shanghai A-share continuous sessions (09:30–11:30 and 13:00–15:00, Asia/Shanghai) and is an SSE trading day.
2. Fetches selected ETF quotes from AKShare / Eastmoney.
3. Converts the upstream `基金折价率` field into this project's IOPV premium convention: positive means premium and negative means discount.
4. Sends a low-premium card when `premium_rate <= threshold` for an ETF.
5. Persists alert timestamps locally, so the same ETF will not be repeated during its cooldown period.
6. Sends a compact group summary at a separate configured interval.
7. Records retries and failures; after repeated source failures it sends a health alert if a health Webhook is configured.

Outside A-share trading sessions, the monitor stays alive but does not fetch quotes or send notifications.

## Notifications

| Type | When it is sent | Destination |
|---|---|---|
| Low-premium alert | An ETF's IOPV premium is less than or equal to its threshold and it is outside cooldown | Main Feishu Webhook |
| Premium summary | Every `summary_interval_seconds` during a valid trading session; use `0` to disable | Main Feishu Webhook |
| Health alert | The quote source fails for `failure_alert_after_rounds` consecutive rounds, or sending fails | `MARKET_SENTINEL_HEALTH_WEBHOOK`, otherwise main Webhook |

A group with one valid ETF displays one premium rate; a group with multiple ETFs displays a minimum-to-maximum range. The summary does not include prices, IOPV values, or individual ETF codes.

## Requirements

- Python 3.11 or later.
- A Feishu/Lark incoming Webhook bot.
- Network access to AKShare upstream data and Feishu/Lark.
- macOS is optional; only the included `launchd` template is macOS-specific.

## Quick start

```bash
git clone https://github.com/aiiirs/market-sentinel.git
cd market-sentinel
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.toml config.toml
cp .env.example .env
```

Then complete the two local files described below. Both are ignored by Git and must remain local.

Run one polling round without starting the long-running process:

```bash
./run_market_sentinel.sh --once
```

Run continuously:

```bash
./run_market_sentinel.sh
```

Stop it with `Ctrl+C` when running in the foreground.

## First-time configuration

### 1. Create a Feishu/Lark incoming Webhook bot

Create an incoming Webhook bot in the target Feishu/Lark chat. Copy its URL, but do not put it in source code, `config.toml`, screenshots, issues, or commits.

### 2. Set Webhook URLs in `.env`

Edit `.env` locally:

```bash
MARKET_SENTINEL_FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/replace-with-your-main-webhook
MARKET_SENTINEL_HEALTH_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/replace-with-your-health-webhook
```

`MARKET_SENTINEL_FEISHU_WEBHOOK` is required. `MARKET_SENTINEL_HEALTH_WEBHOOK` is optional but recommended: use a different bot/chat so a failure of the main notification Webhook can still be reported.

Protect this file:

```bash
chmod 600 .env config.toml
```

### 3. Define ETFs and thresholds in `config.toml`

The sample ETF is only a placeholder. Replace it with ETFs and thresholds appropriate for your own use.

```toml
[monitor]
summary_groups = ["US index ETFs", "Japan ETFs"]

[etfs."513500"]
name = "Example ETF"
threshold = 1.0
# Send an alert when its IOPV premium is <= 1.00%.
group = "US index ETFs"

[etfs."513800"]
name = "Another example ETF"
threshold = -2.0
# A negative threshold means alert only at a discount of 2% or more.
group = "Japan ETFs"
```

`threshold` is a percentage, not a decimal fraction: use `1.0` for 1%, `0.5` for 0.5%, and `-2.0` for -2%.

## Complete configuration reference

### `[monitor]`

| Key | Default | Meaning |
|---|---:|---|
| `poll_seconds` | `300` | Seconds between quote polling rounds during trading sessions. |
| `cooldown_seconds` | `1800` | Minimum seconds between low-premium alerts for the same ETF. |
| `summary_interval_seconds` | `1800` | Seconds between periodic summaries. Set `0` to disable summaries. |
| `summary_groups` | `[...]` | Group names, in display order, included in summary cards. ETFs in other groups can still alert but are omitted from summaries. |
| `health_cooldown_seconds` | `3600` | Minimum seconds between identical health alerts. |
| `failure_alert_after_rounds` | `3` | Consecutive full-source failures before a health alert is attempted. |
| `random_delay_min_seconds` | `1` | Minimum random delay before a quote request. |
| `random_delay_max_seconds` | `5` | Maximum random delay before a quote request. |
| `max_retries` | `3` | Maximum attempts for a failed quote or Webhook request. |
| `retry_delay_seconds` | `2` | Base delay between retries. |
| `request_timeout_seconds` | `15` | Timeout per HTTP request. |
| `state_file` | `data/state.json` | Local JSON state for alert cooldowns and summary timestamps. Do not commit it. |
| `log_file` | `logs/market_sentinel.log` | Local log file path. Do not commit logs. |

### `[calendar]`

| Key | Default | Meaning |
|---|---|---|
| `exchange` | `XSHG` | Exchange calendar used to decide whether a day is an A-share trading day. |

### `[feishu]`

| Key | Meaning |
|---|---|
| `webhook_env` | Name of the required environment variable that holds the main Webhook URL. |
| `health_webhook_env` | Name of the optional environment variable that holds the health-alert Webhook URL. Leave it empty to use the main Webhook for health alerts. |

### `[etfs."<six-digit-code>"]`

Create one table for each ETF you want to monitor.

| Key | Meaning |
|---|---|
| `name` | Display name used in notification cards. |
| `threshold` | Alert condition in percent. An alert is sent when `premium_rate <= threshold`. |
| `group` | Logical group name. Add it to `summary_groups` to include it in periodic summaries. |

## US market-temperature daily report

The independent us_market_temperature.py task turns Nasdaq-100, S&P 500, VIX, VXN and best-effort CNN Fear & Greed data into one Feishu Markdown card. It is separate from ETF-premium monitoring and has its own configuration and restart-safe send state.

Copy temperature.example.toml to temperature.toml and set the daily-report Webhook in .env:

    US_MARKET_TEMPERATURE_FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/replace-with-your-webhook

The report defaults to Singapore time 09:00. It sends only after a new US stock-market close and will not send the same close twice after a restart. Use the runner to preview without sending or to run continuously:

    ./run_us_market_temperature.sh --preview
    ./run_us_market_temperature.sh

The report includes daily index changes, the last completed configured drawdown cycle, distance from that cycle peak and the historical high, volatility stages and low-point emotion context. The threshold is configurable in temperature.toml: S&P 500 defaults to 8 percent, Nasdaq-100 to 10 percent. A positive current-vs-previous-peak value means the index is already above that earlier peak.

The first public version intentionally does not show PE. Free public PE data has inconsistent methodology, timing and availability, so it would give a misleading impression of precision. CNN Fear & Greed is optional: an unavailable endpoint is marked unavailable and never replaced with old data.

## macOS auto-start

The repository includes `launchd/com.marketsentinel.monitor.plist.example`.

1. Replace every `__PROJECT_DIR__` in the file with the absolute path to your clone.
2. Save it as `~/Library/LaunchAgents/com.marketsentinel.monitor.plist`.
3. Load it:

```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.marketsentinel.monitor.plist
launchctl kickstart -k "gui/$(id -u)/com.marketsentinel.monitor"
```

View the service:

```bash
launchctl print "gui/$(id -u)/com.marketsentinel.monitor"
```

Stop and remove it:

```bash
launchctl bootout "gui/$(id -u)/com.marketsentinel.monitor"
```

## Logs and troubleshooting

| Symptom | Check |
|---|---|
| No notification | Confirm it is an A-share trading day and within 09:30–11:30 or 13:00–15:00 Beijing time; check the threshold and cooldown. |
| Configuration error | Confirm `.env` exists, required Webhook variables are non-empty, and `config.toml` is valid TOML. |
| Quote request failure | Check network access and the log file; upstream AKShare/Eastmoney data can time out or change. |
| Webhook failure | Confirm the bot has not been deleted and the URL is valid. Rotate the bot immediately if its URL was exposed. |
| Duplicate alerts | Do not delete `state_file`; it records cooldown and summary state across restarts. |

## Development

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Security

Webhook URLs are secrets. Read [SECURITY.md](SECURITY.md) before reporting security issues or publishing configuration files.

## Data source

The monitor uses [AKShare](https://github.com/akfamily/akshare), which depends on publicly available upstream market data. Verify upstream terms and data suitability for your own use.

## License

MIT. See [LICENSE](LICENSE).
