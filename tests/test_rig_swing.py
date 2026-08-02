"""Tests for the swing_v1 arm: detection, filters, no look-ahead, engine timeout,
paired-baseline geometry and edge pairing."""

import unittest

import numpy as np
import pandas as pd

from signalpilot.rig import swing as S
from signalpilot.rig import metrics as M
from signalpilot.rig.engine import TIMEOUT, Trade, _manage, _open_trade
from signalpilot.rig.plans import Plan
from signalpilot.rig.swing_report import paired_edges


def _bars(rows):
    """rows: list of (high, low, close). Builds a 4h decision frame."""
    n = len(rows)
    start = pd.Timestamp("2025-01-01", tz="UTC")
    df = pd.DataFrame({
        "open_time": [start + pd.Timedelta(hours=4 * i) for i in range(n)],
        "open": [r[2] for r in rows],
        "high": [r[0] for r in rows],
        "low": [r[1] for r in rows],
        "close": [r[2] for r in rows],
        "volume": [100.0] * n,
        "ema50": [1.0] * n,        # далеко внизу: close > ema50 завжди (LONG-режим)
        "atr14": [0.4] * n,
        "rsi14": [60.0] * n,
    })
    df["decision_time"] = df["open_time"] + pd.Timedelta(hours=4)
    return df


def _uptrend_rows():
    """10 плоских свічок (без свінгів), далі HH/HL структура і пробій на idx 24."""
    flat = [(10.2, 9.6, 9.9)] * 10
    pattern = [
        (10.5, 9.5, 10.0),   # 10
        (10.8, 10.0, 10.4),  # 11
        (11.5, 10.4, 11.0),  # 12  свінг-хай 11.5 (підтв. на 14)
        (11.0, 10.2, 10.6),  # 13
        (10.9, 10.1, 10.5),  # 14
        (10.7, 9.9, 10.3),   # 15  свінг-лоу 9.9 (підтв. на 17)
        (11.0, 10.0, 10.6),  # 16
        (11.2, 10.3, 10.8),  # 17
        (12.0, 10.8, 11.4),  # 18  свінг-хай 12.0 (підтв. на 20)
        (11.6, 10.9, 11.2),  # 19
        (11.4, 10.7, 11.0),  # 20
        (11.2, 10.6, 10.9),  # 21  свінг-лоу 10.6 (підтв. на 23)
        (11.5, 10.8, 11.2),  # 22
        (11.8, 11.0, 11.5),  # 23
        (12.6, 11.5, 12.4),  # 24  пробій: close 12.4 > 12.0
    ]
    return flat + pattern


class SwingDetectTests(unittest.TestCase):
    def test_long_breakout_setup_geometry(self):
        dec = _bars(_uptrend_rows())
        setups = S.detect_swing_setups(dec)
        self.assertEqual(len(setups), 1)
        s = setups[0]
        self.assertEqual((s.idx, s.direction), (24, "LONG"))
        self.assertAlmostEqual(s.level, 12.0)
        self.assertAlmostEqual(s.stop, 10.5)     # 10.6 − 0.25·0.4
        self.assertAlmostEqual(s.target, 15.0)   # 12.0 + 2·1.5
        self.assertTrue(s.rsi_ok)                # 60 > 50
        self.assertFalse(s.bb_ok)                # немає 180 свічок — консервативно False

    def test_short_mirror(self):
        rows = [(-lo, -hi, -cl) for hi, lo, cl in _uptrend_rows()]
        dec = _bars(rows)
        dec["ema50"] = 100.0                      # close < ema50: SHORT-режим
        dec["rsi14"] = 40.0
        setups = S.detect_swing_setups(dec)
        self.assertEqual(len(setups), 1)
        s = setups[0]
        self.assertEqual((s.idx, s.direction), (24, "SHORT"))
        self.assertAlmostEqual(s.level, -12.0)
        self.assertAlmostEqual(s.stop, -10.5)
        self.assertAlmostEqual(s.target, -15.0)
        self.assertTrue(s.rsi_ok)

    def test_no_setup_against_trend(self):
        dec = _bars(_uptrend_rows())
        dec["ema50"] = 100.0                      # close < ema50: тренд не підтримує LONG
        self.assertEqual(S.detect_swing_setups(dec), [])

    def test_breakout_fires_once(self):
        rows = _uptrend_rows() + [(12.8, 12.1, 12.5), (12.9, 12.2, 12.6)]
        dec = _bars(rows)
        setups = S.detect_swing_setups(dec)
        self.assertEqual([s.idx for s in setups], [24])

    def test_volume_filter(self):
        rows = _uptrend_rows()
        dec = _bars(rows)
        dec.loc[24, "volume"] = 200.0            # ≥ 1.3×100
        s = S.detect_swing_setups(dec)[0]
        self.assertTrue(s.vol_ok)
        dec.loc[24, "volume"] = 120.0            # < 130
        s = S.detect_swing_setups(dec)[0]
        self.assertFalse(s.vol_ok)

    def test_rsi_filter_blocks_weak_long(self):
        dec = _bars(_uptrend_rows())
        dec["rsi14"] = 40.0
        s = S.detect_swing_setups(dec)[0]
        self.assertFalse(s.rsi_ok)
        self.assertFalse(S.passes_filter(s, "rsi"))
        self.assertTrue(S.passes_filter(s, None))


