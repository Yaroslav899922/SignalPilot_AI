from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from .brief import (
    _atr_label,
    _fmt,
    _h,
    _macd_label,
    _one_hour_state,
    _price,
    _rsi_label,
    _trend_state,
    _val,
    _volume_label,
)
from .market_data import LiveMarketData, MarketFrame


_KYIV_TZ = ZoneInfo("Europe/Kyiv")
_SESSION_WINDOWS = (
    ("Азія", 2 * 60, 12 * 60),
    ("Лондон", 11 * 60, 20 * 60),
    ("Нью-Йорк", 16 * 60, 1 * 60),
)


def generate_move_alerts(
    markets: list[LiveMarketData],
    threshold_pct: float = 1.5,
    now_utc: datetime | None = None,
) -> list[str]:
    """Return Telegram alerts for sharp latest-closed 15m candle moves."""
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_kyiv = now.astimezone(_KYIV_TZ)

    alerts = []
    for market in markets:
        alert = _market_move_alert(market, threshold_pct, now_kyiv)
        if alert:
            alerts.append(alert)
    return alerts


def _market_move_alert(market: LiveMarketData, threshold_pct: float, now_kyiv: datetime) -> str:
    f15m = market.frames.get("15m")
    if not f15m or f15m.candles.empty:
        return ""

    row = f15m.candles.iloc[-1]
    open_price = _val(row, "open")
    close_price = _val(row, "close")
    if open_price is None or open_price <= 0 or close_price is None:
        return ""

    move_pct = (close_price - open_price) / open_price * 100
    if abs(move_pct) < threshold_pct:
        return ""

    direction = "LONG" if move_pct > 0 else "SHORT"
    previous_row = f15m.candles.iloc[-2] if len(f15m.candles) > 1 else None
    return _format_alert(
        market=market,
        f15m=f15m,
        row=row,
        previous_row=previous_row,
        move_pct=move_pct,
        direction=direction,
        now_kyiv=now_kyiv,
    )


def _format_alert(
    market: LiveMarketData,
    f15m: MarketFrame,
    row: pd.Series,
    previous_row: pd.Series | None,
    move_pct: float,
    direction: str,
    now_kyiv: datetime,
) -> str:
    f1h = market.frames.get("1h")
    f4h = market.frames.get("4h")
    level_frame = f1h if f1h and not f1h.candles.empty else f15m
    level_row = level_frame.candles.iloc[-1]

    price = _val(row, "close")
    rsi = _val(row, "rsi14")
    macd_hist = _val(row, "macd_hist")
    previous_macd_hist = _val(previous_row, "macd_hist") if previous_row is not None else None
    volume = _val(row, "volume")
    volume_avg20 = _val(row, "volume_avg20")

    ema20_1h = _val(level_row, "ema20")
    support = _val(level_row, "recent_low20")
    resistance = _val(level_row, "recent_high20")
    atr = _val(level_row, "atr14")

    symbol = market.symbol.replace("USDT", "")
    now_str = now_kyiv.strftime("%d.%m · %H:%M Київ")
    session = _active_session_label(now_kyiv)
    macd = _macd_label(macd_hist, previous_macd_hist)

    return "\n".join(
        [
            f"⚡ <b>SignalPilot Move Alert</b>\n{_h(now_str)} · {_h(session)}",
            "",
            f"<b><u>{_h(symbol)}</u></b> {_h(_price(price))}",
            f"<b>Рух:</b> {_h(_signed_pct(move_pct))} за 15m",
            f"<b>Стан:</b> 4h {_h(_trend_state(f4h))}, 1h {_h(_one_hour_state(price, ema20_1h))}",
            f"<b>Імпульс:</b> RSI {_h(_fmt(rsi, '.0f'))} ({_h(_rsi_label(rsi))}), MACD histogram {_h(macd)}",
            f"<b>Обʼєм 15m:</b> {_h(_volume_label(volume, volume_avg20, price, symbol))}",
            f"<b>Рівні:</b> підтримка {_h(_price(support))} · опір {_h(_price(resistance))}",
            f"<b>ATR:</b> {_h(_price(atr))} — {_h(_atr_label(atr, price))}",
            _direction_setup_block(direction, support, resistance),
        ]
    )


def _direction_setup_block(direction: str, support: float | None, resistance: float | None) -> str:
    resistance_text = _price(resistance)
    support_text = _price(support)
    if direction == "LONG":
        return "\n".join(
            [
                "<blockquote expandable>",
                "<b>Готуватись до LONG:</b>",
                f"15m/1h close &gt; {_h(resistance_text)}",
                f"+ ретест {_h(resistance_text)} зверху",
                "+ 15m тримається вище EMA20",
                "+ MACD histogram росте",
                "+ обʼєм 15m/1h на пробої &gt; 1.2x avg20",
                "</blockquote>",
            ]
        )
    return "\n".join(
        [
            "<blockquote expandable>",
            "<b>Готуватись до SHORT:</b>",
            f"15m/1h close &lt; {_h(support_text)}",
            f"+ ретест {_h(support_text)} знизу",
            "+ 15m нижче EMA20",
            "+ MACD histogram падає",
            "+ обʼєм 15m/1h на пробої &gt; 1.2x avg20",
            "</blockquote>",
        ]
    )


def _active_session_label(now_kyiv: datetime) -> str:
    minute = now_kyiv.hour * 60 + now_kyiv.minute
    sessions = [
        name
        for name, start, end in _SESSION_WINDOWS
        if _in_session_window(minute, start, end)
    ]
    return " + ".join(sessions) if sessions else "поза сесіями"


def _in_session_window(minute: int, start: int, end: int) -> bool:
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def _signed_pct(value: float) -> str:
    return f"{value:+.1f}%"
