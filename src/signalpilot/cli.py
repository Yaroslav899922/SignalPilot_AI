from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .binance import (
    DEFAULT_KLINE_LIMIT,
    fetch_funding_rate,
    fetch_klines,
    fetch_long_short_ratio,
    fetch_open_interest,
    fetch_order_book_spread_pct,
)
from .indicators import add_indicators
from .journal import save_signal, summarize_journal
from .market import FuturesContext
from .paper import backtest_symbol, evaluate_journal
from .signals import DEFAULT_TIMEFRAMES, Signal, build_multi_timeframe_signal, build_signal
from .telegram import TELEGRAM_API_BASE_URL, TelegramConfig, send_signal
from .telegram_bot import run_telegram_bot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate SignalPilot MVP signals.")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    parser.add_argument("--interval", help="Run the older single-timeframe mode, for example 1h.")
    parser.add_argument("--intervals", nargs="+", default=list(DEFAULT_TIMEFRAMES))
    parser.add_argument("--limit", type=int, default=DEFAULT_KLINE_LIMIT)
    parser.add_argument("--journal", default="data/signals.sqlite3")
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument("--report", action="store_true", help="Print a compact paper-test journal summary.")
    parser.add_argument("--paper-loop", action="store_true", help="Run live paper-test cycles until stopped.")
    parser.add_argument("--run-every-minutes", type=float, default=60.0)
    parser.add_argument("--max-runs", type=int, help="Stop paper loop after this many cycles.")
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--backtest-limit", type=int, default=1000)
    parser.add_argument("--target-signals", type=int, default=50)
    parser.add_argument("--lookahead-candles", type=int, default=6)
    parser.add_argument("--notify", action="store_true", help="Send generated signals to Telegram.")
    parser.add_argument("--telegram-bot", action="store_true", help="Reply to Telegram commands via polling.")
    parser.add_argument("--telegram-poll-interval", type=float, default=1.0)
    parser.add_argument("--telegram-poll-timeout", type=int, default=30)
    parser.add_argument("--telegram-max-polls", type=int, help="Stop Telegram bot after this many polling cycles.")
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

    if args.paper_loop:
        return _run_paper_loop(args, journal_path, telegram_config)

    if args.backtest:
        interval = args.interval or "1h"
        for symbol in args.symbols:
            summary, _signals = backtest_symbol(
                symbol=symbol,
                interval=interval,
                limit=args.backtest_limit,
                lookahead_candles=args.lookahead_candles,
                target_signals=args.target_signals,
            )
            print(json.dumps(summary.to_dict(), ensure_ascii=False))
        return 0

    if args.evaluate:
        _run_evaluation(journal_path, args.lookahead_candles)
        return 0

    _run_signal_generation(args, journal_path, telegram_config)
    return 0


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
        _run_signal_generation(args, journal_path, telegram_config)
        _run_evaluation(journal_path, args.lookahead_candles)
        _print_report(journal_path)

        if args.max_runs is not None and cycle >= args.max_runs:
            break
        time.sleep(args.run_every_minutes * 60)

    return 0


def _run_telegram_bot(args: argparse.Namespace, journal_path: Path, telegram_config: TelegramConfig) -> int:
    print(json.dumps({"telegram_bot": "listening", "journal": str(journal_path)}, ensure_ascii=False))
    run_telegram_bot(
        config=telegram_config,
        journal_path=journal_path,
        scan_market=lambda: [signal for signal, _inserted in _generate_signals(args, journal_path)],
        symbols=list(args.symbols),
        base_url=TELEGRAM_API_BASE_URL,
        poll_timeout=args.telegram_poll_timeout,
        poll_interval_seconds=args.telegram_poll_interval,
        max_polls=args.telegram_max_polls,
    )
    return 0


def _run_signal_generation(
    args: argparse.Namespace,
    journal_path: Path,
    telegram_config: TelegramConfig | None,
) -> None:
    for signal, inserted in _generate_signals(args, journal_path):
        if telegram_config is not None:
            send_signal(signal, telegram_config)
        output = signal.to_dict()
        output["journal_inserted"] = inserted
        print(json.dumps(output, ensure_ascii=False))


def _generate_signals(args: argparse.Namespace, journal_path: Path) -> list[tuple[Signal, bool]]:
    results = []
    for symbol in args.symbols:
        futures_context = _fetch_futures_context(symbol)
        if args.interval:
            candles = fetch_klines(symbol=symbol, interval=args.interval, limit=args.limit)
            enriched = add_indicators(candles)
            signal = build_signal(
                symbol=symbol,
                interval=args.interval,
                candles=enriched,
                futures_context=futures_context,
            )
        else:
            candles_by_interval = {
                interval: add_indicators(fetch_klines(symbol=symbol, interval=interval, limit=args.limit))
                for interval in args.intervals
            }
            signal = build_multi_timeframe_signal(
                symbol=symbol,
                candles_by_interval=candles_by_interval,
                futures_context=futures_context,
            )
        inserted = save_signal(signal, journal_path)
        results.append((signal, inserted))
    return results


def _run_evaluation(journal_path: Path, lookahead_candles: int) -> None:
    results = evaluate_journal(str(journal_path), lookahead_candles)
    for result in results:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    if not results:
        print(json.dumps({"evaluated": 0}, ensure_ascii=False))


def _print_report(journal_path: Path) -> None:
    print(json.dumps(summarize_journal(journal_path), ensure_ascii=False))


def _fetch_futures_context(symbol: str) -> FuturesContext:
    funding_rate = None
    open_interest = None
    long_short_ratio = None
    spread_pct = None
    try:
        funding_rate = fetch_funding_rate(symbol)
    except Exception:
        pass
    try:
        open_interest = fetch_open_interest(symbol)
    except Exception:
        pass
    try:
        long_short_ratio = fetch_long_short_ratio(symbol)
    except Exception:
        pass
    try:
        spread_pct = fetch_order_book_spread_pct(symbol)
    except Exception:
        pass
    return FuturesContext(
        funding_rate=funding_rate,
        open_interest=open_interest,
        long_short_ratio=long_short_ratio,
        spread_pct=spread_pct,
    )
