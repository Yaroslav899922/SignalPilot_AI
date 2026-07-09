from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class _BriefRegime:
    code: str
    icon: str
    label: str
    focus: str
    structure: str


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
        "<b>Alert має сенс лише за пріоритетним напрямком, коли:</b>",
        "режим ринку не зламаний, а сценарій від рівня активувався або є пробій + ретест,",
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
    regime = _classify_regime(f4h, f1h)
    macd = _macd_label(macd_hist, previous_macd_hist)

    return "\n".join(
        [
            f"<b><u>{_h(symbol)}</u></b> {_h(_price(price))}",
            f"{_h(regime.icon)} <b>РЕЖИМ: {_h(regime.label)} · 4h</b>",
            f"<b>Структура:</b> {_h(regime.structure)}",
            f"<b>🎯 ФОКУС:</b> {_h(regime.focus)}",
            f"<b>ЗАРАЗ:</b> {_h(_action_text(regime, price, support, resistance, atr))}",
            f"<b>Імпульс:</b> RSI {_h(_fmt(rsi, '.0f'))} ({_h(_rsi_label(rsi))}), MACD histogram {_h(macd)}",
            f"<b>Обʼєм 1h:</b> {_h(_volume_label(volume, volume_avg20, price, base_asset))}",
            f"<b>Рівні:</b> підтримка {_h(_price(support))} · опір {_h(_price(resistance))}",
            f"<b>ATR:</b> {_h(_price(atr))} — {_h(_atr_label(atr, price))}",
            _setup_block(regime, ema20, support, resistance, atr),
            _trend_risk_line(regime, support, resistance),
        ]
    )


def _brief_verdict(markets: list[LiveMarketData]) -> str:
    snapshots = [_market_snapshot(market) for market in markets]
    snapshots = [snapshot for snapshot in snapshots if snapshot["regime"] != "unknown"]
    if not snapshots:
        return "недостатньо даних для оцінки, але збір свічок запустився."

    up = [snapshot["symbol"] for snapshot in snapshots if snapshot["regime"] == "uptrend"]
    down = [snapshot["symbol"] for snapshot in snapshots if snapshot["regime"] == "downtrend"]
    ranges = [snapshot["symbol"] for snapshot in snapshots if snapshot["regime"] == "range"]
    unclear = [snapshot["symbol"] for snapshot in snapshots if snapshot["regime"] == "unclear"]
    hot = [snapshot["symbol"] for snapshot in snapshots if snapshot["rsi"] is not None and snapshot["rsi"] >= 70]
    elevated_volume = [snapshot["symbol"] for snapshot in snapshots if snapshot["volume_ratio"] is not None and snapshot["volume_ratio"] >= 1.2]
    low_volume = [snapshot["symbol"] for snapshot in snapshots if snapshot["volume_ratio"] is not None and snapshot["volume_ratio"] < 0.8]

    parts: list[str] = []
    if up:
        parts.append(f"{'/'.join(up)}: висхідний режим — шукати лише LONG.")
    if down:
        parts.append(f"{'/'.join(down)}: низхідний режим — шукати лише SHORT.")
    if ranges:
        parts.append(f"{'/'.join(ranges)}: діапазон — дія лише від його меж.")
    if unclear:
        parts.append(f"{'/'.join(unclear)}: структура нечітка — NO TRADE.")

    if hot:
        parts.append(f"Імпульс уже гарячий у {'/'.join(hot)}, тому погоня за ціною небезпечна.")
    if elevated_volume:
        parts.append(f"Обʼєм підтверджує рух у {'/'.join(elevated_volume)}.")
    elif low_volume:
        parts.append("Обʼєм поки тонкий, пробій без нового обʼєму слабкий.")

    parts.append("Протилежний напрямок не торгуємо, доки 4h-режим не отримає повне підтвердження.")
    return " ".join(parts)


def _market_snapshot(market: LiveMarketData) -> dict[str, object]:
    f1h = market.frames.get("1h")
    row = f1h.candles.iloc[-1] if f1h and not f1h.candles.empty else None
    volume = _val(row, "volume") if row is not None else None
    volume_avg20 = _val(row, "volume_avg20") if row is not None else None
    volume_ratio = volume / volume_avg20 if volume is not None and volume_avg20 is not None and volume_avg20 > 0 else None
    return {
        "symbol": market.symbol.replace("USDT", ""),
        "regime": _classify_regime(market.frames.get("4h"), f1h).code,
        "rsi": _val(row, "rsi14") if row is not None else None,
        "volume_ratio": volume_ratio,
    }


