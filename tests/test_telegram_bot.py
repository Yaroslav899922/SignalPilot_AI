import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from signalpilot.signals import Signal
from signalpilot.telegram import TelegramConfig
from signalpilot.telegram_bot import (
    MARKET,
    REPORT,
    STATUS,
    UNKNOWN,
    format_report_message,
    parse_bot_command,
    run_telegram_bot,
)


class TelegramBotTests(unittest.TestCase):
    def test_parse_bot_command_understands_ukrainian_phrases(self):
        self.assertEqual(parse_bot_command("надай звіт"), REPORT)
        self.assertEqual(parse_bot_command("звіт"), REPORT)
        self.assertEqual(parse_bot_command("є торгова ситуація?"), MARKET)
        self.assertEqual(parse_bot_command("перевір ринок"), MARKET)
        self.assertEqual(parse_bot_command("статус"), STATUS)
        self.assertEqual(parse_bot_command("щось інше"), UNKNOWN)

    def test_format_report_message_is_ukrainian_html_summary(self):
        message = format_report_message(
            {
                "signals": 10,
                "long": 2,
                "short": 1,
                "no_trade": 7,
                "pending": 1,
                "target_hit": 1,
                "stop_hit": 1,
                "no_result": 0,
                "win_rate": 0.5,
            }
        )

        self.assertIn("<b>Звіт SignalPilot</b>", message)
        self.assertIn("<b>Всього записів:</b> 10", message)
        self.assertIn("<b>НЕ ВХОДИТИ:</b> 7", message)
        self.assertIn("<b>Win rate:</b> 50.0%", message)
        self.assertIn("SignalPilot не відкриває угоди", message)

    def test_run_telegram_bot_replies_to_report_and_advances_offset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "signals.sqlite3"
            sent_messages = []
            offsets = []

            def fake_fetch_updates(config, offset, timeout, base_url):
                offsets.append(offset)
                if offset is None:
                    return [
                        {
                            "update_id": 10,
                            "message": {
                                "chat": {"id": 123},
                                "text": "надай звіт",
                            },
                        }
                    ]
                return []

            def fake_send_message(text, config, chat_id=None, base_url=""):
                sent_messages.append((text, chat_id))
                return {"ok": True}

            with patch("signalpilot.telegram_bot.fetch_updates", side_effect=fake_fetch_updates):
                with patch("signalpilot.telegram_bot.send_message", side_effect=fake_send_message):
                    with patch("signalpilot.telegram_bot.time.sleep"):
                        run_telegram_bot(
                            config=TelegramConfig(bot_token="token", chat_id="channel"),
                            journal_path=journal_path,
                            scan_market=lambda: [],
                            symbols=["BTCUSDT"],
                            base_url="https://example.test",
                            poll_timeout=1,
                            poll_interval_seconds=0.01,
                            max_polls=2,
                        )

        self.assertEqual(offsets, [None, 11])
        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(sent_messages[0][1], "123")
        self.assertIn("<b>Звіт SignalPilot</b>", sent_messages[0][0])

    def test_run_telegram_bot_replies_with_market_scan_signals(self):
        sent_messages = []

        def fake_send_message(text, config, chat_id=None, base_url=""):
            sent_messages.append((text, chat_id))
            return {"ok": True}

        with patch(
            "signalpilot.telegram_bot.fetch_updates",
            return_value=[
                {
                    "update_id": 20,
                    "message": {
                        "chat": {"id": 456},
                        "text": "є торгова ситуація?",
                    },
                }
            ],
        ):
            with patch("signalpilot.telegram_bot.send_message", side_effect=fake_send_message):
                run_telegram_bot(
                    config=TelegramConfig(bot_token="token", chat_id="channel"),
                    journal_path=Path("data/signals.sqlite3"),
                    scan_market=lambda: [_signal()],
                    symbols=["BTCUSDT"],
                    base_url="https://example.test",
                    poll_timeout=1,
                    poll_interval_seconds=0.01,
                    max_polls=1,
                )

        self.assertEqual(len(sent_messages), 2)
        self.assertIn("Перевіряю ринок", sent_messages[0][0])
        self.assertIn("<b>BTCUSDT | LONG - шукати покупку</b>", sent_messages[1][0])
        self.assertEqual(sent_messages[0][1], "456")
        self.assertEqual(sent_messages[1][1], "456")


def _signal() -> Signal:
    return Signal(
        symbol="BTCUSDT",
        interval="1h",
        direction="LONG",
        market_regime="4h:up/1h:up/15m:confirmed",
        close_price=100.5,
        funding_rate=0.0001,
        open_interest=12345.0,
        long_short_ratio=1.1,
        spread_pct=0.01,
        entry_zone="100.00-101.00",
        stop=95.0,
        targets=(110.0,),
        risk_reward=2.0,
        confidence="medium",
        invalidation="Below 95.00",
        reasons=("Risk/reward meets minimum 1:2",),
        created_at="2026-05-31T00:00:00+00:00",
    )


if __name__ == "__main__":
    unittest.main()
