import unittest

import pandas as pd

from signalpilot.indicators import add_indicators


class IndicatorTests(unittest.TestCase):
    def test_adds_required_indicators(self):
        candles = pd.DataFrame(
            {
                "high": [float(value + 1) for value in range(1, 260)],
                "low": [float(value - 1) for value in range(1, 260)],
                "close": [float(value) for value in range(1, 260)],
            }
        )

        result = add_indicators(candles)

        for column in ["ema20", "ema50", "ema200", "rsi14", "atr14", "recent_high20", "recent_low20"]:
            self.assertIn(column, result.columns)
        self.assertFalse(pd.isna(result.iloc[-1]["atr14"]))

    def test_ema200_requires_full_warmup(self):
        short_candles = _candles(199)
        ready_candles = _candles(200)

        short_result = add_indicators(short_candles)
        ready_result = add_indicators(ready_candles)

        self.assertTrue(pd.isna(short_result.iloc[-1]["ema200"]))
        self.assertFalse(pd.isna(ready_result.iloc[-1]["ema200"]))


def _candles(size: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "high": [float(value + 1) for value in range(1, size + 1)],
            "low": [float(value - 1) for value in range(1, size + 1)],
            "close": [float(value) for value in range(1, size + 1)],
        }
    )


if __name__ == "__main__":
    unittest.main()
