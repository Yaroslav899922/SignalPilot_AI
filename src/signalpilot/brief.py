from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd

from .market_data import LiveMarketData, MarketFrame


_SESSION_MAP = {
    12: "Лондонська сесія",
    17: "Нью-Йоркська сесія",
}
_KYIV_TZ = ZoneInfo("Europe/Kyiv")


def generate_brief(markets: list[LiveMarketData], now_utc: datetime | None = None) -> str:
    """Return an HTML-formatted Telegram market briefing from live candle data."""
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(_KYIV_TZ)

    session = _SESSION_MAP.get(now.hour, "Ринковий контроль")
    now_str = now.strftime("%d.%m · %H:%M Київ")
    header = f"📊 <b>SignalPilot Market Brief</b>\n{_h(now_str)} · {_h(session)}"

    blocks = [_symbol_block(market) for market in markets]
    blocks = [block for block in blocks if block]
    body = "\n\n".join(blocks) if blocks else "Дані не завантажились або ще не готові."

    parts = [
        header,
        "",
        body,
        "",
        "<b>Висновок:</b>",
        _h(_brief_verdict(markets)),
        "",
        "<b>Чекаємо окремий LONG/SHORT тільки якщо:</b>",
        "1h пробій + ретест рівня,",
        "15m підтвердження імпульсу,",
        "MACD histogram підтверджує напрямок,",
        "обʼєм 1h на пробої > 1.2x avg20,",
        "чіткий стоп і risk/reward мінімум 1:2.",
        "",
        _h(_futures_context_note(markets)),
        "Це контрольний огляд живого ринку, не сигнал на вхід.",
    ]
    return "\n".join(parts)


