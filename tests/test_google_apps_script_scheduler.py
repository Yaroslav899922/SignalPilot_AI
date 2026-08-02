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


@unittest.skipUnless(NODE, "Node.js is required to execute Apps Script state tests")
class GoogleAppsScriptJournalExecutionTests(unittest.TestCase):
    def test_triggered_setup_is_durable_when_the_following_signal_write_fails(self):
        result = _run_case(
            """
const signalSheet = inMemorySheet_(SIGNAL_COLUMNS, []);
const setupSheet = inMemorySheet_(SETUP_COLUMNS, []);
getSignalsSheet_ = () => signalSheet;
getSetupsSheet_ = () => setupSheet;
signalSheet.failNextSetValues();

const payload = triggeredPayload_();
let firstError = "";
try {
  saveTriggeredEvent_(payload);
} catch (error) {
  firstError = String(error.message || error);
}
const rowsAfterFailure = {
  signals: signalSheet.bodyRows().length,
  setups: setupSheet.bodyRows().length,
};
const retry = saveTriggeredEvent_(payload);
console.log(JSON.stringify({
  firstError,
  rowsAfterFailure,
  retry,
  finalRows: {
    signals: signalSheet.bodyRows().length,
    setups: setupSheet.bodyRows().length,
  },
}));
"""
        )

        self.assertIn("injected setValues failure", result["firstError"])
        self.assertEqual(result["rowsAfterFailure"], {"signals": 0, "setups": 1})
        self.assertEqual(
            result["retry"],
            {
                "ok": True,
                "signal_inserted": True,
                "setup_inserted": False,
                "event_id": "event-1",
            },
        )
        self.assertEqual(result["finalRows"], {"signals": 1, "setups": 1})

    def test_stale_triggered_bundle_does_not_create_a_signal(self):
        result = _run_case(
            """
const signalSheet = inMemorySheet_(SIGNAL_COLUMNS, []);
const setupSheet = inMemorySheet_(SETUP_COLUMNS, [
  setupRow_("ARMED", "armed-later", "2026-08-02T10:20:00Z"),
]);
getSignalsSheet_ = () => signalSheet;
getSetupsSheet_ = () => setupSheet;
const payload = triggeredPayload_();
const receipt = saveTriggeredEvent_(payload);
console.log(JSON.stringify({
  receipt,
  signals: signalSheet.bodyRows().length,
  setups: setupSheet.bodyRows().length,
}));
"""
        )

        self.assertFalse(result["receipt"]["signal_inserted"])
        self.assertFalse(result["receipt"]["setup_inserted"])
        self.assertTrue(result["receipt"]["stale"])
        self.assertEqual(result["signals"], 0)
        self.assertEqual(result["setups"], 1)

    def test_parallel_first_observations_keep_one_active_event(self):
        result = _run_case(
            """
const signalSheet = inMemorySheet_(SIGNAL_COLUMNS, []);
const setupSheet = inMemorySheet_(SETUP_COLUMNS, []);
getSignalsSheet_ = () => signalSheet;
getSetupsSheet_ = () => setupSheet;

const firstPayload = triggeredPayload_();
const first = saveTriggeredEvent_(firstPayload);
const secondPayload = triggeredPayload_();
secondPayload.setup.event_id = "event-2";
secondPayload.signal.event_id = "event-2";
secondPayload.setup.created_at = "2026-08-02T10:10:01Z";
secondPayload.setup.triggered_at = "2026-08-02T10:10:01Z";
secondPayload.signal.created_at = "2026-08-02T10:10:01Z";
secondPayload.signal.triggered_at = "2026-08-02T10:10:01Z";
secondPayload.fingerprint = "triggered-2";
const second = saveTriggeredEvent_(secondPayload);
console.log(JSON.stringify({
  first,
  second,
  signals: signalSheet.bodyRows().length,
  setups: setupSheet.bodyRows().length,
}));
"""
        )

        self.assertTrue(result["first"]["signal_inserted"])
        self.assertTrue(result["first"]["setup_inserted"])
        self.assertFalse(result["second"]["signal_inserted"])
        self.assertFalse(result["second"]["setup_inserted"])
        self.assertTrue(result["second"]["stale"])
        self.assertEqual(result["signals"], 1)
        self.assertEqual(result["setups"], 1)

    def test_evaluation_update_is_one_mapped_row_write(self):
        result = _run_case(
            """
const headers = ["custom_note"].concat(SIGNAL_COLUMNS.slice().reverse());
const row = mappedRow_(headers, {
  custom_note: "keep me",
  id: 7,
  outcome: "not_enough_data",
});
const sheet = inMemorySheet_(headers, [row]);
getSignalsSheet_ = () => sheet;
const receipt = updateSignalEvaluationUnlocked_({
  signal_id: 7,
  activated_at: "2026-08-02T10:01:00Z",
  evaluated_at: "2026-08-02T10:05:00Z",
  outcome: "target_hit",
  max_favorable_price: 111,
  max_adverse_price: 99,
  result_R: 2,
  baseline_R: 1,
  edge_R: 1,
});
const saved = rowObject_(headers, sheet.bodyRows()[0]);
console.log(JSON.stringify({ receipt, saved, stats: sheet.stats() }));
"""
        )

        self.assertTrue(result["receipt"]["updated"])
        self.assertEqual(result["saved"]["custom_note"], "keep me")
        self.assertEqual(result["saved"]["outcome"], "target_hit")
        self.assertEqual(result["saved"]["edge_R"], 1)
        self.assertEqual(result["stats"]["setValues"], 1)
        self.assertEqual(result["stats"]["setValue"], 0)

    def test_evaluation_update_preserves_untouched_formula_cells(self):
        result = _run_case(
            """
const headers = ["custom_formula"].concat(SIGNAL_COLUMNS);
const values = [
  headers,
  mappedRow_(headers, {
    custom_formula: 42,
    id: 7,
    outcome: "not_enough_data",
  }),
];
const formulas = [
  headers.map(() => ""),
  mappedRow_(headers, { custom_formula: "=SUM(20,22)" }),
];
let saved = null;
const sheet = {
  getDataRange: () => ({
    getValues: () => values.map((row) => row.slice()),
    getFormulas: () => formulas.map((row) => row.slice()),
  }),
  getRange: () => ({
    setValues: (rows) => { saved = rows[0].slice(); },
  }),
};
getSignalsSheet_ = () => sheet;
updateSignalEvaluationUnlocked_({
  signal_id: 7,
  evaluated_at: "2026-08-02T10:05:00Z",
  outcome: "target_hit",
  max_favorable_price: 111,
  max_adverse_price: 99,
  result_R: 2,
  baseline_R: 1,
  edge_R: 1,
});
console.log(JSON.stringify({ saved: rowObject_(headers, saved) }));
"""
        )

        self.assertEqual(result["saved"]["custom_formula"], "=SUM(20,22)")
        self.assertEqual(result["saved"]["outcome"], "target_hit")

    def test_exact_terminal_evaluation_replay_does_not_write_again(self):
        result = _run_case(
            """
const payload = {
  signal_id: 7,
  activated_at: "2026-08-02T10:01:00Z",
  evaluated_at: "2026-08-02T10:05:00Z",
  outcome: "target_hit",
  max_favorable_price: 111,
  max_adverse_price: 99,
  result_R: 2,
  baseline_R: 1,
  edge_R: 1,
};
const row = mappedRow_(SIGNAL_COLUMNS, Object.assign(
  { id: 7 },
  payload,
  { evaluated_at: "2026-08-02T10:04:00Z" }
));
const sheet = inMemorySheet_(SIGNAL_COLUMNS, [row]);
getSignalsSheet_ = () => sheet;
const replay = updateSignalEvaluationUnlocked_(payload);
console.log(JSON.stringify({ replay, stats: sheet.stats() }));
"""
        )

        self.assertTrue(result["replay"]["updated"])
        self.assertTrue(result["replay"].get("replayed", False))
        self.assertEqual(result["stats"], {"setValues": 0, "setValue": 0})

    def test_conflicting_terminal_evaluation_is_rejected_without_a_write(self):
        result = _run_case(
            """
const row = mappedRow_(SIGNAL_COLUMNS, {
  id: 7,
  activated_at: "2026-08-02T10:01:00Z",
  evaluated_at: "2026-08-02T10:05:00Z",
  outcome: "target_hit",
  max_favorable_price: 111,
  max_adverse_price: 99,
  result_R: 2,
  baseline_R: 1,
  edge_R: 1,
});
const sheet = inMemorySheet_(SIGNAL_COLUMNS, [row]);
getSignalsSheet_ = () => sheet;
let error = "";
try {
  updateSignalEvaluationUnlocked_({
    signal_id: 7,
    activated_at: "2026-08-02T10:01:00Z",
    evaluated_at: "2026-08-02T10:06:00Z",
    outcome: "stop_hit",
    max_favorable_price: 111,
    max_adverse_price: 94,
    result_R: -1,
    baseline_R: -1,
    edge_R: 0,
  });
} catch (caught) {
  error = String(caught.message || caught);
}
const saved = rowObject_(SIGNAL_COLUMNS, sheet.bodyRows()[0]);
console.log(JSON.stringify({ error, outcome: saved.outcome, stats: sheet.stats() }));
"""
        )

        self.assertIn("conflicting terminal signal evaluation", result["error"])
        self.assertEqual(result["outcome"], "target_hit")
        self.assertEqual(result["stats"], {"setValues": 0, "setValue": 0})

    def test_widened_legacy_sheet_expands_before_header_read_and_append(self):
        result = _run_case(
            """
const sheet = inMemorySheet_(["a", "custom", ""], [], { maxColumns: 3 });
const spreadsheet = {
  getSheetByName: () => sheet,
  insertSheet: () => { throw new Error("unexpected insertSheet"); },
};
globalThis.PropertiesService = {
  getScriptProperties: () => ({ getProperty: () => "" }),
};
globalThis.SpreadsheetApp = {
  getActiveSpreadsheet: () => spreadsheet,
};
let error = "";
try {
  getConfiguredSheet_("legacy", ["a", "b", "c", "d", "e"]);
} catch (caught) {
  error = String(caught.message || caught);
}
console.log(JSON.stringify({
  error,
  headers: sheet.snapshot()[0],
  maxColumns: sheet.getMaxColumns(),
}));
"""
        )

        self.assertEqual(result["error"], "")
        self.assertEqual(result["headers"], ["a", "custom", "b", "c", "d", "e"])
        self.assertEqual(result["maxColumns"], 6)

    def test_older_or_equal_active_setup_delivery_is_a_noop(self):
        result = _run_case(
            """
const rows = [
  setupRow_("WATCH", "watch-1", "2026-08-02T10:00:00Z"),
  setupRow_("ARMED", "armed-1", "2026-08-02T10:10:00Z"),
];
const sheet = inMemorySheet_(SETUP_COLUMNS, rows);
getSetupsSheet_ = () => sheet;
const stale = setupPayload_("WATCH", "2026-08-02T10:05:00Z");
const older = saveSetupEventUnlocked_(stale, "watch-stale-new-fingerprint");
const equal = saveSetupEventUnlocked_(
  setupPayload_("WATCH", "2026-08-02T10:10:00Z"),
  "watch-equal-new-fingerprint"
);
console.log(JSON.stringify({ older, equal, rows: sheet.bodyRows().length }));
"""
        )

        self.assertFalse(result["older"]["inserted"])
        self.assertFalse(result["equal"]["inserted"])
        self.assertEqual(result["rows"], 2)

    def test_terminal_setup_never_returns_to_a_newer_active_state(self):
        result = _run_case(
            """
const rows = [
  setupRow_("TRIGGERED", "triggered-1", "2026-08-02T10:10:00Z"),
  setupRow_("TARGET_HIT", "target-1", "2026-08-02T10:20:00Z"),
];
const sheet = inMemorySheet_(SETUP_COLUMNS, rows);
getSetupsSheet_ = () => sheet;
const active = setupPayload_("ARMED", "2026-08-02T10:30:00Z");
const receipt = saveSetupEventUnlocked_(active, "armed-after-terminal");
console.log(JSON.stringify({ receipt, rows: sheet.bodyRows().length }));
"""
        )

        self.assertFalse(result["receipt"]["inserted"])
        self.assertEqual(result["rows"], 2)

    def test_different_terminal_setup_for_the_same_event_is_rejected(self):
        result = _run_case(
            """
const sheet = inMemorySheet_(SETUP_COLUMNS, [
  setupRow_("TARGET_HIT", "target-1", "2026-08-02T10:20:00Z"),
]);
getSetupsSheet_ = () => sheet;
let error = "";
try {
  saveSetupEventUnlocked_(
    setupPayload_("STOPPED", "2026-08-02T10:21:00Z"),
    "stopped-conflict"
  );
} catch (caught) {
  error = String(caught.message || caught);
}
console.log(JSON.stringify({ error, rows: sheet.bodyRows().length }));
"""
        )

        self.assertIn("conflicting terminal setup state", result["error"])
        self.assertEqual(result["rows"], 1)

    def test_newer_active_and_terminal_setup_transitions_are_persisted(self):
        result = _run_case(
            """
const sheet = inMemorySheet_(SETUP_COLUMNS, [
  setupRow_("WATCH", "watch-1", "2026-08-02T10:00:00Z"),
]);
getSetupsSheet_ = () => sheet;
const armed = saveSetupEventUnlocked_(
  setupPayload_("ARMED", "2026-08-02T10:10:00Z"),
  "armed-1"
);
const terminal = saveSetupEventUnlocked_(
  setupPayload_("INVALIDATED", "2026-08-02T10:20:00Z"),
  "invalidated-1"
);
console.log(JSON.stringify({ armed, terminal, rows: sheet.bodyRows().length }));
"""
        )

        self.assertTrue(result["armed"]["inserted"])
        self.assertTrue(result["terminal"]["inserted"])
        self.assertEqual(result["rows"], 3)


