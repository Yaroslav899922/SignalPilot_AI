"""Тести cohort analyzer v3.1: включення, популяції, bootstrap, вердикти."""

import unittest

from signalpilot.cohort_analysis import (MIN_N, Cohort, block_bootstrap_ci,
                                         build_report, concentration_checks,
                                         confirmatory_verdict, extract_cohort)

START = "2026-08-10T00:00:00+00:00"


def signal_row(**overrides):
    base = dict(
        source="actionable_alert",
        policy_version="v3.1",
        event_id="evt-1",
        detected_at="2026-08-11T04:00:00+00:00",
        triggered_at="2026-08-11T06:00:00+00:00",
        market_source="binance_usdm_public",
        symbol="BTCUSDT",
        direction="LONG",
        outcome="target",
        result_R=1.5,
        baseline_R=1.0,
        edge_R=0.5,
    )
    base.update(overrides)
    return base


def paired_event(edge, symbol="BTCUSDT", direction="LONG", day_offset=0):
    import datetime as dt
    return {"edge": edge, "symbol": symbol, "direction": direction,
            "day": dt.date(2026, 8, 11) + dt.timedelta(days=day_offset)}


def balanced_cohort(edge_value, n=45):
    """n подій, рівномірно по 3 символах, обох напрямках і 15 днях."""
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    events = []
    for i in range(n):
        events.append(paired_event(
            edge_value if not callable(edge_value) else edge_value(i),
            symbol=symbols[i % 3],
            direction="LONG" if i % 2 == 0 else "SHORT",
            day_offset=i % 15,
        ))
    cohort = Cohort(measurement_start=None)
    cohort.paired = events
    return cohort


class ExtractorTests(unittest.TestCase):
    def test_inclusion_rules(self):
        rows = [
            signal_row(),                                            # paired terminal
            signal_row(policy_version="", event_id="legacy"),        # legacy
            signal_row(policy_version="v3"),                         # стара версія
            signal_row(detected_at="2026-08-09T23:00:00+00:00"),     # до старту
            signal_row(market_source=""),                            # без provenance
            signal_row(source="market_brief"),                       # не actionable
            signal_row(outcome="not_activated"),                     # не підтвердився
            signal_row(outcome=""),                                  # pending
            signal_row(outcome="not_enough_data"),                   # pending
            signal_row(outcome="no_result"),                         # timed out (paired)
            signal_row(outcome="stop", baseline_R=None),             # unpaired terminal
        ]
        cohort = extract_cohort(rows, START)
        self.assertEqual(cohort.populations["paired_terminal"], 2)
        self.assertEqual(cohort.populations["barrier_resolved"], 2)
        self.assertEqual(cohort.populations["timed_out"], 1)
        self.assertEqual(cohort.populations["terminal"], 3)
        self.assertEqual(cohort.populations["unpaired_terminal"], 1)
        self.assertEqual(cohort.populations["pending"], 2)
        self.assertEqual(cohort.populations["not_activated"], 1)
        self.assertEqual(cohort.excluded["legacy_or_wrong_version"], 2)
        self.assertEqual(cohort.excluded["before_start"], 1)
        self.assertEqual(cohort.excluded["missing_provenance"], 1)
        self.assertEqual(cohort.excluded["not_actionable"], 1)

    def test_edge_recomputed_and_mismatch_flagged(self):
        rows = [signal_row(edge_R=0.9)]   # збережений edge бреше
        cohort = extract_cohort(rows, START)
        self.assertEqual(cohort.edge_mismatches, 1)
        self.assertAlmostEqual(cohort.paired[0]["edge"], 0.5)


class BootstrapTests(unittest.TestCase):
    def test_constant_edges_give_degenerate_ci(self):
        events = [paired_event(0.5, day_offset=i) for i in range(20)]
        boot = block_bootstrap_ci(events, n_replicas=500)
        self.assertAlmostEqual(boot["point"], 0.5)
        self.assertAlmostEqual(boot["ci"][0], 0.5, places=9)
        self.assertAlmostEqual(boot["ci"][1], 0.5, places=9)

    def test_deterministic_with_seed(self):
        events = [paired_event(0.1 * ((i % 7) - 3), day_offset=i % 20) for i in range(60)]
        a = block_bootstrap_ci(events, n_replicas=2000)
        b = block_bootstrap_ci(events, n_replicas=2000)
        self.assertEqual(a["ci"], b["ci"])
        self.assertEqual(a["replicas"], 2000)


class VerdictTests(unittest.TestCase):
    def test_insufficient_below_min_n(self):
        cohort = balanced_cohort(0.5, n=MIN_N - 1)
        result = confirmatory_verdict(cohort, n_replicas=300)
        self.assertEqual(result["verdict"], "insufficient_data")

    def test_passed_when_positive_and_balanced(self):
        cohort = balanced_cohort(lambda i: 0.3 + 0.01 * (i % 5), n=45)
        result = confirmatory_verdict(cohort, n_replicas=1000)
        self.assertEqual(result["verdict"], "passed")

    def test_closed_when_clearly_negative(self):
        cohort = balanced_cohort(lambda i: -0.3 - 0.01 * (i % 5), n=45)
        result = confirmatory_verdict(cohort, n_replicas=1000)
        self.assertEqual(result["verdict"], "closed")

    def test_positive_ci_but_one_sided_directions_is_inconclusive(self):
        events = [paired_event(0.4, symbol=["BTCUSDT", "ETHUSDT", "SOLUSDT"][i % 3],
                               direction="LONG", day_offset=i % 12) for i in range(45)]
        cohort = Cohort(measurement_start=None)
        cohort.paired = events
        result = confirmatory_verdict(cohort, n_replicas=1000)
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertFalse(result["checks"]["n_SHORT"][0])

    def test_report_contains_populations_and_verdict(self):
        rows = [signal_row(event_id=f"evt-{i}", symbol=["BTCUSDT", "ETHUSDT", "SOLUSDT"][i % 3],
                           direction="LONG" if i % 2 == 0 else "SHORT",
                           triggered_at=f"2026-08-{11 + i % 15:02d}T06:00:00+00:00")
                for i in range(40)]
        cohort = extract_cohort(rows, START)
        result = confirmatory_verdict(cohort, n_replicas=300)
        text = build_report(cohort, result, analyzer_sha="abc1234")
        self.assertIn("paired_terminal: 40", text)
        self.assertIn("Вердикт", text)
        self.assertIn("abc1234", text)


if __name__ == "__main__":
    unittest.main()
