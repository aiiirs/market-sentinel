#!/usr/bin/env python3
"""Monitor A-share QDII ETF IOPV premiums and notify a Feishu bot.

Run with: python3 market_sentinel.py --config config.toml
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 is unsupported.
    import tomli as tomllib


SHANGHAI = ZoneInfo("Asia/Shanghai")
LOGGER = logging.getLogger("market_sentinel")


class ConfigurationError(ValueError):
    """Raised for unsafe or incomplete configuration."""


@dataclass(frozen=True)
class EtfConfig:
    code: str
    name: str
    threshold: float
    group: str


@dataclass(frozen=True)
class AppConfig:
    etfs: dict[str, EtfConfig]
    poll_seconds: int
    cooldown_seconds: int
    summary_interval_seconds: int
    summary_groups: tuple[str, ...]
    health_cooldown_seconds: int
    failure_alert_after_rounds: int
    random_delay_min_seconds: float
    random_delay_max_seconds: float
    max_retries: int
    retry_delay_seconds: float
    request_timeout_seconds: float
    state_file: Path
    log_file: Path
    webhook_url: str
    health_webhook_url: str | None
    exchange_calendar: str


@dataclass(frozen=True)
class Quote:
    code: str
    name: str
    price: float
    iopv: float
    premium_rate: float


def _required(mapping: Mapping[str, Any], key: str) -> Any:
    value = mapping.get(key)
    if value is None or value == "":
        raise ConfigurationError(f"Missing configuration value: {key}")
    return value


def _env_value(env_name: str, required: bool = True) -> str | None:
    value = os.getenv(env_name, "").strip()
    if not value and required:
        raise ConfigurationError(f"Environment variable {env_name} is not set")
    return value or None


def load_config(path: Path) -> AppConfig:
    """Load configuration while keeping webhook secrets in environment variables."""
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)

    monitor = _required(raw, "monitor")
    feishu = _required(raw, "feishu")
    calendar = raw.get("calendar", {})
    raw_etfs = _required(raw, "etfs")
    if not isinstance(raw_etfs, dict) or not raw_etfs:
        raise ConfigurationError("At least one ETF must be configured")

    etfs: dict[str, EtfConfig] = {}
    for code, item in raw_etfs.items():
        normalized_code = str(code).zfill(6)
        threshold = float(_required(item, "threshold"))
        etfs[normalized_code] = EtfConfig(
            code=normalized_code,
            name=str(_required(item, "name")),
            threshold=threshold,
            group=str(item.get("group", "其他")),
        )

    delay_min = float(_required(monitor, "random_delay_min_seconds"))
    delay_max = float(_required(monitor, "random_delay_max_seconds"))
    if delay_min < 0 or delay_max < delay_min:
        raise ConfigurationError("Invalid random delay range")
    summary_interval_seconds = int(_required(monitor, "summary_interval_seconds"))
    if summary_interval_seconds < 0:
        raise ConfigurationError("summary_interval_seconds cannot be negative")
    raw_summary_groups = monitor.get("summary_groups", [])
    if not isinstance(raw_summary_groups, list) or not all(isinstance(group, str) and group for group in raw_summary_groups):
        raise ConfigurationError("summary_groups must be a list of non-empty group names")

    webhook_env = str(_required(feishu, "webhook_env"))
    health_webhook_env = str(feishu.get("health_webhook_env", "")).strip()
    return AppConfig(
        etfs=etfs,
        poll_seconds=int(_required(monitor, "poll_seconds")),
        cooldown_seconds=int(_required(monitor, "cooldown_seconds")),
        summary_interval_seconds=summary_interval_seconds,
        summary_groups=tuple(raw_summary_groups),
        health_cooldown_seconds=int(_required(monitor, "health_cooldown_seconds")),
        failure_alert_after_rounds=int(_required(monitor, "failure_alert_after_rounds")),
        random_delay_min_seconds=delay_min,
        random_delay_max_seconds=delay_max,
        max_retries=int(_required(monitor, "max_retries")),
        retry_delay_seconds=float(_required(monitor, "retry_delay_seconds")),
        request_timeout_seconds=float(_required(monitor, "request_timeout_seconds")),
        state_file=Path(str(_required(monitor, "state_file"))).expanduser(),
        log_file=Path(str(_required(monitor, "log_file"))).expanduser(),
        webhook_url=str(_env_value(webhook_env)),
        health_webhook_url=_env_value(health_webhook_env, required=False)
        if health_webhook_env
        else None,
        exchange_calendar=str(calendar.get("exchange", "XSHG")),
    )


def configure_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file, encoding="utf-8")],
    )


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN is not a usable quote.


def premium_rate_from_values(price: float, iopv: float, discount_rate: float | None) -> float:
    """Return premium rate in percent.

    AKShare labels its field ``基金折价率``: a positive number means a discount,
    so it has the opposite sign to this application's IOPV premium rate.
    """
    return -discount_rate if discount_rate is not None else (price - iopv) / iopv * 100


def is_trading_day(now: datetime, exchange: str) -> bool:
    """Return whether *now* falls on a published session of the exchange."""
    import exchange_calendars as xcals

    calendar = xcals.get_calendar(exchange)
    return bool(calendar.is_session(now.date()))


def is_trading_time(now: datetime) -> bool:
    """Return whether Shanghai local time falls in an A-share continuous session."""
    local_time = now.astimezone(SHANGHAI).time()
    return (clock_time(9, 30) <= local_time < clock_time(11, 30)) or (
        clock_time(13, 0) <= local_time < clock_time(15, 0)
    )


def should_poll(now: datetime, exchange: str) -> bool:
    return is_trading_time(now) and is_trading_day(now.astimezone(SHANGHAI), exchange)


class StateStore:
    """Small JSON state store that survives process restarts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {"etf_alerts": {}, "health_alerts": {}, "source_failure_rounds": 0}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.data.update(data)
        except (OSError, json.JSONDecodeError) as error:
            LOGGER.warning("Unable to load state file %s: %s", self.path, error)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary_path.replace(self.path)

    def in_cooldown(self, category: str, key: str, cooldown_seconds: int, now: datetime) -> bool:
        raw_timestamp = self.data.get(category, {}).get(key)
        if not raw_timestamp:
            return False
        try:
            previous = datetime.fromisoformat(raw_timestamp)
        except ValueError:
            return False
        return now - previous < timedelta(seconds=cooldown_seconds)

    def mark_sent(self, category: str, key: str, now: datetime) -> None:
        self.data.setdefault(category, {})[key] = now.isoformat()
        self.save()


