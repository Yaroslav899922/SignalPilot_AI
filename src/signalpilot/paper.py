from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from inspect import Parameter, signature

import pandas as pd

from .binance import fetch_klines
from .journal_backend import load_evaluable_signals, update_signal_evaluation
from .signals import Signal


ACTIONABLE_ROUND_TRIP_COST_RATE = 0.0012


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
    activated_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_journal(
    db_path: str,
    lookahead_candles: int,
    fetcher=fetch_klines,
    now: pd.Timestamp | None = None,
) -> list[EvaluationResult]:
    results = []
    now_ts = now if now is not None else pd.Timestamp.now(tz="utc")
    for signal in load_evaluable_signals(db_path):
        if not _evaluation_window_closed(signal, lookahead_candles, now_ts):
            continue
        fetch_kwargs: dict[str, object] = {
            "symbol": str(signal["symbol"]),
            "interval": str(signal["interval"]),
            "limit": max(lookahead_candles + 72, 200),
        }
        deadline = _signal_deadline(signal)
        if deadline is not None and _accepts_keyword(fetcher, "end_time"):
            fetch_kwargs["end_time"] = deadline
        candles = fetcher(
            **fetch_kwargs,
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
            activated_at=result.activated_at,
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
    future_candles = _future_candles(candles, signal, lookahead_candles)
    has_explicit_deadline = _signal_deadline(signal) is not None

    if (
        not len(future_candles)
        or (has_explicit_deadline and not _explicit_window_covered(candles, signal))
        or (not has_explicit_deadline and len(future_candles) < lookahead_candles)
    ):
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
    activated_at = _actionable_activated_at(signal)
    if stop is None or not targets:
        return EvaluationResult(
            signal_id=_signal_id(signal),
            symbol=symbol,
            direction=direction,
            outcome="no_result",
            max_favorable_price=None,
            max_adverse_price=None,
            activated_at=activated_at,
        )

    stop_price = float(stop)
    target_price = float(targets[0])
    window = future_candles if has_explicit_deadline else future_candles.head(lookahead_candles)

    if _is_market_brief_plan(signal):
        return _evaluate_market_brief_plan(signal, window, stop_price, target_price)

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
        activated_at=activated_at,
    )


def _is_market_brief_plan(signal: dict[str, object]) -> bool:
    return (
        str(signal.get("source", "")) == "market_brief"
        and _float_or_none(signal.get("entry_low")) is not None
        and _float_or_none(signal.get("entry_high")) is not None
    )


def _evaluate_market_brief_plan(
    signal: dict[str, object],
    window: pd.DataFrame,
    stop: float,
    target: float,
) -> EvaluationResult:
    symbol = str(signal["symbol"])
    direction = str(signal["direction"])
    entry_low = _float_or_none(signal.get("entry_low"))
    entry_high = _float_or_none(signal.get("entry_high"))
    assert entry_low is not None and entry_high is not None

    activation_index = _entry_activation_index(window, entry_low, entry_high)
    if activation_index is None:
        return EvaluationResult(
            signal_id=_signal_id(signal),
            symbol=symbol,
            direction=direction,
            outcome="not_activated",
            max_favorable_price=None,
            max_adverse_price=None,
        )

    activated_window = window.iloc[activation_index:]
    if direction == "LONG":
        max_favorable = float(activated_window["high"].max())
        max_adverse = float(activated_window["low"].min())
    else:
        max_favorable = float(activated_window["low"].min())
        max_adverse = float(activated_window["high"].max())

    outcome = _outcome(direction, stop, target, activated_window)
    result_r = _result_r(signal, direction, stop, target, outcome, activated_window)
    return EvaluationResult(
        signal_id=_signal_id(signal),
        symbol=symbol,
        direction=direction,
        outcome=outcome,
        max_favorable_price=round(max_favorable, 2),
        max_adverse_price=round(max_adverse, 2),
        result_R=result_r,
        activated_at=_candle_time(activated_window.iloc[0]),
    )


def _entry_activation_index(candles: pd.DataFrame, entry_low: float, entry_high: float) -> int | None:
    for index, row in enumerate(candles.itertuples(index=False)):
        if float(row.low) <= entry_high and float(row.high) >= entry_low:
            return index
    return None


def _candle_time(row: pd.Series) -> str | None:
    if "open_time" not in row.index:
        return None
    return pd.to_datetime(row["open_time"], utc=True).isoformat()


