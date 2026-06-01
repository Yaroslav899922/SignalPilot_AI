import unittest

import pandas as pd

from signalpilot.market import FuturesContext
from signalpilot.signals import build_multi_timeframe_signal, build_signal


class SignalEngineTests(unittest.TestCase):
    def test_returns_no_trade_when_data_is_insufficient(self):
        signal = build_signal("BTCUSDT", "1h", pd.DataFrame())

        self.assertEqual(signal.direction, "NO TRADE")
        self.assertIn("No candle data", signal.reasons[0])

    def test_returns_long_candidate_for_clean_breakout(self):
        candles = pd.DataFrame(
            [
                {
                    "close": 110.0,
                    "ema50": 105.0,
                    "ema200": 100.0,
                    "rsi14": 60.0,
                    "atr14": 3.0,
                    "recent_high20": 109.0,
                    "recent_low20": 101.0,
                }
            ]
        )

        signal = build_signal("BTCUSDT", "1h", candles, _valid_context())

        self.assertEqual(signal.direction, "LONG")
        self.assertEqual(signal.risk_reward, 2.0)
        self.assertEqual(signal.market_regime, "up")
        self.assertEqual(signal.close_price, 110.0)
        self.assertEqual(signal.funding_rate, 0.0001)
        self.assertEqual(signal.open_interest, 10000.0)
        self.assertEqual(signal.long_short_ratio, 1.1)
        self.assertEqual(signal.spread_pct, 0.01)
        self.assertTrue(signal.entry_zone)
        self.assertTrue(signal.targets)
        self.assertTrue(any("Funding rate" in reason for reason in signal.reasons))
        self.assertTrue(any("Open interest" in reason for reason in signal.reasons))
        self.assertTrue(any("Long/short ratio" in reason for reason in signal.reasons))
        self.assertTrue(any("Order book spread" in reason for reason in signal.reasons))

    def test_returns_short_candidate_for_clean_breakdown(self):
        candles = pd.DataFrame(
            [
                {
                    "close": 90.0,
                    "ema50": 95.0,
                    "ema200": 100.0,
                    "rsi14": 40.0,
                    "atr14": 3.0,
                    "recent_high20": 99.0,
                    "recent_low20": 91.0,
                }
            ]
        )

        signal = build_signal("ETHUSDT", "1h", candles, _valid_context())

        self.assertEqual(signal.direction, "SHORT")
        self.assertEqual(signal.risk_reward, 2.0)
        self.assertTrue(signal.entry_zone)
        self.assertTrue(signal.targets)

    def test_returns_no_trade_when_funding_is_overheated(self):
        candles = pd.DataFrame(
            [
                {
                    "close": 110.0,
                    "ema50": 105.0,
                    "ema200": 100.0,
                    "rsi14": 60.0,
                    "atr14": 3.0,
                    "recent_high20": 109.0,
                    "recent_low20": 101.0,
                }
            ]
        )

        signal = build_signal(
            "BTCUSDT",
            "1h",
            candles,
            FuturesContext(funding_rate=0.0015, open_interest=10000.0, long_short_ratio=1.1, spread_pct=0.01),
        )

        self.assertEqual(signal.direction, "NO TRADE")
        self.assertTrue(any("overheated" in reason for reason in signal.reasons))

    def test_returns_no_trade_when_futures_context_is_missing(self):
        candles = pd.DataFrame(
            [
                {
                    "close": 110.0,
                    "ema50": 105.0,
                    "ema200": 100.0,
                    "rsi14": 60.0,
                    "atr14": 3.0,
                    "recent_high20": 109.0,
                    "recent_low20": 101.0,
                }
            ]
        )

        signal = build_signal("BTCUSDT", "1h", candles)

        self.assertEqual(signal.direction, "NO TRADE")
        self.assertTrue(any("Futures context unavailable" in reason for reason in signal.reasons))

    def test_returns_no_trade_when_long_short_ratio_is_crowded(self):
        signal = build_signal(
            "BTCUSDT",
            "1h",
            _long_setup_candles(),
            FuturesContext(funding_rate=0.0001, open_interest=10000.0, long_short_ratio=2.5, spread_pct=0.01),
        )

        self.assertEqual(signal.direction, "NO TRADE")
        self.assertTrue(any("Long/short ratio is crowded" in reason for reason in signal.reasons))

    def test_returns_no_trade_when_order_book_spread_is_too_wide(self):
        signal = build_signal(
            "BTCUSDT",
            "1h",
            _long_setup_candles(),
            FuturesContext(funding_rate=0.0001, open_interest=10000.0, long_short_ratio=1.1, spread_pct=0.10),
        )

        self.assertEqual(signal.direction, "NO TRADE")
        self.assertTrue(any("Order book spread is too wide" in reason for reason in signal.reasons))

    def test_returns_long_when_multi_timeframe_setup_aligns(self):
        signal = build_multi_timeframe_signal(
            "BTCUSDT",
            {
                "15m": pd.DataFrame([{"close": 112.0, "ema20": 111.0, "rsi14": 58.0}]),
                "1h": _long_setup_candles(),
                "4h": pd.DataFrame([{"close": 120.0, "ema50": 110.0, "ema200": 100.0}]),
            },
            _valid_context(),
        )

        self.assertEqual(signal.direction, "LONG")
        self.assertIn("4h:up/1h:up/15m:confirmed", signal.market_regime)
        self.assertTrue(any("Multi-timeframe confirmation" in reason for reason in signal.reasons))

    def test_returns_no_trade_when_higher_timeframe_disagrees(self):
        signal = build_multi_timeframe_signal(
            "BTCUSDT",
            {
                "15m": pd.DataFrame([{"close": 112.0, "ema20": 111.0, "rsi14": 58.0}]),
                "1h": _long_setup_candles(),
                "4h": pd.DataFrame([{"close": 90.0, "ema50": 95.0, "ema200": 100.0}]),
            },
            _valid_context(),
        )

        self.assertEqual(signal.direction, "NO TRADE")
        self.assertTrue(any("not aligned" in reason for reason in signal.reasons))

    def test_returns_no_trade_when_lower_timeframe_does_not_confirm(self):
        signal = build_multi_timeframe_signal(
            "BTCUSDT",
            {
                "15m": pd.DataFrame([{"close": 108.0, "ema20": 111.0, "rsi14": 58.0}]),
                "1h": _long_setup_candles(),
                "4h": pd.DataFrame([{"close": 120.0, "ema50": 110.0, "ema200": 100.0}]),
            },
            _valid_context(),
        )

        self.assertEqual(signal.direction, "NO TRADE")
        self.assertTrue(any("does not confirm" in reason for reason in signal.reasons))


def _valid_context() -> FuturesContext:
    return FuturesContext(funding_rate=0.0001, open_interest=10000.0, long_short_ratio=1.1, spread_pct=0.01)


def _long_setup_candles() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "close": 110.0,
                "ema50": 105.0,
                "ema200": 100.0,
                "rsi14": 60.0,
                "atr14": 3.0,
                "recent_high20": 109.0,
                "recent_low20": 101.0,
            }
        ]
    )


if __name__ == "__main__":
    unittest.main()
