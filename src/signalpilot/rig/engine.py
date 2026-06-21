"""The shared trade simulator.

One engine, three arms. Each arm only differs in *how a plan is created*; the
fill / management / accounting rules below are identical for all of them so the
comparison is honest.

Rules (from the measurement spec + two independent reviews):
  * fills and management are checked on 15m candles;
  * stop is assumed before target within a candle (conservative);
  * a LIMIT fill does NOT get credit for the target in its own fill candle
    (intra-candle order is unprovable without tick data) — only a same-candle
    stop is allowed, and that is flagged as zone_pierce;
  * timeout fires at the bar boundary and exits at the candle OPEN (no look-ahead);
  * one open trade per symbol;
  * lifetime "one_window": a new 4h plan cancels the old pending limit;
    lifetime "until_trend": the pending limit rests (frozen) until the 4h trend
    breaks or it fills (models a resting order a manual trader leaves on);
  * a trade lives only by stop / target / timeout (12 4h-bars);
  * cost = 0.15% round-trip, converted into R as fee% * entry / risk_distance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import pandas as pd

from .plans import Plan, trend as plan_trend

TIMEOUT_BARS_4H = 12
TIMEOUT = pd.Timedelta(hours=4 * TIMEOUT_BARS_4H)
FEE_ROUND_TRIP = 0.0015
MISSED_MOVE_ATR = 1.0
BAR_4H = pd.Timedelta(hours=4)
_KYIV = ZoneInfo("Europe/Kyiv")


def kyiv_session(ts: pd.Timestamp) -> str:
    hour = ts.tz_convert(_KYIV).hour
    return "visible" if 7 <= hour <= 23 else "night"


@dataclass
class Trade:
    symbol: str
    arm: str
    direction: str
    fill_mode: str
    created_time: pd.Timestamp
    fill_time: pd.Timestamp
    atr: float
    entry: float
    stop: float
    target: float


@dataclass
class _Pending:
    plan: Plan
    hi: float = -math.inf
    lo: float = math.inf


@dataclass
class ClosedTrade:
    symbol: str
    arm: str
    direction: str
    created_time: pd.Timestamp
    fill_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry: float
    stop: float
    target: float
    exit_price: float
    outcome: str
    gross_R: float
    cost_R: float
    net_R: float
    hold_bars_4h: float
    fill_age_4h: float
    zone_pierce: bool
    session: str
    month: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ArmResult:
    arm: str
    symbol: str
    trades: list = field(default_factory=list)
    plans_created: int = 0
    plans_blocked: int = 0
    pending_expired: int = 0
    missed_move: int = 0
    plans_created_visible: int = 0
    pending_expired_visible: int = 0
    missed_move_visible: int = 0


def _open_trade(plan: Plan, fill_price: float, fill_time: pd.Timestamp) -> Trade:
    sign = 1.0 if plan.direction == "LONG" else -1.0
    if plan.fill_mode == "market":
        entry = fill_price
        stop = plan.stop if plan.stop is not None else entry - sign * plan.stop_mult * plan.atr
        target = plan.target if plan.target is not None else entry + sign * plan.target_mult * plan.atr
    else:
        entry, stop, target = plan.entry, plan.stop, plan.target
    return Trade(plan.symbol, plan.arm, plan.direction, plan.fill_mode,
                 plan.created_time, fill_time, plan.atr, float(entry), float(stop), float(target))


def _try_fill(plan: Plan, open_, high, low) -> float | None:
    if plan.fill_mode == "market":
        return float(open_)
    if plan.direction == "LONG" and low <= plan.entry:
        return float(plan.entry)
    if plan.direction == "SHORT" and high >= plan.entry:
        return float(plan.entry)
    return None


def _manage(trade: Trade, open_, high, low, close, now: pd.Timestamp, suppress_target: bool = False):
    """Return (outcome, exit_price) or None.

    Order of checks: timeout (at bar open) -> stop -> target. Stop is assumed
    before target. On a limit fill candle, suppress_target hides the target.
    """
    if now - trade.fill_time >= TIMEOUT:
        return "timeout", float(open_)
    if trade.direction == "LONG":
        if low <= trade.stop:
            return "stop", trade.stop
        if not suppress_target and high >= trade.target:
            return "target", trade.target
    else:
        if high >= trade.stop:
            return "stop", trade.stop
        if not suppress_target and low <= trade.target:
            return "target", trade.target
    return None


def _finalize(trade: Trade, outcome: str, exit_price: float, exit_time: pd.Timestamp,
              zone_pierce: bool) -> ClosedTrade:
    risk = abs(trade.entry - trade.stop)
    if trade.direction == "LONG":
        gross_R = (exit_price - trade.entry) / risk
    else:
        gross_R = (trade.entry - exit_price) / risk
    cost_R = FEE_ROUND_TRIP * trade.entry / risk
    net_R = gross_R - cost_R
    hold = (exit_time - trade.fill_time) / BAR_4H
    fill_age = (trade.fill_time - trade.created_time) / BAR_4H
    return ClosedTrade(
        symbol=trade.symbol, arm=trade.arm, direction=trade.direction,
        created_time=trade.created_time, fill_time=trade.fill_time, exit_time=exit_time,
        entry=trade.entry, stop=trade.stop, target=trade.target, exit_price=float(exit_price),
        outcome=outcome, gross_R=gross_R, cost_R=cost_R, net_R=net_R,
        hold_bars_4h=float(hold), fill_age_4h=float(fill_age), zone_pierce=zone_pierce,
        session=kyiv_session(trade.created_time), month=trade.created_time.strftime("%Y-%m"),
    )


def _missed(pending: _Pending) -> bool:
    plan = pending.plan
    if plan.direction == "LONG":
        return (pending.hi - plan.created_close) >= MISSED_MOVE_ATR * plan.atr
    return (plan.created_close - pending.lo) >= MISSED_MOVE_ATR * plan.atr


def _create_pending(plan: Plan, result: ArmResult) -> _Pending:
    result.plans_created += 1
    result.plans_created_visible += kyiv_session(plan.created_time) == "visible"
    return _Pending(plan)


def _expire_pending(pending: _Pending, result: ArmResult) -> None:
    vis = kyiv_session(pending.plan.created_time) == "visible"
    result.pending_expired += 1
    result.pending_expired_visible += vis
    if _missed(pending):
        result.missed_move += 1
        result.missed_move_visible += vis


def _trend_supports(direction: str, trend: str | None) -> bool:
    return (direction == "LONG" and trend == "up") or (direction == "SHORT" and trend == "down")


def simulate_plans(symbol: str, arm: str, decisions, d15: pd.DataFrame,
                   lifetime: str = "one_window") -> ArmResult:
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
            plan, trend = dec_index[t]
            if lifetime == "until_trend":
                if trade is not None:
                    if plan is not None:
                        result.plans_blocked += 1
                elif pending is not None:
                    if not _trend_supports(pending.plan.direction, trend):
                        _expire_pending(pending, result)
                        pending = _create_pending(plan, result) if plan is not None else None
                    # else: keep the resting order frozen
                elif plan is not None:
                    pending = _create_pending(plan, result)
            else:  # one_window
                if pending is not None:
                    _expire_pending(pending, result)
                    pending = None
                if trade is not None:
                    if plan is not None:
                        result.plans_blocked += 1
                elif plan is not None:
                    pending = _create_pending(plan, result)

        if trade is not None:
            ex = _manage(trade, c.open, c.high, c.low, c.close, t)
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
                ex = _manage(trade, c.open, c.high, c.low, c.close, t, suppress_target=limit_fill)
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


def build_decisions(sym_data, arm: str):
    from . import plans as plan_mod
    dec = sym_data.decisions
    out = []
    for i in range(len(dec)):
        row = dec.iloc[i]
        trend = plan_trend(float(row.close), float(row.ema50), float(row.ema200))
        if arm == "pullback_v1":
            plan = plan_mod.pullback_v1(sym_data.symbol, row)
        elif arm == "baseline":
            plan = plan_mod.baseline(sym_data.symbol, row)
        elif arm == "pifagor_s1":
            plan = plan_mod.pifagor_s1(sym_data.symbol, dec, i)
        else:
            raise ValueError(f"unknown arm: {arm}")
        out.append((row.decision_time, plan, trend))
    return out


def simulate(sym_data, arm: str, lifetime: str = "one_window") -> ArmResult:
    decisions = build_decisions(sym_data, arm)
    return simulate_plans(sym_data.symbol, arm, decisions, sym_data.bars15m, lifetime=lifetime)
