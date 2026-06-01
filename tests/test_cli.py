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
                "signalpilot.cli._fetch_futures_context",
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

            with patch("signalpilot.cli._run_signal_generation", side_effect=record_generation):
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


if __name__ == "__main__":
    unittest.main()
