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


def generate_brief(
    markets: list[LiveMarketData],
    now_utc: datetime | None = None,
    session_label: str | None = None,
) -> str:
    """Return an HTML-formatted Telegram market briefing from live candle data."""
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(_KYIV_TZ)

    session = session_label or _SESSION_MAP.get(now.hour, "Ринковий контроль")
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
        "<b>Окремий LONG/SHORT alert має сенс, коли:</b>",
        "ранній сценарій від підтримки/опору активувався або є пробій + ретест,",
        "15m підтверджує напрямок,",
        "MACD histogram підтверджує напрямок,",
        "обʼєм не суперечить руху,",
        "є чітка інвалідація і наступна ціль.",
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
            _setup_block(ema20, support, resistance, atr),
        ]
    )


def _brief_verdict(markets: list[LiveMarketData]) -> str:
    snapshots = [_market_snapshot(market) for market in markets]
    snapshots = [snapshot for snapshot in snapshots if snapshot["trend"] != "unknown"]
    if not snapshots:
        return "недостатньо даних для оцінки, але збір свічок запустився."

    up = [snapshot["symbol"] for snapshot in snapshots if snapshot["trend"] == "up"]
    down = [snapshot["symbol"] for snapshot in snapshots if snapshot["trend"] == "down"]
    hot = [snapshot["symbol"] for snapshot in snapshots if snapshot["rsi"] is not None and snapshot["rsi"] >= 70]
    elevated_volume = [snapshot["symbol"] for snapshot in snapshots if snapshot["volume_ratio"] is not None and snapshot["volume_ratio"] >= 1.2]
    low_volume = [snapshot["symbol"] for snapshot in snapshots if snapshot["volume_ratio"] is not None and snapshot["volume_ratio"] < 0.8]

    parts: list[str] = []
    if up and not down:
        parts.append(f"{'/'.join(up)} тримають 4h-тренд вгору.")
    elif down and not up:
        parts.append(f"{'/'.join(down)} лишаються нижче 4h EMA50.")
    elif up and down:
        parts.append(f"{'/'.join(up)} ведуть ринок, а {'/'.join(down)} ще під слабшим 4h-трендом.")
    else:
        parts.append("4h не дає чистої переваги в один бік.")

    if hot:
        parts.append(f"Імпульс уже гарячий у {'/'.join(hot)}, тому погоня за ціною небезпечна.")
    if elevated_volume:
        parts.append(f"Обʼєм підтверджує рух у {'/'.join(elevated_volume)}.")
    elif low_volume:
        parts.append("Обʼєм поки тонкий, пробій без нового обʼєму слабкий.")

    parts.append(
        "План: ранній LONG тільки від підтримки після повернення вище зони; консервативний LONG — після пробою й ретесту опору; "
        "SHORT повертається в гру при втраті підтримки."
    )
    return " ".join(parts)


def _market_snapshot(market: LiveMarketData) -> dict[str, object]:
    f1h = market.frames.get("1h")
    row = f1h.candles.iloc[-1] if f1h and not f1h.candles.empty else None
    volume = _val(row, "volume") if row is not None else None
    volume_avg20 = _val(row, "volume_avg20") if row is not None else None
    volume_ratio = volume / volume_avg20 if volume is not None and volume_avg20 is not None and volume_avg20 > 0 else None
    return {
        "symbol": market.symbol.replace("USDT", ""),
        "trend": _trend_direction(market.frames.get("4h")),
        "rsi": _val(row, "rsi14") if row is not None else None,
        "volume_ratio": volume_ratio,
    }


def _setup_block(
    ema20: float | None,
    support: float | None,
    resistance: float | None,
    atr: float | None,
) -> str:
    resistance_text = _price(resistance)
    support_text = _price(support)
    support_reclaim = _zone_edge(support, atr, 0.5)
    resistance_reject = _zone_edge(resistance, atr, -0.5)
    long_invalidation = _zone_edge(support, atr, -0.25)
    short_invalidation = _zone_edge(resistance, atr, 0.25)
    long_targets = _target_path("LONG", resistance, atr)
    short_targets = _target_path("SHORT", support, atr)
    early_long_zone = _zone_text(support, support_reclaim)
    early_short_zone = _zone_text(resistance_reject, resistance)
    ema20_text = _price(ema20)
    return "\n".join(
        [
            "<blockquote expandable>",
            "<b>Готуватись до LONG — ранній від підтримки:</b>",
            f"зона {_h(early_long_zone)} тримається",
            f"+ 15m повернення &gt; {_h(_price(support_reclaim))} / EMA20 {_h(ema20_text)}",
            f"цілі: {_h(resistance_text)} → {_h(long_targets)}",
            f"інвалідація: close &lt; {_h(_price(long_invalidation))}",
            "",
            "<b>Готуватись до LONG — консервативний:</b>",
            f"1h close &gt; {_h(resistance_text)} + ретест зверху",
            "+ 15m тримається вище EMA20",
            "+ MACD histogram росте",
            "+ обʼєм 1h на пробої &gt; 1.2x avg20",
            f"цілі: {_h(long_targets)}",
            "",
            "<b>Готуватись до SHORT — ранній від опору:</b>",
            f"зона {_h(early_short_zone)} відбиває ціну",
            f"+ 15m втрачає {_h(_price(resistance_reject))} / EMA20 {_h(ema20_text)}",
            f"цілі: {_h(support_text)} → {_h(short_targets)}",
            f"інвалідація: close &gt; {_h(_price(short_invalidation))}",
            "",
            "<b>Готуватись до SHORT — консервативний:</b>",
            f"1h close &lt; {_h(support_text)} + ретест знизу",
            "+ 15m нижче EMA20",
            "+ MACD histogram падає",
            "+ обʼєм 1h на пробої &gt; 1.2x avg20",
            f"цілі: {_h(short_targets)}",
            "</blockquote>",
        ]
    )


def _zone_edge(level: float | None, atr: float | None, atr_mult: float) -> float | None:
    if level is None or atr is None:
        return None
    return level + atr_mult * atr


def _zone_text(low: float | None, high: float | None) -> str:
    if low is None and high is None:
        return "-"
    if low is None:
        return _price(high)
    if high is None:
        return _price(low)
    if low > high:
        low, high = high, low
    return f"{_price(low)}-{_price(high)}"


def _target_path(direction: str, level: float | None, atr: float | None) -> str:
    if level is None or atr is None:
        return "-"
    sign = 1.0 if direction == "LONG" else -1.0
    first = level + sign * atr
    second = level + sign * 2.0 * atr
    return f"{_price(first)} → {_price(second)}"


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
