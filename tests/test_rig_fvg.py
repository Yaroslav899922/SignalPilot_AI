import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd

from signalpilot.rig.fvg import find_fvgs


def _frame(rows):
    return pd.DataFrame(rows)


class FindFvgs(unittest.TestCase):
    def test_bullish_gap_detected(self):
        # candle0 high=10, candle2 low=12 -> gap [10,12]; atr=1 so min size 0.1 ok
        rows = [
            dict(high=10, low=8, atr14=1),
            dict(high=13, low=11, atr14=1),   # impulse candle
            dict(high=14, low=12, atr14=1),
        ]
        fvgs = find_fvgs(_frame(rows), min_atr=0.10, kind="bull")
        self.assertEqual(len(fvgs), 1)
        self.assertEqual((fvgs[0].low, fvgs[0].high, fvgs[0].idx), (10.0, 12.0, 2))

    def test_no_gap_when_overlap(self):
        rows = [
            dict(high=12, low=8, atr14=1),
            dict(high=13, low=11, atr14=1),
            dict(high=14, low=11, atr14=1),   # low 11 < prev-prev high 12 -> no gap
        ]
        self.assertEqual(find_fvgs(_frame(rows), kind="bull"), [])

    def test_gap_too_small_filtered(self):
        # gap = 10.05 - 10.0 = 0.05; atr=1 -> needs >=0.10 -> filtered
        rows = [
            dict(high=10.0, low=8, atr14=1),
            dict(high=11, low=9, atr14=1),
            dict(high=12, low=10.05, atr14=1),
        ]
        self.assertEqual(find_fvgs(_frame(rows), min_atr=0.10, kind="bull"), [])

    def test_bearish_gap_mirror(self):
        # candle0 low=12, candle2 high=10 -> bearish gap [10,12]
        rows = [
            dict(high=14, low=12, atr14=1),
            dict(high=11, low=9, atr14=1),
            dict(high=10, low=8, atr14=1),
        ]
        fvgs = find_fvgs(_frame(rows), min_atr=0.10, kind="bear")
        self.assertEqual(len(fvgs), 1)
        self.assertEqual((fvgs[0].low, fvgs[0].high, fvgs[0].idx), (10.0, 12.0, 2))


if __name__ == "__main__":
    unittest.main()
