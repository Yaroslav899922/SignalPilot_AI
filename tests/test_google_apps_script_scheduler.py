import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODE_GS = ROOT / "google_apps_script" / "Code.gs"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js is required to execute Apps Script state tests")
class GoogleAppsScriptSchedulerTests(unittest.TestCase):
    def test_start_then_finish_updates_one_run_without_losing_start_time(self):
        result = _run_case(
            """
const start = schedulerTransition_(null, schedulerReceipt_("start", "running", "2026-08-02T10:00:00Z"));
const finish = schedulerTransition_(start.row, schedulerReceipt_("finish", "success", "2026-08-02T10:05:00Z"));
console.log(JSON.stringify({ start, finish }));
"""
        )
        self.assertTrue(result["start"]["inserted"])
        self.assertEqual(result["start"]["row"]["started_at"], "2026-08-02T10:00:00Z")
        self.assertTrue(result["finish"]["updated"])
        self.assertEqual(result["finish"]["row"]["status"], "success")
        self.assertEqual(result["finish"]["row"]["started_at"], "2026-08-02T10:00:00Z")
        self.assertEqual(result["finish"]["row"]["finished_at"], "2026-08-02T10:05:00Z")

    def test_repeated_start_and_finish_are_idempotent(self):
        result = _run_case(
            """
const first = schedulerTransition_(null, schedulerReceipt_("start", "running", "2026-08-02T10:00:00Z"));
const repeatedStart = schedulerTransition_(first.row, schedulerReceipt_("start", "running", "2026-08-02T10:01:00Z"));
const finish = schedulerTransition_(first.row, schedulerReceipt_("finish", "failure", "2026-08-02T10:05:00Z"));
const repeatedFinish = schedulerTransition_(finish.row, schedulerReceipt_("finish", "failure", "2026-08-02T10:06:00Z"));
console.log(JSON.stringify({ repeatedStart, repeatedFinish }));
"""
        )
        self.assertFalse(result["repeatedStart"]["inserted"])
        self.assertFalse(result["repeatedStart"]["updated"])
        self.assertEqual(
            result["repeatedStart"]["row"]["started_at"], "2026-08-02T10:00:00Z"
        )
        self.assertFalse(result["repeatedFinish"]["updated"])
        self.assertEqual(result["repeatedFinish"]["row"]["finished_at"], "2026-08-02T10:05:00Z")

    def test_finish_without_start_is_visible_and_late_start_cannot_downgrade_it(self):
        result = _run_case(
            """
const finish = schedulerTransition_(null, schedulerReceipt_("finish", "cancelled", "2026-08-02T10:05:00Z"));
const lateStart = schedulerTransition_(finish.row, schedulerReceipt_("start", "running", "2026-08-02T10:06:00Z"));
console.log(JSON.stringify({ finish, lateStart }));
"""
        )
        self.assertTrue(result["finish"]["inserted"])
        self.assertTrue(result["finish"]["missing_start"])
        self.assertEqual(result["finish"]["row"]["started_at"], "")
        self.assertEqual(result["lateStart"]["row"]["status"], "cancelled")
        self.assertTrue(result["lateStart"]["missing_start"])
        self.assertFalse(result["lateStart"]["updated"])

    def test_conflicting_terminal_receipt_is_rejected(self):
        result = _run_case(
            """
const finish = schedulerTransition_(null, schedulerReceipt_("finish", "success", "2026-08-02T10:05:00Z"));
try {
  schedulerTransition_(finish.row, schedulerReceipt_("finish", "failure", "2026-08-02T10:06:00Z"));
  console.log(JSON.stringify({ error: "" }));
} catch (error) {
  console.log(JSON.stringify({ error: String(error.message || error) }));
}
"""
        )
        self.assertIn("conflicting terminal status", result["error"])

    def test_receipt_validation_rejects_wrong_phase_status_pair(self):
        result = _run_case(
            """
try {
  validateSchedulerReceipt_(schedulerReceipt_("start", "success", "2026-08-02T10:00:00Z"));
  console.log(JSON.stringify({ error: "" }));
} catch (error) {
  console.log(JSON.stringify({ error: String(error.message || error) }));
}
"""
        )
        self.assertIn("start receipt must be running", result["error"])

    def test_receipt_validation_rejects_unstructured_step_results(self):
        result = _run_case(
            """
const receipt = schedulerReceipt_("finish", "failure", "2026-08-02T10:00:00Z");
receipt.steps = { send_brief: "failure" };
try {
  validateSchedulerReceipt_(receipt);
  console.log(JSON.stringify({ error: "" }));
} catch (error) {
  console.log(JSON.stringify({ error: String(error.message || error) }));
}
"""
        )
        self.assertIn("outcome and conclusion", result["error"])

    def test_receipt_validation_recomputes_run_key_and_preserves_string_ids(self):
        result = _run_case(
            """
const valid = schedulerReceipt_("start", "running", "2026-08-02T10:00:00Z");
valid.run_id = "9007199254740993";
valid.run_attempt = "07";
valid.run_key = "owner/repo:wrong:07:market-brief";
try {
  validateSchedulerReceipt_(valid);
  console.log(JSON.stringify({ error: "" }));
} catch (error) {
  console.log(JSON.stringify({ error: String(error.message || error), run_id: valid.run_id }));
}
"""
        )
        self.assertIn("run_key does not match", result["error"])
        self.assertEqual(result["run_id"], "9007199254740993")

    def test_scheduler_summary_uses_only_scheduled_runs_for_freshness(self):
        result = _run_case(
            """
const rows = [
  schedulerRunRow_("workflow_dispatch", "setup-check", "success", "2026-08-02T11:55:00Z"),
  schedulerRunRow_("schedule", "setup-check", "success", "2026-08-02T10:00:00Z"),
  schedulerRunRow_("schedule", "brief", "success", "2026-08-02T06:00:00Z"),
];
console.log(JSON.stringify(summarizeSchedulerRunsAt_(rows, Date.parse("2026-08-02T12:00:00Z"))));
"""
        )
        self.assertEqual(result["health"], "degraded")
        self.assertEqual(result["last_setup_success_at"], "2026-08-02T10:00:00Z")
        self.assertEqual(result["last_brief_success_at"], "2026-08-02T06:00:00Z")
        self.assertIn("stale_setup_check", result["warnings"])

    def test_scheduler_summary_detects_stale_running_and_ignores_recovered_failure(self):
        result = _run_case(
            """
const rows = [
  schedulerRunRow_("schedule", "setup-check", "failure", "2026-08-02T11:00:00Z"),
  schedulerRunRow_("schedule", "setup-check", "success", "2026-08-02T11:45:00Z"),
  schedulerRunRow_("schedule", "brief", "success", "2026-08-02T06:00:00Z"),
  Object.assign(schedulerRunRow_("schedule", "setup-check", "running", ""), {
    started_at: "2026-08-02T10:00:00Z",
    finished_at: "",
    updated_at: "2026-08-02T10:00:00Z",
  }),
];
console.log(JSON.stringify(summarizeSchedulerRunsAt_(rows, Date.parse("2026-08-02T12:00:00Z"))));
"""
        )
        self.assertEqual(result["health"], "degraded")
        self.assertEqual(result["stale_running"], 1)
        self.assertEqual(result["failed_last_24h"], 1)
        self.assertNotIn("latest_setup_check_failed", result["warnings"])

    def test_scheduler_summary_is_unknown_before_any_scheduled_receipt(self):
        result = _run_case(
            """
const rows = [schedulerRunRow_("workflow_dispatch", "brief", "success", "2026-08-02T11:00:00Z")];
console.log(JSON.stringify(summarizeSchedulerRunsAt_(rows, Date.parse("2026-08-02T12:00:00Z"))));
"""
        )
        self.assertEqual(result["health"], "unknown")
        self.assertEqual(result["scheduled_runs"], 0)

    def test_duplicate_run_key_rows_are_rejected(self):
        result = _run_case(
            """
const headers = ["run_key", "status"];
const values = [headers, ["same-key", "running"], ["same-key", "success"]];
try {
  uniqueSchedulerRowNumber_([2, 3], "same-key");
  console.log(JSON.stringify({ error: "" }));
} catch (error) {
  console.log(JSON.stringify({ error: String(error.message || error) }));
}
"""
        )
        self.assertIn("duplicate scheduler run_key", result["error"])

    def test_mapped_update_preserves_custom_columns_in_one_write(self):
        result = _run_case(
            """
const data = [
  ["custom_note", "status", "run_key", "finished_at"],
  ["keep me", "running", "run-1", ""],
];
let writes = 0;
const sheet = {
  getLastColumn: () => data[0].length,
  getRange: (row, column, rowCount, columnCount) => ({
    getValues: () => [data[row - 1].slice(column - 1, column - 1 + columnCount)],
    setValues: (rows) => {
      writes += 1;
      rows[0].forEach((value, index) => { data[row - 1][column - 1 + index] = value; });
    },
  }),
};
updateMappedRow_(
  sheet,
  2,
  data[0],
  data[1],
  { status: "success", finished_at: "2026-08-02T12:00:00Z" }
);
console.log(JSON.stringify({ row: data[1], writes }));
"""
        )
        self.assertEqual(result["row"][0], "keep me")
        self.assertEqual(result["row"][1], "success")
        self.assertEqual(result["row"][3], "2026-08-02T12:00:00Z")
        self.assertEqual(result["writes"], 1)


def _run_case(case_source: str) -> dict[str, object]:
    helper = r"""
function schedulerReceipt_(phase, status, observedAt) {
  return {
    schema_version: "scheduler-receipt/v1",
    run_key: "owner/repo:123:1:market-brief",
    phase: phase,
    status: status,
    repository: "owner/repo",
    workflow: "SignalPilot Market Brief",
    job: "market-brief",
    run_id: "123",
    run_attempt: 1,
    event_name: "schedule",
    event_schedule: "5,20,35,50 0-21,23 * * *",
    mode: "setup-check",
    commit_sha: "abc123",
    run_url: "https://github.com/owner/repo/actions/runs/123",
    observed_at: observedAt,
    steps: { checkout: { outcome: "success", conclusion: "success" } },
  };
}
function schedulerRunRow_(eventName, mode, status, finishedAt) {
  return {
    event_name: eventName,
    mode: mode,
    status: status,
    started_at: finishedAt,
    finished_at: finishedAt,
    updated_at: finishedAt,
  };
}
"""
    completed = subprocess.run(
        [NODE],
        input=CODE_GS.read_text(encoding="utf-8") + helper + case_source,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return json.loads(completed.stdout)


if __name__ == "__main__":
    unittest.main()
