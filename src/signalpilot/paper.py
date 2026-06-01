from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import pandas as pd

from .binance import fetch_klines
from .indicators import add_indicators
from .journal import load_evaluable_signals, update_signal_evaluation
from .market import FuturesContext
from .signals import Signal, build_signal


@dataclass(frozen=True)
class EvaluationResult:
    signal_id: int | None
    symbol: str
    direction: str
    outcome: str
    max_favorable_price: float | None
    max_adverse_price: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BacktestSignal:
    symbol: str
    interval: str
    created_at: str
    direction: str
    outcome: str
    entry_zone: str
    stop: float | None
    target: float | None
    max_favorable_price: float | None
    max_adverse_price: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BacktestSummary:
    symbol: str
    interval: str
    scanned_candles: int
    directional_signals: int
    target_hit: int
    stop_hit: int
    no_result: int
    not_enough_data: int
    futures_context_mode: str = "rule_only_neutral"
    uses_live_futures_filters: bool = False

    def to_dict(self) -> dict[str, object]:
        total_resolved = self.target_hit + self.stop_hit
        win_rate = self.target_hit / total_resolved if total_resolved else None
        data = asdict(self)
        data["win_rate"] = win_rate
        return data


def evaluate_journal(
    db_path: str,
    lookahead_candles: int,
    fetcher=fetch_klines,
) -> list[EvaluationResult]:
    results = []
    for signal in load_evaluable_signals(db_path):
        candles = fetcher(
            symbol=str(signal["symbol"]),
            interval=str(signal["interval"]),
            limit=max(lookahead_candles + 20, 50),
        )
        result = evaluate_signal(signal, candles, lookahead_candles)
        update_signal_evaluation(
            db_path=db_path,
            signal_id=int(signal["id"]),
            outcome=result.outcome,
            max_favorable_price=result.max_favorable_price,
            max_adverse_price=result.max_adverse_price,
        )
        results.append(result)
    return results


def backtest_symbol(
    symbol: str,
    interval: str,
    limit: int,
    lookahead_candles: int,
    target_signals: int,
    fetcher=fetch_klines,
) -> tuple[BacktestSummary, list[BacktestSignal]]:
    raw_candles = fetcher(symbol=symbol, interval=interval, limit=limit)
    enriched = add_indicators(raw_candles)
    results = backtest_candles(
        symbol=symbol,
        interval=interval,
        candles=enriched,
        lookahead_candles=lookahead_candles,
        target_signals=target_signals,
    )
    return summarize_backtest(symbol, interval, len(enriched), results), results


def backtest_candles(
    symbol: str,
    interval: str,
    candles: pd.DataFrame,
    lookahead_candles: int,
    target_signals: int,
    futures_context: FuturesContext | None = None,
) -> list[BacktestSignal]:
    if lookahead_candles <= 0:
        raise ValueError("lookahead_candles must be greater than zero")
    if target_signals <= 0:
        raise ValueError("target_signals must be greater than zero")

    context = futures_context or FuturesContext(
        funding_rate=0.0,
        open_interest=1.0,
        long_short_ratio=1.0,
        spread_pct=0.0,
    )
    signals: list[BacktestSignal] = []
    max_signal_index = len(candles) - lookahead_candles

    for index in range(1, max_signal_index + 1):
        historical_window = candles.iloc[:index].copy()
        signal = build_signal(symbol, interval, historical_window, context)
        if signal.direction == "NO TRADE":
            continue

        created_at = _created_at_for_backtest(candles, index - 1)
        evaluation = evaluate_signal(
            _evaluation_input(signal, created_at),
            candles.iloc[index : index + lookahead_candles],
            lookahead_candles,
        )
        signals.append(
            BacktestSignal(
                symbol=signal.symbol,
                interval=signal.interval,
                created_at=created_at,
                direction=signal.direction,
                outcome=evaluation.outcome,
                entry_zone=signal.entry_zone,
                stop=signal.stop,
                target=signal.targets[0] if signal.targets else None,
                max_favorable_price=evaluation.max_favorable_price,
                max_adverse_price=evaluation.max_adverse_price,
            )
        )
        if len(signals) >= target_signals:
            break

    return signals


