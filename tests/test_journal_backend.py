import os
import unittest
from pathlib import Path
from unittest.mock import patch

from signalpilot import journal_backend
from signalpilot.signals import Signal


class JournalBackendTests(unittest.TestCase):
    def test_default_backend_is_sqlite(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(journal_backend.current_backend_name(), "sqlite")

    def test_sqlite_backend_routes_to_sqlite_journal(self):
        signal = _signal()
        path = Path("data/signals.sqlite3")
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(journal_backend.journal, "save_signal", return_value=True) as save_signal:
                self.assertTrue(journal_backend.save_signal(signal, path))

        save_signal.assert_called_once_with(signal, path)

    def test_apps_script_backend_routes_to_apps_script_journal(self):
        signal = _signal()
        path = Path("ignored.sqlite3")
        with patch.dict(os.environ, {"SIGNALPILOT_JOURNAL_BACKEND": "apps_script"}, clear=True):
            with patch.object(journal_backend.apps_script_journal, "save_signal", return_value=False) as save_signal:
                self.assertFalse(journal_backend.save_signal(signal, path))

        save_signal.assert_called_once_with(signal, path)

    def test_backend_name_is_normalized(self):
        with patch.dict(os.environ, {"SIGNALPILOT_JOURNAL_BACKEND": " Apps_Script "}, clear=True):
            self.assertEqual(journal_backend.current_backend_name(), "apps_script")

    def test_unsupported_backend_raises(self):
        with patch.dict(os.environ, {"SIGNALPILOT_JOURNAL_BACKEND": "google_drive"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Unsupported SIGNALPILOT_JOURNAL_BACKEND"):
                journal_backend.summarize_journal(Path("data/signals.sqlite3"))


def _signal() -> Signal:
    return Signal(
        symbol="BTCUSDT",
        interval="1h",
        direction="NO TRADE",
        market_regime="range",
        close_price=100.0,
        funding_rate=0.0001,
        open_interest=12345.0,
        long_short_ratio=1.1,
        spread_pct=0.01,
        entry_zone="",
        stop=None,
        targets=(),
        risk_reward=None,
        confidence="low",
        invalidation="Wait",
        reasons=("No setup",),
        created_at="2026-06-01T00:00:00+00:00",
    )


if __name__ == "__main__":
    unittest.main()
