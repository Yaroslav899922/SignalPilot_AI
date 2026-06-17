import unittest
from unittest.mock import patch

import pandas as pd

from signalpilot.market import FuturesContext
from signalpilot.market_data import load_live_market_data


class MarketDataTests(unittest.TestCase):
    def test_load_live_market_data_enriches_each_interval_and_reports_status(self):
        with patch(
            "signalpilot.market_data.fetch_futures_context",
            return_value=FuturesContext(funding_rate=0.0001, open_interest=1.0, long_short_ratio=1.0, spread_pct=0.01),
        ):
            market = load_live_market_data(
                "btcusdt",
                intervals=("15m", "1h"),
                limit=250,
                kline_fetcher=_fake_klines,
            )

        self.assertEqual(market.symbol, "BTCUSDT")
        self.assertEqual(set(market.frames), {"15m", "1h"})
        self.assertEqual(market.frame("1h").rows, 250)
        self.assertTrue(market.frame("1h").indicators_ready)
        status = market.to_status_dict()
        self.assertEqual(status["frames"]["1h"]["source"], "binance_usdm_public")
        self.assertEqual(status["futures_context"]["long_short_ratio"], 1.0)


def _fake_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    times = pd.date_range("2026-01-01", periods=limit, freq="h", tz="UTC")
    base = pd.Series(range(limit), dtype="float64") + 100.0
    return pd.DataFrame(
        {
            "open_time": times,
            "open": base,
            "high": base + 2.0,
            "low": base - 2.0,
            "close": base + 1.0,
            "volume": 1000.0,
            "close_time": times + pd.Timedelta(hours=1),
        }
    )


if __name__ == "__main__":
    unittest.main()
