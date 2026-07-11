import unittest
from datetime import datetime, timezone

import pandas as pd

from signalpilot.brief import build_brief_journal_signals, generate_brief
from signalpilot.market import FuturesContext
from signalpilot.market_data import LiveMarketData, MarketFrame


class BriefTests(unittest.TestCase):
    def test_generate_brief_uses_live_market_frames_without_external_ai(self):
        text = generate_brief(
            [_market(FuturesContext())],
            now_utc=datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc),
        )

        self.assertIn("SignalPilot Market Brief", text)
        self.assertIn("Лондонська сесія", text)
        self.assertIn("<b><u>BTC</u></b>", text)
        self.assertIn("🟢 <b>РЕЖИМ: ВИСХІДНИЙ · 4h</b>", text)
        self.assertIn("<b>Структура:</b> HH/HL · ціна вище EMA50 · EMA50 зростає", text)
        self.assertIn("<b>🎯 ФОКУС:</b> тільки LONG", text)
        self.assertIn("🟡 WAIT — LONG лише від підтримки або після пробою й ретесту", text)
        self.assertIn("<b>Обʼєм 1h:</b> 1,000 BTC ≈ $110.0K · 0.8x avg20 — нормальний", text)
        self.assertIn("MACD histogram позитивний і росте", text)
        self.assertIn("<blockquote expandable>", text)
        self.assertIn("<b>LONG — ранній від підтримки:</b>", text)
        self.assertIn("зона $95.00-$97.00 тримається", text)
        self.assertIn("цілі: $115.00 → $119.00 → $123.00", text)
        self.assertIn("<b>LONG — консервативний:</b>", text)
        self.assertIn("1h close &gt; $115.00 + ретест зверху", text)
        self.assertIn("⚠️ Ризик зламу:</b> 1h close &lt; $95.00", text)
        self.assertNotIn("<b>SHORT — ранній від опору:</b>", text)
        self.assertIn("BTC: висхідний режим — шукати лише LONG.", text)
        self.assertIn("<b>Alert має сенс лише за пріоритетним напрямком, коли:</b>", text)
        self.assertIn("режим ринку не зламаний, а сценарій від рівня активувався або є пробій + ретест", text)
        self.assertNotIn("Futures context недоступний", text)
        self.assertNotIn("Це контрольний огляд живого ринку", text)

    def test_generate_brief_prints_available_futures_context(self):
        text = generate_brief(
            [
                _market(
                    FuturesContext(
                        funding_rate=0.0001,
                        open_interest=12345.0,
                        long_short_ratio=1.2,
                        spread_pct=0.01,
                    )
                )
            ],
            now_utc=datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc),
        )

        self.assertIn("Нью-Йоркська сесія", text)
        self.assertNotIn("Futures context частково доступний", text)

    def test_generate_brief_accepts_explicit_session_label(self):
        text = generate_brief(
            [_market(FuturesContext())],
            now_utc=datetime(2026, 6, 21, 15, 48, tzinfo=timezone.utc),
            session_label="Нью-Йорк · open +1h",
        )

        self.assertIn("21.06 · 18:48 Київ · Нью-Йорк · open +1h", text)
        self.assertNotIn("Ринковий контроль", text)

    def test_generate_brief_filters_to_short_in_downtrend(self):
        text = generate_brief(
            [_market(FuturesContext(), four_hour=_downtrend_frame())],
            now_utc=datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc),
        )

        self.assertIn("🔴 <b>РЕЖИМ: НИЗХІДНИЙ · 4h</b>", text)
        self.assertIn("<b>🎯 ФОКУС:</b> тільки SHORT", text)
        self.assertIn("<b>SHORT — ранній від опору:</b>", text)
        self.assertIn("⚠️ Ризик зламу:</b> 1h close &gt; $115.00", text)
        self.assertNotIn("<b>LONG — ранній від підтримки:</b>", text)
        self.assertIn("BTC: низхідний режим — шукати лише SHORT.", text)

    def test_generate_brief_uses_no_trade_when_structure_is_unclear(self):
        text = generate_brief(
            [_market(FuturesContext(), four_hour=_unclear_frame())],
            now_utc=datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc),
        )

        self.assertIn("⚪ <b>РЕЖИМ: НЕЧІТКИЙ · 4h</b>", text)
        self.assertIn("<b>🎯 ФОКУС:</b> NO TRADE", text)
        self.assertIn("⚪ NO TRADE — чекаємо чисту 4h-структуру", text)
        self.assertNotIn("<b>LONG — ранній від підтримки:</b>", text)
        self.assertNotIn("<b>SHORT — ранній від опору:</b>", text)

    def test_generate_brief_allows_both_sides_only_in_range(self):
        text = generate_brief(
            [_market(FuturesContext(), one_hour=_range_one_hour_frame(), four_hour=_range_four_hour_frame())],
            now_utc=datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc),
        )

        self.assertIn("🔵 <b>РЕЖИМ: ДІАПАЗОН · 4h</b>", text)
        self.assertIn("<b>🎯 ФОКУС:</b> LONG від підтримки · SHORT від опору", text)
        self.assertIn("⚪ NO TRADE — ціна в середині діапазону", text)
        self.assertIn("<b>LONG — ранній від підтримки:</b>", text)
        self.assertIn("<b>SHORT — ранній від опору:</b>", text)

    def test_brief_journal_signal_records_only_the_trend_direction(self):
        signal = build_brief_journal_signals(
            [_market(FuturesContext(), four_hour=_uptrend_frame())],
            now_utc=datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc),
        )[0]

        self.assertEqual(signal.direction, "LONG")
        self.assertEqual(signal.source, "market_brief")
        self.assertEqual(signal.pattern, "brief_support_retest")
        self.assertIsNotNone(signal.entry_low)
        self.assertIsNotNone(signal.entry_high)
        self.assertGreater(signal.targets[0], signal.entry_high)
        self.assertLess(signal.stop, signal.entry_low)


