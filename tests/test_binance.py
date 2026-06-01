import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

import pandas as pd

from signalpilot.binance import (
    _closed_candles,
    _get_json,
    fetch_funding_rate,
    fetch_long_short_ratio,
    fetch_open_interest,
    fetch_order_book_spread_pct,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class BinanceTests(unittest.TestCase):
    def test_closed_candles_drop_unfinished_candle(self):
        candles = pd.DataFrame(
            {
                "close": [100.0, 101.0],
                "close_time": pd.to_datetime(
                    ["2026-05-31T10:00:00Z", "2026-05-31T11:00:00Z"],
                    utc=True,
                ),
            }
        )

        result = _closed_candles(candles, now_utc=pd.Timestamp("2026-05-31T10:30:00Z"))

        self.assertEqual(result["close"].tolist(), [100.0])

    def test_fetch_open_interest_parses_payload(self):
        with patch("signalpilot.binance.urlopen", return_value=FakeResponse({"openInterest": "12345.678"})):
            value = fetch_open_interest("BTCUSDT")

        self.assertEqual(value, 12345.678)

    def test_fetch_funding_rate_parses_latest_payload(self):
        with patch("signalpilot.binance.urlopen", return_value=FakeResponse({"lastFundingRate": "0.00010000"})):
            value = fetch_funding_rate("ETHUSDT")

        self.assertEqual(value, 0.0001)

    def test_fetch_long_short_ratio_parses_latest_payload(self):
        payload = [{"longShortRatio": "1.2345"}]
        with patch("signalpilot.binance.urlopen", return_value=FakeResponse(payload)):
            value = fetch_long_short_ratio("BTCUSDT")

        self.assertEqual(value, 1.2345)

    def test_fetch_order_book_spread_pct_uses_best_bid_and_ask(self):
        payload = {"bids": [["99.0", "1.0"]], "asks": [["101.0", "1.0"]]}
        with patch("signalpilot.binance.urlopen", return_value=FakeResponse(payload)):
            value = fetch_order_book_spread_pct("BTCUSDT")

        self.assertEqual(value, 2.0)

    def test_get_json_retries_retryable_http_errors(self):
        retryable_error = HTTPError(
            url="https://example.test",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=None,
        )
        with patch("signalpilot.binance.urlopen", side_effect=[retryable_error, FakeResponse({"ok": True})]) as urlopen:
            with patch("signalpilot.binance.time.sleep") as sleep:
                payload = _get_json("/test", {}, "https://example.test")

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()

    def test_get_json_does_not_retry_non_retryable_http_errors(self):
        non_retryable_error = HTTPError(
            url="https://example.test",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=None,
        )
        with patch("signalpilot.binance.urlopen", side_effect=non_retryable_error) as urlopen:
            with self.assertRaises(HTTPError):
                _get_json("/test", {}, "https://example.test")

        self.assertEqual(urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
