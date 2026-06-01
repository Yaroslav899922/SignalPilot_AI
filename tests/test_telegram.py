import json
import os
import unittest
from unittest.mock import patch

from signalpilot.signals import Signal
from signalpilot.telegram import (
    TELEGRAM_MESSAGE_LIMIT,
    TelegramConfig,
    fetch_updates,
    format_signal_message,
    send_message,
    send_signal,
)


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload or {"ok": True, "result": {"message_id": 1}}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class TelegramTests(unittest.TestCase):
    def test_format_signal_message_includes_trade_fields_and_safety_note(self):
        message = format_signal_message(_signal())

        self.assertIn("<b>BTCUSDT | LONG - шукати покупку</b>", message)
        self.assertIn("<b>Дія:</b> LONG - шукати покупку", message)
        self.assertIn("<b>Зона входу:</b> 100.00-101.00", message)
        self.assertIn("<b>Стоп:</b> 95.00", message)
        self.assertIn("<b>Цілі:</b> 110.00", message)
        self.assertIn("<b>Ризик/прибуток:</b> 1:2.0", message)
        self.assertIn("<b>Впевненість:</b> середня", message)
        self.assertIn("<b>Long/short ratio:</b> 1.100 - чи не забагато трейдерів в один бік", message)
        self.assertIn("<b>Spread:</b> 0.0100% - різниця між купівлею і продажем", message)
        self.assertIn("<b>Висновок:</b> можливий LONG, але тільки після ручного підтвердження.", message)
        self.assertIn("SignalPilot не відкриває угоди", message)

    def test_format_signal_message_explains_no_trade_in_ukrainian(self):
        message = format_signal_message(
            _signal(
                direction="NO TRADE",
                confidence="low",
                entry_zone="",
                stop=None,
                targets=(),
                risk_reward=None,
                invalidation="Wait for a cleaner setup with a defined stop",
                reasons=(
                    "4h regime is down",
                    "1h regime is down",
                    "15m confirmation skipped because 1h setup is NO TRADE",
                    "Long/short ratio is crowded",
                    "No clean trend + level + momentum setup with minimum 1:2 risk/reward",
                ),
            )
        )

        self.assertIn("<b>BTCUSDT | НЕ ВХОДИТИ</b>", message)
        self.assertIn("<b>Дія:</b> НЕ ВХОДИТИ", message)
        self.assertIn("<b>Впевненість:</b> низька", message)
        self.assertIn("4h тренд вниз", message)
        self.assertIn("15m не перевірявся, бо на 1h немає входу", message)
        self.assertIn("Long/short ratio crowded - забагато трейдерів стоять в один бік", message)
        self.assertIn("Немає чистого сетапу з нормальним ризик/прибуток", message)
        self.assertIn("<b>Висновок:</b> не входити в угоду.", message)

    def test_format_signal_message_truncates_long_reasons_for_telegram_limit(self):
        long_reasons = tuple(f"Reason {index}: {'x' * 500}" for index in range(20))

        message = format_signal_message(_signal(reasons=long_reasons))

        self.assertLessEqual(len(message), TELEGRAM_MESSAGE_LIMIT)
        self.assertIn("<b>BTCUSDT | LONG - шукати покупку</b>", message)
        self.assertIn("причини скорочено", message)

    def test_config_from_env_requires_token_and_chat(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                TelegramConfig.from_env()

    def test_config_from_env_reads_token_and_chat(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "chat"}, clear=True):
            config = TelegramConfig.from_env()

        self.assertEqual(config.bot_token, "token")
        self.assertEqual(config.chat_id, "chat")

    def test_send_signal_posts_json_payload(self):
        with patch("signalpilot.telegram.urlopen", return_value=FakeResponse()) as urlopen:
            response = send_signal(
                _signal(),
                TelegramConfig(bot_token="token", chat_id="chat"),
                base_url="https://example.test",
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(response["ok"], True)
        self.assertEqual(request.full_url, "https://example.test/bottoken/sendMessage")
        self.assertEqual(payload["chat_id"], "chat")
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertIn("<b>BTCUSDT | LONG - шукати покупку</b>", payload["text"])
        self.assertEqual(payload["disable_web_page_preview"], True)

    def test_send_message_can_reply_to_specific_chat(self):
        with patch("signalpilot.telegram.urlopen", return_value=FakeResponse()) as urlopen:
            send_message(
                "<b>Звіт</b>",
                TelegramConfig(bot_token="token", chat_id="channel"),
                chat_id=123,
                base_url="https://example.test",
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://example.test/bottoken/sendMessage")
        self.assertEqual(payload["chat_id"], "123")
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertEqual(payload["text"], "<b>Звіт</b>")

    def test_fetch_updates_posts_poll_payload(self):
        telegram_payload = {"ok": True, "result": [{"update_id": 10}]}
        with patch("signalpilot.telegram.urlopen", return_value=FakeResponse(telegram_payload)) as urlopen:
            updates = fetch_updates(
                TelegramConfig(bot_token="token", chat_id="channel"),
                offset=11,
                timeout=5,
                base_url="https://example.test",
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://example.test/bottoken/getUpdates")
        self.assertEqual(payload["offset"], 11)
        self.assertEqual(payload["timeout"], 5)
        self.assertEqual(payload["allowed_updates"], ["message"])
        self.assertEqual(updates, [{"update_id": 10}])


def _signal(
    direction: str = "LONG",
    confidence: str = "medium",
    entry_zone: str = "100.00-101.00",
    stop: float | None = 95.0,
    targets: tuple[float, ...] = (110.0,),
    risk_reward: float | None = 2.0,
    invalidation: str = "Below 95.00",
    reasons: tuple[str, ...] = ("Risk/reward meets minimum 1:2", "Funding rate is 0.0100%"),
) -> Signal:
    return Signal(
        symbol="BTCUSDT",
        interval="1h",
        direction=direction,
        market_regime="4h:up/1h:up/15m:confirmed",
        close_price=100.5,
        funding_rate=0.0001,
        open_interest=12345.0,
        long_short_ratio=1.1,
        spread_pct=0.01,
        entry_zone=entry_zone,
        stop=stop,
        targets=targets,
        risk_reward=risk_reward,
        confidence=confidence,
        invalidation=invalidation,
        reasons=reasons,
        created_at="2026-05-31T00:00:00+00:00",
    )


if __name__ == "__main__":
    unittest.main()
