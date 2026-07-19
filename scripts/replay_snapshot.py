from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from signalpilot.actionable import (
    TRIGGERED,
    analyze_actionable_setup,
    format_setup_message,
    reconcile_setup_state,
    should_notify_setup_event,
)
from signalpilot.binance import DEFAULT_KLINE_LIMIT, fetch_klines
from signalpilot.indicators import add_indicators
from signalpilot.market import FuturesContext
from signalpilot.market_data import LiveMarketData, MarketFrame


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Replay the actionable-alert engine at a historical UTC time."
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--at", required=True, help="ISO timestamp, for example 2026-07-18T18:00:00Z")
    parser.add_argument("--limit", type=int, default=DEFAULT_KLINE_LIMIT)
    parser.add_argument(
        "--scan-hours",
        type=int,
        default=0,
        help="Replay every closed 15m step in this lookback and summarize unique entries.",
    )
    args = parser.parse_args()

    at = datetime.fromisoformat(args.at.replace("Z", "+00:00"))
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    at = at.astimezone(timezone.utc)
    symbol = args.symbol.upper()
    frames = {}
    for interval in ("15m", "1h", "4h"):
        candles = add_indicators(
            fetch_klines(symbol, interval=interval, limit=args.limit, end_time=at)
        )
        frames[interval] = MarketFrame(
            symbol=symbol,
            interval=interval,
            source="binance_historical_replay",
            candles=candles,
        )

    market = _market_at(symbol, frames, at)
    if args.scan_hours > 0:
        return _scan_history(symbol, frames, at, args.scan_hours)

    setup = analyze_actionable_setup(market, now_utc=at)
    print(
        json.dumps(
            {
                "symbol": symbol,
                "at": at.isoformat(),
                "latest_candles": {
                    interval: frame.latest_closed_at for interval, frame in frames.items()
                },
                "setup": None if setup is None else setup.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if setup is not None:
        print("\n--- Telegram preview ---\n")
        print(format_setup_message(setup))
    return 0


def _scan_history(
    symbol: str,
    source_frames: dict[str, MarketFrame],
    at: datetime,
    scan_hours: int,
) -> int:
    start = at - timedelta(hours=scan_hours)
    step = start.replace(minute=(start.minute // 15) * 15, second=0, microsecond=0)
    history = []
    state_changes = []
    notification_events = []
    while step <= at:
        market = _market_at(symbol, source_frames, step)
        candidate = analyze_actionable_setup(market, now_utc=step)
        events = reconcile_setup_state(candidate, history, market, now_utc=step)
        for event in events:
            if should_notify_setup_event(event, history):
                notification_events.append(event)
            history.append(event)
            state_changes.append(event)
        step += timedelta(minutes=15)

    entries = [event for event in state_changes if event.status == TRIGGERED]
    print(
        json.dumps(
            {
                "symbol": symbol,
                "from": start.isoformat(),
                "to": at.isoformat(),
                "state_changes": len(state_changes),
                "telegram_messages": len(notification_events),
                "confirmed_entries": len({entry.setup_id for entry in entries}),
                "event_counts": {
                    status: sum(event.status == status for event in state_changes)
                    for status in sorted({event.status for event in state_changes})
                },
                "entries": [
                    {
                        "setup_id": entry.setup_id,
                        "created_at": entry.created_at,
                        "pattern": entry.pattern,
                        "direction": entry.direction,
                        "entry": [entry.entry_low, entry.entry_high],
                        "stop": entry.stop,
                        "target_1": entry.targets[0],
                    }
                    for entry in entries
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _market_at(
    symbol: str,
    source_frames: dict[str, MarketFrame],
    at: datetime,
) -> LiveMarketData:
    frames = {}
    for interval, frame in source_frames.items():
        candles = frame.candles
        if "close_time" in candles.columns:
            candles = candles.loc[candles["close_time"] <= at].reset_index(drop=True)
        candles = candles.tail(250).reset_index(drop=True)
        frames[interval] = MarketFrame(
            symbol=symbol,
            interval=interval,
            source=frame.source,
            candles=candles,
        )
    return LiveMarketData(
        symbol=symbol,
        source="binance_historical_replay",
        collected_at=at.isoformat(),
        frames=frames,
        futures_context=FuturesContext(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
