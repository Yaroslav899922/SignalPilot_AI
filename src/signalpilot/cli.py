from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .binance import DEFAULT_KLINE_LIMIT
from .brief import generate_brief
from .journal_backend import save_signal, summarize_journal
from .live_analyst import analyze_live_market, format_market_status
from .market_data import load_live_market_data
from .paper import evaluate_journal
from .signals import DEFAULT_TIMEFRAMES, Signal
from .telegram import TELEGRAM_API_BASE_URL, TelegramConfig, send_signal
from .telegram_bot import run_telegram_bot
from .tradingview import TradingViewTrigger, parse_tradingview_trigger


DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SignalPilot live chart analyst.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--intervals", nargs="+", default=list(DEFAULT_TIMEFRAMES))
    parser.add_argument("--limit", type=int, default=DEFAULT_KLINE_LIMIT)
    parser.add_argument("--journal", default="data/signals.sqlite3")
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument("--lookahead-candles", type=int, default=6)
    parser.add_argument("--report", action="store_true", help="Print a compact paper-test journal summary.")
    parser.add_argument("--paper-loop", action="store_true", help="Run live paper-test cycles until stopped.")
    parser.add_argument("--run-every-minutes", type=float, default=60.0)
    parser.add_argument("--max-runs", type=int, help="Stop paper loop after this many cycles.")
    parser.add_argument("--live-analyst", action="store_true", help="Run live chart analyst pattern engine.")
    parser.add_argument("--market-status", action="store_true", help="Print live data health without journaling.")
    parser.add_argument("--notify", action="store_true", help="Send directional signals to Telegram.")
    parser.add_argument("--notify-no-trade", action="store_true", help="Also send NO TRADE analyses to Telegram.")
    parser.add_argument("--tradingview-trigger", help="TradingView alert JSON; also read from SIGNALPILOT_TRADINGVIEW_TRIGGER.")
    parser.add_argument("--telegram-bot", action="store_true", help="Reply to Telegram commands via polling.")
    parser.add_argument("--telegram-poll-interval", type=float, default=1.0)
    parser.add_argument("--telegram-poll-timeout", type=int, default=30)
    parser.add_argument("--telegram-max-polls", type=int, help="Stop Telegram bot after this many polling cycles.")
    parser.add_argument("--brief", action="store_true", help="Send a market briefing to Telegram.")
    parser.add_argument("--brief-session", help="Session label to print in a scheduled market brief.")
    parser.add_argument("--move-alert", action="store_true", help="Send alerts for sharp 15m market moves.")
    parser.add_argument("--move-threshold-pct", type=float, default=1.5)
    args = parser.parse_args(argv)

    journal_path = Path(args.journal)
    if args.run_every_minutes <= 0:
        parser.error("--run-every-minutes must be greater than zero")
    if args.max_runs is not None and args.max_runs <= 0:
        parser.error("--max-runs must be greater than zero")
    if args.telegram_poll_interval <= 0:
        parser.error("--telegram-poll-interval must be greater than zero")
    if args.telegram_poll_timeout <= 0:
        parser.error("--telegram-poll-timeout must be greater than zero")
    if args.telegram_max_polls is not None and args.telegram_max_polls <= 0:
        parser.error("--telegram-max-polls must be greater than zero")
    if args.move_threshold_pct <= 0:
        parser.error("--move-threshold-pct must be greater than zero")

    try:
        args.tradingview_trigger_obj = _tradingview_trigger(args)
    except ValueError as error:
        parser.error(str(error))
    if args.tradingview_trigger_obj is not None and args.symbols == DEFAULT_SYMBOLS:
        args.symbols = [args.tradingview_trigger_obj.symbol]

    if args.report:
        _print_report(journal_path)
        return 0

    telegram_config = None
    if args.notify or args.telegram_bot:
        try:
            telegram_config = TelegramConfig.from_env()
        except ValueError as error:
            parser.error(str(error))

    if args.telegram_bot:
        assert telegram_config is not None
        return _run_telegram_bot(args, journal_path, telegram_config)

    if args.brief:
        _run_brief(args, telegram_config)
        return 0

    if args.move_alert:
        _run_move_alert(args, telegram_config)
        return 0

    if args.market_status:
        _run_market_status(args, telegram_config)
        return 0

    if args.paper_loop:
        return _run_paper_loop(args, journal_path, telegram_config)

    if args.evaluate:
        _run_evaluation(journal_path, args.lookahead_candles)
        return 0

    _run_live_analysis(args, journal_path, telegram_config)
    return 0


def _run_brief(args: argparse.Namespace, telegram_config: TelegramConfig | None) -> None:
    markets = [
        load_live_market_data(symbol=symbol, intervals=args.intervals, limit=args.limit)
        for symbol in args.symbols
    ]
    text = generate_brief(markets, session_label=args.brief_session)
    print(json.dumps({"brief": "generated", "symbols": list(args.symbols)}, ensure_ascii=False))
    if telegram_config is not None:
        from .telegram import send_message
        send_message(text, telegram_config)
        print(json.dumps({"brief": "sent"}, ensure_ascii=False))


