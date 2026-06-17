"""Download frozen Binance USD-M futures history for the evaluation rig.

Run this ONCE on a machine that can reach Binance (e.g. your computer):

    python -m signalpilot.rig.download

It saves closed candles to ``data/ohlcv/{SYMBOL}_{interval}.csv`` for:
  * 4h  — drives trend / EMA50 / EMA200 / ATR / pullback zone
  * 15m — used to check intrabar fills and stop-vs-target ordering

The files form a frozen data slice so every rig run is deterministic.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

BASE_URL = "https://fapi.binance.com"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
INTERVAL_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}

# Evaluation window starts here. 4h also needs ~200 candles of warm-up for
# EMA200 (~34 days), so we fetch 4h from a little earlier.
EVAL_START = "2024-11-01T00:00:00Z"
WARMUP_DAYS_4H = 45
PAGE_LIMIT = 1500

OUT_DIR = Path(__file__).resolve().parents[3] / "data" / "ohlcv"


def _get_json(path: str, params: dict[str, object]) -> object:
    url = f"{BASE_URL}{path}?{urlencode(params)}"
    for attempt in range(1, 6):
        try:
            with urlopen(url, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code in {418, 429} or 500 <= error.code < 600:
                time.sleep(0.5 * attempt)
                continue
            raise
        except (TimeoutError, URLError):
            time.sleep(0.5 * attempt)
            continue
    raise RuntimeError(f"failed after retries: {url}")


def _to_ms(iso: str) -> int:
    return int(pd.Timestamp(iso).timestamp() * 1000)


def fetch_range(symbol: str, interval: str, start_ms: int) -> list:
    step = INTERVAL_MS[interval]
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows: list = []
    cursor = start_ms
    while cursor < now_ms:
        batch = _get_json(
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": interval, "startTime": cursor, "limit": PAGE_LIMIT},
        )
        if not batch:
            break
        rows.extend(batch)
        last_open = int(batch[-1][0])
        last_date = datetime.utcfromtimestamp(last_open / 1000).date()
        print(f"    {symbol} {interval}: {len(rows):>6} candles ... up to {last_date}", flush=True)
        if len(batch) < PAGE_LIMIT:
            break
        nxt = last_open + step
        if nxt <= cursor:
            break
        cursor = nxt
        time.sleep(0.2)
    return rows


def to_frame(raw: list) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame()
    frame = pd.DataFrame(
        [
            {
                "open_time": pd.to_datetime(row[0], unit="ms", utc=True),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "close_time": pd.to_datetime(row[6], unit="ms", utc=True),
            }
            for row in raw
        ]
    )
    frame = frame.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    now = pd.Timestamp.now(tz="UTC")
    frame = frame.loc[frame["close_time"] <= now].reset_index(drop=True)
    return frame


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    eval_start = _to_ms(EVAL_START)
    start_4h = eval_start - WARMUP_DAYS_4H * 24 * 3_600 * 1000

    print("SignalPilot history download")
    print(f"Saving to: {OUT_DIR}")
    print(f"Symbols:   {', '.join(SYMBOLS)}")
    print(f"Window:    4h from {datetime.utcfromtimestamp(start_4h/1000).date()} "
          f"(incl. warm-up), 15m from {EVAL_START[:10]}\n")

    summary = []
    for symbol in SYMBOLS:
        for interval, start in (("4h", start_4h), ("15m", eval_start)):
            print(f"  Downloading {symbol} {interval} ...", flush=True)
            frame = to_frame(fetch_range(symbol, interval, start))
            out_path = OUT_DIR / f"{symbol}_{interval}.csv"
            frame.to_csv(out_path, index=False)
            if len(frame):
                rng = f"{frame['open_time'].iloc[0]:%Y-%m-%d} -> {frame['open_time'].iloc[-1]:%Y-%m-%d}"
            else:
                rng = "EMPTY"
            print(f"  Saved {out_path.name}: {len(frame)} rows ({rng})\n", flush=True)
            summary.append((symbol, interval, len(frame), rng))

    print("==== DOWNLOAD COMPLETE ====")
    for symbol, interval, n, rng in summary:
        print(f"  {symbol:9} {interval:3}: {n:>6} rows  {rng}")
    print("\nFiles saved in data/ohlcv/. You can close this window.")
    print(">>> Now go back to Claude and write: gotovo <<<")
    return 0


if __name__ == "__main__":
    sys.exit(main())
