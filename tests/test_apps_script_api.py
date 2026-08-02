import json
import unittest
from urllib.error import URLError
from unittest.mock import Mock

from signalpilot.apps_script_api import request


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class AppsScriptApiTests(unittest.TestCase):
    def test_reserved_envelope_fields_cannot_be_overridden_by_body(self):
        opener = Mock(return_value=FakeResponse({"ok": True, "saved": True}))

        result = request(
            "expected_action",
            {"action": "wrong", "token": "wrong", "value": 7},
            opener=opener,
            sleeper=Mock(),
            environ=_env(),
        )

        payload = json.loads(opener.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(result, {"ok": True, "saved": True})
        self.assertEqual(payload["action"], "expected_action")
        self.assertEqual(payload["token"], "journal-token")
        self.assertEqual(payload["value"], 7)

    def test_transient_network_failure_uses_bounded_shared_retry(self):
        opener = Mock(
            side_effect=[
                URLError("temporary"),
                FakeResponse({"ok": True, "saved": True}),
            ]
        )
        sleeper = Mock()

        result = request(
            "save",
            {},
            opener=opener,
            sleeper=sleeper,
            environ=_env(),
        )

        self.assertEqual(result, {"ok": True, "saved": True})
        self.assertEqual(opener.call_count, 2)
        sleeper.assert_called_once_with(0.5)

    def test_missing_credentials_fails_before_opening_network(self):
        opener = Mock()
        with self.assertRaisesRegex(RuntimeError, "SIGNALPILOT_JOURNAL_API_URL"):
            request("save", {}, opener=opener, environ={})
        opener.assert_not_called()


def _env() -> dict[str, str]:
    return {
        "SIGNALPILOT_JOURNAL_API_URL": "https://script.google.test/exec",
        "SIGNALPILOT_JOURNAL_API_TOKEN": "journal-token",
    }


if __name__ == "__main__":
    unittest.main()