def request_with_retry(
    operation: Callable[[], Any], config: AppConfig, description: str
) -> Any:
    """Run an external request with jitter, bounded retries and clear logging."""
    last_error: Exception | None = None
    for attempt in range(1, config.max_retries + 1):
        time.sleep(random.uniform(config.random_delay_min_seconds, config.random_delay_max_seconds))
        try:
            return operation()
        except Exception as error:  # Network and upstream-library exceptions vary by provider.
            last_error = error
            LOGGER.warning("%s failed (%s/%s): %s", description, attempt, config.max_retries, error)
            if attempt < config.max_retries:
                time.sleep(config.retry_delay_seconds * attempt)
    raise RuntimeError(f"{description} failed after {config.max_retries} attempts") from last_error


def fetch_quotes(config: AppConfig) -> dict[str, Quote]:
    """Fetch all ETF quotes once, then retain only the configured ETF codes."""
    def fetch() -> Any:
        import akshare as ak

        return ak.fund_etf_spot_em()

    dataframe = request_with_retry(fetch, config, "AKShare ETF quote request")
    required_columns = {"代码", "最新价", "IOPV实时估值"}
    missing = required_columns.difference(dataframe.columns)
    if missing:
        raise RuntimeError(f"AKShare response is missing required columns: {sorted(missing)}")

    rows = dataframe[dataframe["代码"].astype(str).str.zfill(6).isin(config.etfs)]
    quotes: dict[str, Quote] = {}
    for _, row in rows.iterrows():
        code = str(row["代码"]).zfill(6)
        price = _as_float(row["最新价"])
        iopv = _as_float(row["IOPV实时估值"])
        direct_rate = _as_float(row.get("基金折价率"))
        if price is None or iopv is None or price <= 0 or iopv <= 0:
            LOGGER.warning("Skipping %s because latest price or IOPV is invalid", code)
            continue
        premium_rate = premium_rate_from_values(price, iopv, direct_rate)
        quotes[code] = Quote(
            code=code,
            name=config.etfs[code].name,
            price=price,
            iopv=iopv,
            premium_rate=premium_rate,
        )
    return quotes


