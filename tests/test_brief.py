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

        self.assertIn("SignalPilot market brief", text)
        self.assertIn("Лондонська сесія", text)
        self.assertIn("<b>BTC</b>", text)
        self.assertIn("4h ↑ вище EMA50", text)
        self.assertIn("Futures context: недоступний з GitHub Actions, не блокує brief", text)
        self.assertIn("LONG/SHORT приходять окремо", text)

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
        self.assertIn("funding 0.0100%", text)
        self.assertIn("OI 12345", text)
        self.assertIn("L/S 1.20", text)
        self.assertIn("spread 0.0100%", text)


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
                            "close": 110.0,
                            "rsi14": 58.0,
                            "atr14": 4.0,
                            "ema20": 105.0,
                            "ema50": 100.0,
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
