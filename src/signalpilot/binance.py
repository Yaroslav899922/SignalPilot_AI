from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd


BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"
BINANCE_SPOT_BASE_URL = "https://data-api.binance.vision"
DEFAULT_KLINE_LIMIT = 500
MAX_HTTP_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 0.5


def fetch_klines(
    symbol: str,
    interval: str = "1h",
    limit: int = DEFAULT_KLINE_LIMIT,
    base_url: str = BINANCE_FUTURES_BASE_URL,
) -> pd.DataFrame:
    """Fetch closed Binance USD-M futures candles; fall back to spot if futures is geo-blocked."""
    try:
        raw_rows = _get_json(
            "/fapi/v1/klines",
            {"symbol": symbol.upper(), "interval": interval, "limit": limit},
            base_url,
        )
    except HTTPError as error:
        if error.code != 451:
            raise
        raw_rows = _get_json(
            "/api/v3/klines",
            {"symbol": symbol.upper(), "interval": interval, "limit": limit},
            BINANCE_SPOT_BASE_URL,
        )

    rows = [
        {
            "open_time": pd.to_datetime(row[0], unit="ms", utc=True),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "close_time": pd.to_datetime(row[6], unit="ms", utc=True),
        }
        for row in raw_rows
    ]
    return _closed_candles(pd.DataFrame(rows))


def fetch_open_interest(
    symbol: str,
    base_url: str = BINANCE_FUTURES_BASE_URL,
) -> float:
    """Fetch present USD-M futures open interest for a symbol."""
    payload = _get_json("/fapi/v1/openInterest", {"symbol": symbol.upper()}, base_url)
    return float(payload["openInterest"])


def fetch_funding_rate(
    symbol: str,
    base_url: str = BINANCE_FUTURES_BASE_URL,
) -> float:
    """Fetch latest USD-M futures funding rate for a symbol."""
    payload = _get_json("/fapi/v1/premiumIndex", {"symbol": symbol.upper()}, base_url)
    return float(payload["lastFundingRate"])


def fetch_long_short_ratio(
    symbol: str,
    period: str = "5m",
    base_url: str = BINANCE_FUTURES_BASE_URL,
) -> float:
    """Fetch latest global long/short account ratio for a USD-M futures symbol."""
    payload = _get_json(
        "/futures/data/globalLongShortAccountRatio",
        {"symbol": symbol.upper(), "period": period, "limit": 1},
        base_url,
    )
    if not payload:
        raise ValueError(f"long/short ratio unavailable for {symbol.upper()}")
    return float(payload[-1]["longShortRatio"])


def fetch_order_book_spread_pct(
    symbol: str,
    limit: int = 5,
    base_url: str = BINANCE_FUTURES_BASE_URL,
) -> float:
    """Fetch top-of-book spread as a percentage of mid price."""
    payload = _get_json(
        "/fapi/v1/depth",
        {"symbol": symbol.upper(), "limit": limit},
        base_url,
    )
    best_bid = float(payload["bids"][0][0])
    best_ask = float(payload["asks"][0][0])
    mid = (best_bid + best_ask) / 2
    if mid <= 0:
        raise ValueError(f"invalid order book mid price for {symbol.upper()}")
    return ((best_ask - best_bid) / mid) * 100


def _get_json(path: str, params: dict[str, object], base_url: str) -> object:
    query = urlencode(params)
    url = f"{base_url}{path}?{query}"

    for attempt in range(1, MAX_HTTP_ATTEMPTS + 1):
        try:
            with urlopen(url, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if not _should_retry_http(error.code) or attempt == MAX_HTTP_ATTEMPTS:
                raise
            time.sleep(RETRY_DELAY_SECONDS * attempt)
        except (TimeoutError, URLError):
            if attempt == MAX_HTTP_ATTEMPTS:
                raise
            time.sleep(RETRY_DELAY_SECONDS * attempt)

    raise RuntimeError("unreachable HTTP retry state")


def _closed_candles(candles: pd.DataFrame, now_utc: datetime | pd.Timestamp | None = None) -> pd.DataFrame:
    if candles.empty or "close_time" not in candles.columns:
        return candles

    now = pd.Timestamp(now_utc or datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.tz_localize(timezone.utc)
    else:
        now = now.tz_convert(timezone.utc)

    close_times = pd.to_datetime(candles["close_time"], utc=True)
    return candles.loc[close_times <= now].reset_index(drop=True)


def _should_retry_http(status_code: int) -> bool:
    return status_code in {418, 429} or 500 <= status_code < 600
