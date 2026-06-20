from __future__ import annotations

from datetime import datetime, timezone
from html import escape

import pandas as pd

from .market_data import LiveMarketData, MarketFrame


_SESSION_MAP = {
    9: "Лондонська сесія",
    14: "Нью-Йоркська сесія",
}


def generate_brief(markets: list[LiveMarketData], now_utc: datetime | None = None) -> str:
    """Return an HTML-formatted Telegram market briefing from live candle data."""
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    session = _SESSION_MAP.get(now.hour, "Ринковий контроль")
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")
    header = f"📊 <b>SignalPilot market brief</b>\n{_h(session)} · {_h(now_str)}"

    blocks = [_symbol_block(market) for market in markets]
    blocks = [block for block in blocks if block]
    body = "\n\n".join(blocks) if blocks else "Дані не завантажились або ще не готові."

    parts = [
        header,
        "",
        body,
        "",
        f"<b>Висновок:</b> {_h(_brief_verdict(markets))}",
        "",
        "Це контрольний огляд живого ринку, не сигнал на вхід. LONG/SHORT приходять окремо тільки коли є чистий сетап.",
    ]
    return "\n".join(parts)


def _symbol_block(market: LiveMarketData) -> str:
    f1h = market.frames.get("1h")
    f4h = market.frames.get("4h")
    if not f1h or f1h.candles.empty:
        return ""

    row = f1h.candles.iloc[-1]
    price = _val(row, "close")
    rsi = _val(row, "rsi14")
    atr = _val(row, "atr14")
    ema20 = _val(row, "ema20")
    ema50 = _val(row, "ema50")
    support = _val(row, "recent_low20")
    resistance = _val(row, "recent_high20")

    symbol = market.symbol.replace("USDT", "")
    trend_4h = _trend_label(f4h)
    trend_1h = _price_vs_level(price, ema20)
    futures = _futures_context_label(market)

    return "\n".join(
        [
            f"<b>{_h(symbol)}</b> {_h(_price(price))} | 4h {_h(trend_4h)} · 1h {_h(trend_1h)}",
            f"RSI: {_h(_fmt(rsi, '.0f'))} ({_h(_rsi_label(rsi))}) · ATR: {_h(_price(atr))}",
            f"EMA20: {_h(_price(ema20))} ({_h(_pct(price, ema20))}) · EMA50: {_h(_price(ema50))} ({_h(_pct(price, ema50))})",
            f"Підтримка: {_h(_price(support))} · Опір: {_h(_price(resistance))}",
            f"Futures context: {_h(futures)}",
        ]
    )


def _brief_verdict(markets: list[LiveMarketData]) -> str:
    trend_votes = [_trend_direction(market.frames.get("4h")) for market in markets]
    trend_votes = [vote for vote in trend_votes if vote != "unknown"]
    if not trend_votes:
        return "недостатньо даних для оцінки, але збір свічок запустився."

    up = trend_votes.count("up")
    down = trend_votes.count("down")
    if up == len(trend_votes):
        return "старший таймфрейм переважно вгору; шукаємо тільки якісні LONG, без входу посередині руху."
    if down == len(trend_votes):
        return "старший таймфрейм переважно вниз; шукаємо тільки якісні SHORT, без погоні за ціною."
    if up and down:
        return "ринок змішаний між парами; режим більше для спостереження, ніж для агресивних входів."
    return "немає чіткої переваги; NO TRADE залишається нормальним рішенням."


def _futures_context_label(market: LiveMarketData) -> str:
    context = market.futures_context
    values = (
        context.funding_rate,
        context.open_interest,
        context.long_short_ratio,
        context.spread_pct,
    )
    if all(value is None for value in values):
        return "недоступний з GitHub Actions, не блокує brief"

    parts: list[str] = []
    if context.funding_rate is not None:
        parts.append(f"funding {context.funding_rate * 100:.4f}%")
    if context.open_interest is not None:
        parts.append(f"OI {context.open_interest:.0f}")
    if context.long_short_ratio is not None:
        parts.append(f"L/S {context.long_short_ratio:.2f}")
    if context.spread_pct is not None:
        parts.append(f"spread {context.spread_pct:.4f}%")
    return ", ".join(parts) if parts else "частково недоступний"


def _trend_label(frame: MarketFrame | None) -> str:
    direction = _trend_direction(frame)
    if direction == "up":
        return "↑ вище EMA50"
    if direction == "down":
        return "↓ нижче EMA50"
    return "→ невідомо"


def _trend_direction(frame: MarketFrame | None) -> str:
    if not frame or frame.candles.empty:
        return "unknown"
    row = frame.candles.iloc[-1]
    close = _val(row, "close")
    ema50 = _val(row, "ema50")
    if close is None or ema50 is None:
        return "unknown"
    return "up" if close > ema50 else "down"


def _price_vs_level(price: float | None, level: float | None) -> str:
    if price is None or level is None:
        return "→ невідомо"
    if price > level:
        return "↑ вище EMA20"
    if price < level:
        return "↓ нижче EMA20"
    return "→ біля EMA20"


def _rsi_label(rsi: float | None) -> str:
    if rsi is None:
        return "невідомо"
    if rsi >= 70:
        return "перегрітий"
    if rsi <= 30:
        return "слабкий/перепроданий"
    if rsi >= 55:
        return "покупці активні"
    if rsi <= 45:
        return "продавці активні"
    return "нейтрально"


def _val(row: pd.Series, key: str) -> float | None:
    value = row.get(key)
    return float(value) if value is not None and pd.notna(value) else None


def _price(value: float | None) -> str:
    if value is None:
        return "-"
    if value >= 1000:
        return f"${value:,.0f}"
    if value >= 10:
        return f"${value:.2f}"
    return f"${value:.4f}"


def _pct(price: float | None, level: float | None) -> str:
    if price is None or level is None or level == 0:
        return "-"
    return f"{(price - level) / level * 100:+.1f}%"


def _fmt(value: float | None, spec: str = ".2f") -> str:
    return "-" if value is None else format(value, spec)


def _h(value: object) -> str:
    return escape(str(value), quote=False)
