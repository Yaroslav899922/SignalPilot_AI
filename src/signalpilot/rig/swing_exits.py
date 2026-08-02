"""Exit engine for hypothesis #7 ``swing_v2``: structural trailing stops.

Entries are IDENTICAL to swing_v1 (same detector, same limit plans). This
module only changes how an open trade is managed:

  * mode "fixed"  — behaves exactly like the shared engine (parity-tested);
  * mode "trail"  — no fixed target; after the fill, every NEWLY CONFIRMED
    opposite-side swing (low for LONG, high for SHORT) moves the stop to that
    swing price -/+ 0.25*ATR14 of the confirmation bar. The stop only ever
    ratchets in the trade's favour. Exit = (trailed) stop or a 30-day cap.

No look-ahead: a swing confirmed at bar ``idx + 2`` becomes usable only from
that bar's decision time (its close). Updates apply from the next 15m candle.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

import pandas as pd

from .engine import (_create_pending, _expire_pending, _finalize, _manage,
                     _open_trade, _try_fill, ArmResult, TIMEOUT)
from .structure import find_swings
from .swing import STOP_BUFFER_ATR, N_SWING

TRAIL_TIMEOUT_BARS_4H = 180   # 30 days safety cap


@dataclass
class StructureTrailer:
    """Confirmed-swing stop updates for one symbol (both directions)."""

    long_events: list   # sorted [(effective_time, stop_candidate)] from swing LOWS
    short_events: list  # from swing HIGHS

    @classmethod
    def from_decisions(cls, dec: pd.DataFrame) -> "StructureTrailer":
        atr = dec["atr14"].to_numpy(dtype=float)
        times = list(dec["decision_time"])
        longs, shorts = [], []
        for swing in find_swings(dec, n=N_SWING):
            if swing.confirmed_at >= len(dec):
                continue
            effective = times[swing.confirmed_at]
            buffer = STOP_BUFFER_ATR * atr[swing.confirmed_at]
            if buffer <= 0 or not math.isfinite(buffer):
                continue
            if swing.kind == "low":
                longs.append((effective, swing.price - buffer))
            else:
                shorts.append((effective, swing.price + buffer))
        longs.sort(key=lambda item: item[0])
        shorts.sort(key=lambda item: item[0])
        return cls(longs, shorts)

    def updated_stop(self, trade, now: pd.Timestamp) -> float | None:
        events = self.long_events if trade.direction == "LONG" else self.short_events
        keys = [event[0] for event in events]
        start = bisect.bisect_right(keys, trade.fill_time)
        end = bisect.bisect_right(keys, now)
        if start >= end:
            return None
        candidates = [events[i][1] for i in range(start, end)]
        best = max(candidates) if trade.direction == "LONG" else min(candidates)
        if trade.direction == "LONG" and best > trade.stop:
            return float(best)
        if trade.direction == "SHORT" and best < trade.stop:
            return float(best)
        return None


def simulate_plans_exits(symbol: str, arm: str, decisions, d15: pd.DataFrame,
                         rest_bars: int = 10,
                         timeout: pd.Timedelta = TIMEOUT,
                         trailer: StructureTrailer | None = None) -> ArmResult:
    """The engine loop with a trailing hook. lifetime is always "rest_bars".

    With ``trailer=None`` this is behaviourally identical to
    engine.simulate_plans(..., lifetime="rest_bars") — verified by a parity
    test byte-for-byte on the trade list.
    """
    result = ArmResult(arm=arm, symbol=symbol)
    if not decisions:
        return result
    norm = [(d[0], d[1], d[2] if len(d) > 2 else None) for d in decisions]
    dec_index = {t: (plan, trend) for t, plan, trend in norm}
    first_time = norm[0][0]

    window = d15.loc[d15["open_time"] >= first_time]
    pending = None
    trade = None

    for c in window.itertuples(index=False):
        t = c.open_time
        if t in dec_index:
            plan, _trend = dec_index[t]
            if trade is not None:
                if plan is not None:
                    result.plans_blocked += 1
            elif pending is not None:
                pending.age_windows += 1
                if plan is not None or pending.age_windows >= rest_bars:
                    _expire_pending(pending, result)
                    pending = _create_pending(plan, result) if plan is not None else None
            elif plan is not None:
                pending = _create_pending(plan, result)

        if trade is not None:
            if trailer is not None:
                new_stop = trailer.updated_stop(trade, t)
                if new_stop is not None:
                    trade.stop = new_stop
            ex = _manage(trade, c.open, c.high, c.low, c.close, t, timeout=timeout)
            if ex is not None:
                result.trades.append(_finalize(trade, ex[0], ex[1], t, zone_pierce=False))
                trade = None

        if trade is None and pending is not None:
            pending.hi = max(pending.hi, c.high)
            pending.lo = min(pending.lo, c.low)
            fill = _try_fill(pending.plan, c.open, c.high, c.low)
            if fill is not None:
                limit_fill = pending.plan.fill_mode == "limit"
                trade = _open_trade(pending.plan, fill, t)
                pending = None
                ex = _manage(trade, c.open, c.high, c.low, c.close, t,
                             suppress_target=limit_fill, timeout=timeout)
                if ex is not None:
                    zp = limit_fill and ex[0] == "stop"
                    result.trades.append(_finalize(trade, ex[0], ex[1], t, zone_pierce=zp))
                    trade = None

    if pending is not None:
        _expire_pending(pending, result)
    if trade is not None:
        last = window.iloc[-1]
        result.trades.append(_finalize(trade, "unresolved", float(last["close"]),
                                        last["open_time"], zone_pierce=False))
    return result
