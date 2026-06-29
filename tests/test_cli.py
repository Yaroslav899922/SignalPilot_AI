import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
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
                "win_rate": None,
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
                with patch("signalpilot.cli.generate_brief", return_value="<b>brief</b>") as generate_brief:
                    with patch("signalpilot.telegram.send_message", return_value={"ok": True}) as send_message:
                        with redirect_stdout(output):
                            exit_code = main(["--brief", "--notify", "--symbols", "BTCUSDT", "ETHUSDT"])

        self.assertEqual(exit_code, 0)
        self.assertEqual([call.kwargs["symbol"] for call in fetch_market.call_args_list], ["BTCUSDT", "ETHUSDT"])
        generate_brief.assert_called_once_with(
            [
                {"symbol": "BTCUSDT", "intervals": ("15m", "1h", "4h"), "limit": 500},
                {"symbol": "ETHUSDT", "intervals": ("15m", "1h", "4h"), "limit": 500},
            ],
            session_label=None,
        )
        send_message.assert_called_once()
        self.assertEqual(send_message.call_args.args[0], "<b>brief</b>")
        self.assertEqual(send_message.call_args.args[1].bot_token, "token")

        out = output.getvalue()
        self.assertIn("===SIGNALPILOT-BRIEF-START===", out)
        self.assertIn("<b>brief</b>", out)
        self.assertIn("===SIGNALPILOT-BRIEF-END===", out)
        status_lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
        self.assertEqual(status_lines, [{"brief": "generated", "symbols": ["BTCUSDT", "ETHUSDT"]}, {"brief": "sent"}])

    def test_brief_passes_session_label(self):
        output = io.StringIO()

        with patch("signalpilot.cli.load_live_market_data", return_value={"symbol": "BTCUSDT"}):
            with patch("signalpilot.cli.generate_brief", return_value="<b>brief</b>") as generate_brief:
                with redirect_stdout(output):
                    exit_code = main(["--brief", "--brief-session", "Лондон · open +1h", "--symbols", "BTCUSDT"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(generate_brief.call_args.kwargs["session_label"], "Лондон · open +1h")
        out = output.getvalue()
        self.assertIn("===SIGNALPILOT-BRIEF-START===", out)
        self.assertIn("<b>brief</b>", out)
        self.assertIn("===SIGNALPILOT-BRIEF-END===", out)
        status_lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
        self.assertEqual(status_lines, [{"brief": "generated", "symbols": ["BTCUSDT"]}])

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
