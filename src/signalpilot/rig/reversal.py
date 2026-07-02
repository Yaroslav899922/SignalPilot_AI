"""Reversal-setup state machine (bullish core): liquidity sweep + FVG + MSS.

Walks 4h decision bars left to right and, using only information available at
each bar, emits a setup on the bar where a Market-Structure-Shift (MSS) confirms
the reversal. Sequence (bullish):

    downtrend -> range (RL low, RH high) -> sweep dips below RL and closes back
    inside -> price leaves a bullish FVG on the way up -> close breaks a minor
    swing high (MSS) = confirmation.

Entry is a limit at the FVG midpoint; stop sits just under the swept low; the
first target is the range high (the far, asymmetric side of the trade).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .fvg import find_fvgs
from .structure import find_swings

N_SWING = 2
FVG_MIN_ATR = 0.10
RANGE_LOOKBACK = 20   # bars before the sweep to look for the range high
SWEEP_WINDOW = 12     # max bars from range high to the sweep
SETUP_WINDOW = 12     # max bars from sweep to the MSS confirmation
STOP_BUFFER_ATR = 0.25
FIB_EXT = 0.618       # 1.618 extension of the RH->RL leg (downside sweep floor)


@dataclass(frozen=True)
class ReversalSetup:
    idx: int            # bar where MSS confirms (the emit bar)
    direction: str      # "LONG"
    range_low: float
    range_high: float
    swept_low: float
    fib_1618: float
    entry: float
    stop: float
    target: float


def detect_long_reversals(dec: pd.DataFrame) -> list[ReversalSetup]:
    high = dec["high"].to_numpy(dtype=float)
    low = dec["low"].to_numpy(dtype=float)
    close = dec["close"].to_numpy(dtype=float)
    ema50 = dec["ema50"].to_numpy(dtype=float)
    ema200 = dec["ema200"].to_numpy(dtype=float)
    atr = dec["atr14"].to_numpy(dtype=float)
    m = len(dec)

    swings = find_swings(dec, n=N_SWING)
    swing_highs = [s for s in swings if s.kind == "high"]
    swing_lows = [s for s in swings if s.kind == "low"]
    fvgs = find_fvgs(dec, min_atr=FVG_MIN_ATR, kind="bull")

    setups: list[ReversalSetup] = []
    used_until = -1

    for rl in swing_lows:
        r = rl.idx
        if r <= used_until:
            continue
        # 1. downtrend context at the range low
        if not (close[r] < ema50[r] < ema200[r]):
            continue

        # 2. sweep = first bar after r that dips below RL, within the window,
        #    and closes back inside (a sweep, not a breakdown). First dip => untapped.
        s = None
        for k in range(r + 1, min(r + 1 + SWEEP_WINDOW, m)):
            if low[k] < rl.price:
                if close[k] > rl.price:
                    s = k
                break  # first dip decides: sweep or breakdown
        if s is None:
            continue

        # 3. range high = highest swing high in the lookback just before the sweep
        #    (the range's high can form either before or after the range low)
        rh_candidates = [sh for sh in swing_highs
                         if s - RANGE_LOOKBACK <= sh.idx < s and sh.price > rl.price]
        if not rh_candidates:
            continue
        rh = max(rh_candidates, key=lambda sh: sh.price)

        # 4. fib floor: the sweep must dip below RL but not deeper than the 1.618 ext
        fib = rl.price - FIB_EXT * (rh.price - rl.price)
        swept_low = low[s]
        if not (fib <= swept_low < rl.price):
            continue

        # 5. first bullish FVG after the sweep
        fvg = next((g for g in fvgs if s < g.idx <= s + SETUP_WINDOW), None)
        if fvg is None:
            continue

        # 6. minor swing high after the sweep, then MSS = first close above it
        mh = next((sh for sh in swing_highs if sh.idx > s), None)
        if mh is None or mh.idx > s + SETUP_WINDOW:
            continue
        t = None
        start = max(mh.confirmed_at, fvg.idx)
        for k in range(start, min(s + 1 + SETUP_WINDOW, m)):
            if close[k] > mh.price:
                t = k
                break
        if t is None:
            continue

        entry = (fvg.low + fvg.high) / 2.0
        stop = float(swept_low) - STOP_BUFFER_ATR * float(atr[s])
        target = rh.price
        if not (stop < entry < target):
            continue

        setups.append(ReversalSetup(
            idx=t, direction="LONG", range_low=rl.price, range_high=rh.price,
            swept_low=float(swept_low), fib_1618=float(fib),
            entry=float(entry), stop=float(stop), target=float(target),
        ))
        used_until = t

    return setups
