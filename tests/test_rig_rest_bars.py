import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd

from signalpilot.rig.engine import simulate_plans
from signalpilot.rig.plans import Plan

T0 = pd.Timestamp("2025-01-06 08:00", tz="UTC")   # Kyiv-visible weekday hours
BAR4H = pd.Timedelta(hours=4)


def _plan():
    return Plan("BTCUSDT", "reversal_v1", "LONG", "limit", T0, 105.0, 5.0,
                100.0, 95.0, 110.0, None, None, None, None)


def _d15(dip_window):
    """3 four-hour windows of 15m candles; price sits above entry=100 except
    (optionally) a dip to 100 in ``dip_window`` that fills the limit."""
    times = pd.date_range(T0, periods=16 * 3, freq="15min", tz="UTC")
    rows = []
    for i, t in enumerate(times):
        w = i // 16
        hi, lo, op, cl = 106.0, 101.0, 103.0, 104.0
        if dip_window is not None and w == dip_window:
            lo, cl = 100.0, 111.0   # touch limit, then close above target
            hi = 111.0
        rows.append(dict(open_time=t, open=op, high=hi, low=lo, close=cl))
    return pd.DataFrame(rows)


def _decisions():
    # limit is armed once at T0; the next two windows bring no new plan
    return [(T0, _plan(), "down"), (T0 + BAR4H, None, "down"), (T0 + 2 * BAR4H, None, "down")]


class RestBarsLifetime(unittest.TestCase):
    def test_limit_rests_and_fills_within_budget(self):
        # dip happens in window 1 (age 1 < rest_bars 2) -> should fill
        r = simulate_plans("BTCUSDT", "reversal_v1", _decisions(), _d15(dip_window=1),
                           lifetime="rest_bars", rest_bars=2)
        self.assertEqual(len(r.trades), 1)

    def test_limit_expires_after_budget_without_fill(self):
        # price never reaches the limit -> expires once age hits rest_bars
        r = simulate_plans("BTCUSDT", "reversal_v1", _decisions(), _d15(dip_window=None),
                           lifetime="rest_bars", rest_bars=2)
        self.assertEqual(len(r.trades), 0)
        self.assertEqual(r.pending_expired, 1)

    def test_one_window_expires_next_bar(self):
        # same dip in window 1, but one_window cancels the limit at the next
        # decision (T0+4h) before the dip -> no fill
        r = simulate_plans("BTCUSDT", "reversal_v1", _decisions(), _d15(dip_window=1),
                           lifetime="one_window")
        self.assertEqual(len(r.trades), 0)


if __name__ == "__main__":
    unittest.main()