def _setup_block(
    regime: _BriefRegime,
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
    long_lines = [
        "<b>LONG — ранній від підтримки:</b>",
        f"зона {_h(early_long_zone)} тримається",
        f"+ 15m повернення &gt; {_h(_price(support_reclaim))} / EMA20 {_h(ema20_text)}",
        f"цілі: {_h(resistance_text)} → {_h(long_targets)}",
        f"інвалідація: close &lt; {_h(_price(long_invalidation))}",
        "",
        "<b>LONG — консервативний:</b>",
        f"1h close &gt; {_h(resistance_text)} + ретест зверху",
        "+ 15m тримається вище EMA20",
        "+ MACD histogram росте",
        "+ обʼєм 1h на пробої &gt; 1.2x avg20",
        f"цілі: {_h(long_targets)}",
    ]
    short_lines = [
        "<b>SHORT — ранній від опору:</b>",
        f"зона {_h(early_short_zone)} відбиває ціну",
        f"+ 15m втрачає {_h(_price(resistance_reject))} / EMA20 {_h(ema20_text)}",
        f"цілі: {_h(support_text)} → {_h(short_targets)}",
        f"інвалідація: close &gt; {_h(_price(short_invalidation))}",
        "",
        "<b>SHORT — консервативний:</b>",
        f"1h close &lt; {_h(support_text)} + ретест знизу",
        "+ 15m нижче EMA20",
        "+ MACD histogram падає",
        "+ обʼєм 1h на пробої &gt; 1.2x avg20",
        f"цілі: {_h(short_targets)}",
    ]
    if regime.code == "uptrend":
        lines = long_lines
    elif regime.code == "downtrend":
        lines = short_lines
    elif regime.code == "range":
        lines = [
            "<b>ДІАПАЗОН: LONG лише від підтримки, SHORT лише від опору.</b>",
            "",
            *long_lines[:5],
            "",
            *short_lines[:5],
        ]
    else:
        lines = [
            "<b>⚪ NO TRADE</b>",
            "4h-структура й рівні не дають достатньо чистої переваги.",
        ]
    return "\n".join(["<blockquote expandable>", *lines, "</blockquote>"])


def _classify_regime(f4h: MarketFrame | None, f1h: MarketFrame | None) -> _BriefRegime:
    if not f4h or not f1h or f4h.candles.empty or f1h.candles.empty:
        return _BriefRegime("unknown", "⚪", "ДАНИХ НЕДОСТАТНЬО", "NO TRADE", "даних недостатньо")

    row4h = f4h.candles.iloc[-1]
    row1h = f1h.candles.iloc[-1]
    close4h = _val(row4h, "close")
    ema50 = _val(row4h, "ema50")
    ema50_previous = _val(f4h.candles.iloc[-4], "ema50") if len(f4h.candles) >= 4 else None
    close1h = _val(row1h, "close")
    support = _val(row1h, "recent_low20")
    resistance = _val(row1h, "recent_high20")
    structure = _four_hour_structure(f4h)

    if None not in (close4h, ema50, ema50_previous, close1h, support, resistance):
        if structure == "HH/HL" and close4h > ema50 and ema50 > ema50_previous and close1h >= support:
            return _BriefRegime("uptrend", "🟢", "ВИСХІДНИЙ", "тільки LONG", "HH/HL · ціна вище EMA50 · EMA50 зростає")
        if structure == "LL/LH" and close4h < ema50 and ema50 < ema50_previous and close1h <= resistance:
            return _BriefRegime("downtrend", "🔴", "НИЗХІДНИЙ", "тільки SHORT", "LL/LH · ціна нижче EMA50 · EMA50 падає")

    if _is_range(f4h, f1h, structure):
        return _BriefRegime("range", "🔵", "ДІАПАЗОН", "LONG від підтримки · SHORT від опору", "змішана 4h-структура · EMA50 пласка")

    return _BriefRegime("unclear", "⚪", "НЕЧІТКИЙ", "NO TRADE", "4h-структура або рівні суперечливі")


def _four_hour_structure(frame: MarketFrame) -> str:
    candles = frame.candles
    if len(candles) < 9 or not {"high", "low"}.issubset(candles.columns):
        return "невизначена"

    highs: list[float] = []
    lows: list[float] = []
    for index in range(2, len(candles) - 2):
        high = _val(candles.iloc[index], "high")
        low = _val(candles.iloc[index], "low")
        high_window = [_val(candles.iloc[position], "high") for position in range(index - 2, index + 3)]
        low_window = [_val(candles.iloc[position], "low") for position in range(index - 2, index + 3)]
        if high is not None and all(value is not None for value in high_window) and high > max(high_window[:2] + high_window[3:]):
            highs.append(high)
        if low is not None and all(value is not None for value in low_window) and low < min(low_window[:2] + low_window[3:]):
            lows.append(low)

    if len(highs) < 2 or len(lows) < 2:
        return "невизначена"
    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "HH/HL"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "LL/LH"
    return "змішана"


def _is_range(f4h: MarketFrame, f1h: MarketFrame, structure: str) -> bool:
    if structure != "змішана" or len(f4h.candles) < 4:
        return False
    row4h = f4h.candles.iloc[-1]
    previous_row4h = f4h.candles.iloc[-4]
    row1h = f1h.candles.iloc[-1]
    ema50 = _val(row4h, "ema50")
    ema50_previous = _val(previous_row4h, "ema50")
    atr4h = _val(row4h, "atr14")
    close1h = _val(row1h, "close")
    support = _val(row1h, "recent_low20")
    resistance = _val(row1h, "recent_high20")
    atr1h = _val(row1h, "atr14")
    if None in (ema50, ema50_previous, atr4h, close1h, support, resistance, atr1h) or atr4h <= 0 or atr1h <= 0:
        return False
    if abs(ema50 - ema50_previous) > 0.25 * atr4h or not support < close1h < resistance:
        return False
    candles = f1h.candles.tail(20)
    if not {"high", "low"}.issubset(candles.columns):
        return False
    tolerance = 0.1 * atr1h
    support_touches = sum(_val(row, "low") is not None and _val(row, "low") <= support + tolerance for _, row in candles.iterrows())
    resistance_touches = sum(_val(row, "high") is not None and _val(row, "high") >= resistance - tolerance for _, row in candles.iterrows())
    return support_touches >= 2 and resistance_touches >= 2


def _action_text(
    regime: _BriefRegime,
    price: float | None,
    support: float | None,
    resistance: float | None,
    atr: float | None,
) -> str:
    if regime.code == "unclear" or regime.code == "unknown":
        return "⚪ NO TRADE — чекаємо чисту 4h-структуру"
    if None in (price, support, resistance, atr):
        return "⚪ NO TRADE — бракує рівня або волатильності"
    if regime.code == "uptrend":
        if price <= support + 0.5 * atr:
            return "🟡 WAIT — чекаємо 15m-підтвердження LONG від підтримки"
        if price >= resistance:
            return "🟡 WAIT — чекаємо пробій і ретест опору для LONG"
        return "🟡 WAIT — LONG лише від підтримки або після пробою й ретесту"
    if regime.code == "downtrend":
        if price >= resistance - 0.5 * atr:
            return "🟡 WAIT — чекаємо 15m-підтвердження SHORT від опору"
        if price <= support:
            return "🟡 WAIT — чекаємо пробій і ретест підтримки для SHORT"
        return "🟡 WAIT — SHORT лише від опору або після пробою й ретесту"
    middle_low = support + 0.3 * (resistance - support)
    middle_high = resistance - 0.3 * (resistance - support)
    if middle_low <= price <= middle_high:
        return "⚪ NO TRADE — ціна в середині діапазону"
    return "🟡 WAIT — дія лише після підтвердження від межі діапазону"


def _trend_risk_line(regime: _BriefRegime, support: float | None, resistance: float | None) -> str:
    if regime.code == "uptrend":
        return f"<b>⚠️ Ризик зламу:</b> 1h close &lt; {_h(_price(support))}; до нового DOWNTREND SHORT не розглядаємо."
    if regime.code == "downtrend":
        return f"<b>⚠️ Ризик зламу:</b> 1h close &gt; {_h(_price(resistance))}; до нового UPTREND LONG не розглядаємо."
    if regime.code == "range":
        return "<b>⚠️ Скасування діапазону:</b> 1h пробій межі без повернення запускає переоцінку режиму."
    return "<b>⚪ Дія:</b> нових сценаріїв немає до появи чистого режиму."


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
