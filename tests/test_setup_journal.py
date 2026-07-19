import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from tests.test_actionable import _market

from signalpilot.actionable import ARMED, INVALIDATED, TRIGGERED, analyze_actionable_setup
from signalpilot.setup_journal import load_latest_setups, save_setup_event


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

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "signals.sqlite3"
            self.assertTrue(save_setup_event(armed, path))
            self.assertFalse(save_setup_event(armed, path))
            self.assertTrue(save_setup_event(triggered, path))
            latest = load_latest_setups(path)

        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0].status, TRIGGERED)
        self.assertEqual(latest[0].conditions, triggered.conditions)

    def test_same_state_can_be_saved_again_after_an_invalidation(self):
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
            self.assertTrue(save_setup_event(rearmed, path))
            self.assertFalse(save_setup_event(rearmed, path))
            latest = load_latest_setups(path)

        self.assertEqual(latest[0].status, ARMED)


if __name__ == "__main__":
    unittest.main()