class EngineTimeoutTests(unittest.TestCase):
    def _trade(self):
        t0 = pd.Timestamp("2025-01-01", tz="UTC")
        return Trade("BTCUSDT", "swing_v1", "LONG", "limit", t0, t0, 0.4, 100.0, 99.0, 102.0)

    def test_default_timeout_unchanged_and_custom_respected(self):
        tr = self._trade()
        now = tr.fill_time + pd.Timedelta(hours=50)   # > 48h, < 240h
        candle = (100.5, 101.0, 100.0, 100.5)
        self.assertEqual(_manage(tr, *candle, now)[0], "timeout")
        self.assertIsNone(_manage(tr, *candle, now, timeout=pd.Timedelta(hours=240)))
        late = tr.fill_time + pd.Timedelta(hours=240)
        self.assertEqual(_manage(tr, *candle, late, timeout=pd.Timedelta(hours=240))[0], "timeout")


class PairedBaselineTests(unittest.TestCase):
    def test_market_plan_carries_absolute_distances(self):
        dec = _bars(_uptrend_rows())
        setup = S.detect_swing_setups(dec)[0]
        row = dec.iloc[setup.idx]
        plan = S.paired_baseline_plan("BTCUSDT", "swing_v1_base", row, setup)
        self.assertEqual(plan.fill_mode, "market")
        trade = _open_trade(plan, 12.1, row.decision_time)   # філ на 12.1
        self.assertAlmostEqual(trade.entry, 12.1)
        self.assertAlmostEqual(trade.stop, 12.1 - 1.5)       # той самий ризик 1.5
        self.assertAlmostEqual(trade.target, 12.1 + 3.0)     # 2R

    def test_paired_edges_match_on_created_time(self):
        from signalpilot.rig.engine import ClosedTrade
        t0 = pd.Timestamp("2025-01-01", tz="UTC")

        def ct(arm, created, outcome, net):
            return ClosedTrade("BTCUSDT", arm, "LONG", created, created, created,
                               1.0, 0.5, 2.0, 1.5, outcome, net, 0.0, net,
                               1.0, 0.0, False, "visible", created.strftime("%Y-%m"))
        a1, a2 = ct("swing_v1", t0, "target", 2.0), ct("swing_v1", t0 + pd.Timedelta(hours=8), "stop", -1.0)
        b1 = ct("swing_v1_base", t0, "stop", -1.0)
        b2_unresolved = ct("swing_v1_base", t0 + pd.Timedelta(hours=8), "unresolved", 0.3)
        edges = paired_edges([a1, a2], [b1, b2_unresolved])
        self.assertEqual(len(edges), 1)                      # unresolved пару відкинуто
        self.assertAlmostEqual(edges[0]["edge"], 3.0)


if __name__ == "__main__":
    unittest.main()