def _run_move_alert(args: argparse.Namespace, telegram_config: TelegramConfig | None) -> None:
    from .move_alert import generate_move_alerts

    markets = [
        load_live_market_data(symbol=symbol, intervals=args.intervals, limit=args.limit)
        for symbol in args.symbols
    ]
    alerts = generate_move_alerts(markets, threshold_pct=args.move_threshold_pct)
    print(
        json.dumps(
            {"move_alert": "checked", "symbols": list(args.symbols), "alerts": len(alerts)},
            ensure_ascii=False,
        )
    )
    if telegram_config is not None:
        from .telegram import send_message

        for index, text in enumerate(alerts, start=1):
            send_message(text, telegram_config)
            print(json.dumps({"move_alert": "sent", "index": index}, ensure_ascii=False))


def _run_paper_loop(args: argparse.Namespace, journal_path: Path, telegram_config: TelegramConfig | None) -> int:
    cycle = 0
    while args.max_runs is None or cycle < args.max_runs:
        cycle += 1
        print(
            json.dumps(
                {
                    "paper_loop_cycle": cycle,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            )
        )
        _run_live_analysis(args, journal_path, telegram_config)
        _run_evaluation(journal_path, args.lookahead_candles)
        _print_report(journal_path)

        if args.max_runs is not None and cycle >= args.max_runs:
            break
        time.sleep(args.run_every_minutes * 60)

    return 0


def _run_telegram_bot(args: argparse.Namespace, journal_path: Path, telegram_config: TelegramConfig) -> int:
    print(json.dumps({"telegram_bot": "listening", "journal": str(journal_path)}, ensure_ascii=False))
    scan_market = lambda: [result.signal for result, _inserted in _generate_live_analyses(args, journal_path)]
    run_telegram_bot(
        config=telegram_config,
        journal_path=journal_path,
        scan_market=scan_market,
        symbols=list(args.symbols),
        base_url=TELEGRAM_API_BASE_URL,
        poll_timeout=args.telegram_poll_timeout,
        poll_interval_seconds=args.telegram_poll_interval,
        max_polls=args.telegram_max_polls,
    )
    return 0


def _run_market_status(args: argparse.Namespace, telegram_config: TelegramConfig | None) -> None:
    messages = []
    for symbol in args.symbols:
        market = load_live_market_data(symbol=symbol, intervals=args.intervals, limit=args.limit)
        result = analyze_live_market(market, _matching_trigger(args.tradingview_trigger_obj, symbol))
        message = format_market_status(result)
        messages.append(message)
        print(json.dumps(result.status, ensure_ascii=False))
    if telegram_config is not None:
        from .telegram import send_message
        send_message(
            "\n\n".join(messages),
            telegram_config,
            chat_id=telegram_config.chat_id,
            base_url=TELEGRAM_API_BASE_URL,
        )


def _run_live_analysis(
    args: argparse.Namespace,
    journal_path: Path,
    telegram_config: TelegramConfig | None,
) -> None:
    for result, inserted in _generate_live_analyses(args, journal_path):
        signal = result.signal
        if telegram_config is not None and (signal.direction != "NO TRADE" or args.notify_no_trade):
            send_signal(signal, telegram_config)
        output = result.to_dict()
        output["journal_inserted"] = inserted
        print(json.dumps(output, ensure_ascii=False))


def _generate_live_analyses(args: argparse.Namespace, journal_path: Path):
    results = []
    for symbol in args.symbols:
        market = load_live_market_data(symbol=symbol, intervals=args.intervals, limit=args.limit)
        result = analyze_live_market(market, _matching_trigger(args.tradingview_trigger_obj, symbol))
        try:
            inserted = save_signal(result.signal, journal_path)
        except Exception as exc:
            print(json.dumps({"journal_error": str(exc), "symbol": symbol}, ensure_ascii=False))
            inserted = False
        results.append((result, inserted))
    return results


def _run_evaluation(journal_path: Path, lookahead_candles: int) -> None:
    results = evaluate_journal(str(journal_path), lookahead_candles)
    for result in results:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    if not results:
        print(json.dumps({"evaluated": 0}, ensure_ascii=False))


def _print_report(journal_path: Path) -> None:
    print(json.dumps(summarize_journal(journal_path), ensure_ascii=False))


def _tradingview_trigger(args: argparse.Namespace) -> TradingViewTrigger | None:
    payload = args.tradingview_trigger or os.environ.get("SIGNALPILOT_TRADINGVIEW_TRIGGER")
    return parse_tradingview_trigger(payload)


def _matching_trigger(trigger: TradingViewTrigger | None, symbol: str) -> TradingViewTrigger | None:
    if trigger is None:
        return None
    return trigger if trigger.symbol == symbol.upper() else None
