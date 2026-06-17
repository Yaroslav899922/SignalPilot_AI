import unittest

import pandas as pd

from signalpilot.paper import evaluate_signal


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

    def test_evaluation_calculates_result_and_baseline_r(self):
        result = evaluate_signal(
            {
                "id": 1,
                "created_at": "2026-05-31T00:00:00+00:00",
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "close_price": 100.0,
                "stop": 95.0,
                "targets_json": "[110.0]",
            },
            pd.DataFrame(
                {
                    "open_time": pd.to_datetime(["2026-05-31T01:00:00Z", "2026-05-31T02:00:00Z"], utc=True),
                    "open": [101.0, 104.0],
                    "high": [106.0, 112.0],
                    "low": [100.0, 103.0],
                    "close": [104.0, 111.0],
                }
            ),
            lookahead_candles=2,
        )

        self.assertEqual(result.outcome, "target_hit")
        self.assertEqual(result.result_R, 2.0)
        self.assertEqual(result.baseline_R, 2.0)
        self.assertEqual(result.edge_R, 0.0)

    def test_not_enough_data(self):
        result = evaluate_signal(
            _signal(direction="LONG", stop=95.0, target=110.0),
            pd.DataFrame({"high": [104.0], "low": [99.0]}),
            lookahead_candles=2,
        )

        self.assertEqual(result.outcome, "not_enough_data")


def _signal(direction: str, stop: float, target: float) -> dict[str, object]:
    return {
        "id": 1,
        "created_at": "2026-05-31T00:00:00+00:00",
        "symbol": "BTCUSDT",
        "direction": direction,
        "stop": stop,
        "targets_json": f"[{target}]",
    }


if __name__ == "__main__":
    unittest.main()
