import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from signalpilot.journal import (
    load_signal_rows,
    save_signal,
    summarize_journal,
    update_signal_evaluation,
)
from signalpilot.signals import Signal


class JournalTests(unittest.TestCase):
    def test_saves_signal_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "signals.sqlite3"
            signal = Signal(
                symbol="BTCUSDT",
                interval="1h",
                direction="NO TRADE",
                market_regime="range",
                close_price=100.0,
                funding_rate=0.0001,
                open_interest=12345.0,
                long_short_ratio=1.2,
                spread_pct=0.01,
                entry_zone="",
                stop=None,
                targets=(),
                risk_reward=None,
                confidence="low",
                invalidation="Wait",
                reasons=("No setup",),
                created_at="2026-05-31T00:00:00+00:00",
            )

            inserted = save_signal(signal, db_path)

            connection = sqlite3.connect(db_path)
            try:
                row = connection.execute(
                    """
                    SELECT COUNT(*), funding_rate, open_interest, market_regime,
                           close_price, long_short_ratio, spread_pct
                    FROM signals
                    """
                ).fetchone()
            finally:
                connection.close()
            self.assertTrue(inserted)
            self.assertEqual(row[0], 1)
            self.assertEqual(row[1], 0.0001)
            self.assertEqual(row[2], 12345.0)
            self.assertEqual(row[3], "range")
            self.assertEqual(row[4], 100.0)
            self.assertEqual(row[5], 1.2)
            self.assertEqual(row[6], 0.01)

    def test_load_signal_rows_decodes_targets_and_reasons(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "signals.sqlite3"
            signal = Signal(
                symbol="ETHUSDT",
                interval="1h",
                direction="LONG",
                market_regime="up",
                close_price=100.0,
                funding_rate=0.0001,
                open_interest=12345.0,
                long_short_ratio=1.2,
                spread_pct=0.01,
                entry_zone="99.00-101.00",
                stop=95.0,
                targets=(110.0,),
                risk_reward=2.0,
                confidence="medium",
                invalidation="Close below stop",
                reasons=("Breakout", "Risk/reward meets minimum 1:2"),
                created_at="2026-05-31T00:00:00+00:00",
            )

            save_signal(signal, db_path)
            rows = load_signal_rows(db_path)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["symbol"], "ETHUSDT")
            self.assertEqual(rows[0]["targets"], [110.0])
            self.assertEqual(rows[0]["reasons"], ["Breakout", "Risk/reward meets minimum 1:2"])

    def test_save_signal_skips_duplicate_market_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "signals.sqlite3"
            first = _signal(direction="LONG", created_at="2026-05-31T01:00:00+00:00")
            duplicate = _signal(direction="LONG", created_at="2026-05-31T01:10:00+00:00")
            changed = replace(duplicate, close_price=101.0, entry_zone="100.00-102.00")

            self.assertTrue(save_signal(first, db_path))
            self.assertFalse(save_signal(duplicate, db_path))
            self.assertTrue(save_signal(changed, db_path))

            rows = load_signal_rows(db_path)

        self.assertEqual(len(rows), 2)
        self.assertEqual([row["close_price"] for row in rows], [101.0, 100.0])

    def test_summarize_journal_returns_empty_summary_for_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = summarize_journal(Path(temp_dir) / "missing.sqlite3")

        self.assertEqual(summary["signals"], 0)
        self.assertEqual(summary["pending"], 0)
        self.assertIsNone(summary["win_rate"])

    def test_summarize_journal_counts_directions_outcomes_and_win_rate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "signals.sqlite3"
            long_pending = _signal(direction="LONG", created_at="2026-05-31T01:00:00+00:00")
            long_target = replace(
                _signal(direction="LONG", created_at="2026-05-31T02:00:00+00:00"),
                close_price=101.0,
                entry_zone="100.00-102.00",
                stop=96.0,
                targets=(111.0,),
            )
            short_stop = _signal(direction="SHORT", created_at="2026-05-31T03:00:00+00:00")
            short_no_result = replace(
                _signal(direction="SHORT", created_at="2026-05-31T04:00:00+00:00"),
                close_price=99.0,
                entry_zone="98.00-100.00",
                stop=104.0,
                targets=(89.0,),
            )
            save_signal(
                _signal(direction="NO TRADE", created_at="2026-05-31T00:00:00+00:00"),
                db_path,
            )
            save_signal(long_pending, db_path)
            save_signal(long_target, db_path)
            save_signal(short_stop, db_path)
            save_signal(short_no_result, db_path)

            update_signal_evaluation(
                db_path,
                signal_id=3,
                outcome="target_hit",
                max_favorable_price=110.0,
                max_adverse_price=99.0,
            )
            update_signal_evaluation(
                db_path,
                signal_id=4,
                outcome="stop_hit",
                max_favorable_price=95.0,
                max_adverse_price=106.0,
            )
            update_signal_evaluation(
                db_path,
                signal_id=5,
                outcome="no_result",
                max_favorable_price=100.0,
                max_adverse_price=100.0,
            )

            summary = summarize_journal(db_path)

        self.assertEqual(summary["signals"], 5)
        self.assertEqual(summary["long"], 2)
        self.assertEqual(summary["short"], 2)
        self.assertEqual(summary["no_trade"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["target_hit"], 1)
        self.assertEqual(summary["stop_hit"], 1)
        self.assertEqual(summary["no_result"], 1)
        self.assertEqual(summary["win_rate"], 0.5)


def _signal(direction: str, created_at: str) -> Signal:
    is_directional = direction in {"LONG", "SHORT"}
    return Signal(
        symbol="BTCUSDT",
        interval="1h",
        direction=direction,
        market_regime=_market_regime(direction),
        close_price=100.0,
        funding_rate=0.0001,
        open_interest=12345.0,
        long_short_ratio=1.2,
        spread_pct=0.01,
        entry_zone="99.00-101.00" if is_directional else "",
        stop=95.0 if direction == "LONG" else 105.0 if direction == "SHORT" else None,
        targets=(110.0,) if direction == "LONG" else (90.0,) if direction == "SHORT" else (),
        risk_reward=2.0 if is_directional else None,
        confidence="medium" if is_directional else "low",
        invalidation="Close beyond stop" if is_directional else "Wait",
        reasons=("Test signal",),
        created_at=created_at,
    )


def _market_regime(direction: str) -> str:
    if direction == "LONG":
        return "up"
    if direction == "SHORT":
        return "down"
    return "range"


if __name__ == "__main__":
    unittest.main()
