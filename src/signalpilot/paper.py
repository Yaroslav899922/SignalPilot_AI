from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import pandas as pd

from .binance import fetch_klines
from .journal_backend import load_evaluable_signals, update_signal_evaluation
from .signals import Signal


@dataclass(frozen=True)
class EvaluationResult:
    signal_id: int | None
    symbol: str
    direction: str
    outcome: str
    max_favorable_price: float | None
    max_adverse_price: float | None
    result_R: float | None = None
    baseline_R: float | None = None
    edge_R: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


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
            result_R=result.result_R,
            baseline_R=result.baseline_R,
            edge_R=result.edge_R,
        )
        results.append(result)
    return results


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
    result_R = _result_r(signal, direction, stop_price, target_price, outcome, window)
    baseline_R = _baseline_r(signal, direction, stop_price, target_price, window)
    edge_R = _edge_r(result_R, baseline_R)
    return EvaluationResult(
        signal_id=_signal_id(signal),
        symbol=symbol,
        direction=direction,
        outcome=outcome,
        max_favorable_price=round(max_favorable, 2),
        max_adverse_price=round(max_adverse, 2),
        result_R=result_R,
        baseline_R=baseline_R,
        edge_R=edge_R,
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


def _result_r(
    signal: dict[str, object],
    direction: str,
    stop: float,
    target: float,
    outcome: str,
    candles: pd.DataFrame,
) -> float | None:
    entry = _float_or_none(signal.get("close_price"))
    if entry is None:
        return None
    return _r_for_entry(direction, entry, stop, target, outcome, candles)


def _baseline_r(
    signal: dict[str, object],
    direction: str,
    stop: float,
    target: float,
    candles: pd.DataFrame,
) -> float | None:
    if candles.empty:
        return None
    entry = _first_open_or_close(candles)
    signal_entry = _float_or_none(signal.get("close_price"))
    if entry is None or signal_entry is None:
        return None
    risk = abs(signal_entry - stop)
    reward = abs(target - signal_entry)
    if risk <= 0:
        return None
    sign = 1 if direction == "LONG" else -1
    baseline_stop = entry - sign * risk
    baseline_target = entry + sign * reward
    outcome = _outcome(direction, baseline_stop, baseline_target, candles)
    return _r_for_entry(direction, entry, baseline_stop, baseline_target, outcome, candles)


def _r_for_entry(
    direction: str,
    entry: float,
    stop: float,
    target: float,
    outcome: str,
    candles: pd.DataFrame,
) -> float | None:
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    if outcome == "target_hit":
        return round(abs(target - entry) / risk, 4)
    if outcome == "stop_hit":
        return -1.0
    if outcome == "no_result":
        mark = _last_close_or_mid(candles)
        if mark is None:
            return None
        value = (mark - entry) / risk if direction == "LONG" else (entry - mark) / risk
        return round(float(value), 4)
    return None


def _edge_r(result_R: float | None, baseline_R: float | None) -> float | None:
    if result_R is None or baseline_R is None:
        return None
    return round(result_R - baseline_R, 4)


def _first_open_or_close(candles: pd.DataFrame) -> float | None:
    if candles.empty:
        return None
    if "open" in candles.columns:
        return float(candles.iloc[0]["open"])
    if "close" in candles.columns:
        return float(candles.iloc[0]["close"])
    return None


def _last_close_or_mid(candles: pd.DataFrame) -> float | None:
    if candles.empty:
        return None
    if "close" in candles.columns:
        return float(candles.iloc[-1]["close"])
    high = candles.iloc[-1].get("high") if hasattr(candles.iloc[-1], "get") else None
    low = candles.iloc[-1].get("low") if hasattr(candles.iloc[-1], "get") else None
    if high is not None and low is not None:
        return (float(high) + float(low)) / 2
    return None


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _signal_id(signal: dict[str, object]) -> int | None:
    value = signal.get("id")
    return None if value is None else int(value)


def _evaluation_input(signal: Signal, created_at: str) -> dict[str, object]:
    return {
        "id": None,
        "created_at": created_at,
        "symbol": signal.symbol,
        "direction": signal.direction,
        "close_price": signal.close_price,
        "stop": signal.stop,
        "targets_json": json.dumps(signal.targets),
    }
