import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from signalpilot.cli import main


class CliTests(unittest.TestCase):
    def test_report_prints_summary_without_fetching_binance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "missing.sqlite3"
            output = io.StringIO()

            with patch(
                "signalpilot.cli.load_live_market_data",
                side_effect=AssertionError("unexpected Binance call"),
            ):
                with redirect_stdout(output):
                    exit_code = main(["--report", "--journal", str(db_path)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "signals": 0,
                "long": 0,
                "short": 0,
                "no_trade": 0,
                "pending": 0,
                    "target_hit": 0,
                    "stop_hit": 0,
                    "no_result": 0,
                    "not_activated": 0,
                    "win_rate": None,
                    "confirmed_entries": 0,
                    "confirmed_pending": 0,
                    "confirmed_target_hit": 0,
                    "confirmed_stop_hit": 0,
                    "confirmed_barrier_resolved": 0,
                    "confirmed_timed_out": 0,
                    "confirmed_terminal": 0,
                    "confirmed_no_result": 0,
                    "confirmed_unpaired_terminal": 0,
                    "confirmed_win_rate": None,
                    "confirmed_barrier_result_R": None,
                    "confirmed_timed_out_result_R": None,
                    "confirmed_barrier_paired_n": 0,
                    "confirmed_timed_out_paired_n": 0,
                    "confirmed_paired_n": 0,
                    "confirmed_paired_result_R": None,
                    "confirmed_paired_baseline_R": None,
                    "confirmed_paired_edge_R": None,
                    "confirmed_result_R": None,
                    "confirmed_baseline_R": None,
                    "confirmed_edge_R": None,
                    "legacy_market_brief_rows": 0,
            },
        )

    def test_report_uses_apps_script_backend_from_environment(self):
        output = io.StringIO()
        summary = {
            "signals": 3,
            "long": 1,
            "short": 1,
            "no_trade": 1,
            "pending": 2,
            "target_hit": 0,
            "stop_hit": 0,
            "no_result": 0,
            "win_rate": None,
        }

        with patch.dict(
            "os.environ",
            {
                "SIGNALPILOT_JOURNAL_BACKEND": "apps_script",
                "SIGNALPILOT_JOURNAL_API_URL": "https://script.google.test/exec",
                "SIGNALPILOT_JOURNAL_API_TOKEN": "journal-token",
            },
            clear=True,
        ):
            with patch(
                "signalpilot.apps_script_journal.urlopen",
                return_value=FakeResponse({"ok": True, "summary": summary}),
            ):
                with redirect_stdout(output):
                    exit_code = main(["--report"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue()), summary)

    def test_paper_loop_runs_generation_evaluation_and_report_cycles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "signals.sqlite3"
            output = io.StringIO()
            events = []

            def record_generation(args, journal_path, telegram_config):
                events.append(("generate", tuple(args.symbols), str(journal_path), telegram_config))

            def record_evaluation(journal_path, lookahead_candles):
                events.append(("evaluate", str(journal_path), lookahead_candles))

            def record_report(journal_path):
                events.append(("report", str(journal_path)))

            with patch("signalpilot.cli._run_live_analysis", side_effect=record_generation):
                with patch("signalpilot.cli._run_evaluation", side_effect=record_evaluation):
                    with patch("signalpilot.cli._print_report", side_effect=record_report):
                        with patch("signalpilot.cli.time.sleep") as sleep:
                            with redirect_stdout(output):
                                exit_code = main(
                                    [
                                        "--paper-loop",
                                        "--symbols",
                                        "BTCUSDT",
                                        "--journal",
                                        str(db_path),
                                        "--lookahead-candles",
                                        "6",
                                        "--run-every-minutes",
                                        "0.01",
                                        "--max-runs",
                                        "2",
                                    ]
                                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            events,
            [
                ("generate", ("BTCUSDT",), str(db_path), None),
                ("evaluate", str(db_path), 6),
                ("report", str(db_path)),
                ("generate", ("BTCUSDT",), str(db_path), None),
                ("evaluate", str(db_path), 6),
                ("report", str(db_path)),
            ],
        )
        sleep.assert_called_once_with(0.6)

        cycle_lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([line["paper_loop_cycle"] for line in cycle_lines], [1, 2])

    def test_telegram_bot_mode_reads_env_and_starts_bot_loop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "signals.sqlite3"
            events = []

            def record_bot(args, journal_path, telegram_config):
                events.append((str(journal_path), telegram_config.bot_token, telegram_config.chat_id))
                return 0

            with patch.dict(
                "os.environ",
                {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "channel"},
                clear=True,
            ):
                with patch("signalpilot.cli._run_telegram_bot", side_effect=record_bot):
                    exit_code = main(["--telegram-bot", "--journal", str(db_path), "--telegram-max-polls", "1"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(events, [(str(db_path), "token", "channel")])

    def test_brief_with_notify_fetches_market_data_and_sends_telegram(self):
        output = io.StringIO()

        def fake_market(symbol, intervals, limit):
            return {"symbol": symbol, "intervals": tuple(intervals), "limit": limit}

        with patch.dict(
            "os.environ",
            {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "channel"},
            clear=True,
        ):
            with patch("signalpilot.cli.load_live_market_data", side_effect=fake_market) as fetch_market:
                with patch("signalpilot.cli.analyze_actionable_setup", return_value=None):
                    with patch("signalpilot.cli.format_action_brief", return_value="<b>brief</b>") as format_brief:
                        with patch("signalpilot.telegram.send_message", return_value={"ok": True}) as send_message:
                            with redirect_stdout(output):
                                exit_code = main(["--brief", "--notify", "--symbols", "BTCUSDT", "ETHUSDT"])

        self.assertEqual(exit_code, 0)
        self.assertEqual([call.kwargs["symbol"] for call in fetch_market.call_args_list], ["BTCUSDT", "ETHUSDT"])
        self.assertEqual(
            format_brief.call_args.args[0],
            [
                {"symbol": "BTCUSDT", "intervals": ("15m", "1h", "4h"), "limit": 500},
                {"symbol": "ETHUSDT", "intervals": ("15m", "1h", "4h"), "limit": 500},
            ],
        )
        self.assertEqual(format_brief.call_args.args[1], [])
        self.assertIsNotNone(format_brief.call_args.kwargs["now_utc"])
        self.assertIsNone(format_brief.call_args.kwargs["session_label"])
        send_message.assert_called_once()
        self.assertEqual(send_message.call_args.args[0], "<b>brief</b>")
        self.assertEqual(send_message.call_args.args[1].bot_token, "token")

        out = output.getvalue()
        self.assertIn("===SIGNALPILOT-BRIEF-START===", out)
        self.assertIn("<b>brief</b>", out)
        self.assertIn("===SIGNALPILOT-BRIEF-END===", out)
        status_lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
        self.assertEqual(
            status_lines,
            [
                {"brief": "generated", "symbols": ["BTCUSDT", "ETHUSDT"]},
                {"brief": "sent"},
            ],
        )

    def test_brief_passes_session_label(self):
        output = io.StringIO()

        with patch("signalpilot.cli.load_live_market_data", return_value={"symbol": "BTCUSDT"}):
            with patch("signalpilot.cli.analyze_actionable_setup", return_value=None):
                with patch("signalpilot.cli.format_action_brief", return_value="<b>brief</b>") as format_brief:
                    with redirect_stdout(output):
                        exit_code = main(["--brief", "--brief-session", "Лондон · open +1h", "--symbols", "BTCUSDT"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(format_brief.call_args.kwargs["session_label"], "Лондон · open +1h")
        out = output.getvalue()
        self.assertIn("===SIGNALPILOT-BRIEF-START===", out)
        self.assertIn("<b>brief</b>", out)
        self.assertIn("===SIGNALPILOT-BRIEF-END===", out)
        status_lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
        self.assertEqual(
            status_lines,
            [
                {"brief": "generated", "symbols": ["BTCUSDT"]},
            ],
        )

    def test_setup_check_sends_only_persisted_state_changes(self):
        output = io.StringIO()
        market = {"symbol": "BTCUSDT"}
        event = SimpleNamespace(status="TRIGGERED")
        signal = SimpleNamespace(symbol="BTCUSDT")

        with patch.dict(
            "os.environ",
            {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "channel"},
            clear=True,
        ):
            with patch("signalpilot.cli.load_live_market_data", return_value=market):
                with patch("signalpilot.cli.load_latest_setups", return_value=[]):
                    with patch("signalpilot.cli.analyze_actionable_setup", return_value=event):
                        with patch("signalpilot.cli.reconcile_setup_state", return_value=[event]):
                            with patch("signalpilot.cli.save_setup_event", return_value=True):
                                with patch("signalpilot.cli.setup_to_signal", return_value=signal):
                                    with patch(
                                        "signalpilot.cli.save_triggered_event",
                                        return_value=(True, True),
                                    ):
                                        with patch("signalpilot.cli.format_setup_message", return_value="<b>entry</b>"):
                                            with patch("signalpilot.telegram.send_message", return_value={"ok": True}) as send:
                                                with redirect_stdout(output):
                                                    exit_code = main(
                                                        ["--setup-check", "--notify", "--symbols", "BTCUSDT"]
                                                    )

        self.assertEqual(exit_code, 0)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "<b>entry</b>")
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "setup_check": "completed",
                "symbols": ["BTCUSDT"],
                "checked_symbols": ["BTCUSDT"],
                "failed_symbols": [],
                "state_changes": 1,
                "paper_entries": 1,
                "messages_sent": 1,
            },
        )

    def test_setup_check_does_not_commit_trigger_when_paper_entry_write_fails(self):
        output = io.StringIO()
        event = SimpleNamespace(status="TRIGGERED")
        operations = []

        def fail_bundle(*args, **kwargs):
            operations.append("bundle")
            raise RuntimeError("journal unavailable")

        with patch("signalpilot.cli.load_live_market_data", return_value={"symbol": "BTCUSDT"}):
            with patch("signalpilot.cli.load_latest_setups", return_value=[]):
                with patch("signalpilot.cli.analyze_actionable_setup", return_value=event):
                    with patch("signalpilot.cli.reconcile_setup_state", return_value=[event]):
                        with patch("signalpilot.cli.should_notify_setup_event", return_value=False):
                            with patch("signalpilot.cli.setup_to_signal", return_value=SimpleNamespace()):
                                with patch(
                                    "signalpilot.cli.save_triggered_event",
                                    side_effect=fail_bundle,
                                ):
                                    with redirect_stdout(output):
                                        exit_code = main(["--setup-check", "--symbols", "BTCUSDT"])

        self.assertEqual(exit_code, 1)
        self.assertEqual(operations, ["bundle"])
        status = json.loads(output.getvalue())
        self.assertEqual(status["setup_check"], "degraded")
        self.assertEqual(status["checked_symbols"], [])
        self.assertEqual(status["failed_symbols"], ["BTCUSDT"])
        self.assertEqual(status["state_changes"], 0)
        self.assertEqual(status["paper_entries"], 0)

    def test_setup_check_commits_trigger_when_paper_entry_is_already_durable(self):
        output = io.StringIO()
        event = SimpleNamespace(status="TRIGGERED")
        operations = []

        def save_bundle(*args, **kwargs):
            operations.append("bundle")
            return False, True

        with patch("signalpilot.cli.load_live_market_data", return_value={"symbol": "BTCUSDT"}):
            with patch("signalpilot.cli.load_latest_setups", return_value=[]):
                with patch("signalpilot.cli.analyze_actionable_setup", return_value=event):
                    with patch("signalpilot.cli.reconcile_setup_state", return_value=[event]):
                        with patch("signalpilot.cli.should_notify_setup_event", return_value=False):
                            with patch("signalpilot.cli.setup_to_signal", return_value=SimpleNamespace()):
                                with patch(
                                    "signalpilot.cli.save_triggered_event",
                                    side_effect=save_bundle,
                                ):
                                    with redirect_stdout(output):
                                        exit_code = main(["--setup-check", "--symbols", "BTCUSDT"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(operations, ["bundle"])
        status = json.loads(output.getvalue())
        self.assertEqual(status["setup_check"], "completed")
        self.assertEqual(status["state_changes"], 1)
        self.assertEqual(status["paper_entries"], 0)

    def test_setup_check_repairs_persisted_trigger_before_market_reconciliation(self):
        output = io.StringIO()
        triggered = SimpleNamespace(status="TRIGGERED", symbol="BTCUSDT")
        signal = SimpleNamespace(symbol="BTCUSDT")
        operations = []

        def repair(*args, **kwargs):
            operations.append("repair")
            return True, False

        def load_market(*args, **kwargs):
            operations.append("market")
            return {"symbol": "BTCUSDT"}

        def reconcile(*args, **kwargs):
            operations.append("reconcile")
            return []

        with patch("signalpilot.cli.load_latest_setups", return_value=[triggered]):
            with patch("signalpilot.cli.setup_to_signal", return_value=signal):
                with patch("signalpilot.cli.save_triggered_event", side_effect=repair):
                    with patch("signalpilot.cli.load_live_market_data", side_effect=load_market):
                        with patch("signalpilot.cli.analyze_actionable_setup", return_value=None):
                            with patch("signalpilot.cli.reconcile_setup_state", side_effect=reconcile):
                                with redirect_stdout(output):
                                    exit_code = main(["--setup-check", "--symbols", "BTCUSDT"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(operations, ["repair", "market", "reconcile"])
        self.assertEqual(json.loads(output.getvalue())["paper_entries"], 1)

    def test_setup_check_stops_symbol_when_trigger_repair_fails(self):
        output = io.StringIO()
        triggered = SimpleNamespace(status="TRIGGERED", symbol="BTCUSDT")

        with patch("signalpilot.cli.load_latest_setups", return_value=[triggered]):
            with patch("signalpilot.cli.setup_to_signal", return_value=SimpleNamespace()):
                with patch(
                    "signalpilot.cli.save_triggered_event",
                    side_effect=RuntimeError("repair failed"),
                ):
                    with patch(
                        "signalpilot.cli.load_live_market_data",
                        side_effect=AssertionError("market reconciliation must not run"),
                    ):
                        with patch(
                            "signalpilot.cli.reconcile_setup_state",
                            side_effect=AssertionError("state reconciliation must not run"),
                        ):
                            with redirect_stdout(output):
                                exit_code = main(["--setup-check", "--symbols", "BTCUSDT"])

        self.assertEqual(exit_code, 1)
        status = json.loads(output.getvalue())
        self.assertEqual(status["checked_symbols"], [])
        self.assertEqual(status["failed_symbols"], ["BTCUSDT"])
        self.assertIn("repair failed", status["failures"][0]["error"])

    def test_setup_check_preserves_successful_symbols_when_one_symbol_fails(self):
        output = io.StringIO()
        event = SimpleNamespace(status="ARMED")

        def load_market(symbol, intervals, limit):
            if symbol == "BTCUSDT":
                raise RuntimeError("market unavailable")
            return {"symbol": symbol}

        with patch("signalpilot.cli.load_live_market_data", side_effect=load_market):
            with patch("signalpilot.cli.load_latest_setups", return_value=[]):
                with patch("signalpilot.cli.analyze_actionable_setup", return_value=event):
                    with patch("signalpilot.cli.reconcile_setup_state", return_value=[event]):
                        with patch("signalpilot.cli.should_notify_setup_event", return_value=False):
                            with patch("signalpilot.cli.save_setup_event", return_value=True):
                                with redirect_stdout(output):
                                    exit_code = main(
                                        ["--setup-check", "--symbols", "BTCUSDT", "ETHUSDT"]
                                    )

        self.assertEqual(exit_code, 1)
        status = json.loads(output.getvalue())
        self.assertEqual(status["checked_symbols"], ["ETHUSDT"])
        self.assertEqual(status["failed_symbols"], ["BTCUSDT"])
        self.assertEqual(status["state_changes"], 1)

    def test_move_alert_with_notify_sends_triggered_alerts(self):
        output = io.StringIO()

        def fake_market(symbol, intervals, limit):
            return {"symbol": symbol, "intervals": tuple(intervals), "limit": limit}

        with patch.dict(
            "os.environ",
            {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "channel"},
            clear=True,
        ):
            with patch("signalpilot.cli.load_live_market_data", side_effect=fake_market):
                with patch("signalpilot.move_alert.generate_move_alerts", return_value=["<b>alert</b>"]) as alerts:
                    with patch("signalpilot.telegram.send_message", return_value={"ok": True}) as send_message:
                        with redirect_stdout(output):
                            exit_code = main(["--move-alert", "--notify", "--symbols", "BTCUSDT"])

        self.assertEqual(exit_code, 0)
        alerts.assert_called_once()
        self.assertEqual(alerts.call_args.kwargs["threshold_pct"], 1.5)
        send_message.assert_called_once()
        self.assertEqual(send_message.call_args.args[0], "<b>alert</b>")

        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            lines,
            [
                {"move_alert": "checked", "symbols": ["BTCUSDT"], "alerts": 1},
                {"move_alert": "sent", "index": 1},
            ],
        )


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