_INTERVAL_HOURS = {
    "5m": 5 / 60,
    "15m": 0.25,
    "30m": 0.5,
    "1h": 1.0,
    "2h": 2.0,
    "4h": 4.0,
    "1d": 24.0,
}


def _evaluation_window_closed(
    signal: dict[str, object],
    lookahead_candles: int,
    now: pd.Timestamp,
) -> bool:
    """True, коли повне вікно спостереження плану вже минуло і його час оцінювати."""
    deadline = _signal_deadline(signal)
    if deadline is not None:
        return bool(_as_utc(now) >= deadline)
    created = _signal_start(signal)
    if created is None:
        return True
    hours = _INTERVAL_HOURS.get(str(signal.get("interval") or "1h"), 1.0)
    return bool(_as_utc(now) >= created + pd.Timedelta(hours=lookahead_candles * hours))


def _future_candles(
    candles: pd.DataFrame,
    signal: dict[str, object],
    lookahead_candles: int,
) -> pd.DataFrame:
    if "open_time" not in candles.columns:
        return candles.head(lookahead_candles)

    start = _signal_start(signal)
    if start is None:
        return candles.head(lookahead_candles)
    open_times = pd.to_datetime(candles["open_time"], utc=True)
    mask = open_times >= start
    deadline = _signal_deadline(signal)
    if deadline is not None:
        mask &= _candle_close_times(candles, signal) <= deadline
    selected = candles.loc[mask].copy()
    selected = selected.sort_values("open_time")
    return selected if deadline is not None else selected.head(lookahead_candles)


def _signal_start(signal: dict[str, object]) -> pd.Timestamp | None:
    triggered = _timestamp_or_none(signal.get("triggered_at"))
    if triggered is not None:
        return triggered
    return _timestamp_or_none(signal.get("created_at"))


def _signal_deadline(signal: dict[str, object]) -> pd.Timestamp | None:
    return _timestamp_or_none(signal.get("expires_at"))


def _timestamp_or_none(value: object) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        return pd.to_datetime(str(value), utc=True)
    except (TypeError, ValueError):
        return None


def _as_utc(value: pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("utc")
    return timestamp.tz_convert("utc")


def _candle_close_times(
    candles: pd.DataFrame,
    signal: dict[str, object],
) -> pd.Series:
    if "close_time" in candles.columns:
        return pd.to_datetime(candles["close_time"], utc=True)
    open_times = pd.to_datetime(candles["open_time"], utc=True)
    hours = _INTERVAL_HOURS.get(str(signal.get("interval") or "1h"), 1.0)
    return open_times + pd.Timedelta(hours=hours)


def _explicit_window_covered(
    candles: pd.DataFrame,
    signal: dict[str, object],
) -> bool:
    deadline = _signal_deadline(signal)
    if deadline is None or candles.empty or "open_time" not in candles.columns:
        return False
    close_times = _candle_close_times(candles, signal)
    if close_times.empty:
        return False
    hours = _INTERVAL_HOURS.get(str(signal.get("interval") or "1h"), 1.0)
    return bool(close_times.max() + pd.Timedelta(hours=hours) >= deadline)


def _actionable_activated_at(signal: dict[str, object]) -> str | None:
    if str(signal.get("source") or "") != "actionable_alert":
        return None
    activated = _signal_start(signal)
    return activated.isoformat() if activated is not None else None


def _accepts_keyword(callable_object: object, keyword: str) -> bool:
    try:
        parameters = signature(callable_object).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.name == keyword or parameter.kind == Parameter.VAR_KEYWORD
        for parameter in parameters
    )


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
    raw = _r_for_entry(direction, entry, stop, target, outcome, candles)
    return _apply_actionable_cost(signal, raw, entry, stop)


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
    raw = _r_for_entry(direction, entry, baseline_stop, baseline_target, outcome, candles)
    return _apply_actionable_cost(signal, raw, entry, baseline_stop)


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


def _apply_actionable_cost(
    signal: dict[str, object],
    result_r: float | None,
    entry: float,
    stop: float,
) -> float | None:
    if result_r is None or str(signal.get("source", "")) != "actionable_alert":
        return result_r
    risk = abs(entry - stop)
    if risk <= 0:
        return result_r
    cost_r = entry * ACTIONABLE_ROUND_TRIP_COST_RATE / risk
    return round(result_r - cost_r, 4)


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
