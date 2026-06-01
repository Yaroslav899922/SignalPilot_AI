import unittest

import pandas as pd

from signalpilot.paper import backtest_candles, evaluate_signal, summarize_backtest


class PaperEvaluationTests(unittest.TestCase):
    def test_long_target_hit(self):
        result = evaluate_signal(
            _signal(direction="LONG", stop=95.0, target=110.0),
            pd.DataFrame({"high": [106.0, 111.0], "low": [99.0, 101.0]}),
            lookahead_candles=2,
        )

        self.assertEqual(result.outcome, "target_hit")
        self.assertEqual(result.max_favorable_price, 111.0)
        self.assertEqual(result.max_adverse_price, 99.0)

    def test_short_stop_hit(self):
        result = evaluate_signal(
            _signal(direction="SHORT", stop=105.0, target=90.0),
            pd.DataFrame({"high": [101.0, 106.0], "low": [96.0, 94.0]}),
            lookahead_candles=2,
        )

        self.assertEqual(result.outcome, "stop_hit")
        self.assertEqual(result.max_favorable_price, 94.0)
        self.assertEqual(result.max_adverse_price, 106.0)

    def test_no_result(self):
        result = evaluate_signal(
            _signal(direction="LONG", stop=95.0, target=110.0),
            pd.DataFrame({"high": [104.0, 106.0], "low": [99.0, 98.0]}),
            lookahead_candles=2,
        )

        self.assertEqual(result.outcome, "no_result")

    def test_not_enough_data(self):
        result = evaluate_signal(
            _signal(direction="LONG", stop=95.0, target=110.0),
            pd.DataFrame({"high": [104.0], "low": [99.0]}),
            lookahead_candles=2,
        )

        self.assertEqual(result.outcome, "not_enough_data")

    def test_backtest_candles_collects_directional_signals(self):
        results = backtest_candles(
            symbol="BTCUSDT",
            interval="1h",
            candles=_backtest_candles(),
            lookahead_candles=2,
            target_signals=1,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].direction, "LONG")
        self.assertEqual(results[0].outcome, "target_hit")

    def test_summarize_backtest_counts_outcomes(self):
        signals = backtest_candles(
            symbol="BTCUSDT",
            interval="1h",
            candles=_backtest_candles(),
            lookahead_candles=2,
            target_signals=1,
        )

        summary = summarize_backtest("BTCUSDT", "1h", 3, signals)

        self.assertEqual(summary.directional_signals, 1)
        self.assertEqual(summary.target_hit, 1)
        self.assertEqual(summary.to_dict()["win_rate"], 1.0)
        self.assertEqual(summary.to_dict()["futures_context_mode"], "rule_only_neutral")
        self.assertEqual(summary.to_dict()["uses_live_futures_filters"], False)


def _signal(direction: str, stop: float, target: float) -> dict[str, object]:
    return {
        "id": 1,
        "created_at": "2026-05-31T00:00:00+00:00",
        "symbol": "BTCUSDT",
        "direction": direction,
        "stop": stop,
        "targets_json": f"[{target}]",
    }


def _backtest_candles() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open_time": pd.to_datetime(
                [
                    "2026-05-31T00:00:00Z",
                    "2026-05-31T01:00:00Z",
                    "2026-05-31T02:00:00Z",
                ],
                utc=True,
            ),
            "high": [111.0, 130.0, 131.0],
            "low": [109.0, 108.0, 112.0],
            "close": [110.0, 129.0, 130.0],
            "ema50": [105.0, 106.0, 107.0],
            "ema200": [100.0, 101.0, 102.0],
            "rsi14": [60.0, 62.0, 64.0],
            "atr14": [3.0, 3.0, 3.0],
            "recent_high20": [109.0, 120.0, 121.0],
            "recent_low20": [101.0, 102.0, 103.0],
        }
    )


if __name__ == "__main__":
    unittest.main()
