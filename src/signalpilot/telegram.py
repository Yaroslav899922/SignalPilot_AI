from __future__ import annotations

import json
import os
from html import escape
from dataclasses import dataclass
from urllib.request import Request, urlopen

from .signals import Signal


TELEGRAM_API_BASE_URL = "https://api.telegram.org"
TELEGRAM_MESSAGE_LIMIT = 4096
TRUNCATION_MARKER = "- ... причини скорочено, щоб вмістити ліміт Telegram"


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str

    @classmethod
    def from_env(cls) -> "TelegramConfig":
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not bot_token or not chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set for Telegram features")
        return cls(bot_token=bot_token, chat_id=chat_id)


def format_signal_message(signal: Signal) -> str:
    targets = " / ".join(f"{target:.2f}" for target in signal.targets) if signal.targets else "-"
    stop = f"{signal.stop:.2f}" if signal.stop is not None else "-"
    risk_reward = f"1:{signal.risk_reward:.1f}" if signal.risk_reward is not None else "-"
    close_price = f"{signal.close_price:.2f}" if signal.close_price is not None else "-"
    funding_rate = f"{signal.funding_rate * 100:.4f}%" if signal.funding_rate is not None else "-"
    open_interest = f"{signal.open_interest:.3f}" if signal.open_interest is not None else "-"
    long_short_ratio = f"{signal.long_short_ratio:.3f}" if signal.long_short_ratio is not None else "-"
    spread = f"{signal.spread_pct:.4f}%" if signal.spread_pct is not None else "-"
    action = _action(signal.direction)
    pattern = signal.pattern or "-"
    setup_score = "-" if signal.setup_score is None else f"{signal.setup_score:.1f}/100"
    trailing_plan = signal.trailing_plan or "-"

    header_lines = [
        f"<b>{_html(signal.symbol)} | {_html(action)}</b>",
        "",
        f"<b>Дія:</b> {_html(action)}",
        f"<b>Таймфрейм:</b> {_html(signal.interval)}",
        f"<b>Формація:</b> {_html(_pattern(pattern))}",
        f"<b>Оцінка сетапу:</b> {_html(setup_score)}",
        f"<b>Режим ринку:</b> {_html(_market_regime(signal.market_regime))}",
        f"<b>Поточна ціна:</b> {_html(close_price)}",
        "",
        f"<b>Зона входу:</b> {_html(signal.entry_zone or '-')}",
        f"<b>Стоп:</b> {_html(stop)}",
        f"<b>Цілі:</b> {_html(targets)}",
        f"<b>Ризик/прибуток:</b> {_html(risk_reward)}",
        f"<b>Впевненість:</b> {_html(_confidence(signal.confidence))}",
        "",
        f"<b>Funding:</b> {_html(funding_rate)} - чи не перегрітий ринок",
        f"<b>Open interest:</b> {_html(open_interest)} - активність ф'ючерсного ринку",
        f"<b>Long/short ratio:</b> {_html(long_short_ratio)} - чи не забагато трейдерів в один бік",
        f"<b>Spread:</b> {_html(spread)} - різниця між купівлею і продажем",
        "",
        f"<b>Інвалідація:</b> {_html(_invalidation(signal.invalidation))}",
        f"<b>Трейлінг:</b> {_html(_trailing(trailing_plan))}",
        "",
        "<b>Чому так:</b>",
    ]
    reason_lines = [f"- {_html(_reason(reason))}" for reason in signal.reasons]
    footer_lines = [
        "",
        f"<b>Висновок:</b> {_html(_conclusion(signal.direction))}",
        "SignalPilot не відкриває угоди. Це тільки підказка для ручного аналізу.",
    ]
    return _fit_telegram_limit(header_lines, reason_lines, footer_lines)


def send_signal(
    signal: Signal,
    config: TelegramConfig,
    base_url: str = TELEGRAM_API_BASE_URL,
) -> dict[str, object]:
    return send_message(
        text=format_signal_message(signal),
        config=config,
        chat_id=config.chat_id,
        base_url=base_url,
    )


