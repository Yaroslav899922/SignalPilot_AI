from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone

import pandas as pd

from .market import FuturesContext


FUNDING_OVERHEATED_ABS = 0.001
LONG_SHORT_RATIO_EXTREME_LOW = 0.5
LONG_SHORT_RATIO_EXTREME_HIGH = 2.0
MAX_SPREAD_PCT = 0.05
DEFAULT_TIMEFRAMES = ("15m", "1h", "4h")
CONFIRM_INTERVAL = "15m"
SETUP_INTERVAL = "1h"
TREND_INTERVAL = "4h"


@dataclass(frozen=True)
class Signal:
    symbol: str
    interval: str
    direction: str
    market_regime: str
    close_price: float | None
    funding_rate: float | None
    open_interest: float | None
    long_short_ratio: float | None
    spread_pct: float | None
    entry_zone: str
    stop: float | None
    targets: tuple[float, ...]
    risk_reward: float | None
    confidence: str
    invalidation: str
    reasons: tuple[str, ...]
    created_at: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["targets"] = list(self.targets)
        data["reasons"] = list(self.reasons)
        return data


def build_signal(
    symbol: str,
    interval: str,
    candles: pd.DataFrame,
    futures_context: FuturesContext | None = None,
) -> Signal:
    if candles.empty:
        return _no_trade(
            symbol,
            interval,
            market_regime="unknown",
            close_price=None,
            futures_context=futures_context,
            reasons=("No candle data available",),
        )

    row = candles.dropna(subset=["ema50", "ema200", "rsi14", "atr14", "recent_high20", "recent_low20"]).tail(1)
    if row.empty:
        close_price = float(candles.iloc[-1]["close"]) if "close" in candles.columns else None
        return _no_trade(
            symbol,
            interval,
            market_regime="unknown",
            close_price=close_price,
            futures_context=futures_context,
            reasons=("Not enough candles for EMA/RSI/ATR and local levels",),
        )

    last = row.iloc[0]
    close = float(last["close"])
    atr = float(last["atr14"])
    rsi = float(last["rsi14"])
    recent_high = float(last["recent_high20"])
    recent_low = float(last["recent_low20"])

    if atr <= 0:
        return _no_trade(
            symbol,
            interval,
            market_regime="unknown",
            close_price=close,
            futures_context=futures_context,
            reasons=("ATR is zero; stop distance cannot be calculated",),
        )

    trend = _trend(last)
    context_allows_signal, context_reasons = _context_reasons(futures_context)
    if trend == "up" and 45 <= rsi <= 70 and close > recent_high:
        if not context_allows_signal:
            return _no_trade(
                symbol,
                interval,
                market_regime=trend,
                close_price=close,
                futures_context=futures_context,
                reasons=(
                    f"Uptrend breakout candidate above recent high {recent_high:.2f}",
                    *context_reasons,
                ),
            )
        return _directional_signal(
            symbol=symbol,
            interval=interval,
            direction="LONG",
            market_regime=trend,
            close=close,
            stop=min(recent_low, close - (1.5 * atr)),
            futures_context=futures_context,
            reason=f"Uptrend with breakout above recent high {recent_high:.2f}",
            context_reasons=context_reasons,
        )

    if trend == "down" and 30 <= rsi <= 55 and close < recent_low:
        if not context_allows_signal:
            return _no_trade(
                symbol,
                interval,
                market_regime=trend,
                close_price=close,
                futures_context=futures_context,
                reasons=(
                    f"Downtrend breakdown candidate below recent low {recent_low:.2f}",
                    *context_reasons,
                ),
            )
        return _directional_signal(
            symbol=symbol,
            interval=interval,
            direction="SHORT",
            market_regime=trend,
            close=close,
            stop=max(recent_high, close + (1.5 * atr)),
            futures_context=futures_context,
            reason=f"Downtrend with breakdown below recent low {recent_low:.2f}",
            context_reasons=context_reasons,
        )

    return _no_trade(
        symbol,
        interval,
        market_regime=trend,
        close_price=close,
        futures_context=futures_context,
        reasons=(
            f"Market regime is {trend}",
            f"RSI is {rsi:.1f}",
            *context_reasons,
            "No clean trend + level + momentum setup with minimum 1:2 risk/reward",
        ),
    )