def _card(title: str, lines: list[str], color: str) -> dict[str, Any]:
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title}, "template": color},
            "elements": [{"tag": "markdown", "content": "\n".join(lines)}],
        },
    }


def low_premium_card(quote: Quote, threshold: float, now: datetime) -> dict[str, Any]:
    return _card(
        "QDII ETF 低溢价提醒",
        [
            f"**ETF：** {quote.name}（`{quote.code}`）",
            f"**当前价格：** {quote.price:.4f}",
            f"**IOPV：** {quote.iopv:.4f}",
            f"**当前溢价率：** {quote.premium_rate:.2f}%",
            f"**触发阈值：** ≤ {threshold:.2f}%",
            f"**触发时间：** {now.astimezone(SHANGHAI):%Y-%m-%d %H:%M:%S}（北京时间）",
        ],
        "orange",
    )


def health_card(kind: str, details: str, now: datetime) -> dict[str, Any]:
    return _card(
        "MarketSentinel 健康告警",
        [
            f"**类型：** {kind}",
            f"**详情：** {details}",
            f"**时间：** {now.astimezone(SHANGHAI):%Y-%m-%d %H:%M:%S}（北京时间）",
        ],
        "red",
    )


def summary_card(quotes: Mapping[str, Quote], config: AppConfig, now: datetime) -> dict[str, Any]:
    """Build a compact group-range card without individual ETF details."""
    grouped_rates: dict[str, list[float]] = {group: [] for group in config.summary_groups}
    grouped_thresholds: dict[str, set[float]] = {group: set() for group in config.summary_groups}
    for etf in config.etfs.values():
        if etf.group in grouped_thresholds:
            grouped_thresholds[etf.group].add(etf.threshold)
    for code, quote in quotes.items():
        group = config.etfs[code].group
        if group in grouped_rates:
            grouped_rates[group].append(quote.premium_rate)

    lines = ["**本轮实时溢价范围：**"]
    for group in config.summary_groups:
        rates = grouped_rates[group]
        thresholds = sorted(grouped_thresholds[group])
        threshold_text = (
            f"≤ {thresholds[0]:.2f}%"
            if len(thresholds) == 1
            else f"≤ {thresholds[0]:.2f}% 至 {thresholds[-1]:.2f}%"
            if thresholds
            else "未配置"
        )
        if len(rates) == 1:
            lines.append(f"- **{group} 溢价：** {rates[0]:+.2f}%｜**告警阈值：** {threshold_text}")
        elif rates:
            lines.append(
                f"- **{group}：** {min(rates):+.2f}% 至 {max(rates):+.2f}%｜"
                f"**告警阈值：** {threshold_text}"
            )
        else:
            lines.append(f"- **{group}：** 暂无有效行情｜**告警阈值：** {threshold_text}")
    lines.append(f"**更新时间：** {now.astimezone(SHANGHAI):%Y-%m-%d %H:%M:%S}（北京时间）")
    return _card("MarketSentinel · ETF 实时溢价汇总", lines, "blue")


