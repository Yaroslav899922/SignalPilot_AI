import unittest
from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd

from signalpilot.actionable import (
    ARMED,
    TARGET_HIT,
    TRIGGERED,
    WATCH,
    analyze_actionable_setup,
    format_setup_message,
    reconcile_setup_state,
    should_notify_setup_event,
    setup_to_signal,
)
from signalpilot.market import FuturesContext
from signalpilot.market_data import LiveMarketData, MarketFrame


class ActionableSetupTests(unittest.TestCase):
    def test_breakout_retest_becomes_confirmed_entry(self):
        setup = analyze_actionable_setup(
            _market(one_hour_close=116.0, one_hour_low=114.8, volume=1500.0),
            now_utc=datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc),
        )

        self.assertIsNotNone(setup)
        assert setup is not None
        self.assertEqual(setup.status, TRIGGERED)
        self.assertEqual(setup.direction, "LONG")
        self.assertEqual(setup.pattern, "breakout_retest")
        self.assertEqual(setup.trigger_level, 115.0)
        self.assertGreaterEqual(setup.risk_reward, 1.5)
        self.assertTrue(all(condition.met for condition in setup.conditions if condition.required))

    def test_normal_breakout_close_is_not_rejected_as_chasing(self):
        setup = analyze_actionable_setup(
            _market(
                one_hour_close=116.0,
                one_hour_low=114.8,
                volume=1500.0,
                confirm_close=118.0,
                last_high=118.2,
            ),
            now_utc=datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc),
        )

        assert setup is not None
        self.assertEqual(setup.status, TRIGGERED)
        self.assertLessEqual(setup.current_price, setup.entry_high)

    def test_near_breakout_level_is_watch_but_not_an_entry(self):
        setup = analyze_actionable_setup(
            _market(one_hour_close=113.0, one_hour_low=112.0, volume=900.0, confirm_close=113.0),
            now_utc=datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc),
        )

        self.assertIsNotNone(setup)
        assert setup is not None
        self.assertEqual(setup.status, WATCH)
        self.assertIn("Зараз не входити", setup.action)

    def test_confirmed_message_uses_plain_ukrainian_instructions(self):
        setup = analyze_actionable_setup(
            _market(one_hour_close=116.0, one_hour_low=114.8, volume=1500.0),
            now_utc=datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc),
        )

        assert setup is not None
        text = format_setup_message(setup)

        self.assertIn("ВХІД ПІДТВЕРДЖЕНО", text)
        self.assertIn("Що робити зараз", text)
        self.assertIn("Зона входу", text)
        self.assertIn("Вихід зі збитком", text)
        self.assertIn("Ціль 1", text)
        self.assertIn("План скасовано", text)
        self.assertNotIn("WAIT", text)

    def test_confirmed_setup_converts_to_unique_paper_signal(self):
        setup = analyze_actionable_setup(
            _market(one_hour_close=116.0, one_hour_low=114.8, volume=1500.0),
            now_utc=datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc),
        )

        assert setup is not None
        signal = setup_to_signal(setup)

        self.assertEqual(signal.source, "actionable_alert")
        self.assertEqual(signal.setup_id, setup.setup_id)
        self.assertEqual(signal.setup_status, TRIGGERED)
        self.assertEqual(signal.entry_low, setup.entry_low)
        self.assertEqual(signal.entry_high, setup.entry_high)
        self.assertEqual(signal.close_price, setup.current_price)
        actual_ratio = (setup.targets[0] - signal.close_price) / (signal.close_price - setup.stop)
        self.assertAlmostEqual(actual_ratio, 1.5)

    def test_same_setup_and_state_stays_silent(self):
        now = datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc)
        market = _market(one_hour_close=113.0, one_hour_low=112.0, volume=900.0, confirm_close=113.0)
        setup = analyze_actionable_setup(market, now_utc=now)

        assert setup is not None
        events = reconcile_setup_state(setup, [setup], market, now_utc=now)

        self.assertEqual(events, [])

    def test_armed_setup_emits_one_confirmed_state_change(self):
        now = datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc)
        armed_market = _market(
            one_hour_close=116.0,
            one_hour_low=114.8,
            volume=900.0,
            confirm_macd=0.1,
        )
        triggered_market = _market(one_hour_close=116.0, one_hour_low=114.8, volume=1500.0)
        armed = analyze_actionable_setup(armed_market, now_utc=now)
        triggered = analyze_actionable_setup(triggered_market, now_utc=now)

        assert armed is not None and triggered is not None
        self.assertEqual(armed.setup_id, triggered.setup_id)
        events = reconcile_setup_state(triggered, [armed], triggered_market, now_utc=now)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, TRIGGERED)

    def test_confirmed_setup_reports_first_target_once(self):
        now = datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc)
        setup = analyze_actionable_setup(
            _market(one_hour_close=116.0, one_hour_low=114.8, volume=1500.0),
            now_utc=now,
        )
        assert setup is not None
        target_market = _market(
            one_hour_close=116.0,
            one_hour_low=114.8,
            volume=1500.0,
            last_high=setup.targets[0] + 0.1,
            last_low=setup.stop + 0.1,
        )

        events = reconcile_setup_state(None, [setup], target_market, now_utc=now)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, TARGET_HIT)

    def test_watch_is_quiet_but_armed_and_confirmed_are_announced(self):
        now = datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc)
        armed = analyze_actionable_setup(
            _market(
                one_hour_close=116.0,
                one_hour_low=114.8,
                volume=900.0,
                confirm_macd=0.1,
            ),
            now_utc=now,
        )
        assert armed is not None
        watch = replace(armed, status="WATCH")
        triggered = replace(armed, status=TRIGGERED)

        self.assertFalse(should_notify_setup_event(watch, []))
        self.assertTrue(should_notify_setup_event(armed, [watch]))
        self.assertTrue(should_notify_setup_event(triggered, [armed]))

    def test_same_setup_cannot_create_a_second_confirmed_entry(self):
        now = datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc)
        market = _market(one_hour_close=116.0, one_hour_low=114.8, volume=1500.0)
        triggered = analyze_actionable_setup(market, now_utc=now)
        assert triggered is not None
        retired = replace(
            triggered,
            status=TARGET_HIT,
            created_at="2026-07-19T19:00:00+00:00",
        )
        later_other_setup = replace(
            retired,
            setup_id="BTCUSDT-other-LONG-example",
            created_at="2026-07-19T19:30:00+00:00",
        )

        events = reconcile_setup_state(
            triggered,
            [triggered, retired, later_other_setup],
            market,
            now_utc=datetime(2026, 7, 19, 20, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(events, [])


def _market(
    *,
    one_hour_close: float,
    one_hour_low: float,
    volume: float,
    confirm_close: float = 116.0,
    confirm_macd: float = 0.4,
    last_high: float = 116.5,
    last_low: float = 114.0,
) -> LiveMarketData:
    return LiveMarketData(
        symbol="BTCUSDT",
        source="binance_usdm_public",
        collected_at="2026-07-19T18:00:00+00:00",
        futures_context=FuturesContext(),
        frames={
            "15m": MarketFrame(
                symbol="BTCUSDT",
                interval="15m",
                source="binance_usdm_public",
                candles=pd.DataFrame(
                    [
                        {"high": 115.0, "low": 113.5, "close": 114.5, "ema20": 113.5, "macd_hist": 0.2},
                        {
                            "high": last_high,
                            "low": last_low,
                            "close": confirm_close,
                            "ema20": 114.0,
                            "macd_hist": confirm_macd,
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
                            "open": 113.0,
                            "high": max(one_hour_close, 116.5),
                            "low": one_hour_low,
                            "close": one_hour_close,
                            "ema20": 104.0,
                            "ema50": 100.0,
                            "atr14": 4.0,
                            "macd_hist": 0.4,
                            "recent_high20": 115.0,
                            "recent_low20": 95.0,
                            "volume": volume,
                            "volume_avg20": 1000.0,
                        }
                    ]
                ),
            ),
            "4h": _uptrend_frame(),
        },
    )


def _uptrend_frame() -> MarketFrame:
    high = [100, 101, 105, 102, 103, 104, 110, 106, 107, 111, 109, 112]
    low = [90, 91, 92, 88, 91, 92, 93, 90, 94, 95, 96, 97]
    close = [95, 96, 100, 97, 98, 99, 105, 100, 103, 108, 109, 110]
    ema50 = [93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104]
    return MarketFrame(
        symbol="BTCUSDT",
        interval="4h",
        source="binance_usdm_public",
        candles=pd.DataFrame(
            {"high": high, "low": low, "close": close, "ema50": ema50, "atr14": [4.0] * len(close)}
        ),
    )


if __name__ == "__main__":
    unittest.main()