def summarize_backtest(
    symbol: str,
    interval: str,
    scanned_candles: int,
    signals: list[BacktestSignal],
) -> BacktestSummary:
    return BacktestSummary(
        symbol=symbol.upper(),
        interval=interval,
        scanned_candles=scanned_candles,
        directional_signals=len(signals),
        target_hit=sum(1 for signal in signals if signal.outcome == "target_hit"),
        stop_hit=sum(1 for signal in signals if signal.outcome == "stop_hit"),
        no_result=sum(1 for signal in signals if signal.outcome == "no_result"),
        not_enough_data=sum(1 for signal in signals if signal.outcome == "not_enough_data"),
    )


def evaluate_signal(
    signal: dict[str, object],
    candles: pd.DataFrame,
    lookahead_candles: int,
) -> EvaluationResult:
    symbol = str(signal["symbol"])
    direction = str(signal["direction"])
    future_candles = _future_candles(candles, str(signal["created_at"]), lookahead_candles)

    if len(future_candles) < lookahead_candles:
        return EvaluationResult(
            signal_id=_signal_id(signal),
            symbol=symbol,
            direction=direction,
            outcome="not_enough_data",
            max_favorable_price=None,
            max_adverse_price=None,
        )

    stop = signal.get("stop")
    targets = json.loads(str(signal.get("targets_json", "[]")))
    if stop is None or not targets:
        return EvaluationResult(
            signal_id=_signal_id(signal),
            symbol=symbol,
            direction=direction,
            outcome="no_result",
            max_favorable_price=None,
            max_adverse_price=None,
        )

    stop_price = float(stop)
    target_price = float(targets[0])
    window = future_candles.head(lookahead_candles)

    if direction == "LONG":
        max_favorable = float(window["high"].max())
        max_adverse = float(window["low"].min())
    else:
        max_favorable = float(window["low"].min())
        max_adverse = float(window["high"].max())

    outcome = _outcome(direction, stop_price, target_price, window)
    return EvaluationResult(
        signal_id=_signal_id(signal),
        symbol=symbol,
        direction=direction,
        outcome=outcome,
        max_favorable_price=round(max_favorable, 2),
        max_adverse_price=round(max_adverse, 2),
    )


def _future_candles(candles: pd.DataFrame, created_at: str, lookahead_candles: int) -> pd.DataFrame:
    if "open_time" not in candles.columns:
        return candles.head(lookahead_candles)

    created = pd.to_datetime(created_at, utc=True)
    open_times = pd.to_datetime(candles["open_time"], utc=True)
    return candles.loc[open_times > created].head(lookahead_candles)


def _outcome(direction: str, stop: float, target: float, candles: pd.DataFrame) -> str:
    for row in candles.itertuples(index=False):
        high = float(row.high)
        low = float(row.low)
        if direction == "LONG":
            if low <= stop:
                return "stop_hit"
            if high >= target:
                return "target_hit"
        elif direction == "SHORT":
            if high >= stop:
                return "stop_hit"
            if low <= target:
                return "target_hit"
    return "no_result"


def _signal_id(signal: dict[str, object]) -> int | None:
    value = signal.get("id")
    return None if value is None else int(value)


def _created_at_for_backtest(candles: pd.DataFrame, index: int) -> str:
    if "open_time" in candles.columns:
        return pd.to_datetime(candles.iloc[index]["open_time"], utc=True).isoformat()
    return str(index)


def _evaluation_input(signal: Signal, created_at: str) -> dict[str, object]:
    return {
        "id": None,
        "created_at": created_at,
        "symbol": signal.symbol,
        "direction": signal.direction,
        "stop": signal.stop,
        "targets_json": json.dumps(signal.targets),
    }