def build_multi_timeframe_signal(
    symbol: str,
    candles_by_interval: dict[str, pd.DataFrame],
    futures_context: FuturesContext | None = None,
    confirm_interval: str = CONFIRM_INTERVAL,
    setup_interval: str = SETUP_INTERVAL,
    trend_interval: str = TREND_INTERVAL,
) -> Signal:
    required_intervals = (confirm_interval, setup_interval, trend_interval)
    missing = [
        interval
        for interval in required_intervals
        if interval not in candles_by_interval or candles_by_interval[interval].empty
    ]
    if missing:
        return _no_trade(
            symbol,
            setup_interval,
            market_regime="unknown",
            close_price=None,
            futures_context=futures_context,
            reasons=(f"Missing timeframe data: {', '.join(missing)}",),
        )

    setup_candles = candles_by_interval[setup_interval]
    setup_signal = build_signal(symbol, setup_interval, setup_candles, futures_context)
    setup_row = _latest_ready_row(setup_candles, _SETUP_COLUMNS)
    trend_row = _latest_ready_row(candles_by_interval[trend_interval], _TREND_COLUMNS)
    confirm_row = _latest_ready_row(candles_by_interval[confirm_interval], _CONFIRM_COLUMNS)

    if setup_row is None or trend_row is None or confirm_row is None:
        return replace(
            setup_signal,
            direction="NO TRADE",
            entry_zone="",
            stop=None,
            targets=(),
            risk_reward=None,
            confidence="low",
            invalidation="Wait for complete multi-timeframe data",
            reasons=("Not enough indicator data for 15m/1h/4h confirmation", *setup_signal.reasons),
        )

    setup_trend = _trend(setup_row)
    higher_trend = _trend(trend_row)
    confirm_ok, confirm_reason = _confirm_lower_timeframe(confirm_row, setup_signal.direction)
    confirm_status = "confirmed" if confirm_ok else "not_confirmed"
    regime = f"{trend_interval}:{higher_trend}/{setup_interval}:{setup_trend}/{confirm_interval}:{confirm_status}"
    timeframe_reasons = (
        f"{trend_interval} regime is {higher_trend}",
        f"{setup_interval} regime is {setup_trend}",
        confirm_reason,
    )

    if setup_signal.direction == "NO TRADE":
        return replace(setup_signal, market_regime=regime, reasons=(*timeframe_reasons, *setup_signal.reasons))

    expected_trend = "up" if setup_signal.direction == "LONG" else "down"
    if higher_trend != expected_trend:
        return replace(
            setup_signal,
            direction="NO TRADE",
            market_regime=regime,
            entry_zone="",
            stop=None,
            targets=(),
            risk_reward=None,
            confidence="low",
            invalidation="Wait for higher timeframe alignment",
            reasons=(
                f"{trend_interval} trend is {higher_trend}, not aligned with {setup_signal.direction}",
                *timeframe_reasons,
                *setup_signal.reasons,
            ),
        )

    if not confirm_ok:
        return replace(
            setup_signal,
            direction="NO TRADE",
            market_regime=regime,
            entry_zone="",
            stop=None,
            targets=(),
            risk_reward=None,
            confidence="low",
            invalidation="Wait for lower timeframe confirmation",
            reasons=(
                f"{confirm_interval} does not confirm {setup_signal.direction}",
                *timeframe_reasons,
                *setup_signal.reasons,
            ),
        )

    return replace(
        setup_signal,
        market_regime=regime,
        reasons=(f"Multi-timeframe confirmation: {trend_interval} trend + {setup_interval} setup + {confirm_interval} trigger", *timeframe_reasons, *setup_signal.reasons),
    )


def _directional_signal(
    symbol: str,
    interval: str,
    direction: str,
    market_regime: str,
    close: float,
    stop: float,
    futures_context: FuturesContext | None,
    reason: str,
    context_reasons: tuple[str, ...],
) -> Signal:
    risk = abs(close - stop)
    target = close + (2 * risk) if direction == "LONG" else close - (2 * risk)
    entry_buffer = risk * 0.1
    entry_low = close - entry_buffer
    entry_high = close + entry_buffer

    return Signal(
        symbol=symbol.upper(),
        interval=interval,
        direction=direction,
        market_regime=market_regime,
        close_price=round(close, 2),
        funding_rate=_funding_rate(futures_context),
        open_interest=_open_interest(futures_context),
        long_short_ratio=_long_short_ratio(futures_context),
        spread_pct=_spread_pct(futures_context),
        entry_zone=f"{entry_low:.2f}-{entry_high:.2f}",
        stop=round(stop, 2),
        targets=(round(target, 2),),
        risk_reward=2.0,
        confidence="medium",
        invalidation=f"{direction} invalid if price closes beyond stop {stop:.2f}",
        reasons=(reason, *context_reasons, "Risk/reward meets minimum 1:2"),
        created_at=_now(),
    )


def _trend(row: pd.Series) -> str:
    close = float(row["close"])
    ema50 = float(row["ema50"])
    ema200 = float(row["ema200"])

    if close > ema50 > ema200:
        return "up"
    if close < ema50 < ema200:
        return "down"
    return "range"


