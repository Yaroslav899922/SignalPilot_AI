"""Market-structure primitives for the reversal arm: confirmed swing pivots.

A swing (pivot) is a local extreme of price. To stay honest (no look-ahead), a
swing at bar ``idx`` is only *confirmed* once ``n`` bars to its right exist —
i.e. at bar ``idx + n``. Any state machine that walks bars left to right must
use only swings whose ``confirmed_at`` is at or before the current bar.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Swing:
    idx: int           # positional index of the pivot bar
    kind: str          # "high" | "low"
    price: float
    confirmed_at: int  # idx + n: first bar at which this swing is known


def find_swings(candles: pd.DataFrame, n: int = 2) -> list[Swing]:
    """Return confirmed swing highs/lows over ``candles`` (needs high/low columns).

    A bar ``i`` is a swing high if ``high[i]`` is the *unique* maximum of the
    window ``[i-n, i+n]`` (a flat top is not a pivot); mirror for swing lows.
    """
    highs = candles["high"].to_numpy(dtype=float)
    lows = candles["low"].to_numpy(dtype=float)
    m = len(highs)
    out: list[Swing] = []
    for i in range(n, m - n):
        wh = highs[i - n : i + n + 1]
        if highs[i] == wh.max() and np.count_nonzero(wh == highs[i]) == 1:
            out.append(Swing(i, "high", float(highs[i]), i + n))
        wl = lows[i - n : i + n + 1]
        if lows[i] == wl.min() and np.count_nonzero(wl == lows[i]) == 1:
            out.append(Swing(i, "low", float(lows[i]), i + n))
    return out
