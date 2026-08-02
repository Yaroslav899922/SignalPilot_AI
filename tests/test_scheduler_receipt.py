import json
import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from signalpilot import scheduler_receipt


class SchedulerReceiptTests(unittest.TestCase):
    def test_start_receipt_uses_stable_run_key_and_running_status(self):
        response = {
            "ok": True,
            "run_key": "owner/repo:123:2:market-brief",
            "status": "running",
            "inserted": True,
            "updated": False,
            "missing_start": False,
        }
        with patch.object(scheduler_receipt, "api_request", return_value=response) as request:
            receipt = scheduler_receipt.save_receipt(
                "start",
                environ=_env(),
                observed_at="2026-08-02T10:00:00+00:00",
            )

        self.assertEqual(receipt, response)
        action, body = request.call_args.args
        payload = body["receipt"]
        self.assertEqual(action, "save_scheduler_receipt")
        self.assertEqual(payload["schema_version"], "scheduler-receipt/v1")
        self.assertEqual(payload["run_key"], "owner/repo:123:2:market-brief")
        self.assertEqual(payload["phase"], "start")
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["mode"], "setup-check")
        self.assertEqual(payload["event_schedule"], "5,20,35,50 0-21,23 * * *")
        self.assertEqual(payload["steps"], {})
        self.assertEqual(payload["run_attempt"], "2")
        self.assertEqual(payload["run_url"], "https://github.com/owner/repo/actions/runs/123")

    def test_finish_receipt_captures_terminal_status_and_step_outcomes(self):
        environ = _env()
        environ.update(
            {
                "SCHEDULER_STATUS": "failure",
                "SCHEDULER_STEPS_JSON": json.dumps(
                    {
                        "send_brief": {"outcome": "failure", "conclusion": "failure"},
                        "evaluate": {"outcome": "skipped", "conclusion": "skipped"},
                    }
                ),
            }
        )
        response = {
            "ok": True,
            "run_key": "owner/repo:123:2:market-brief",
            "status": "failure",
            "inserted": False,
            "updated": True,
            "missing_start": False,
        }
        with patch.object(scheduler_receipt, "api_request", return_value=response) as request:
            scheduler_receipt.save_receipt(
                "finish",
                environ=environ,
                observed_at="2026-08-02T10:05:00+00:00",
            )

        payload = request.call_args.args[1]["receipt"]
        self.assertEqual(payload["phase"], "finish")
        self.assertEqual(payload["status"], "failure")
        self.assertEqual(
            payload["steps"],
            {
                "send_brief": {"outcome": "failure", "conclusion": "failure"},
                "evaluate": {"outcome": "skipped", "conclusion": "skipped"},
            },
        )

    def test_missing_identity_is_rejected_before_api_call(self):
        environ = _env()
        del environ["GITHUB_RUN_ID"]
        with patch.object(scheduler_receipt, "api_request") as request:
            with self.assertRaisesRegex(RuntimeError, "GITHUB_RUN_ID"):
                scheduler_receipt.save_receipt("start", environ=environ)
        request.assert_not_called()

    def test_invalid_finish_status_and_steps_are_rejected(self):
        for status in ("", "running", "skipped"):
            with self.subTest(status=status):
                environ = _env()
                environ["SCHEDULER_STATUS"] = status
                with self.assertRaisesRegex(RuntimeError, "terminal status"):
                    scheduler_receipt.build_receipt("finish", environ=environ)

        environ = _env()
        environ["SCHEDULER_STATUS"] = "success"
        environ["SCHEDULER_STEPS_JSON"] = "[]"
        with self.assertRaisesRegex(RuntimeError, "JSON object"):
            scheduler_receipt.build_receipt("finish", environ=environ)

        environ["SCHEDULER_STEPS_JSON"] = json.dumps({"send_brief": "failure"})
        with self.assertRaisesRegex(RuntimeError, "outcome and conclusion"):
            scheduler_receipt.build_receipt("finish", environ=environ)

    def test_api_receipt_requires_matching_identity_and_boolean_fields(self):
        valid = {
            "ok": True,
            "run_key": "owner/repo:123:2:market-brief",
            "status": "running",
            "inserted": True,
            "updated": False,
            "missing_start": False,
        }
        bad_receipts = [
            {**valid, "run_key": "other"},
            {**valid, "status": "unknown"},
            {**valid, "inserted": 1},
            {key: value for key, value in valid.items() if key != "missing_start"},
        ]
        for response in bad_receipts:
            with self.subTest(response=response):
                with patch.object(scheduler_receipt, "api_request", return_value=response):
                    with self.assertRaises(RuntimeError):
                        scheduler_receipt.save_receipt(
                            "start",
                            environ=_env(),
                            observed_at="2026-08-02T10:00:00+00:00",
                        )

    def test_late_start_accepts_an_existing_terminal_receipt(self):
        response = {
            "ok": True,
            "run_key": "owner/repo:123:2:market-brief",
            "status": "success",
            "inserted": False,
            "updated": False,
            "missing_start": True,
        }
        with patch.object(scheduler_receipt, "api_request", return_value=response):
            self.assertEqual(
                scheduler_receipt.save_receipt(
                    "start",
                    environ=_env(),
                    observed_at="2026-08-02T10:00:00+00:00",
                ),
                response,
            )

    def test_cli_prints_machine_readable_receipt(self):
        response = {
            "ok": True,
            "run_key": "owner/repo:123:2:market-brief",
            "status": "running",
            "inserted": True,
            "updated": False,
            "missing_start": False,
        }
        output = StringIO()
        with patch.dict(os.environ, _env(), clear=True):
            with patch.object(scheduler_receipt, "save_receipt", return_value=response):
                with redirect_stdout(output):
                    exit_code = scheduler_receipt.main(["start"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue()), response)


def _env() -> dict[str, str]:
    return {
        "SIGNALPILOT_JOURNAL_API_URL": "https://script.google.test/exec",
        "SIGNALPILOT_JOURNAL_API_TOKEN": "journal-token",
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_WORKFLOW": "SignalPilot Market Brief",
        "GITHUB_JOB": "market-brief",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_EVENT_NAME": "schedule",
        "GITHUB_SHA": "abc123",
        "GITHUB_SERVER_URL": "https://github.com",
        "EVENT_SCHEDULE": "5,20,35,50 0-21,23 * * *",
        "SCHEDULER_MODE": "setup-check",
    }


if __name__ == "__main__":
    unittest.main()