def _latest_ready_row(candles: pd.DataFrame, required_columns: tuple[str, ...]) -> pd.Series | None:
    missing = set(required_columns) - set(candles.columns)
    if missing:
        return None

    rows = candles.dropna(subset=list(required_columns)).tail(1)
    if rows.empty:
        return None
    return rows.iloc[0]


def _confirm_lower_timeframe(row: pd.Series, direction: str) -> tuple[bool, str]:
    close = float(row["close"])
    ema20 = float(row["ema20"])
    rsi = float(row["rsi14"])

    if direction == "LONG":
        ok = close > ema20 and 45 <= rsi <= 75
        return ok, f"15m confirmation: close {'above' if close > ema20 else 'below'} EMA20, RSI {rsi:.1f}"
    if direction == "SHORT":
        ok = close < ema20 and 25 <= rsi <= 55
        return ok, f"15m confirmation: close {'below' if close < ema20 else 'above'} EMA20, RSI {rsi:.1f}"
    return False, "15m confirmation skipped because 1h setup is NO TRADE"


def _context_reasons(futures_context: FuturesContext | None) -> tuple[bool, tuple[str, ...]]:
    if futures_context is None:
        return False, ("Futures context unavailable: funding/open interest confirmation missing",)

    reasons: list[str] = []
    allows_signal = True

    if futures_context.funding_rate is None:
        reasons.append("Funding rate unavailable")
        allows_signal = False
    else:
        reasons.append(f"Funding rate is {_format_percent(futures_context.funding_rate)}")
        if abs(futures_context.funding_rate) >= FUNDING_OVERHEATED_ABS:
            reasons.append("Funding rate is overheated")
            allows_signal = False

    if futures_context.open_interest is None:
        reasons.append("Open interest unavailable")
        allows_signal = False
    elif futures_context.open_interest <= 0:
        reasons.append("Open interest is invalid")
        allows_signal = False
    else:
        reasons.append(f"Open interest is {futures_context.open_interest:.3f}")

    if futures_context.long_short_ratio is None:
        reasons.append("Long/short ratio unavailable")
        allows_signal = False
    else:
        reasons.append(f"Long/short ratio is {futures_context.long_short_ratio:.3f}")
        if not LONG_SHORT_RATIO_EXTREME_LOW <= futures_context.long_short_ratio <= LONG_SHORT_RATIO_EXTREME_HIGH:
            reasons.append("Long/short ratio is crowded")
            allows_signal = False

    if futures_context.spread_pct is None:
        reasons.append("Order book spread unavailable")
        allows_signal = False
    else:
        reasons.append(f"Order book spread is {futures_context.spread_pct:.4f}%")
        if futures_context.spread_pct > MAX_SPREAD_PCT:
            reasons.append("Order book spread is too wide")
            allows_signal = False

    return allows_signal, tuple(reasons)


def _no_trade(
    symbol: str,
    interval: str,
    market_regime: str,
    close_price: float | None,
    futures_context: FuturesContext | None,
    reasons: tuple[str, ...],
) -> Signal:
    return Signal(
        symbol=symbol.upper(),
        interval=interval,
        direction="NO TRADE",
        market_regime=market_regime,
        close_price=round(close_price, 2) if close_price is not None else None,
        funding_rate=_funding_rate(futures_context),
        open_interest=_open_interest(futures_context),
        long_short_ratio=_long_short_ratio(futures_context),
        spread_pct=_spread_pct(futures_context),
        entry_zone="",
        stop=None,
        targets=(),
        risk_reward=None,
        confidence="low",
        invalidation="Wait for a cleaner setup with a defined stop",
        reasons=reasons,
        created_at=_now(),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _funding_rate(futures_context: FuturesContext | None) -> float | None:
    return None if futures_context is None else futures_context.funding_rate


def _open_interest(futures_context: FuturesContext | None) -> float | None:
    return None if futures_context is None else futures_context.open_interest


def _long_short_ratio(futures_context: FuturesContext | None) -> float | None:
    return None if futures_context is None else futures_context.long_short_ratio


def _spread_pct(futures_context: FuturesContext | None) -> float | None:
    return None if futures_context is None else futures_context.spread_pct


def _format_percent(value: float) -> str:
    return f"{value * 100:.4f}%"


_SETUP_COLUMNS = ("ema50", "ema200", "rsi14", "atr14", "recent_high20", "recent_low20")
_TREND_COLUMNS = ("close", "ema50", "ema200")
_CONFIRM_COLUMNS = ("close", "ema20", "rsi14")
