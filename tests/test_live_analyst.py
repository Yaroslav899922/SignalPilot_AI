import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from signalpilot.live_analyst import analyze_live_market
from signalpilot.market import FuturesContext
from signalpilot.market_data import LiveMarketData, MarketFrame
from signalpilot.patterns import detect_breakout_retest
from signalpilot.tradingview import parse_tradingview_trigger


class LiveAnalystTests(unittest.TestCase):
    def test_detects_long_breakout_retest_setup(self):
        setup = detect_breakout_retest(_market())

        self.assertIsNotNone(setup)
        assert setup is not None
        self.assertEqual(setup.direction, "LONG")
        self.assertEqual(setup.pattern, "breakout_retest")
        self.assertEqual(setup.quality, "high")
        self.assertEqual(setup.plan.entry_zone, "110.00-111.00")
        self.assertEqual(setup.plan.stop, 102.0)
        self.assertTrue(setup.plan.trailing_plan)

    def test_live_analysis_returns_structured_signal_with_plan_metadata(self):
        trigger = parse_tradingview_trigger(
            '{"source":"tradingview","ticker":"BINANCE:BTCUSDT.P","interval":"1h","indicator":"My Retest","direction":"LONG"}'
        )

        result = analyze_live_market(_market(), trigger)
        signal = result.signal

        self.assertEqual(signal.direction, "LONG")
        self.assertEqual(signal.pattern, "breakout_retest")
        self.assertGreater(signal.setup_score or 0, 75)
        self.assertEqual(signal.source, "binance_usdm_public")
        self.assertIn("TradingView trigger received", signal.reasons[0])
        self.assertIn("After +1R", signal.trailing_plan)
        self.assertEqual(result.trigger["symbol"], "BTCUSDT")

    def test_returns_no_trade_when_futures_context_blocks_alert(self):
        result = analyze_live_market(
            _market(FuturesContext(funding_rate=0.0001, open_interest=10000.0, long_short_ratio=3.0, spread_pct=0.01))
        )

        self.assertEqual(result.signal.direction, "NO TRADE")
        self.assertEqual(result.signal.pattern, "breakout_retest")
        self.assertTrue(any("Futures context blocks" in reason for reason in result.signal.reasons))

    def test_tradingview_trigger_normalizes_symbol_and_direction(self):
        trigger = parse_tradingview_trigger(
            {"ticker": "BINANCE:ETHUSDT.P", "timeframe": "4h", "side": "buy", "indicator": "Custom", "secret": "do-not-leak"}
        )

        self.assertEqual(trigger.symbol, "ETHUSDT")
        self.assertEqual(trigger.interval, "4h")
        self.assertEqual(trigger.direction, "LONG")
        self.assertEqual(trigger.indicator, "Custom")
        self.assertEqual(trigger.raw["secret"], "<redacted>")

    def test_cli_live_analyst_writes_json_and_journal(self):
        from signalpilot.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "signals.sqlite3"
            output = _run_cli(
                [
                    "--live-analyst",
                    "--symbols",
                    "BTCUSDT",
                    "--journal",
                    str(db_path),
                ],
                _market(),
            )

        payload = json.loads(output)
        self.assertEqual(payload["signal"]["direction"], "LONG")
        self.assertEqual(payload["signal"]["pattern"], "breakout_retest")
        self.assertTrue(payload["journal_inserted"])


def _run_cli(argv, market):
    import io
    from contextlib import redirect_stdout

    from signalpilot.cli import main

    output = io.StringIO()
    with patch("signalpilot.cli.load_live_market_data", return_value=market):
        with redirect_stdout(output):
            exit_code = main(argv)
    assert exit_code == 0
    return output.getvalue()


def _market(context: FuturesContext | None = None) -> LiveMarketData:
    context = context or FuturesContext(
        funding_rate=0.0001,
        open_interest=10000.0,
        long_short_ratio=1.1,
        spread_pct=0.01,
    )
    return LiveMarketData(
        symbol="BTCUSDT",
        source="binance_usdm_public",
        collected_at="2026-06-17T00:00:00+00:00",
        futures_context=context,
        frames={
            "4h": MarketFrame(
                symbol="BTCUSDT",
                interval="4h",
                source="binance_usdm_public",
                candles=pd.DataFrame(
                    [{"close": 120.0, "ema50": 110.0, "ema200": 100.0}]
                ),
            ),
            "1h": MarketFrame(
                symbol="BTCUSDT",
                interval="1h",
                source="binance_usdm_public",
                candles=pd.DataFrame(
                    [
                        {
                            "open": 109.0,
                            "high": 112.0,
                            "low": 109.5,
                            "close": 111.0,
                            "ema50": 105.0,
                            "ema200": 100.0,
                            "atr14": 4.0,
                            "rsi14": 60.0,
                            "recent_high20": 110.0,
                            "recent_low20": 102.0,
                        }
                    ]
                ),
            ),
            "15m": MarketFrame(
                symbol="BTCUSDT",
                interval="15m",
                source="binance_usdm_public",
                candles=pd.DataFrame([{"close": 111.5, "ema20": 110.0, "rsi14": 58.0}]),
            ),
        },
    )


if __name__ == "__main__":
    unittest.main()
