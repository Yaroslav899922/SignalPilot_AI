"""Swing arm ``swing_v1``: 4h breakout-retest of a confirmed swing extreme.

Mechanics (frozen in SignalPilot-Swing-Setup-Spec-2026-08-02.md and registered
as hypothesis #6 in HYPOTHESES.md BEFORE this run):

  * trend filter: close above EMA50(4h) AND the two most recent confirmed
    swing highs/lows form HH/HL (mirror for SHORT: below EMA50 + LH/LL);
  * breakout: the FIRST 4h close beyond the most recent confirmed swing
    extreme in the trend direction (a close, not a wick — sweeps don't count);
  * entry: limit at the broken level (retest), resting up to 10 4h-bars;
  * stop: beyond the most recent opposite swing extreme with a 0.25*ATR14
    buffer; target: 2R; timeout 60 4h-bars (10 days); stop-first in a candle.

Secondary pre-registered filter flags, all evaluated on the breakout bar and
strictly backward-looking:

  * vol_ok: breakout-bar volume >= 1.3x mean volume of the previous 20 bars
    (False when fewer than 20 previous bars exist);
  * rsi_ok: RSI14 agrees with direction (>50 LONG, <50 SHORT);
  * bb_ok: Bollinger(20, 2 std) relative width <= its 25th percentile over the
    trailing 180 bars (squeeze). Bars without the full 180-bar base are
    conservatively False.

The gate from the spec applies to the CORE only; filters are secondary
pre-registered comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .plans import Plan
from .structure import find_swings

N_SWING = 2
STOP_BUFFER_ATR = 0.25
TARGET_R = 2.0
REST_BARS = 10          # limit lifetime in 4h bars
TIMEOUT_BARS_4H = 60    # 10 days
VOL_MULT = 1.3
VOL_LOOKBACK = 20
RSI_MID = 50.0
BB_WINDOW = 20
BB_STD = 2.0
BB_PCTL = 25.0
BB_LOOKBACK = 180


@dataclass(frozen=True)
class SwingSetup:
    idx: int            # breakout bar (emit bar)
    direction: str      # "LONG" | "SHORT"
    level: float        # broken swing extreme = limit entry
    stop: float
    target: float
    vol_ok: bool
    rsi_ok: bool
    bb_ok: bool


def _bb_width(close: np.ndarray) -> np.ndarray:
    s = pd.Series(close)
    mid = s.rolling(BB_WINDOW).mean()
    sd = s.rolling(BB_WINDOW).std(ddof=0)
    return ((2 * BB_STD * sd) / mid).to_numpy(dtype=float)


def detect_swing_setups(dec: pd.DataFrame) -> list[SwingSetup]:
    high = dec["high"].to_numpy(dtype=float)
    low = dec["low"].to_numpy(dtype=float)
    close = dec["close"].to_numpy(dtype=float)
    ema50 = dec["ema50"].to_numpy(dtype=float)
    atr = dec["atr14"].to_numpy(dtype=float)
    rsi = dec["rsi14"].to_numpy(dtype=float)
    volume = dec["volume"].to_numpy(dtype=float)
    m = len(dec)

    width = _bb_width(close)
    swings = find_swings(dec, n=N_SWING)
    conf_order = sorted(swings, key=lambda s: (s.confirmed_at, s.idx))

    conf_highs: list = []
    conf_lows: list = []
    broken: set[tuple[str, int]] = set()
    ptr = 0
    setups: list[SwingSetup] = []

    def vol_ok(i: int) -> bool:
        if i < VOL_LOOKBACK:
            return False
        base = volume[i - VOL_LOOKBACK: i].mean()
        return base > 0 and volume[i] >= VOL_MULT * base

    def bb_ok(i: int) -> bool:
        lo_edge = i - BB_LOOKBACK + 1
        if lo_edge < 0:
            return False
        window = width[lo_edge: i + 1]
        if np.isnan(window).any():
            return False
        return width[i] <= np.percentile(window, BB_PCTL)

    for i in range(m):
        while ptr < len(conf_order) and conf_order[ptr].confirmed_at <= i:
            s = conf_order[ptr]
            (conf_highs if s.kind == "high" else conf_lows).append(s)
            ptr += 1
        if len(conf_highs) < 2 or len(conf_lows) < 2 or atr[i] <= 0:
            continue
        h1, h2 = conf_highs[-1], conf_highs[-2]
        l1, l2 = conf_lows[-1], conf_lows[-2]
        trend_up = close[i] > ema50[i] and h1.price > h2.price and l1.price > l2.price
        trend_down = close[i] < ema50[i] and h1.price < h2.price and l1.price < l2.price

        if ("high", h1.idx) not in broken and close[i] > h1.price:
            broken.add(("high", h1.idx))
            if trend_up:
                entry = h1.price
                stop = l1.price - STOP_BUFFER_ATR * atr[i]
                risk = entry - stop
                if risk > 0:
                    setups.append(SwingSetup(
                        i, "LONG", float(entry), float(stop), float(entry + TARGET_R * risk),
                        vol_ok(i), bool(rsi[i] > RSI_MID), bb_ok(i)))

        if ("low", l1.idx) not in broken and close[i] < l1.price:
            broken.add(("low", l1.idx))
            if trend_down:
                entry = l1.price
                stop = h1.price + STOP_BUFFER_ATR * atr[i]
                risk = stop - entry
                if risk > 0:
                    setups.append(SwingSetup(
                        i, "SHORT", float(entry), float(stop), float(entry - TARGET_R * risk),
                        vol_ok(i), bool(rsi[i] < RSI_MID), bb_ok(i)))
    return setups


def passes_filter(setup: SwingSetup, variant: str | None) -> bool:
    if variant is None:
        return True
    if variant == "vol":
        return setup.vol_ok
    if variant == "rsi":
        return setup.rsi_ok
    if variant == "bb":
        return setup.bb_ok
    raise ValueError(f"unknown swing variant: {variant}")


def swing_plan(symbol: str, arm: str, row, setup: SwingSetup) -> Plan:
    """Limit retest plan at the broken level (frozen absolute geometry)."""
    return Plan(symbol, arm, setup.direction, "limit", row.decision_time,
                float(row.close), float(row.atr14),
                setup.level, setup.stop, setup.target, None, None, None, None)


def paired_baseline_plan(symbol: str, arm: str, row, setup: SwingSetup) -> Plan:
    """Paired control: market entry at the next 15m open with the SAME absolute
    stop and target DISTANCES carried over from the swing plan (spec section 3).

    Encoded via the engine's ATR-relative market mode: atr = risk distance,
    stop_mult = 1, target_mult = TARGET_R.
    """
    risk = abs(setup.level - setup.stop)
    return Plan(symbol, arm, setup.direction, "market", row.decision_time,
                float(row.close), risk, None, None, None, 1.0, TARGET_R, None, None)


def build_swing_decisions(sym_data, setups: list[SwingSetup], arm: str,
                          variant: str | None, paired: bool):
    """Full decision list for the engine: (decision_time, plan | None, trend)."""
    dec = sym_data.decisions
    chosen = {s.idx: s for s in setups if passes_filter(s, variant)}
    out = []
    for i in range(len(dec)):
        row = dec.iloc[i]
        setup = chosen.get(i)
        if setup is None:
            plan = None
        elif paired:
            plan = paired_baseline_plan(sym_data.symbol, arm, row, setup)
        else:
            plan = swing_plan(sym_data.symbol, arm, row, setup)
        out.append((row.decision_time, plan, None))
    return out
