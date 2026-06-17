from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

import pandas as pd

from .binance import (
    DEFAULT_KLINE_LIMIT,
    fetch_funding_rate,
    fetch_klines,
    fetch_long_short_ratio,
    fetch_open_interest,
    fetch_order_book_spread_pct,
)
from .indicators import add_indicators
from .market import FuturesContext


DEFAULT_LIVE_INTERVALS = ("15m", "1h", "4h")


@dataclass(frozen=True)
class MarketFrame:
    symbol: str
    interval: str
    source: str
    candles: pd.DataFrame

    @property
    def rows(self) -> int:
        return len(self.candles)

    @property
    def latest_closed_at(self) -> str | None:
        if self.candles.empty:
            return None
        if "open_time" in self.candles.columns:
            return pd.to_datetime(self.candles.iloc[-1]["open_time"], utc=True).isoformat()
        return None

    @property
    def latest_close(self) -> float | None:
        if self.candles.empty or "close" not in self.candles.columns:
            return None
        return float(self.candles.iloc[-1]["close"])

    @property
    def indicators_ready(self) -> bool:
        required = {"ema20", "ema50", "ema200", "atr14", "rsi14", "recent_high20", "recent_low20"}
        return required.issubset(self.candles.columns) and not self.candles.dropna(subset=list(required)).empty

    def to_status_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "source": self.source,
            "rows": self.rows,
            "latest_closed_at": self.latest_closed_at,
            "latest_close": self.latest_close,
            "indicators_ready": self.indicators_ready,
        }


@dataclass(frozen=True)
class LiveMarketData:
    symbol: str
    source: str
    collected_at: str
    frames: dict[str, MarketFrame]
    futures_context: FuturesContext

    def frame(self, interval: str) -> MarketFrame:
        return self.frames[interval]

    def to_status_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "collected_at": self.collected_at,
            "frames": {interval: frame.to_status_dict() for interval, frame in self.frames.items()},
            "futures_context": {
                "funding_rate": self.futures_context.funding_rate,
                "open_interest": self.futures_context.open_interest,
                "long_short_ratio": self.futures_context.long_short_ratio,
                "spread_pct": self.futures_context.spread_pct,
            },
        }


KlineFetcher = Callable[[str, str, int], pd.DataFrame]


def load_live_market_data(
    symbol: str,
    intervals: Iterable[str] = DEFAULT_LIVE_INTERVALS,
    limit: int = DEFAULT_KLINE_LIMIT,
    source: str = "binance_usdm_public",
    kline_fetcher: KlineFetcher | None = None,
) -> LiveMarketData:
    fetcher = kline_fetcher or _fetch_klines
    frames: dict[str, MarketFrame] = {}
    for interval in intervals:
        raw = fetcher(symbol.upper(), interval, limit)
        enriched = add_indicators(raw)
        frames[interval] = MarketFrame(
            symbol=symbol.upper(),
            interval=interval,
            source=source,
            candles=enriched,
        )
    return LiveMarketData(
        symbol=symbol.upper(),
        source=source,
        collected_at=datetime.now(timezone.utc).isoformat(),
        frames=frames,
        futures_context=fetch_futures_context(symbol),
    )


def load_live_market_universe(
    symbols: Iterable[str],
    intervals: Iterable[str] = DEFAULT_LIVE_INTERVALS,
    limit: int = DEFAULT_KLINE_LIMIT,
    kline_fetcher: KlineFetcher | None = None,
) -> list[LiveMarketData]:
    return [
        load_live_market_data(symbol, intervals=intervals, limit=limit, kline_fetcher=kline_fetcher)
        for symbol in symbols
    ]


def fetch_futures_context(symbol: str) -> FuturesContext:
    return FuturesContext(
        funding_rate=_safe_fetch(fetch_funding_rate, symbol),
        open_interest=_safe_fetch(fetch_open_interest, symbol),
        long_short_ratio=_safe_fetch(fetch_long_short_ratio, symbol),
        spread_pct=_safe_fetch(fetch_order_book_spread_pct, symbol),
    )


def _fetch_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    return fetch_klines(symbol=symbol, interval=interval, limit=limit)


def _safe_fetch(fetcher: Callable[[str], float], symbol: str) -> float | None:
    try:
        return fetcher(symbol)
    except Exception:
        return None
