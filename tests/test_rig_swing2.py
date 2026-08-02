"""Тести swing_v2: паритет із движком, трейлінг-храповик, без зазирання вперед."""

import math
import unittest

import pandas as pd

from signalpilot.rig import engine
from signalpilot.rig.dataset import load_symbol
from signalpilot.rig.plans import Plan
from signalpilot.rig.swing import REST_BARS, build_swing_decisions, detect_swing_setups
from signalpilot.rig.swing_exits import StructureTrailer, simulate_plans_exits


def _bars15(rows, start="2025-01-01"):
    t0 = pd.Timestamp(start, tz="UTC")
    n = len(rows)
    return pd.DataFrame({
        "open_time": [t0 + pd.Timedelta(minutes=15 * i) for i in range(n)],
        "open": [r[0] for r in rows],
        "high": [r[1] for r in rows],
        "low": [r[2] for r in rows],
        "close": [r[3] for r in rows],
    })


class ParityTests(unittest.TestCase):
    """fixed 2R без трейлінгу == основний движок, на РЕАЛЬНИХ даних BTC."""

    def test_parity_with_engine_on_real_btc(self):
        sym = load_symbol("BTCUSDT")
        setups = detect_swing_setups(sym.decisions)
        decisions = build_swing_decisions(sym, setups, "parity", None, paired=False)
        timeout = pd.Timedelta(hours=4 * 60)
        ours = simulate_plans_exits(sym.symbol, "parity", decisions, sym.bars15m,
                                    rest_bars=REST_BARS, timeout=timeout, trailer=None)
        theirs = engine.simulate_plans(sym.symbol, "parity", decisions, sym.bars15m,
                                       lifetime="rest_bars", rest_bars=REST_BARS,
                                       timeout=timeout)
        self.assertEqual(len(ours.trades), len(theirs.trades))
        for a, b in zip(ours.trades, theirs.trades):
            self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(ours.plans_created, theirs.plans_created)
        self.assertEqual(ours.plans_blocked, theirs.plans_blocked)


class TrailerTests(unittest.TestCase):
    def _trade(self, direction="LONG", fill="2025-01-01 00:00", stop=95.0):
        t = pd.Timestamp(fill, tz="UTC")
        return engine.Trade("X", "arm", direction, "limit", t, t, 1.0, 100.0, stop, math.inf)

    def test_stop_ratchets_up_only_and_respects_time(self):
        t = lambda s: pd.Timestamp(s, tz="UTC")
        trailer = StructureTrailer(
            long_events=[(t("2025-01-01 08:00"), 97.0), (t("2025-01-01 16:00"), 96.0),
                         (t("2025-01-02 00:00"), 98.5)],
            short_events=[],
        )
        trade = self._trade()
        # до першої події — нічого
        self.assertIsNone(trailer.updated_stop(trade, t("2025-01-01 04:00")))
        # перша подія піднімає стоп
        self.assertEqual(trailer.updated_stop(trade, t("2025-01-01 08:00")), 97.0)
        trade.stop = 97.0
        # нижчий свінг НЕ опускає стоп (храповик)
        self.assertIsNone(trailer.updated_stop(trade, t("2025-01-01 16:00")))
        # вища подія знову піднімає
        self.assertEqual(trailer.updated_stop(trade, t("2025-01-02 00:00")), 98.5)

    def test_events_before_fill_are_ignored(self):
        t = lambda s: pd.Timestamp(s, tz="UTC")
        trailer = StructureTrailer(long_events=[(t("2024-12-31 00:00"), 99.0)], short_events=[])
        trade = self._trade()
        self.assertIsNone(trailer.updated_stop(trade, t("2025-01-02 00:00")))

    def test_short_mirror(self):
        t = lambda s: pd.Timestamp(s, tz="UTC")
        trailer = StructureTrailer(long_events=[],
                                   short_events=[(t("2025-01-01 08:00"), 103.0)])
        trade = self._trade(direction="SHORT", stop=105.0)
        trade.target = -math.inf
        self.assertEqual(trailer.updated_stop(trade, t("2025-01-01 08:00")), 103.0)


class TrailExitTests(unittest.TestCase):
    def test_trailed_stop_exit_uses_trailed_price(self):
        t0 = pd.Timestamp("2025-01-01", tz="UTC")
        plan = Plan("X", "arm", "LONG", "limit", t0, 100.0, 1.0,
                    100.0, 95.0, math.inf, None, None, None, None)
        decisions = [(t0, plan, None)]
        rows = [(101, 101.5, 99.9, 100.2)]           # філ ліміту на 100
        rows += [(100.2, 102.0, 100.0, 101.5)] * 40  # рух угору
        rows += [(101.5, 101.6, 96.5, 96.6)]         # падіння: трейлений стоп 97 -> вихід
        d15 = _bars15(rows)
        trailer = StructureTrailer(
            long_events=[(t0 + pd.Timedelta(hours=5), 97.0)], short_events=[])
        res = simulate_plans_exits("X", "arm", decisions, d15,
                                   rest_bars=10, timeout=pd.Timedelta(days=30),
                                   trailer=trailer)
        self.assertEqual(len(res.trades), 1)
        trade = res.trades[0]
        self.assertEqual(trade.outcome, "stop")
        self.assertEqual(trade.exit_price, 97.0)
        self.assertGreater(trade.exit_time, t0 + pd.Timedelta(hours=5))


if __name__ == "__main__":
    unittest.main()
