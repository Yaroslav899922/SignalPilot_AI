import json
import os
import unittest
from unittest.mock import patch

from signalpilot import apps_script_journal
from signalpilot.signals import Signal


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class AppsScriptJournalTests(unittest.TestCase):
    def test_save_signal_posts_signal_payload_and_returns_inserted(self):
        with patch.dict(os.environ, _env(), clear=True):
            with patch(
                "signalpilot.apps_script_journal.urlopen",
                return_value=FakeResponse({"ok": True, "inserted": False}),
            ) as urlopen:
                inserted = apps_script_journal.save_signal(_signal())

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertFalse(inserted)
        self.assertEqual(request.full_url, "https://script.google.test/exec")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30)
        self.assertEqual(payload["action"], "save_signal")
        self.assertEqual(payload["token"], "journal-token")
        self.assertEqual(payload["signal"]["symbol"], "BTCUSDT")
        self.assertEqual(payload["signal"]["targets"], [110.0])

    def test_load_evaluable_signals_returns_signal_rows(self):
        rows = [
            {
                "id": 1,
                "created_at": "2026-06-01T00:00:00+00:00",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "direction": "LONG",
                "stop": 95.0,
                "targets_json": "[110.0]",
            }
        ]
        with patch.dict(os.environ, _env(), clear=True):
            with patch(
                "signalpilot.apps_script_journal.urlopen",
                return_value=FakeResponse({"ok": True, "signals": rows}),
            ):
                self.assertEqual(apps_script_journal.load_evaluable_signals(), rows)

    def test_update_signal_evaluation_posts_result_payload(self):
        with patch.dict(os.environ, _env(), clear=True):
            with patch(
                "signalpilot.apps_script_journal.urlopen",
                return_value=FakeResponse({"ok": True}),
            ) as urlopen:
                apps_script_journal.update_signal_evaluation(
                    db_path="ignored",
                    signal_id=7,
                    outcome="target_hit",
                    max_favorable_price=111.0,
                    max_adverse_price=99.0,
                    evaluated_at="2026-06-01T01:00:00+00:00",
                    result_R=2.0,
                    baseline_R=1.0,
                    edge_R=1.0,
                )

        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["action"], "update_signal_evaluation")
        self.assertEqual(payload["signal_id"], 7)
        self.assertEqual(payload["outcome"], "target_hit")
        self.assertEqual(payload["max_favorable_price"], 111.0)
        self.assertEqual(payload["max_adverse_price"], 99.0)
        self.assertEqual(payload["evaluated_at"], "2026-06-01T01:00:00+00:00")
        self.assertEqual(payload["result_R"], 2.0)
        self.assertEqual(payload["baseline_R"], 1.0)
        self.assertEqual(payload["edge_R"], 1.0)

    def test_summarize_journal_returns_summary(self):
        summary = {"signals": 2, "long": 1, "short": 0, "no_trade": 1, "win_rate": None}
        with patch.dict(os.environ, _env(), clear=True):
            with patch(
                "signalpilot.apps_script_journal.urlopen",
                return_value=FakeResponse({"ok": True, "summary": summary}),
            ):
                self.assertEqual(apps_script_journal.summarize_journal(), summary)

    def test_missing_environment_raises_before_http_call(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("signalpilot.apps_script_journal.urlopen") as urlopen:
                with self.assertRaises(RuntimeError):
                    apps_script_journal.summarize_journal()

        urlopen.assert_not_called()

    def test_api_error_raises_runtime_error(self):
        with patch.dict(os.environ, _env(), clear=True):
            with patch(
                "signalpilot.apps_script_journal.urlopen",
                return_value=FakeResponse({"ok": False, "error": "unauthorized"}),
            ):
                with self.assertRaisesRegex(RuntimeError, "unauthorized"):
                    apps_script_journal.summarize_journal()


def _env() -> dict[str, str]:
    return {
        "SIGNALPILOT_JOURNAL_API_URL": "https://script.google.test/exec",
        "SIGNALPILOT_JOURNAL_API_TOKEN": "journal-token",
    }


def _signal() -> Signal:
    return Signal(
        symbol="BTCUSDT",
        interval="1h",
        direction="LONG",
        market_regime="up",
        close_price=100.0,
        funding_rate=0.0001,
        open_interest=12345.0,
        long_short_ratio=1.1,
        spread_pct=0.01,
        entry_zone="99.00-101.00",
        stop=95.0,
        targets=(110.0,),
        risk_reward=2.0,
        confidence="medium",
        invalidation="Below 95.00",
        reasons=("Test signal",),
        created_at="2026-06-01T00:00:00+00:00",
    )


if __name__ == "__main__":
    unittest.main()
