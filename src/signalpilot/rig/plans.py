"""Plan generators for the three arms compared by the rig.

A Plan is a frozen intention created at a 4h close:
  * pullback_v1 — limit order inside the EMA50 +/- 0.25*ATR zone (the v1 idea)
  * baseline    — market entry at next open in the direction of the 4h trend
  * breakout    — the project's current logic (signals.build_signal), market entry

All numbers (zone, stop, target) are frozen at creation: no look-ahead.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..market import FuturesContext
from ..signals import build_signal

# v1 defaults (from the measurement spec)
ZONE_K = 0.25          # zone half-width in ATR around EMA50
STOP_ATR = 1.0         # stop sits this many ATR beyond the far edge of the zone
TARGET_ATR = 1.5       # target distance from entry, in ATR
# baseline defaults
BASE_STOP_ATR = 1.25
BASE_TARGET_ATR = 1.5

_NEUTRAL = FuturesContext(funding_rate=0.0, open_interest=1.0, long_short_ratio=1.0, spread_pct=0.0)


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


def breakout(symbol: str, row_frame: pd.DataFrame) -> Plan | None:
    """Current project logic. row_frame is a 1-row enriched 4h frame (the decision bar)."""
    signal = build_signal(symbol, "4h", row_frame, _NEUTRAL)
    if signal.direction not in ("LONG", "SHORT") or signal.stop is None or not signal.targets:
        return None
    row = row_frame.iloc[0]
    return Plan(symbol, "breakout", signal.direction, "market", row.decision_time,
                float(row.close), float(row.atr14),
                None, float(signal.stop), float(signal.targets[0]), None, None, None, None)
