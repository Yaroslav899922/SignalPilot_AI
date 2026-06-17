from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .market import FuturesContext
from .market_data import LiveMarketData
from .regime import classify_trend, volatility_state
from .signals import (
    FUNDING_OVERHEATED_ABS,
    LONG_SHORT_RATIO_EXTREME_HIGH,
    LONG_SHORT_RATIO_EXTREME_LOW,
    MAX_SPREAD_PCT,
)
from .trade_plan import TradePlan, build_retest_plan


@dataclass(frozen=True)
class PatternSetup:
    symbol: str
    pattern: str
    direction: str
    timeframe: str
    market_regime: str
    close_price: float
    score: float
    quality: str
    plan: TradePlan
    reasons: tuple[str, ...]
    futures_context: FuturesContext
    source: str = "signalpilot"


def detect_breakout_retest(market: LiveMarketData) -> PatternSetup | None:
    setup_row = _latest_ready_row(market.frame("1h").candles, _SETUP_COLUMNS)
    trend_row = _latest_ready_row(market.frame("4h").candles, _TREND_COLUMNS)
    confirm_row = _latest_ready_row(market.frame("15m").candles, _CONFIRM_COLUMNS)
    if setup_row is None or trend_row is None or confirm_row is None:
        return None

    trend = classify_trend(trend_row)
    setup_trend = classify_trend(setup_row)
    vol = volatility_state(setup_row)
    regime = f"4h:{trend}/1h:{setup_trend}/vol:{vol}"

    if trend == "up" and setup_trend == "up":
        setup = _long_breakout_retest(market, setup_row, confirm_row, regime)
    elif trend == "down" and setup_trend == "down":
        setup = _short_breakout_retest(market, setup_row, confirm_row, regime)
    else:
        return None

    if setup is None:
        return None
    return setup if _context_allows(market.futures_context)[0] else None


def explain_no_breakout_retest(market: LiveMarketData) -> tuple[str, ...]:
    reasons: list[str] = []
    try:
        setup_row = _latest_ready_row(market.frame("1h").candles, _SETUP_COLUMNS)
        trend_row = _latest_ready_row(market.frame("4h").candles, _TREND_COLUMNS)
        confirm_row = _latest_ready_row(market.frame("15m").candles, _CONFIRM_COLUMNS)
    except KeyError as error:
        return (f"Missing timeframe data: {error}",)

    if setup_row is None or trend_row is None or confirm_row is None:
        return ("Not enough complete indicator data for 15m/1h/4h live analyst",)

    trend = classify_trend(trend_row)
    setup_trend = classify_trend(setup_row)
    reasons.append(f"4h regime is {trend}")
    reasons.append(f"1h regime is {setup_trend}")
    reasons.append(f"1h volatility is {volatility_state(setup_row)}")
    context_ok, context_reasons = _context_allows(market.futures_context)
    reasons.extend(context_reasons)
    if not context_ok:
        reasons.append("Futures context blocks professional alert")
    reasons.append("No breakout + retest setup with clean level, stop, target, and confirmation")
    return tuple(reasons)


def _long_breakout_retest(
    market: LiveMarketData,
    setup_row: pd.Series,
    confirm_row: pd.Series,
    regime: str,
) -> PatternSetup | None:
    close = float(setup_row["close"])
    low = float(setup_row["low"])
    open_ = float(setup_row["open"]) if "open" in setup_row else close
    atr = float(setup_row["atr14"])
    level = float(setup_row["recent_high20"])
    recent_low = float(setup_row["recent_low20"])
    retest_zone_high = level + 0.25 * atr

    if close < level or low > retest_zone_high or close <= open_:
        return None
    if not _confirm_long(confirm_row):
        return None

    plan = build_retest_plan("LONG", close=close, level=level, atr=atr, recent_extreme=recent_low)
    score, quality = _score_setup(close, level, atr, market.futures_context)
    if quality == "low":
        return None
    reasons = (
        f"Pattern breakout_retest LONG: 1h broke and retested level {level:.2f}",
        f"4h trend supports LONG",
        f"Retest held: low {low:.2f}, close {close:.2f}",
        _confirm_reason(confirm_row, "LONG"),
        *_context_allows(market.futures_context)[1],
        f"Trailing plan: {plan.trailing_plan}",
        "No auto-trading; alert is for manual confirmation and journaling",
    )
    return PatternSetup(
        symbol=market.symbol,
        pattern="breakout_retest",
        direction="LONG",
        timeframe="1h",
        market_regime=regime,
        close_price=round(close, 2),
        score=score,
        quality=quality,
        plan=plan,
        reasons=reasons,
        futures_context=market.futures_context,
        source=market.source,
    )


