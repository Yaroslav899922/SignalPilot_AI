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
    data["macd"], data["macd_signal"], data["macd_hist"] = _macd(close)
    data["recent_high20"] = high.shift(1).rolling(20).max()
    data["recent_low20"] = low.shift(1).rolling(20).min()
    if "volume" in data.columns:
        data["volume_avg20"] = data["volume"].shift(1).rolling(20).mean()
    else:
        data["volume_avg20"] = pd.NA

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


def _macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    hist = macd - signal
    return macd, signal, hist
