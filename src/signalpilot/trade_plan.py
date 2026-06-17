from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TradePlan:
    entry_low: float
    entry_high: float
    reference_entry: float
    stop: float
    targets: tuple[float, ...]
    invalidation: str
    trailing_plan: str

    @property
    def entry_zone(self) -> str:
        low, high = sorted((self.entry_low, self.entry_high))
        return f"{low:.2f}-{high:.2f}"

    @property
    def risk_reward(self) -> float | None:
        if not self.targets:
            return None
        risk = abs(self.reference_entry - self.stop)
        if risk <= 0:
            return None
        reward = abs(self.targets[0] - self.reference_entry)
        return round(reward / risk, 2)


def build_retest_plan(
    direction: str,
    close: float,
    level: float,
    atr: float,
    recent_extreme: float,
    entry_width_atr: float = 0.25,
    stop_atr: float = 1.0,
    target_r: float = 2.0,
) -> TradePlan:
    width = entry_width_atr * atr
    if direction == "LONG":
        entry_low = level
        entry_high = level + width
        stop = min(recent_extreme, level - stop_atr * atr)
        risk = close - stop
        target = close + target_r * risk
        invalidation = f"LONG invalid if 1h closes below retest level {level:.2f} or stop {stop:.2f}"
        trailing = "After +1R, move stop to breakeven; after target 1, trail below 15m EMA20 or latest 15m swing low."
    else:
        entry_low = level - width
        entry_high = level
        stop = max(recent_extreme, level + stop_atr * atr)
        risk = stop - close
        target = close - target_r * risk
        invalidation = f"SHORT invalid if 1h closes above retest level {level:.2f} or stop {stop:.2f}"
        trailing = "After +1R, move stop to breakeven; after target 1, trail above 15m EMA20 or latest 15m swing high."

    return TradePlan(
        entry_low=float(entry_low),
        entry_high=float(entry_high),
        reference_entry=float(close),
        stop=round(float(stop), 2),
        targets=(round(float(target), 2),),
        invalidation=invalidation,
        trailing_plan=trailing,
    )
