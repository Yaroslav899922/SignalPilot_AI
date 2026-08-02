import os
import unittest
from pathlib import Path
from unittest.mock import patch, sentinel

from signalpilot import setup_backend


class SetupBackendTests(unittest.TestCase):
    def test_sqlite_trigger_bundle_routes_to_one_transaction(self):
        path = Path("data/signals.sqlite3")
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(
                setup_backend.setup_journal,
                "save_triggered_event",
                return_value=(True, True),
            ) as save:
                receipt = setup_backend.save_triggered_event(
                    sentinel.setup,
                    sentinel.signal,
                    path,
                )

        self.assertEqual(receipt, (True, True))
        save.assert_called_once_with(sentinel.setup, sentinel.signal, path)

    def test_apps_script_trigger_bundle_routes_to_single_api_action(self):
        path = Path("ignored.sqlite3")
        with patch.dict(
            os.environ,
            {"SIGNALPILOT_JOURNAL_BACKEND": "apps_script"},
            clear=True,
        ):
            with patch.object(
                setup_backend.apps_script_journal,
                "save_triggered_event",
                return_value=(False, True),
            ) as save:
                receipt = setup_backend.save_triggered_event(
                    sentinel.setup,
                    sentinel.signal,
                    path,
                )

        self.assertEqual(receipt, (False, True))
        save.assert_called_once_with(sentinel.setup, sentinel.signal, path)


if __name__ == "__main__":
    unittest.main()
