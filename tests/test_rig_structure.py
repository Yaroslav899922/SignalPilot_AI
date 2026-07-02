import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd

from signalpilot.rig.structure import find_swings


def _frame(mids, half=0.5):
    return pd.DataFrame({"high": [m + half for m in mids], "low": [m - half for m in mids]})


class FindSwings(unittest.TestCase):
    def test_zigzag_trough_and_peak(self):
        # down to a trough at idx2, up to a peak at idx6, then down
        mids = [10, 9, 8, 9, 10, 11, 12, 11, 10]
        sw = find_swings(_frame(mids), n=2)
        lows = [s for s in sw if s.kind == "low"]
        highs = [s for s in sw if s.kind == "high"]
        self.assertEqual([s.idx for s in lows], [2])
        self.assertEqual([s.idx for s in highs], [6])
        self.assertEqual(lows[0].confirmed_at, 2 + 2)   # honest lag
        self.assertEqual(highs[0].confirmed_at, 6 + 2)
        self.assertAlmostEqual(lows[0].price, 8 - 0.5)
        self.assertAlmostEqual(highs[0].price, 12 + 0.5)

    def test_plateau_is_not_a_swing(self):
        # equal highs at the top -> not a unique extreme -> no swing high
        mids = [1, 2, 3, 3, 2, 1]
        sw = find_swings(_frame(mids), n=1)
        self.assertEqual([s for s in sw if s.kind == "high"], [])

    def test_monotonic_has_no_interior_swings(self):
        mids = [1, 2, 3, 4, 5, 6, 7, 8]
        self.assertEqual(find_swings(_frame(mids), n=2), [])

    def test_no_swing_in_first_or_last_n(self):
        mids = [10, 9, 8, 9, 10, 11, 12, 11, 10]
        sw = find_swings(_frame(mids), n=2)
        self.assertTrue(all(2 <= s.idx <= len(mids) - 1 - 2 for s in sw))


if __name__ == "__main__":
    unittest.main()
