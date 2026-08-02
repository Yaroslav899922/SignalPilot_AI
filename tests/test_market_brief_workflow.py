import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "market-brief.yml"


class MarketBriefWorkflowTests(unittest.TestCase):
    def test_scheduler_receipts_wrap_the_entire_job(self):
        text = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("id: scheduler_start", text)
        self.assertIn("id: scheduler_finish", text)
        self.assertLess(text.index("id: run_mode"), text.index("id: scheduler_start"))
        self.assertLess(text.index("id: scheduler_start"), text.index("uses: actions/setup-python"))
        start_block = text[text.index("id: scheduler_start") : text.index("uses: actions/setup-python")]
        self.assertIn("continue-on-error: true", start_block)
        self.assertIn("if: always()", text[text.index("id: scheduler_finish") - 100 :])
        self.assertIn("python3 -m signalpilot.scheduler_receipt finish", text)
        self.assertIn("SCHEDULER_STATUS: ${{ job.status }}", text)
        self.assertIn('"outcome":"${{ steps.send_brief.outcome }}"', text)
        self.assertIn('"conclusion":"${{ steps.send_brief.conclusion }}"', text)
        self.assertIn("timeout-minutes:", text)

    def test_brief_delivery_precedes_evaluation_and_unknown_cron_fails(self):
        text = WORKFLOW.read_text(encoding="utf-8")

        self.assertLess(text.index("id: send_brief"), text.index("id: evaluate"))
        self.assertIn("Unsupported scheduled cron", text)
        self.assertIn('fail_mode "Unsupported scheduled cron', text)
        fail_helper = text[text.index("fail_mode()") : text.index('if [[ "$EVENT_NAME"')]
        self.assertIn("exit 1", fail_helper)
        self.assertIn("Unsupported dispatch mode", text)

    def test_every_operational_step_has_an_id_for_the_finish_receipt(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        for step_id in (
            "checkout",
            "run_mode",
            "scheduler_start",
            "setup_python",
            "install",
            "send_brief",
            "evaluate",
            "setup_check",
            "move_alert",
            "scheduler_finish",
        ):
            with self.subTest(step_id=step_id):
                self.assertIn(f"id: {step_id}", text)


if __name__ == "__main__":
    unittest.main()