def send_card(url: str, card: dict[str, Any], config: AppConfig) -> None:
    # Keep imports lazy so local configuration and unit tests can run before
    # production dependencies have been installed.
    import requests

    def post() -> None:
        response = requests.post(url, json=card, timeout=config.request_timeout_seconds)
        response.raise_for_status()
        body = response.json()
        if body.get("code", 0) != 0:
            raise RuntimeError(f"Feishu rejected message: {body}")

    request_with_retry(post, config, "Feishu webhook request")


class Monitor:
    def __init__(self, config: AppConfig, state: StateStore) -> None:
        self.config = config
        self.state = state

    def _send_health_alert(self, key: str, details: str, now: datetime) -> None:
        if self.state.in_cooldown("health_alerts", key, self.config.health_cooldown_seconds, now):
            return
        webhook = self.config.health_webhook_url or self.config.webhook_url
        try:
            send_card(webhook, health_card(key, details, now), self.config)
        except Exception as error:
            LOGGER.error("Unable to send health alert (%s): %s", key, error)
            return
        self.state.mark_sent("health_alerts", key, now)

    def _send_summary(self, quotes: Mapping[str, Quote], now: datetime) -> None:
        interval = self.config.summary_interval_seconds
        if interval == 0 or self.state.in_cooldown("summary_alerts", "all", interval, now):
            return
        try:
            send_card(self.config.webhook_url, summary_card(quotes, self.config, now), self.config)
        except Exception as error:
            LOGGER.error("Unable to send ETF premium summary: %s", error)
            self._send_health_alert("飞书推送异常", f"实时溢价汇总发送失败：{error}", now)
            return
        self.state.mark_sent("summary_alerts", "all", now)
        LOGGER.info("ETF premium summary sent for %s quotes", len(quotes))

    def run_once(self, now: datetime | None = None) -> None:
        now = now or datetime.now(SHANGHAI)
        try:
            quotes = fetch_quotes(self.config)
        except Exception as error:
            failures = int(self.state.data.get("source_failure_rounds", 0)) + 1
            self.state.data["source_failure_rounds"] = failures
            self.state.save()
            LOGGER.error("ETF quote round failed (%s consecutive rounds): %s", failures, error)
            if failures >= self.config.failure_alert_after_rounds:
                self._send_health_alert("数据源异常", f"连续失败 {failures} 轮：{error}", now)
            return

        if self.state.data.get("source_failure_rounds", 0):
            LOGGER.info("ETF quote source recovered")
            self.state.data["source_failure_rounds"] = 0
            self.state.save()

        missing_codes = set(self.config.etfs).difference(quotes)
        for code in sorted(missing_codes):
            LOGGER.warning("No valid quote returned for configured ETF %s", code)

        self._send_summary(quotes, now)

        for code, quote in quotes.items():
            etf = self.config.etfs[code]
            if quote.premium_rate > etf.threshold:
                continue
            if self.state.in_cooldown("etf_alerts", code, self.config.cooldown_seconds, now):
                LOGGER.info("%s is in notification cooldown", code)
                continue
            try:
                send_card(self.config.webhook_url, low_premium_card(quote, etf.threshold, now), self.config)
            except Exception as error:
                LOGGER.error("Unable to send low-premium alert for %s: %s", code, error)
                self._send_health_alert("飞书推送异常", f"{code} 的低溢价通知发送失败：{error}", now)
                continue
            self.state.mark_sent("etf_alerts", code, now)
            LOGGER.info("Low-premium alert sent for %s at %.2f%%", code, quote.premium_rate)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.toml"), help="TOML configuration path")
    parser.add_argument("--once", action="store_true", help="Run at most one polling round, then exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args.config)
    except (ConfigurationError, OSError, tomllib.TOMLDecodeError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    configure_logging(config.log_file)
    monitor = Monitor(config, StateStore(config.state_file))
    LOGGER.info("MarketSentinel started with %s configured ETFs", len(config.etfs))
    while True:
        now = datetime.now(SHANGHAI)
        if should_poll(now, config.exchange_calendar):
            monitor.run_once(now)
        else:
            LOGGER.debug("Outside A-share trading session; waiting")
        if args.once:
            return 0
        time.sleep(config.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
