from __future__ import annotations

import pandas as pd


def add_indicators(candles: pd.DataFrame) -> pd.DataFrame:
    required = {"high", "low", "close"}
    missing = required - set(candles.columns)
    if missing:
        raise ValueError(f"candles missing required columns: {', '.join(sorted(missing))}")

    data = candles.copy()
    close = data["close"]
    high = data["high"]
    low = data["low"]

    data["ema20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    data["ema50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()
    data["ema200"] = close.ewm(span=200, adjust=False, min_periods=200).mean()
    data["rsi14"] = _rsi(close, 14)
    data["atr14"] = _atr(high, low, close, 14)
    data["recent_high20"] = high.shift(1).rolling(20).max()
    data["recent_low20"] = low.shift(1).rolling(20).min()

    return data


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