def send_message(
    text: str,
    config: TelegramConfig,
    chat_id: str | int | None = None,
    base_url: str = TELEGRAM_API_BASE_URL,
    parse_mode: str = "HTML",
) -> dict[str, object]:
    payload = {
        "chat_id": str(chat_id or config.chat_id),
        "text": _fit_text_limit(text),
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    return _post_telegram("sendMessage", config, payload, base_url)


def fetch_updates(
    config: TelegramConfig,
    offset: int | None = None,
    timeout: int = 30,
    base_url: str = TELEGRAM_API_BASE_URL,
) -> list[dict[str, object]]:
    payload: dict[str, object] = {
        "timeout": timeout,
        "allowed_updates": ["message"],
    }
    if offset is not None:
        payload["offset"] = offset

    response = _post_telegram("getUpdates", config, payload, base_url)
    result = response.get("result", [])
    return result if isinstance(result, list) else []


def _post_telegram(
    method_name: str,
    config: TelegramConfig,
    payload: dict[str, object],
    base_url: str,
) -> dict[str, object]:
    request = Request(
        url=f"{base_url}/bot{config.bot_token}/{method_name}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _fit_telegram_limit(header_lines: list[str], reason_lines: list[str], footer_lines: list[str]) -> str:
    message = "\n".join([*header_lines, *reason_lines, *footer_lines])
    if len(message) <= TELEGRAM_MESSAGE_LIMIT:
        return message

    kept_reasons: list[str] = []
    for reason in reason_lines:
        candidate = "\n".join([*header_lines, *kept_reasons, reason, TRUNCATION_MARKER, *footer_lines])
        if len(candidate) > TELEGRAM_MESSAGE_LIMIT:
            break
        kept_reasons.append(reason)

    message = "\n".join([*header_lines, *kept_reasons, TRUNCATION_MARKER, *footer_lines])
    if len(message) <= TELEGRAM_MESSAGE_LIMIT:
        return message

    return message[: TELEGRAM_MESSAGE_LIMIT - 3] + "..."


def _fit_text_limit(text: str) -> str:
    if len(text) <= TELEGRAM_MESSAGE_LIMIT:
        return text
    return text[: TELEGRAM_MESSAGE_LIMIT - 3] + "..."


def _html(value: object) -> str:
    return escape(str(value), quote=False)


def _action(direction: str) -> str:
    if direction == "NO TRADE":
        return "НЕ ВХОДИТИ"
    if direction == "LONG":
        return "LONG - шукати покупку"
    if direction == "SHORT":
        return "SHORT - шукати продаж"
    return direction


def _confidence(confidence: str) -> str:
    return {
        "low": "низька",
        "medium": "середня",
        "high": "висока",
    }.get(confidence, confidence)


def _trend(value: str) -> str:
    return {
        "up": "вгору",
        "down": "вниз",
        "range": "боковик",
        "unknown": "невідомо",
        "confirmed": "підтвердив",
        "not_confirmed": "не підтвердив",
        "compressed": "стиснення",
        "expanded": "розширення",
        "normal": "нормальна волатильність",
        "no_setup": "немає сетапу",
    }.get(value, value)


def _market_regime(regime: str) -> str:
    parts = []
    for item in regime.split("/"):
        if ":" not in item:
            parts.append(_trend(item))
            continue
        interval, value = item.split(":", 1)
        parts.append(f"{interval} {_trend(value)}")
    return " / ".join(parts)


def _invalidation(value: str) -> str:
    translations = {
        "Wait for a cleaner setup with a defined stop": "Чекати чистіший сетап із чітким стопом",
        "Wait for complete multi-timeframe data": "Чекати повні дані по 15m/1h/4h",
        "Wait for higher timeframe alignment": "Чекати, поки старший таймфрейм підтвердить напрямок",
        "Wait for lower timeframe confirmation": "Чекати підтвердження на молодшому таймфреймі",
    }
    if value in translations:
        return translations[value]
    if value.startswith("LONG invalid if price closes beyond stop "):
        stop = value.removeprefix("LONG invalid if price closes beyond stop ")
        return f"LONG скасовано, якщо ціна закриється за стопом {stop}"
    if value.startswith("SHORT invalid if price closes beyond stop "):
        stop = value.removeprefix("SHORT invalid if price closes beyond stop ")
        return f"SHORT скасовано, якщо ціна закриється за стопом {stop}"
    if value.startswith("LONG invalid if 1h closes below retest level "):
        return value.replace("LONG invalid if", "LONG скасовано, якщо").replace("or stop", "або стоп")
    if value.startswith("SHORT invalid if 1h closes above retest level "):
        return value.replace("SHORT invalid if", "SHORT скасовано, якщо").replace("or stop", "або стоп")
    return value


def _reason(value: str) -> str:
    if value.startswith("Pattern breakout_retest LONG:"):
        return value.replace("Pattern breakout_retest LONG:", "Breakout + retest LONG:")
    if value.startswith("Pattern breakout_retest SHORT:"):
        return value.replace("Pattern breakout_retest SHORT:", "Breakout + retest SHORT:")
    if value == "4h trend supports LONG":
        return "4h тренд підтримує LONG"
    if value == "4h trend supports SHORT":
        return "4h тренд підтримує SHORT"
    if value.startswith("Retest held:"):
        return value.replace("Retest held:", "Ретест утримався:")
    if value.startswith("15m confirmation for "):
        return value.replace("15m confirmation for", "15m підтвердження для").replace("close above EMA20", "ціна вище EMA20").replace("close below EMA20", "ціна нижче EMA20")
    if value.startswith("Trailing plan: "):
        return _trailing(value.removeprefix("Trailing plan: "))
    if value.startswith("TradingView trigger received"):
        return "TradingView trigger отримано; SignalPilot перевірив його на Binance-даних"
    if value.startswith("TradingView trigger payload: "):
        return "TradingView payload записано для аудиту"
    if value == "Futures context blocks professional alert":
        return "Ф'ючерсний контекст блокує професійний алерт"
    if value == "No breakout + retest setup with clean level, stop, target, and confirmation":
        return "Немає breakout + retest із чистим рівнем, стопом, ціллю і підтвердженням"
    if value == "No auto-trading; alert is for manual confirmation and journaling":
        return "Автоторгівлі немає; це алерт для ручного підтвердження і журналу"
    if value.startswith("1h volatility is "):
        return f"1h волатильність: {_trend(value.removeprefix('1h volatility is '))}"
    if value.startswith("Market regime is "):
        return f"Режим ринку: {_trend(value.removeprefix('Market regime is '))}"
    if value.endswith(" regime is up"):
        return f"{value.split()[0]} тренд вгору"
    if value.endswith(" regime is down"):
        return f"{value.split()[0]} тренд вниз"
    if value.endswith(" regime is range"):
        return f"{value.split()[0]} боковик"
    if " trend is " in value and "not aligned with" in value:
        interval, rest = value.split(" trend is ", 1)
        trend, direction = rest.split(", not aligned with ", 1)
        return f"{interval} тренд {_trend(trend)}, не збігається з {direction}"
    if value.endswith(" does not confirm LONG"):
        interval = value.removesuffix(" does not confirm LONG")
        return f"{interval} не підтвердив LONG"
    if value.endswith(" does not confirm SHORT"):
        interval = value.removesuffix(" does not confirm SHORT")
        return f"{interval} не підтвердив SHORT"
    if value.startswith("RSI is "):
        rsi = value.removeprefix("RSI is ")
        return f"RSI {rsi} - показує силу руху"
    if value == "15m confirmation skipped because 1h setup is NO TRADE":
        return "15m не перевірявся, бо на 1h немає входу"
    if value.startswith("15m confirmation: "):
        return _translate_confirmation(value)
    if value == "Funding rate is overheated":
        return "Funding перегрітий - краще не входити"
    if value.startswith("Funding rate is "):
        funding = value.removeprefix("Funding rate is ")
        return f"Funding {funding} - показує, чи ринок не перегрітий"
    if value == "Funding rate unavailable":
        return "Funding недоступний"
    if value.startswith("Open interest is "):
        open_interest = value.removeprefix("Open interest is ")
        return f"Open interest {open_interest} - активність ф'ючерсного ринку"
    if value == "Open interest unavailable":
        return "Open interest недоступний"
    if value == "Open interest is invalid":
        return "Open interest некоректний"
    if value == "Long/short ratio is crowded":
        return "Long/short ratio crowded - забагато трейдерів стоять в один бік"
    if value.startswith("Long/short ratio is "):
        ratio = value.removeprefix("Long/short ratio is ")
        return f"Long/short ratio {ratio} - чи не забагато трейдерів в один бік"
    if value == "Long/short ratio unavailable":
        return "Long/short ratio недоступний"
    if value == "Order book spread is too wide":
        return "Spread занадто широкий - входити ризиковано"
    if value.startswith("Order book spread is "):
        spread = value.removeprefix("Order book spread is ")
        return f"Spread {spread} - різниця між купівлею і продажем"
    if value == "Order book spread unavailable":
        return "Spread недоступний"
    if value == "No clean trend + level + momentum setup with minimum 1:2 risk/reward":
        return "Немає чистого сетапу з нормальним ризик/прибуток"
    if value == "Risk/reward meets minimum 1:2":
        return "Ризик/прибуток відповідає мінімуму 1:2"
    if value.startswith("Uptrend with breakout above recent high "):
        level = value.removeprefix("Uptrend with breakout above recent high ")
        return f"Висхідний тренд і пробій вище локального максимуму {level}"
    if value.startswith("Downtrend with breakdown below recent low "):
        level = value.removeprefix("Downtrend with breakdown below recent low ")
        return f"Низхідний тренд і пробій нижче локального мінімуму {level}"
    if value.startswith("Uptrend breakout candidate above recent high "):
        level = value.removeprefix("Uptrend breakout candidate above recent high ")
        return f"Можливий LONG: пробій вище локального максимуму {level}"
    if value.startswith("Downtrend breakdown candidate below recent low "):
        level = value.removeprefix("Downtrend breakdown candidate below recent low ")
        return f"Можливий SHORT: пробій нижче локального мінімуму {level}"
    if value.startswith("Multi-timeframe confirmation: "):
        return "15m/1h/4h підтверджують один напрямок"
    if value.startswith("Futures context unavailable"):
        return "Ф'ючерсний контекст недоступний"
    if value.startswith("No candle data available"):
        return "Немає даних свічок"
    if value.startswith("Not enough candles"):
        return "Недостатньо свічок для індикаторів"
    if value.startswith("Not enough indicator data"):
        return "Недостатньо даних індикаторів для 15m/1h/4h"
    if value.startswith("Not enough complete indicator data"):
        return "Недостатньо повних даних індикаторів для live-аналізу"
    if value == "ATR is zero; stop distance cannot be calculated":
        return "ATR дорівнює нулю - не можна розрахувати стоп"
    return value


def _translate_confirmation(value: str) -> str:
    translated = value.replace("15m confirmation:", "15m підтвердження:")
    translated = translated.replace("close above EMA20", "ціна вище EMA20")
    translated = translated.replace("close below EMA20", "ціна нижче EMA20")
    return translated


def _conclusion(direction: str) -> str:
    if direction == "NO TRADE":
        return "не входити в угоду."
    if direction == "LONG":
        return "можливий LONG, але тільки після ручного підтвердження."
    if direction == "SHORT":
        return "можливий SHORT, але тільки після ручного підтвердження."
    return "потрібна ручна перевірка."


def _pattern(value: str) -> str:
    return {
        "breakout_retest": "breakout + retest",
        "-": "-",
    }.get(value, value)


def _trailing(value: str) -> str:
    translations = {
        "After +1R, move stop to breakeven; after target 1, trail below 15m EMA20 or latest 15m swing low.": (
            "Після +1R перенести стоп у беззбиток; після цілі 1 вести стоп під 15m EMA20 або останнім 15m swing low."
        ),
        "After +1R, move stop to breakeven; after target 1, trail above 15m EMA20 or latest 15m swing high.": (
            "Після +1R перенести стоп у беззбиток; після цілі 1 вести стоп над 15m EMA20 або останнім 15m swing high."
        ),
    }
    return translations.get(value, value)
