"""Fair Value Gap (FVG) detection for the reversal arm.

A (bullish) FVG is a 3-candle imbalance a, b, c where candle a's high is below
candle c's low: the middle candle b ran so hard that it left an unfilled gap
``[high[a], low[c]]``. Mirror for bearish. Tiny gaps are noise, so a gap counts
only if it is at least ``min_atr`` * ATR tall (ATR taken at candle c).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FVG:
    kind: str    # "bull" | "bear"
    low: float   # zone lower bound
    high: float  # zone upper bound
    idx: int     # index of candle c, the bar at which the gap is confirmed


def find_fvgs(candles: pd.DataFrame, min_atr: float = 0.10, kind: str = "bull") -> list[FVG]:
    """Return FVGs of the requested ``kind`` over ``candles`` (needs high/low/atr14)."""
    highs = candles["high"].to_numpy(dtype=float)
    lows = candles["low"].to_numpy(dtype=float)
    atr = candles["atr14"].to_numpy(dtype=float)
    out: list[FVG] = []
    for i in range(2, len(highs)):
        a = i - 2
        if kind == "bull":
            gap = lows[i] - highs[a]
            if gap > 0 and gap >= min_atr * atr[i]:
                out.append(FVG("bull", float(highs[a]), float(lows[i]), i))
        else:
            gap = lows[a] - highs[i]
            if gap > 0 and gap >= min_atr * atr[i]:
                out.append(FVG("bear", float(highs[i]), float(lows[a]), i))
    return out
