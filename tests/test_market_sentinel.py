import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import market_sentinel as sentinel


SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeConfig:
    poll_seconds = 300
    cooldown_seconds = 1800
    summary_interval_seconds = 0
    health_cooldown_seconds = 3600
    failure_alert_after_rounds = 3
    random_delay_min_seconds = 0
    random_delay_max_seconds = 0
    max_retries = 1
    retry_delay_seconds = 0
    request_timeout_seconds = 1
    webhook_url = "https://example.invalid/main"
    health_webhook_url = "https://example.invalid/health"
    exchange_calendar = "XSHG"
    summary_groups = ("标普500", "纳斯达克", "南方东证ETF")
    etfs = {"513500": sentinel.EtfConfig("513500", "测试 ETF", 0.8, "标普500")}


class MarketSentinelTests(unittest.TestCase):
    def test_akshare_discount_rate_is_converted_to_premium_rate(self):
        # 2.649 / 2.4829 - 1 is about +6.69%, while AKShare's discount field
        # reports -6.69 for the same quote.
        self.assertAlmostEqual(sentinel.premium_rate_from_values(2.649, 2.4829, -6.69), 6.69)
        self.assertAlmostEqual(sentinel.premium_rate_from_values(1.858, 1.8644, 0.34), -0.34)
        self.assertAlmostEqual(
            sentinel.premium_rate_from_values(1.858, 1.8644, None), (1.858 - 1.8644) / 1.8644 * 100
        )

    def test_trading_time_boundaries(self):
        self.assertTrue(sentinel.is_trading_time(datetime(2026, 8, 3, 9, 30, tzinfo=SHANGHAI)))
        self.assertTrue(sentinel.is_trading_time(datetime(2026, 8, 3, 11, 29, 59, tzinfo=SHANGHAI)))
        self.assertFalse(sentinel.is_trading_time(datetime(2026, 8, 3, 11, 30, tzinfo=SHANGHAI)))
        self.assertFalse(sentinel.is_trading_time(datetime(2026, 8, 3, 12, 0, tzinfo=SHANGHAI)))
        self.assertTrue(sentinel.is_trading_time(datetime(2026, 8, 3, 13, 0, tzinfo=SHANGHAI)))
        self.assertFalse(sentinel.is_trading_time(datetime(2026, 8, 3, 15, 0, tzinfo=SHANGHAI)))

    def test_state_store_cooldown_persists(self):
        now = datetime(2026, 8, 3, 10, 0, tzinfo=SHANGHAI)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = sentinel.StateStore(path)
            state.mark_sent("etf_alerts", "513500", now)
            restored = sentinel.StateStore(path)
            self.assertTrue(restored.in_cooldown("etf_alerts", "513500", 1800, now + timedelta(minutes=29)))
            self.assertFalse(restored.in_cooldown("etf_alerts", "513500", 1800, now + timedelta(minutes=30)))

    def test_low_premium_sends_once_in_cooldown(self):
        now = datetime(2026, 8, 3, 10, 0, tzinfo=SHANGHAI)
        quote = sentinel.Quote("513500", "测试 ETF", 1.0, 1.01, -0.99)
        with tempfile.TemporaryDirectory() as directory:
            config = FakeConfig()
            config.state_file = Path(directory) / "state.json"
            monitor = sentinel.Monitor(config, sentinel.StateStore(config.state_file))
            with patch("market_sentinel.fetch_quotes", return_value={"513500": quote}), patch(
                "market_sentinel.send_card"
            ) as send_card:
                monitor.run_once(now)
                monitor.run_once(now + timedelta(minutes=1))
            self.assertEqual(send_card.call_count, 1)

    def test_summary_sends_every_configured_interval(self):
        now = datetime(2026, 8, 3, 10, 0, tzinfo=SHANGHAI)
        quotes = {
            "513500": sentinel.Quote("513500", "测试 ETF A", 1.1, 1.0, 10.0),
            "513650": sentinel.Quote("513650", "测试 ETF B", 1.09, 1.0, 9.0),
        }
        with tempfile.TemporaryDirectory() as directory:
            config = FakeConfig()
            config.summary_interval_seconds = 1800
            config.state_file = Path(directory) / "state.json"
            config.etfs = {
                "513500": sentinel.EtfConfig("513500", "测试 ETF A", 0.8, "标普500"),
                "513650": sentinel.EtfConfig("513650", "测试 ETF B", 0.8, "标普500"),
            }
            monitor = sentinel.Monitor(config, sentinel.StateStore(config.state_file))
            with patch("market_sentinel.fetch_quotes", return_value=quotes), patch(
                "market_sentinel.send_card"
            ) as send_card:
                monitor.run_once(now)
                monitor.run_once(now + timedelta(minutes=29))
                monitor.run_once(now + timedelta(minutes=30))
            self.assertEqual(send_card.call_count, 2)
            first_card = send_card.call_args_list[0].args[1]
            content = first_card["card"]["elements"][0]["content"]
            self.assertEqual(first_card["card"]["header"]["title"]["content"], "MarketSentinel · ETF 实时溢价汇总")
            self.assertIn("**标普500：** +9.00% 至 +10.00%｜**告警阈值：** ≤ 0.80%", content)
            self.assertIn("**纳斯达克：** 暂无有效行情", content)
            self.assertNotIn("513500", content)
            self.assertNotIn("价格", content)

    def test_single_quote_group_summary_shows_only_premium(self):
        now = datetime(2026, 8, 3, 10, 0, tzinfo=SHANGHAI)
        config = FakeConfig()
        config.summary_groups = ("日本东证",)
        config.etfs = {"513800": sentinel.EtfConfig("513800", "日本东证指数ETF南方", -2.0, "日本东证")}
        quote = sentinel.Quote("513800", "日本东证指数ETF南方", 1.866, 1.8697, -0.20)
        content = sentinel.summary_card({"513800": quote}, config, now)["card"]["elements"][0]["content"]
        self.assertIn("**日本东证 溢价：** -0.20%｜**告警阈值：** ≤ -2.00%", content)
        self.assertNotIn("513800", content)
        self.assertNotIn("价格", content)
        self.assertNotIn("IOPV", content)

    def test_source_failure_health_alert_after_configured_rounds(self):
        now = datetime(2026, 8, 3, 10, 0, tzinfo=SHANGHAI)
        with tempfile.TemporaryDirectory() as directory:
            config = FakeConfig()
            config.state_file = Path(directory) / "state.json"
            monitor = sentinel.Monitor(config, sentinel.StateStore(config.state_file))
            with patch("market_sentinel.fetch_quotes", side_effect=RuntimeError("offline")), patch(
                "market_sentinel.send_card"
            ) as send_card:
                monitor.run_once(now)
                monitor.run_once(now + timedelta(minutes=5))
                self.assertEqual(send_card.call_count, 0)
                monitor.run_once(now + timedelta(minutes=10))
            self.assertEqual(send_card.call_count, 1)


if __name__ == "__main__":
    unittest.main()
