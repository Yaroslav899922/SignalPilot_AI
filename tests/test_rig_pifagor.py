import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
from signalpilot.rig.plans import pifagor_s1


def _dec(rows):
    return pd.DataFrame(rows)


class PifagorPlan(unittest.TestCase):
    def _bull_dec(self):
        # candle1 then candle2 that takes out high1 and stays above mid1 -> impulse
        c1 = dict(open=100, high=110, low=100, close=108, ema50=95, ema200=90,
                  atr14=5, decision_time=pd.Timestamp("2025-01-01", tz="UTC"))
        c2 = dict(open=108, high=120, low=106, close=118, ema50=100, ema200=90,
                  atr14=5, decision_time=pd.Timestamp("2025-01-01 04:00", tz="UTC"))
        return _dec([c1, c2])

    def test_bullish_impulse_makes_long(self):
        plan = pifagor_s1("BTCUSDT", self._bull_dec(), 1)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.direction, "LONG")
        leg = 120 - 100  # HAI - LOY
        self.assertAlmostEqual(plan.entry, 120 - 0.5 * leg, places=6)     # 110
        self.assertAlmostEqual(plan.target, 120 - 0.382 * leg, places=6)  # 112.36
        self.assertAlmostEqual(plan.stop, 120 - 0.66 * leg, places=6)     # 106.8
        self.assertLess(plan.stop, plan.entry)
        self.assertGreater(plan.target, plan.entry)

    def test_no_impulse_when_retraced_past_mid(self):
        d = self._bull_dec()
        d.loc[1, "low"] = 104   # below mid1 (=105) -> retraced too deep -> not impulse
        self.assertIsNone(pifagor_s1("BTCUSDT", d, 1))

    def test_first_bar_returns_none(self):
        self.assertIsNone(pifagor_s1("BTCUSDT", self._bull_dec(), 0))


if __name__ == "__main__":
    unittest.main()
