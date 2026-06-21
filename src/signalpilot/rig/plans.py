"""Plan generators for the three arms compared by the rig.

A Plan is a frozen intention created at a 4h close:
  * pullback_v1 — limit order inside the EMA50 +/- 0.25*ATR zone (the v1 idea)
  * baseline    — market entry at next open in the direction of the 4h trend

All numbers (zone, stop, target) are frozen at creation: no look-ahead.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# v1 defaults (from the measurement spec)
ZONE_K = 0.25          # zone half-width in ATR around EMA50
STOP_ATR = 1.0         # stop sits this many ATR beyond the far edge of the zone
TARGET_ATR = 1.5       # target distance from entry, in ATR
# baseline defaults
BASE_STOP_ATR = 1.25
BASE_TARGET_ATR = 1.5


@dataclass(frozen=True)
class Plan:
    symbol: str
    arm: str
    direction: str          # "LONG" | "SHORT"
    fill_mode: str          # "limit" | "market"
    created_time: pd.Timestamp
    created_close: float     # 4h close at creation (for missed-move diagnostic)
    atr: float
    entry: float | None      # known for limit; None for market (filled at next open)
    stop: float | None       # absolute price if known
    target: float | None
    stop_mult: float | None  # for market arms whose stop/target are ATR-relative to fill
    target_mult: float | None
    zone_low: float | None
    zone_high: float | None


def trend(close: float, ema50: float, ema200: float) -> str:
    if close > ema50 > ema200:
        return "up"
    if close < ema50 < ema200:
        return "down"
    return "range"


def pullback_v1(symbol: str, row) -> Plan | None:
    close, ema, ema200, atr = float(row.close), float(row.ema50), float(row.ema200), float(row.atr14)
    if atr <= 0:
        return None
    direction = trend(close, ema, ema200)
    zone_low, zone_high = ema - ZONE_K * atr, ema + ZONE_K * atr
    if direction == "up":
        if close <= zone_high:          # no room to fall: price must be above the whole zone
            return None
        entry = ema
        return Plan(symbol, "pullback_v1", "LONG", "limit", row.decision_time, close, atr,
                    entry, zone_low - STOP_ATR * atr, entry + TARGET_ATR * atr,
                    None, None, zone_low, zone_high)
    if direction == "down":
        if close >= zone_low:           # mirror: price must be below the whole zone
            return None
        entry = ema
        return Plan(symbol, "pullback_v1", "SHORT", "limit", row.decision_time, close, atr,
                    entry, zone_high + STOP_ATR * atr, entry - TARGET_ATR * atr,
                    None, None, zone_low, zone_high)
    return None


def baseline(symbol: str, row) -> Plan | None:
    close, atr = float(row.close), float(row.atr14)
    if atr <= 0:
        return None
    direction = trend(close, float(row.ema50), float(row.ema200))
    if direction == "up":
        return Plan(symbol, "baseline", "LONG", "market", row.decision_time, close, atr,
                    None, None, None, BASE_STOP_ATR, BASE_TARGET_ATR, None, None)
    if direction == "down":
        return Plan(symbol, "baseline", "SHORT", "market", row.decision_time, close, atr,
                    None, None, None, BASE_STOP_ATR, BASE_TARGET_ATR, None, None)
    return None


# --- Pifagor Strategy 1 ("Manipulation on the hour"), mechanical core ---
# Impulse: candle 2 takes out candle 1's extreme but does NOT retrace past the
# 50% of candle 1. Fib drawn LOY..HAI of that 2-candle leg. Single limit entry at
# the 50% retracement, take at 38.2%, stop just beyond 61.8%. No ladder, no
# averaging-into-losers ("rocket") — those are deliberately left out.
PIF_ENTRY = 0.5
PIF_TARGET = 0.382
PIF_STOP = 0.66      # a hair beyond the 61.8% level


def pifagor_s1(symbol: str, dec, i: int) -> Plan | None:
    if i < 1:
        return None
    c1, c2 = dec.iloc[i - 1], dec.iloc[i]
    close = float(c2.close)
    direction = trend(close, float(c2.ema50), float(c2.ema200))
    high1, low1 = float(c1.high), float(c1.low)
    high2, low2 = float(c2.high), float(c2.low)
    mid1 = (high1 + low1) / 2.0

    if direction == "up" and high2 > high1 and low2 > mid1:
        hai, loy = high2, low1
        leg = hai - loy
        if leg <= 0:
            return None
        entry = hai - PIF_ENTRY * leg
        if close <= entry:                 # need room to retrace down into the zone
            return None
        return Plan(symbol, "pifagor_s1", "LONG", "limit", c2.decision_time, close,
                    float(c2.atr14), entry, hai - PIF_STOP * leg, hai - PIF_TARGET * leg,
                    None, None, loy, hai)

    if direction == "down" and low2 < low1 and high2 < mid1:
        hai, loy = high1, low2
        leg = hai - loy
        if leg <= 0:
            return None
        entry = loy + PIF_ENTRY * leg
        if close >= entry:                 # need room to retrace up into the zone
            return None
        return Plan(symbol, "pifagor_s1", "SHORT", "limit", c2.decision_time, close,
                    float(c2.atr14), entry, loy + PIF_STOP * leg, loy + PIF_TARGET * leg,
                    None, None, loy, hai)
    return None