def _run_case(case_source: str) -> dict[str, object]:
    helper = r"""
globalThis.LockService = {
  getScriptLock: () => ({
    tryLock: () => true,
    releaseLock: () => {},
  }),
};

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

function inMemorySheet_(headers, rows, options) {
  const settings = options || {};
  const data = [headers.slice()].concat((rows || []).map((row) => row.slice()));
  let maxColumns = settings.maxColumns || Math.max(headers.length, 1);
  let setValuesCalls = 0;
  let setValueCalls = 0;
  let failNextSetValues = false;

  function lastNonEmptyIndex_(row) {
    for (let index = row.length - 1; index >= 0; index -= 1) {
      if (row[index] !== "" && row[index] !== null && row[index] !== undefined) {
        return index;
      }
    }
    return -1;
  }

  function ensureRow_(rowIndex) {
    while (data.length <= rowIndex) {
      data.push([]);
    }
  }

  function getRange_(row, column, rowCount, columnCount) {
    const height = rowCount || 1;
    const width = columnCount || 1;
    if (row < 1 || column < 1 || height < 1 || width < 1) {
      throw new Error("invalid range");
    }
    if (column + width - 1 > maxColumns) {
      throw new Error("range exceeds sheet column capacity");
    }
    return {
      getValues: () => Array.from({ length: height }, (_, rowOffset) => (
        Array.from({ length: width }, (_, columnOffset) => {
          const source = data[row - 1 + rowOffset] || [];
          const value = source[column - 1 + columnOffset];
          return value === undefined ? "" : value;
        })
      )),
      getFormulas: () => Array.from(
        { length: height },
        () => Array(width).fill("")
      ),
      setValues: (values) => {
        setValuesCalls += 1;
        if (failNextSetValues) {
          failNextSetValues = false;
          throw new Error("injected setValues failure");
        }
        if (values.length !== height || values.some((valueRow) => valueRow.length !== width)) {
          throw new Error("setValues dimension mismatch");
        }
        values.forEach((valueRow, rowOffset) => {
          const targetRow = row - 1 + rowOffset;
          ensureRow_(targetRow);
          valueRow.forEach((value, columnOffset) => {
            data[targetRow][column - 1 + columnOffset] = value;
          });
        });
      },
      setValue: (value) => {
        setValueCalls += 1;
        ensureRow_(row - 1);
        data[row - 1][column - 1] = value;
      },
    };
  }

  return {
    getMaxColumns: () => maxColumns,
    getLastColumn: () => data.reduce(
      (maximum, row) => Math.max(maximum, lastNonEmptyIndex_(row) + 1),
      0
    ),
    getLastRow: () => {
      for (let index = data.length - 1; index >= 0; index -= 1) {
        if (lastNonEmptyIndex_(data[index]) >= 0) {
          return index + 1;
        }
      }
      return 0;
    },
    insertColumnsAfter: (afterPosition, howMany) => {
      if (afterPosition < 1 || afterPosition > maxColumns || howMany < 1) {
        throw new Error("invalid column insertion");
      }
      data.forEach((row) => {
        while (row.length < afterPosition) {
          row.push("");
        }
        row.splice(afterPosition, 0, ...Array(howMany).fill(""));
      });
      maxColumns += howMany;
    },
    getRange: getRange_,
    getDataRange: () => getRange_(
      1,
      1,
      Math.max(1, data.length),
      Math.max(1, data.reduce(
        (maximum, row) => Math.max(maximum, lastNonEmptyIndex_(row) + 1),
        0
      ))
    ),
    failNextSetValues: () => { failNextSetValues = true; },
    bodyRows: () => data.slice(1).filter((row) => row.some((value) => value !== "")),
    snapshot: () => data.map((row) => row.slice(0, maxColumns)),
    stats: () => ({ setValues: setValuesCalls, setValue: setValueCalls }),
  };
}

function mappedRow_(headers, values) {
  return headers.map((header) => (
    Object.prototype.hasOwnProperty.call(values, header) ? values[header] : ""
  ));
}

function rowObject_(headers, row) {
  const result = {};
  headers.forEach((header, index) => { result[header] = row[index]; });
  return result;
}

function setupPayload_(status, createdAt) {
  return {
    setup_id: "setup-1",
    event_id: "event-1",
    symbol: "BTCUSDT",
    pattern: "breakout_retest",
    direction: "LONG",
    status: status,
    regime: "uptrend",
    current_price: 100,
    trigger_level: 101,
    entry_low: 101,
    entry_high: 102,
    stop: 98,
    targets: [106, 109],
    risk_reward: 1.5,
    score: 75,
    action: "test action",
    reason: "test reason",
    invalidation: "test invalidation",
    conditions: [],
    created_at: createdAt,
    detected_at: "2026-08-02T10:00:00Z",
    triggered_at: status === "TRIGGERED" ? createdAt : "",
    expires_at: "2026-08-02T22:00:00Z",
    source: "actionable_setup",
    policy_version: "v3.1",
    market_source: "binance_usdm_public",
  };
}

function setupRow_(status, fingerprint, createdAt) {
  const setup = setupPayload_(status, createdAt);
  const values = Object.assign({}, setup, {
    targets_json: JSON.stringify(setup.targets),
    conditions_json: JSON.stringify(setup.conditions),
    fingerprint: fingerprint,
  });
  return mappedRow_(SETUP_COLUMNS, values);
}

function triggeredPayload_() {
  const setup = setupPayload_("TRIGGERED", "2026-08-02T10:10:00Z");
  return {
    fingerprint: "triggered-1",
    setup: setup,
    signal: {
      created_at: setup.created_at,
      symbol: setup.symbol,
      interval: "15m",
      direction: setup.direction,
      market_regime: setup.regime,
      close_price: setup.current_price,
      entry_zone: "101-102",
      stop: setup.stop,
      targets: setup.targets,
      risk_reward: setup.risk_reward,
      confidence: "medium",
      invalidation: setup.invalidation,
      reasons: [setup.reason],
      source: "actionable_alert",
      setup_id: setup.setup_id,
      setup_status: setup.status,
      expires_at: setup.expires_at,
      event_id: setup.event_id,
      policy_version: setup.policy_version,
      detected_at: setup.detected_at,
      triggered_at: setup.triggered_at,
      market_source: setup.market_source,
    },
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
