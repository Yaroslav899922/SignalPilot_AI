import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd

from signalpilot.journal import save_signal
from signalpilot.paper import evaluate_journal, evaluate_signal
from signalpilot.signals import Signal


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

    def test_actionable_uses_only_fully_closed_candles_inside_trigger_and_expiry(self):
        signal = {
            **_signal(direction="LONG", stop=95.0, target=110.0),
            "interval": "15m",
            "source": "actionable_alert",
            "created_at": "2026-05-31T00:07:00+00:00",
            "triggered_at": "2026-05-31T00:07:00+00:00",
            "expires_at": "2026-05-31T00:37:00+00:00",
            "close_price": 100.0,
        }
        candles = pd.DataFrame(
            {
                "open_time": pd.to_datetime(
                    [
                        "2026-05-31T00:00:00Z",
                        "2026-05-31T00:15:00Z",
                        "2026-05-31T00:30:00Z",
                        "2026-05-31T00:45:00Z",
                    ],
                    utc=True,
                ),
                "open": [100.0, 100.0, 105.0, 105.0],
                "high": [111.0, 106.0, 111.0, 106.0],
                "low": [99.0, 99.0, 99.0, 99.0],
                "close": [110.0, 105.0, 110.0, 105.0],
            }
        )

        result = evaluate_signal(signal, candles, lookahead_candles=48)

        self.assertEqual(result.outcome, "no_result")
        self.assertEqual(result.max_favorable_price, 106.0)
        self.assertEqual(result.activated_at, "2026-05-31T00:07:00+00:00")

    def test_actionable_includes_candle_closing_exactly_at_expiry(self):
        signal = {
            **_signal(direction="LONG", stop=95.0, target=110.0),
            "interval": "15m",
            "source": "actionable_alert",
            "created_at": "2026-05-31T00:07:00+00:00",
            "triggered_at": "2026-05-31T00:07:00+00:00",
            "expires_at": "2026-05-31T00:30:00+00:00",
            "close_price": 100.0,
        }
        candles = pd.DataFrame(
            {
                "open_time": pd.to_datetime(
                    ["2026-05-31T00:15:00Z", "2026-05-31T00:30:00Z"], utc=True
                ),
                "open": [100.0, 110.0],
                "high": [111.0, 112.0],
                "low": [99.0, 109.0],
                "close": [110.0, 111.0],
            }
        )

        result = evaluate_signal(signal, candles, lookahead_candles=48)

        self.assertEqual(result.outcome, "target_hit")

    def test_actionable_does_not_finalize_when_last_explicit_candle_is_missing(self):
        signal = {
            **_signal(direction="LONG", stop=95.0, target=110.0),
            "interval": "15m",
            "source": "actionable_alert",
            "created_at": "2026-05-31T00:00:00+00:00",
            "triggered_at": "2026-05-31T00:00:00+00:00",
            "expires_at": "2026-05-31T00:30:00+00:00",
            "close_price": 100.0,
        }
        candles = pd.DataFrame(
            {
                "open_time": pd.to_datetime(["2026-05-31T00:00:00Z"], utc=True),
                "close_time": pd.to_datetime(["2026-05-31T00:15:00Z"], utc=True),
                "open": [100.0],
                "high": [106.0],
                "low": [99.0],
                "close": [105.0],
            }
        )

        result = evaluate_signal(signal, candles, lookahead_candles=48)

        self.assertEqual(result.outcome, "not_enough_data")

    def test_actionable_future_expiry_blocks_evaluation_even_when_generic_age_has_passed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "signals.sqlite3"
            signal = replace(
                _plan("BTCUSDT", created_at="2026-07-19T00:00:00+00:00"),
                interval="15m",
                source="actionable_alert",
                setup_id="BTCUSDT-future-expiry-setup",
                event_id="BTCUSDT-future-expiry-event",
                triggered_at="2026-07-19T00:00:00+00:00",
                expires_at="2026-07-19T03:00:00+00:00",
            )
            save_signal(signal, db_path)
            fetch_calls = []

            results = evaluate_journal(
                str(db_path),
                lookahead_candles=4,
                fetcher=lambda **kwargs: fetch_calls.append(kwargs),
                now=pd.Timestamp("2026-07-19T02:00:00Z"),
            )

        self.assertEqual(results, [])
        self.assertEqual(fetch_calls, [])

    def test_actionable_waits_until_explicit_expiry_not_generic_lookahead(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "signals.sqlite3"
            signal = replace(
                _plan("BTCUSDT", created_at="2026-07-19T00:07:00+00:00"),
                interval="15m",
                source="actionable_alert",
                setup_id="BTCUSDT-test-setup",
                event_id="BTCUSDT-test-event",
                triggered_at="2026-07-19T00:07:00+00:00",
                expires_at="2026-07-19T02:07:00+00:00",
            )
            save_signal(signal, db_path)

            fetch_calls = []

            def fake_fetcher(symbol, interval, limit, end_time=None):
                fetch_calls.append((symbol, end_time))
                return pd.DataFrame(
                    {
                        "open_time": pd.date_range("2026-07-19T00:00:00Z", periods=12, freq="15min"),
                        "open": [100.0] * 12,
                        "high": [104.0] * 12,
                        "low": [99.0] * 12,
                        "close": [102.0] * 12,
                    }
                )

            before = evaluate_journal(
                str(db_path), 48, fetcher=fake_fetcher,
                now=pd.Timestamp("2026-07-19T02:06:59Z"),
            )
            after = evaluate_journal(
                str(db_path), 48, fetcher=fake_fetcher,
                now=pd.Timestamp("2026-07-19T02:07:00Z"),
            )

        self.assertEqual(before, [])
        self.assertEqual(len(after), 1)
        self.assertEqual(
            fetch_calls,
            [("BTCUSDT", pd.Timestamp("2026-07-19T02:07:00Z"))],
        )
        self.assertEqual(after[0].outcome, "no_result")
        self.assertEqual(after[0].activated_at, "2026-07-19T00:07:00+00:00")


class EvaluateJournalAgeGateTests(unittest.TestCase):
    def test_young_plan_waits_for_full_window_before_evaluation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "signals.sqlite3"
            save_signal(_plan("BTCUSDT", created_at="2026-07-19T00:00:00+00:00"), db_path)  # id=1, молодий
            save_signal(_plan("ETHUSDT", created_at="2026-07-16T00:00:00+00:00"), db_path)  # id=2, старий

            fetch_calls = []

            def fake_fetcher(symbol, interval, limit):
                fetch_calls.append(symbol)
                open_times = pd.date_range("2026-07-16T00:00:00Z", periods=120, freq="h")
                return pd.DataFrame(
                    {
                        "open_time": open_times,
                        "open": [100.0] * 120,
                        "high": [101.0] * 120,
                        "low": [99.0] * 120,
                        "close": [100.0] * 120,
                    }
                )

            results = evaluate_journal(
                str(db_path),
                lookahead_candles=48,
                fetcher=fake_fetcher,
                now=pd.Timestamp("2026-07-19T06:00:00Z"),
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].signal_id, 2)
            self.assertEqual(len(fetch_calls), 1)
            self.assertNotEqual(results[0].outcome, "not_enough_data")


def _plan(symbol: str, created_at: str) -> Signal:
    return Signal(
        symbol=symbol,
        interval="1h",
        direction="LONG",
        market_regime="uptrend",
        close_price=100.0,
        funding_rate=None,
        open_interest=None,
        long_short_ratio=None,
        spread_pct=None,
        entry_zone="",
        stop=95.0,
        targets=(110.0,),
        risk_reward=2.0,
        confidence="medium",
        invalidation="",
        reasons=("test",),
        created_at=created_at,
    )


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
