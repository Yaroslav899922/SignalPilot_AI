import unittest
from datetime import datetime, timezone

import pandas as pd

from signalpilot.market import FuturesContext
from signalpilot.market_data import LiveMarketData, MarketFrame
from signalpilot.move_alert import generate_move_alerts


class MoveAlertTests(unittest.TestCase):
    def test_generate_move_alerts_skips_small_moves(self):
        alerts = generate_move_alerts(
            [_market(open_price=100.0, close_price=101.0)],
            threshold_pct=1.5,
            now_utc=datetime(2026, 6, 21, 15, 35, tzinfo=timezone.utc),
        )

        self.assertEqual(alerts, [])

    def test_generate_move_alerts_formats_long_setup(self):
        alerts = generate_move_alerts(
            [_market(open_price=100.0, close_price=101.6)],
            threshold_pct=1.5,
            now_utc=datetime(2026, 6, 21, 15, 35, tzinfo=timezone.utc),
        )

        self.assertEqual(len(alerts), 1)
        text = alerts[0]
        self.assertIn("SignalPilot Move Alert", text)
        self.assertIn("21.06 · 18:35 Київ · Лондон + Нью-Йорк", text)
        self.assertIn("<b><u>BTC</u></b> $101.60", text)
        self.assertIn("<b>Рух:</b> +1.6% за 15m", text)
        self.assertIn("<b>Готуватись до LONG:</b>", text)
        self.assertIn("15m/1h close &gt; $115.00", text)
        self.assertNotIn("не сигнал", text)

    def test_generate_move_alerts_formats_short_setup(self):
        alerts = generate_move_alerts(
            [_market(open_price=100.0, close_price=98.4)],
            threshold_pct=1.5,
            now_utc=datetime(2026, 6, 21, 21, 35, tzinfo=timezone.utc),
        )

        self.assertEqual(len(alerts), 1)
        text = alerts[0]
        self.assertIn("22.06 · 00:35 Київ · Нью-Йорк", text)
        self.assertIn("<b>Рух:</b> -1.6% за 15m", text)
        self.assertIn("<b>Готуватись до SHORT:</b>", text)
        self.assertIn("15m/1h close &lt; $95.00", text)


def _market(open_price: float, close_price: float) -> LiveMarketData:
    return LiveMarketData(
        symbol="BTCUSDT",
        source="binance_usdm_public",
        collected_at="2026-06-21T15:35:00+00:00",
        futures_context=FuturesContext(),
        frames={
            "15m": MarketFrame(
                symbol="BTCUSDT",
                interval="15m",
                source="binance_usdm_public",
                candles=pd.DataFrame(
                    [
                        {
                            "open": 100.0,
                            "high": 101.0,
                            "low": 99.0,
                            "close": 100.0,
                            "rsi14": 52.0,
                            "ema20": 99.0,
                            "macd_hist": 0.1,
                            "volume": 900.0,
                            "volume_avg20": 1000.0,
                        },
                        {
                            "open": open_price,
                            "high": max(open_price, close_price) + 1.0,
                            "low": min(open_price, close_price) - 1.0,
                            "close": close_price,
                            "rsi14": 63.0 if close_price > open_price else 37.0,
                            "ema20": 99.5,
                            "macd_hist": 0.3 if close_price > open_price else -0.3,
                            "volume": 1300.0,
                            "volume_avg20": 1000.0,
                        },
                    ]
                ),
            ),
            "1h": MarketFrame(
                symbol="BTCUSDT",
                interval="1h",
                source="binance_usdm_public",
                candles=pd.DataFrame(
                    [
                        {
                            "close": close_price,
                            "ema20": 99.0,
                            "ema50": 98.0,
                            "atr14": 4.0,
                            "recent_low20": 95.0,
                            "recent_high20": 115.0,
                        }
                    ]
                ),
            ),
            "4h": MarketFrame(
                symbol="BTCUSDT",
                interval="4h",
                source="binance_usdm_public",
                candles=pd.DataFrame([{"close": close_price, "ema50": 98.0}]),
            ),
        },
    )


if __name__ == "__main__":
    unittest.main()
