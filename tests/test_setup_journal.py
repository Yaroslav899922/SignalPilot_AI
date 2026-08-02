import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tests.test_actionable import _market

from signalpilot.actionable import (
    ARMED,
    INVALIDATED,
    TRIGGERED,
    analyze_actionable_setup,
    reconcile_setup_state,
    setup_to_signal,
)
from signalpilot.journal import load_signal_rows
from signalpilot.setup_journal import (
    load_latest_setups,
    save_setup_event,
    save_triggered_event,
)


class SetupJournalTests(unittest.TestCase):
    def test_saves_state_changes_and_skips_exact_repeats(self):
        armed = analyze_actionable_setup(
            _market(
                one_hour_close=116.0,
                one_hour_low=114.8,
                volume=900.0,
                confirm_macd=0.1,
            ),
            now_utc=datetime(2026, 7, 19, 17, 0, tzinfo=timezone.utc),
        )
        triggered = analyze_actionable_setup(
            _market(one_hour_close=116.0, one_hour_low=114.8, volume=1500.0),
            now_utc=datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc),
        )
        assert armed is not None and triggered is not None
        self.assertEqual(armed.status, ARMED)
        self.assertEqual(triggered.status, TRIGGERED)
        self.assertEqual(armed.setup_id, triggered.setup_id)
        triggered_events = reconcile_setup_state(
            triggered,
            [armed],
            _market(one_hour_close=116.0, one_hour_low=114.8, volume=1500.0),
            now_utc=datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(triggered_events), 1)
        triggered = triggered_events[0]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "signals.sqlite3"
            self.assertTrue(save_setup_event(armed, path))
            self.assertFalse(save_setup_event(armed, path))
            self.assertTrue(save_setup_event(triggered, path))
            latest = load_latest_setups(path)

        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0].status, TRIGGERED)
        self.assertEqual(latest[0].conditions, triggered.conditions)
        self.assertEqual(latest[0].event_id, triggered.event_id)
        self.assertEqual(latest[0].policy_version, "v3.1")
        self.assertEqual(latest[0].detected_at, armed.created_at)
        self.assertEqual(latest[0].triggered_at, triggered.created_at)
        self.assertEqual(latest[0].market_source, "binance_usdm_public")

    def test_delayed_same_state_retry_cannot_overwrite_an_invalidation(self):
        armed = analyze_actionable_setup(
            _market(
                one_hour_close=116.0,
                one_hour_low=114.8,
                volume=900.0,
                confirm_macd=0.1,
            ),
            now_utc=datetime(2026, 7, 19, 17, 0, tzinfo=timezone.utc),
        )
        assert armed is not None
        invalidated = replace(
            armed,
            status=INVALIDATED,
            created_at="2026-07-19T17:15:00+00:00",
        )
        rearmed = replace(armed, created_at="2026-07-19T17:30:00+00:00")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "signals.sqlite3"
            self.assertTrue(save_setup_event(armed, path))
            self.assertTrue(save_setup_event(invalidated, path))
            self.assertFalse(save_setup_event(rearmed, path))
            latest = load_latest_setups(path)

        self.assertEqual(latest[0].status, INVALIDATED)

    def test_same_level_keeps_separate_latest_rows_for_independent_events(self):
        first = analyze_actionable_setup(
            _market(one_hour_close=114.9, one_hour_low=114.5, volume=800.0),
            now_utc=datetime(2026, 7, 19, 17, 0, tzinfo=timezone.utc),
        )
        assert first is not None
        second = replace(
            first,
            event_id=f"{first.setup_id}-later-event",
            created_at="2026-07-20T17:00:00+00:00",
            detected_at="2026-07-20T17:00:00+00:00",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "signals.sqlite3"
            self.assertTrue(save_setup_event(first, path))
            self.assertTrue(save_setup_event(second, path))
            latest = load_latest_setups(path)

        self.assertEqual([setup.event_id for setup in latest], [first.event_id, second.event_id])

    def test_legacy_setup_table_is_migrated_for_event_metadata(self):
        setup = analyze_actionable_setup(
            _market(one_hour_close=116.0, one_hour_low=114.8, volume=1500.0),
            now_utc=datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc),
        )
        assert setup is not None

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "signals.sqlite3"
            _create_legacy_setup_table(path)

            self.assertTrue(save_setup_event(setup, path))
            latest = load_latest_setups(path)

        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0].event_id, setup.event_id)
        self.assertEqual(latest[0].policy_version, "v3.1")
        self.assertEqual(latest[0].detected_at, setup.detected_at)
        self.assertEqual(latest[0].triggered_at, setup.triggered_at)

    def test_triggered_event_and_paper_entry_commit_as_one_idempotent_unit(self):
        setup = analyze_actionable_setup(
            _market(one_hour_close=116.0, one_hour_low=114.8, volume=1500.0),
            now_utc=datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc),
        )
        assert setup is not None
        signal = setup_to_signal(setup)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "signals.sqlite3"
            first = save_triggered_event(setup, signal, path)
            retry = save_triggered_event(setup, signal, path)
            latest_setups = load_latest_setups(path)
            signals = load_signal_rows(path)

        self.assertEqual(first, (True, True))
        self.assertEqual(retry, (False, False))
        self.assertEqual(len(latest_setups), 1)
        self.assertEqual(len(signals), 1)
        self.assertEqual(latest_setups[0].event_id, signals[0]["event_id"])

    def test_triggered_sqlite_transaction_rolls_back_signal_if_setup_write_fails(self):
        setup = analyze_actionable_setup(
            _market(one_hour_close=116.0, one_hour_low=114.8, volume=1500.0),
            now_utc=datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc),
        )
        assert setup is not None
        signal = setup_to_signal(setup)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "signals.sqlite3"
            with patch(
                "signalpilot.setup_journal._save_setup_event_on_connection",
                side_effect=RuntimeError("setup write failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "setup write failed"):
                    save_triggered_event(setup, signal, path)
            signals = load_signal_rows(path)
            latest_setups = load_latest_setups(path)

        self.assertEqual(signals, [])
        self.assertEqual(latest_setups, [])


def _create_legacy_setup_table(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE setup_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setup_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                pattern TEXT NOT NULL,
                direction TEXT NOT NULL,
                status TEXT NOT NULL,
                regime TEXT NOT NULL,
                current_price REAL NOT NULL,
                trigger_level REAL NOT NULL,
                entry_low REAL NOT NULL,
                entry_high REAL NOT NULL,
                stop REAL NOT NULL,
                targets_json TEXT NOT NULL,
                risk_reward REAL NOT NULL,
                score REAL NOT NULL,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                invalidation TEXT NOT NULL,
                conditions_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                source TEXT NOT NULL,
                fingerprint TEXT NOT NULL
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