def _symbol_block(market: LiveMarketData) -> str:
    f1h = market.frames.get("1h")
    f4h = market.frames.get("4h")
    if not f1h or f1h.candles.empty:
        return ""

    row = f1h.candles.iloc[-1]
    previous_row = f1h.candles.iloc[-2] if len(f1h.candles) > 1 else None
    price = _val(row, "close")
    rsi = _val(row, "rsi14")
    atr = _val(row, "atr14")
    ema20 = _val(row, "ema20")
    ema50 = _val(row, "ema50")
    macd_hist = _val(row, "macd_hist")
    previous_macd_hist = _val(previous_row, "macd_hist") if previous_row is not None else None
    volume = _val(row, "volume")
    volume_avg20 = _val(row, "volume_avg20")
    support = _val(row, "recent_low20")
    resistance = _val(row, "recent_high20")

    symbol = market.symbol.replace("USDT", "")
    base_asset = symbol
    trend_4h = _trend_state(f4h)
    trend_1h = _one_hour_state(price, ema20)
    macd = _macd_label(macd_hist, previous_macd_hist)

    return "\n".join(
        [
            f"<b><u>{_h(symbol)}</u></b> {_h(_price(price))}",
            f"<b>Стан:</b> 4h {_h(trend_4h)}, 1h {_h(trend_1h)}",
            f"<b>Тренд:</b> 4h {_h(_trend_label(f4h))}",
            f"<b>Імпульс:</b> RSI {_h(_fmt(rsi, '.0f'))} ({_h(_rsi_label(rsi))}), MACD histogram {_h(macd)}",
            f"<b>Обʼєм 1h:</b> {_h(_volume_label(volume, volume_avg20, price, base_asset))}",
            f"<b>Рівні:</b> підтримка {_h(_price(support))} · опір {_h(_price(resistance))}",
            f"<b>ATR:</b> {_h(_price(atr))} — {_h(_atr_label(atr, price))}",
            _setup_block(support, resistance),
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
        return "старший таймфрейм переважно вгору. Пріоритет — якісні LONG після пробою і ретесту, без входу посередині руху."
    if down == len(trend_votes):
        return "старший таймфрейм переважно вниз. Пріоритет — якісні SHORT після втрати підтримки і ретесту знизу, без погоні за ціною."
    if up and down:
        strong = _symbols_with_trend(markets, "up")
        weak = _symbols_with_trend(markets, "down")
        strong_text = "/".join(strong) if strong else "частина ринку"
        weak_text = "/".join(weak) if weak else "частина ринку"
        return (
            f"ринок змішаний: {strong_text} сильніші, {weak_text} слабші. "
            "Режим більше для спостереження, ніж для агресивних входів."
        )
    return "немає чіткої переваги; NO TRADE залишається нормальним рішенням."


def _symbols_with_trend(markets: list[LiveMarketData], direction: str) -> list[str]:
    return [
        market.symbol.replace("USDT", "")
        for market in markets
        if _trend_direction(market.frames.get("4h")) == direction
    ]


def _futures_context_note(markets: list[LiveMarketData]) -> str:
    values = [
        value
        for market in markets
        for value in (
            market.futures_context.funding_rate,
            market.futures_context.open_interest,
            market.futures_context.long_short_ratio,
            market.futures_context.spread_pct,
        )
    ]
    if all(value is None for value in values):
        return "Futures context недоступний з GitHub Actions; brief не блокується."
    return "Futures context частково доступний; якщо даних немає, це не блокує brief."


def _setup_block(support: float | None, resistance: float | None) -> str:
    resistance_text = _price(resistance)
    support_text = _price(support)
    return "\n".join(
        [
            "<blockquote expandable>",
            "<b>Готуватись до LONG:</b>",
            f"1h close > {_h(resistance_text)}",
            f"+ ретест {_h(resistance_text)} зверху",
            "+ 15m тримається вище EMA20",
            "+ MACD histogram росте",
            "+ обʼєм 1h на пробої > 1.2x avg20",
            "",
            "<b>Готуватись до SHORT:</b>",
            f"1h close < {_h(support_text)}",
            f"+ ретест {_h(support_text)} знизу",
            "+ 15m нижче EMA20",
            "+ MACD histogram падає",
            "+ обʼєм 1h на пробої > 1.2x avg20",
            "</blockquote>",
        ]
    )


def _trend_label(frame: MarketFrame | None) -> str:
    direction = _trend_direction(frame)
    if direction == "up":
        return "вище EMA50"
    if direction == "down":
        return "нижче EMA50"
    return "невідомо"


def _trend_state(frame: MarketFrame | None) -> str:
    direction = _trend_direction(frame)
    if direction == "up":
        return "сильний"
    if direction == "down":
        return "слабкий"
    return "невідомий"


def _trend_direction(frame: MarketFrame | None) -> str:
    if not frame or frame.candles.empty:
        return "unknown"
    row = frame.candles.iloc[-1]
    close = _val(row, "close")
    ema50 = _val(row, "ema50")
    if close is None or ema50 is None:
        return "unknown"
    return "up" if close > ema50 else "down"


def _one_hour_state(price: float | None, level: float | None) -> str:
    if price is None or level is None:
        return "невідомо"
    if price > level:
        return "відскок/імпульс вище EMA20"
    if price < level:
        return "слабкість нижче EMA20"
    return "біля EMA20"


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


def _macd_label(macd_hist: float | None, previous_macd_hist: float | None) -> str:
    if macd_hist is None:
        return "недостатньо даних"
    if previous_macd_hist is None:
        return "позитивний" if macd_hist > 0 else "негативний" if macd_hist < 0 else "нейтральний"

    if macd_hist > 0 and macd_hist > previous_macd_hist:
        return "позитивний і росте"
    if macd_hist > 0:
        return "позитивний, але слабшає"
    if macd_hist < 0 and macd_hist < previous_macd_hist:
        return "негативний і падає"
    if macd_hist < 0:
        return "негативний, але відновлюється"
    return "нейтральний"


def _volume_label(volume: float | None, volume_avg20: float | None, price: float | None, base_asset: str) -> str:
    if volume is None:
        return "-"

    quote_volume = volume * price if price is not None else None
    volume_text = f"{_compact_number(volume)} {base_asset}"
    quote_text = f" ≈ {_money_compact(quote_volume)}" if quote_volume is not None else ""

    if volume_avg20 is None or volume_avg20 <= 0:
        return f"{volume_text}{quote_text} · avg20 недоступний"

    ratio = volume / volume_avg20
    return f"{volume_text}{quote_text} · {ratio:.1f}x avg20 — {_volume_ratio_label(ratio)}"


def _volume_ratio_label(ratio: float) -> str:
    if ratio >= 1.5:
        return "підвищений"
    if ratio >= 1.1:
        return "вище середнього"
    if ratio >= 0.8:
        return "нормальний"
    return "нижче середнього"


def _atr_label(atr: float | None, price: float | None) -> str:
    if atr is None or price is None or price <= 0:
        return "волатильність невідома"
    ratio = atr / price
    if ratio >= 0.03:
        return "висока волатильність"
    if ratio <= 0.005:
        return "низька волатильність"
    return "робоча волатильність"


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


def _compact_number(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value:,.0f}"
    if value >= 10:
        return f"{value:.2f}"
    return f"{value:.4f}"


def _money_compact(value: float | None) -> str:
    if value is None:
        return "-"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.2f}"


def _pct(price: float | None, level: float | None) -> str:
    if price is None or level is None or level == 0:
        return "-"
    return f"{(price - level) / level * 100:+.1f}%"


def _fmt(value: float | None, spec: str = ".2f") -> str:
    return "-" if value is None else format(value, spec)


def _h(value: object) -> str:
    return escape(str(value), quote=False)
