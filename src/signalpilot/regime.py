from __future__ import annotations

import pandas as pd


def classify_trend(row: pd.Series) -> str:
    close = float(row["close"])
    ema50 = float(row["ema50"])
    ema200 = float(row["ema200"])
    if close > ema50 > ema200:
        return "up"
    if close < ema50 < ema200:
        return "down"
    return "range"


def volatility_state(row: pd.Series) -> str:
    close = float(row["close"])
    atr = float(row["atr14"])
    if close <= 0 or atr <= 0:
        return "unknown"
    atr_pct = atr / close
    if atr_pct < 0.01:
        return "compressed"
    if atr_pct > 0.04:
        return "expanded"
    return "normal"
