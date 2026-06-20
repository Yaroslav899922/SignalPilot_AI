import unittest
from datetime import datetime, timezone

import pandas as pd

from signalpilot.brief import generate_brief
from signalpilot.market import FuturesContext
from signalpilot.market_data import LiveMarketData, MarketFrame


class BriefTests(unittest.TestCase):
    def test_generate_brief_uses_live_market_frames_without_external_ai(self):
        text = generate_brief(
            [_market(FuturesContext())],
            now_utc=datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc),
        )

        self.assertIn("SignalPilot Market Brief", text)
        self.assertIn("Лондонська сесія", text)
        self.assertIn("<b><u>BTC</u></b>", text)
        self.assertIn("<b>Обʼєм 1h:</b> 1,000 BTC ≈ $110.0K · 0.8x avg20 — нормальний", text)
        self.assertIn("MACD histogram позитивний і росте", text)
        self.assertIn("<blockquote expandable>", text)
        self.assertIn("<b>Готуватись до LONG:</b>", text)
        self.assertIn("1h close > $115.00", text)
        self.assertIn("Futures context недоступний з GitHub Actions; brief не блокується.", text)
        self.assertIn("Це контрольний огляд живого ринку, не сигнал на вхід.", text)

    def test_generate_brief_prints_available_futures_context(self):
        text = generate_brief(
            [
                _market(
                    FuturesContext(
                        funding_rate=0.0001,
                        open_interest=12345.0,
                        long_short_ratio=1.2,
                        spread_pct=0.01,
                    )
                )
            ],
            now_utc=datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc),
        )

        self.assertIn("Нью-Йоркська сесія", text)
        self.assertIn("Futures context частково доступний", text)


def _market(context: FuturesContext) -> LiveMarketData:
    return LiveMarketData(
        symbol="BTCUSDT",
        source="binance_usdm_public",
        collected_at="2026-06-20T09:00:00+00:00",
        futures_context=context,
        frames={
            "1h": MarketFrame(
                symbol="BTCUSDT",
                interval="1h",
                source="binance_usdm_public",
                candles=pd.DataFrame(
                    [
                        {
                            "close": 108.0,
                            "rsi14": 54.0,
                            "atr14": 4.0,
                            "ema20": 104.0,
                            "ema50": 100.0,
                            "macd_hist": 0.2,
                            "volume": 900.0,
                            "volume_avg20": 1200.0,
                            "recent_low20": 95.0,
                            "recent_high20": 115.0,
                        },
                        {
                            "close": 110.0,
                            "rsi14": 58.0,
                            "atr14": 4.0,
                            "ema20": 105.0,
                            "ema50": 100.0,
                            "macd_hist": 0.4,
                            "volume": 1000.0,
                            "volume_avg20": 1200.0,
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
                candles=pd.DataFrame([{"close": 110.0, "ema50": 100.0}]),
            ),
        },
    )


if __name__ == "__main__":
    unittest.main()