def _market(
    context: FuturesContext,
    *,
    one_hour: MarketFrame | None = None,
    four_hour: MarketFrame | None = None,
) -> LiveMarketData:
    return LiveMarketData(
        symbol="BTCUSDT",
        source="binance_usdm_public",
        collected_at="2026-06-20T09:00:00+00:00",
        futures_context=context,
        frames={
            "1h": one_hour or _one_hour_frame(),
            "4h": four_hour or _uptrend_frame(),
        },
    )


def _one_hour_frame() -> MarketFrame:
    return MarketFrame(
        symbol="BTCUSDT",
        interval="1h",
        source="binance_usdm_public",
        candles=pd.DataFrame(
            [
                {
                    "close": 108.0,
                    "rsi14": 54.0,
                    "atr14": 4.0,
                    "ema20": 104.0,
                    "ema50": 100.0,
                    "macd_hist": 0.2,
                    "volume": 900.0,
                    "volume_avg20": 1200.0,
                    "recent_low20": 95.0,
                    "recent_high20": 115.0,
                },
                {
                    "close": 110.0,
                    "rsi14": 58.0,
                    "atr14": 4.0,
                    "ema20": 105.0,
                    "ema50": 100.0,
                    "macd_hist": 0.4,
                    "volume": 1000.0,
                    "volume_avg20": 1200.0,
                    "recent_low20": 95.0,
                    "recent_high20": 115.0,
                },
            ]
        ),
    )


def _uptrend_frame() -> MarketFrame:
    return _four_hour_frame(
        high=[100, 101, 105, 102, 103, 104, 110, 106, 107, 111],
        low=[90, 91, 92, 88, 91, 92, 93, 90, 94, 95],
        close=[95, 96, 100, 97, 98, 99, 105, 100, 103, 110],
        ema50=[93, 94, 95, 96, 97, 98, 99, 100, 101, 102],
    )


def _downtrend_frame() -> MarketFrame:
    return _four_hour_frame(
        high=[110, 109, 108, 112, 109, 108, 107, 110, 106, 105, 104, 103],
        low=[100, 99, 98, 96, 97, 98, 99, 97, 94, 96, 97, 98],
        close=[105, 104, 103, 100, 104, 103, 102, 105, 96, 100, 101, 99],
        ema50=[110, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100, 100],
    )


def _range_four_hour_frame() -> MarketFrame:
    return _four_hour_frame(
        high=[20, 21, 25, 22, 23, 24, 25, 22, 23, 24, 25],
        low=[10, 11, 12, 8, 11, 12, 13, 9, 12, 13, 14],
        close=[15] * 11,
        ema50=[15] * 11,
    )


def _unclear_frame() -> MarketFrame:
    return _four_hour_frame(high=[111], low=[99], close=[110], ema50=[100])


def _four_hour_frame(high: list[float], low: list[float], close: list[float], ema50: list[float]) -> MarketFrame:
    return MarketFrame(
        symbol="BTCUSDT",
        interval="4h",
        source="binance_usdm_public",
        candles=pd.DataFrame(
            {
                "high": high,
                "low": low,
                "close": close,
                "ema50": ema50,
                "atr14": [4.0] * len(close),
            }
        ),
    )


def _range_one_hour_frame() -> MarketFrame:
    rows = []
    for index in range(20):
        rows.append(
            {
                "high": 20.0 if index in {4, 14} else 19.0,
                "low": 10.0 if index in {2, 12} else 11.0,
                "close": 15.0,
                "rsi14": 50.0,
                "atr14": 2.0,
                "ema20": 15.0,
                "ema50": 15.0,
                "macd_hist": 0.0,
                "volume": 1000.0,
                "volume_avg20": 1000.0,
                "recent_low20": 10.0,
                "recent_high20": 20.0,
            }
        )
    return MarketFrame(symbol="BTCUSDT", interval="1h", source="binance_usdm_public", candles=pd.DataFrame(rows))


if __name__ == "__main__":
    unittest.main()
