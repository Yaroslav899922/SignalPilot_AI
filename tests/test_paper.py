import unittest

import pandas as pd

from signalpilot.paper import evaluate_signal


class PaperEvaluationTests(unittest.TestCase):
    def test_candle_opening_at_confirmation_time_is_evaluated(self):
        signal = _signal(direction="LONG", stop=95.0, target=110.0)
        candles = pd.DataFrame(
            {
                "open_time": pd.to_datetime(
                    ["2026-05-31T00:00:00Z", "2026-05-31T01:00:00Z"], utc=True
                ),
                "open": [100.0, 100.0],
                "high": [111.0, 101.0],
                "low": [99.0, 99.0],
                "close": [110.0, 100.0],
            }
        )

        result = evaluate_signal(signal, candles, lookahead_candles=1)

        self.assertEqual(result.outcome, "target_hit")

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

    def test_market_brief_plan_waits_for_entry_zone_before_evaluating(self):
        result = evaluate_signal(
            {
                **_signal(direction="LONG", stop=95.0, target=110.0),
                "close_price": 100.0,
                "entry_low": 99.0,
                "entry_high": 101.0,
                "source": "market_brief",
            },
            pd.DataFrame(
                {
                    "open_time": pd.to_datetime(
                        ["2026-05-31T01:00:00Z", "2026-05-31T02:00:00Z", "2026-05-31T03:00:00Z"],
                        utc=True,
                    ),
                    "high": [105.0, 102.0, 111.0],
                    "low": [103.0, 99.0, 104.0],
                    "close": [104.0, 101.0, 110.0],
                }
            ),
            lookahead_candles=3,
        )

        self.assertEqual(result.outcome, "target_hit")
        self.assertEqual(result.activated_at, "2026-05-31T02:00:00+00:00")

    def test_market_brief_plan_marks_unreached_entry_zone(self):
        result = evaluate_signal(
            {
                **_signal(direction="SHORT", stop=105.0, target=90.0),
                "entry_low": 99.0,
                "entry_high": 101.0,
                "source": "market_brief",
            },
            pd.DataFrame({"high": [110.0, 108.0], "low": [103.0, 102.0]}),
            lookahead_candles=2,
        )

        self.assertEqual(result.outcome, "not_activated")
        self.assertIsNone(result.activated_at)

    def test_actionable_entry_includes_fees_and_small_slippage(self):
        result = evaluate_signal(
            {
                **_signal(direction="LONG", stop=95.0, target=110.0),
                "close_price": 100.0,
                "source": "actionable_alert",
            },
            pd.DataFrame(
                {
                    "open": [100.0, 105.0],
                    "high": [106.0, 111.0],
                    "low": [99.0, 103.0],
                    "close": [105.0, 110.0],
                }
            ),
            lookahead_candles=2,
        )

        self.assertEqual(result.outcome, "target_hit")
        self.assertEqual(result.result_R, 1.976)
        self.assertIsNotNone(result.baseline_R)
        self.assertIsNotNone(result.edge_R)


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