def _short_breakout_retest(
    market: LiveMarketData,
    setup_row: pd.Series,
    confirm_row: pd.Series,
    regime: str,
) -> PatternSetup | None:
    close = float(setup_row["close"])
    high = float(setup_row["high"])
    open_ = float(setup_row["open"]) if "open" in setup_row else close
    atr = float(setup_row["atr14"])
    level = float(setup_row["recent_low20"])
    recent_high = float(setup_row["recent_high20"])
    retest_zone_low = level - 0.25 * atr

    if close > level or high < retest_zone_low or close >= open_:
        return None
    if not _confirm_short(confirm_row):
        return None

    plan = build_retest_plan("SHORT", close=close, level=level, atr=atr, recent_extreme=recent_high)
    score, quality = _score_setup(close, level, atr, market.futures_context)
    if quality == "low":
        return None
    reasons = (
        f"Pattern breakout_retest SHORT: 1h broke and retested level {level:.2f}",
        f"4h trend supports SHORT",
        f"Retest held: high {high:.2f}, close {close:.2f}",
        _confirm_reason(confirm_row, "SHORT"),
        *_context_allows(market.futures_context)[1],
        f"Trailing plan: {plan.trailing_plan}",
        "No auto-trading; alert is for manual confirmation and journaling",
    )
    return PatternSetup(
        symbol=market.symbol,
        pattern="breakout_retest",
        direction="SHORT",
        timeframe="1h",
        market_regime=regime,
        close_price=round(close, 2),
        score=score,
        quality=quality,
        plan=plan,
        reasons=reasons,
        futures_context=market.futures_context,
        source=market.source,
    )


def _context_allows(context: FuturesContext) -> tuple[bool, tuple[str, ...]]:
    allows = True
    reasons: list[str] = []
    if context.funding_rate is None:
        allows = False
        reasons.append("Funding rate unavailable")
    else:
        reasons.append(f"Funding rate is {context.funding_rate * 100:.4f}%")
        if abs(context.funding_rate) >= FUNDING_OVERHEATED_ABS:
            allows = False
            reasons.append("Funding rate is overheated")

    if context.open_interest is None or context.open_interest <= 0:
        allows = False
        reasons.append("Open interest unavailable")
    else:
        reasons.append(f"Open interest is {context.open_interest:.3f}")

    if context.long_short_ratio is None:
        allows = False
        reasons.append("Long/short ratio unavailable")
    else:
        reasons.append(f"Long/short ratio is {context.long_short_ratio:.3f}")
        if not LONG_SHORT_RATIO_EXTREME_LOW <= context.long_short_ratio <= LONG_SHORT_RATIO_EXTREME_HIGH:
            allows = False
            reasons.append("Long/short ratio is crowded")

    if context.spread_pct is None:
        allows = False
        reasons.append("Order book spread unavailable")
    else:
        reasons.append(f"Order book spread is {context.spread_pct:.4f}%")
        if context.spread_pct > MAX_SPREAD_PCT:
            allows = False
            reasons.append("Order book spread is too wide")

    return allows, tuple(reasons)


def _score_setup(close: float, level: float, atr: float, context: FuturesContext) -> tuple[float, str]:
    distance_atr = abs(close - level) / atr if atr > 0 else 99.0
    score = 100.0
    score -= min(distance_atr * 25.0, 35.0)
    if context.spread_pct is not None:
        score -= min(context.spread_pct * 100.0, 10.0)
    if context.long_short_ratio is not None:
        score -= min(abs(context.long_short_ratio - 1.0) * 5.0, 10.0)
    score = max(0.0, round(score, 1))
    if score >= 75:
        return score, "high"
    if score >= 55:
        return score, "medium"
    return score, "low"


def _latest_ready_row(candles: pd.DataFrame, required_columns: tuple[str, ...]) -> pd.Series | None:
    missing = set(required_columns) - set(candles.columns)
    if missing:
        return None
    rows = candles.dropna(subset=list(required_columns)).tail(1)
    if rows.empty:
        return None
    return rows.iloc[0]


def _confirm_long(row: pd.Series) -> bool:
    return float(row["close"]) > float(row["ema20"]) and 45 <= float(row["rsi14"]) <= 75


def _confirm_short(row: pd.Series) -> bool:
    return float(row["close"]) < float(row["ema20"]) and 25 <= float(row["rsi14"]) <= 55


def _confirm_reason(row: pd.Series, direction: str) -> str:
    close = float(row["close"])
    ema20 = float(row["ema20"])
    rsi = float(row["rsi14"])
    side = "above" if close > ema20 else "below"
    return f"15m confirmation for {direction}: close {side} EMA20, RSI {rsi:.1f}"


_SETUP_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "ema50",
    "ema200",
    "atr14",
    "rsi14",
    "recent_high20",
    "recent_low20",
)
_TREND_COLUMNS = ("close", "ema50", "ema200")
_CONFIRM_COLUMNS = ("close", "ema20", "rsi14")
