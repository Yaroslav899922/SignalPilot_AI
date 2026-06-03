from __future__ import annotations

import time
from html import escape
from pathlib import Path
from typing import Callable

from .journal_backend import summarize_journal
from .signals import Signal
from .telegram import TelegramConfig, fetch_updates, format_signal_message, send_message


HELP = "help"
REPORT = "report"
MARKET = "market"
STATUS = "status"
UNKNOWN = "unknown"


def parse_bot_command(text: str) -> str:
    normalized = _normalize(text)
    if normalized.startswith("/start") or normalized in {"help", "/help", "допомога", "команди"}:
        return HELP
    if normalized in {"звіт", "звит", "надай звіт", "надай звит", "дай звіт", "дай звит", "статистика"}:
        return REPORT
    if normalized == "статус":
        return STATUS
    if normalized in {"перевір ринок", "перевірити ринок", "перевир ринок"}:
        return MARKET
    if "торгов" in normalized and "ситуац" in normalized:
        return MARKET
    return UNKNOWN


def run_telegram_bot(
    config: TelegramConfig,
    journal_path: Path,
    scan_market: Callable[[], list[Signal]],
    symbols: list[str],
    base_url: str,
    poll_timeout: int = 30,
    poll_interval_seconds: float = 1.0,
    max_polls: int | None = None,
) -> None:
    offset = None
    polls = 0

    while max_polls is None or polls < max_polls:
        updates = fetch_updates(config, offset=offset, timeout=poll_timeout, base_url=base_url)
        for update in updates:
            update_id = _update_id(update)
            if update_id is not None:
                next_offset = update_id + 1
                offset = next_offset if offset is None else max(offset, next_offset)
            handle_update(update, config, journal_path, scan_market, symbols, base_url)

        polls += 1
        if max_polls is not None and polls >= max_polls:
            break
        time.sleep(poll_interval_seconds)


def handle_update(
    update: dict[str, object],
    config: TelegramConfig,
    journal_path: Path,
    scan_market: Callable[[], list[Signal]],
    symbols: list[str],
    base_url: str,
) -> None:
    chat_id = _chat_id(update)
    text = _message_text(update)
    if chat_id is None or text is None:
        return

    command = parse_bot_command(text)
    if command == HELP:
        send_message(_help_message(), config, chat_id=chat_id, base_url=base_url)
    elif command == REPORT:
        send_message(format_report_message(summarize_journal(journal_path)), config, chat_id=chat_id, base_url=base_url)
    elif command == STATUS:
        send_message(_status_message(journal_path, symbols), config, chat_id=chat_id, base_url=base_url)
    elif command == MARKET:
        _reply_with_market_scan(config, chat_id, scan_market, base_url)
    else:
        send_message(_unknown_message(), config, chat_id=chat_id, base_url=base_url)


def format_report_message(summary: dict[str, object]) -> str:
    win_rate = summary.get("win_rate")
    win_rate_text = "-" if win_rate is None else f"{float(win_rate):.1%}"
    return "\n".join(
        [
            "<b>Звіт SignalPilot</b>",
            "",
            f"<b>Всього записів:</b> {summary.get('signals', 0)}",
            f"<b>LONG:</b> {summary.get('long', 0)}",
            f"<b>SHORT:</b> {summary.get('short', 0)}",
            f"<b>НЕ ВХОДИТИ:</b> {summary.get('no_trade', 0)}",
            f"<b>Очікують оцінки:</b> {summary.get('pending', 0)}",
            "",
            f"<b>Target hit:</b> {summary.get('target_hit', 0)}",
            f"<b>Stop hit:</b> {summary.get('stop_hit', 0)}",
            f"<b>No result:</b> {summary.get('no_result', 0)}",
            f"<b>Win rate:</b> {win_rate_text}",
            "",
            "Це paper-test статистика. SignalPilot не відкриває угоди.",
        ]
    )


def _reply_with_market_scan(
    config: TelegramConfig,
    chat_id: str,
    scan_market: Callable[[], list[Signal]],
    base_url: str,
) -> None:
    send_message("<b>Перевіряю ринок...</b>", config, chat_id=chat_id, base_url=base_url)
    try:
        signals = scan_market()
    except Exception as error:
        send_message(
            f"<b>Помилка:</b> {_html(str(error))}",
            config,
            chat_id=chat_id,
            base_url=base_url,
        )
        return

    if not signals:
        send_message(
            "<b>Результат:</b> сигналів не знайдено.",
            config,
            chat_id=chat_id,
            base_url=base_url,
        )
        return

    for signal in signals:
        send_message(format_signal_message(signal), config, chat_id=chat_id, base_url=base_url)


def _help_message() -> str:
    return "\n".join(
        [
            "<b>Команди SignalPilot</b>",
            "",
            "<b>надай звіт</b> - показати статистику журналу",
            "<b>є торгова ситуація?</b> - перевірити BTC/ETH/SOL зараз",
            "<b>перевір ринок</b> - те саме, швидка перевірка ринку",
            "<b>статус</b> - показати, що бот працює",
            "",
            "Бот не відкриває угоди. Він тільки дає підказку для ручного аналізу.",
        ]
    )


def _status_message(journal_path: Path, symbols: list[str]) -> str:
    return "\n".join(
        [
            "<b>Статус:</b> бот працює",
            f"<b>Журнал:</b> {_html(journal_path)}",
            f"<b>Пари:</b> {_html(', '.join(symbols))}",
            "Напиши: <b>надай звіт</b> або <b>є торгова ситуація?</b>",
        ]
    )


def _unknown_message() -> str:
    return "\n".join(
        [
            "<b>Не зрозумів команду.</b>",
            "Напиши <b>допомога</b>, щоб побачити доступні команди.",
        ]
    )


def _normalize(text: str) -> str:
    cleaned = text.casefold().strip()
    for character in "?!.,:;":
        cleaned = cleaned.replace(character, "")
    return " ".join(cleaned.split())


def _html(value: object) -> str:
    return escape(str(value), quote=False)


def _update_id(update: dict[str, object]) -> int | None:
    value = update.get("update_id")
    return value if isinstance(value, int) else None


def _message_text(update: dict[str, object]) -> str | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    return text if isinstance(text, str) else None


def _chat_id(update: dict[str, object]) -> str | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id = chat.get("id")
    if isinstance(chat_id, int | str):
        return str(chat_id)
    return None
