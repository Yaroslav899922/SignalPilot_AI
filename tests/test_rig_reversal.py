import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd

from signalpilot.rig.reversal import detect_long_reversals

# A hand-built bullish reversal that walks all six steps:
# downtrend -> RL(low 100)@5 -> range high(133)@9 -> sweep(low 90, close 105)@15
# -> bullish FVG@17 -> minor high(125)@18 -> MSS(close 128 > 125)@21.
_ROWS = [
    (140, 135, 136), (138, 130, 131), (133, 124, 125), (128, 118, 119), (120, 108, 110),
    (112, 100, 101), (118, 104, 116), (124, 110, 122), (129, 116, 127), (133, 122, 129),
    (128, 118, 124), (126, 112, 114), (120, 104, 106), (114, 101, 103), (112, 100.5, 104),
    (107, 90, 105), (116, 108, 114), (124, 112, 122), (125, 118, 120), (122, 116, 118),
    (121, 115, 117), (130, 120, 128), (132, 124, 129), (134, 126, 131), (136, 128, 133),
]


def _frame(rows=None):
    rows = rows or _ROWS
    df = pd.DataFrame(rows, columns=["high", "low", "close"])
    df["ema50"] = 110.0
    df["ema200"] = 120.0
    df["atr14"] = 5.0
    df["decision_time"] = pd.date_range("2025-01-01", periods=len(df), freq="4h", tz="UTC")
    return df


class DetectLongReversals(unittest.TestCase):
    def test_full_sequence_emits_one_setup(self):
        setups = detect_long_reversals(_frame())
        self.assertEqual(len(setups), 1)
        s = setups[0]
        self.assertEqual(s.idx, 21)                 # MSS confirmation bar
        self.assertEqual(s.direction, "LONG")
        self.assertEqual((s.range_low, s.range_high), (100.0, 133.0))
        self.assertEqual(s.swept_low, 90.0)
        self.assertAlmostEqual(s.fib_1618, 100 - 0.618 * 33)
        self.assertEqual(s.entry, 109.5)            # FVG [107,112] midpoint
        self.assertAlmostEqual(s.stop, 90.0 - 0.25 * 5.0)
        self.assertEqual(s.target, 133.0)
        self.assertTrue(s.stop < s.entry < s.target)

    def test_breakdown_not_sweep_is_rejected(self):
        rows = list(_ROWS)
        rows[15] = (107, 90, 95)                     # closes BELOW range low -> breakdown
        self.assertEqual(detect_long_reversals(_frame(rows)), [])

    def test_sweep_deeper_than_fib_is_rejected(self):
        rows = list(_ROWS)
        rows[15] = (107, 70, 105)                    # 70 < fib floor 79.6 -> too deep
        self.assertEqual(detect_long_reversals(_frame(rows)), [])

    def test_no_mss_no_setup(self):
        rows = list(_ROWS)
        rows[18] = (140, 118, 120)                   # minor high 140 never broken -> no MSS
        self.assertEqual(detect_long_reversals(_frame(rows)), [])


if __name__ == "__main__":
    unittest.main()
