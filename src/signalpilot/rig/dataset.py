"""Load the frozen OHLCV slice and prepare 4h decision bars."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..indicators import add_indicators

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "ohlcv"
EVAL_START = pd.Timestamp("2024-11-01", tz="UTC")
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

_INDICATOR_COLUMNS = ["ema50", "ema200", "atr14", "rsi14", "recent_high20", "recent_low20"]


@dataclass(frozen=True)
class SymbolData:
    symbol: str
    bars4h: pd.DataFrame      # enriched, includes warm-up
    bars15m: pd.DataFrame     # sorted by open_time
    decisions: pd.DataFrame   # eval-window 4h bars with a decision_time column


def load_symbol(symbol: str, data_dir: Path = DATA_DIR, eval_start: pd.Timestamp = EVAL_START) -> SymbolData:
    d4 = pd.read_csv(data_dir / f"{symbol}_4h.csv", parse_dates=["open_time", "close_time"])
    d15 = pd.read_csv(data_dir / f"{symbol}_15m.csv", parse_dates=["open_time", "close_time"])
    d15 = d15.sort_values("open_time").reset_index(drop=True)

    enriched = add_indicators(d4).reset_index(drop=True)
    decisions = enriched.dropna(subset=_INDICATOR_COLUMNS).copy()
    decisions = decisions[decisions["open_time"] >= eval_start].copy()
    # The plan made at a 4h close becomes actionable at open_time + 4h, which is
    # exactly the next 15m candle's open (Binance close_time is open+4h-1ms).
    decisions["decision_time"] = decisions["open_time"] + pd.Timedelta(hours=4)
    decisions = decisions.reset_index(drop=True)
    return SymbolData(symbol=symbol, bars4h=enriched, bars15m=d15, decisions=decisions)


def load_all(symbols=SYMBOLS, data_dir: Path = DATA_DIR, eval_start: pd.Timestamp = EVAL_START) -> dict[str, SymbolData]:
    return {s: load_symbol(s, data_dir, eval_start) for s in symbols}
