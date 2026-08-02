"""Тести нового шару повідомлень: ПЛАН ОНОВЛЕНО, контекст ринку, змішаний чекліст."""

import unittest
from datetime import datetime, timezone

from signalpilot.actionable import (
    ARMED,
    INVALIDATED,
    WATCH,
    ActionableSetup,
    SetupCondition,
    compose_setup_messages,
    format_direction_change_message,
    format_setup_message,
    format_update_message,
    market_context_line,
    reconcile_setup_state,
    _short_checklist_line,
)


def make_setup(**overrides):
    base = dict(
        setup_id="ETHUSDT-breakout_retest-SHORT-abc",
        symbol="ETHUSDT",
        pattern="breakout_retest",
        direction="SHORT",
        status=ARMED,
        regime="downtrend",
        current_price=1863.0,
        trigger_level=1865.0,
        entry_low=1862.0,
        entry_high=1866.0,
        stop=1874.0,
        targets=(1850.0, 1840.0),
        risk_reward=1.5,
        score=80.0,
        action="Поки не входити.",
        reason="Ціна повертається до робочої зони.",
        invalidation="1h закриється вище $1,874",
        conditions=(
            SetupCondition("level_break", "1h закрилася за ключовим рівнем", True),
            SetupCondition("retest", "Повернення до рівня втрималося", True),
            SetupCondition("momentum", "Сила руху (MACD)", False),
            SetupCondition("not_chasing", "Ціна ще в допустимій зоні входу", False),
        ),
        created_at="2026-08-02T15:00:00+00:00",
        expires_at="2026-08-03T03:00:00+00:00",
    )
    base.update(overrides)
    return ActionableSetup(**base)


class MarketContextTests(unittest.TestCase):
    def test_all_three_agree(self):
        regimes = {"BTCUSDT": "downtrend", "ETHUSDT": "downtrend", "SOLUSDT": "downtrend"}
        self.assertEqual(market_context_line(regimes, "SOLUSDT"), "SOL, BTC і ETH в один бік")

    def test_partial_agreement(self):
        regimes = {"BTCUSDT": "downtrend", "ETHUSDT": "downtrend", "SOLUSDT": "range"}
        line = market_context_line(regimes, "ETHUSDT")
        self.assertEqual(line, "BTC теж вниз")

    def test_opposition_warns(self):
        regimes = {"BTCUSDT": "uptrend", "ETHUSDT": "downtrend"}
        self.assertEqual(market_context_line(regimes, "ETHUSDT"), "але BTC вгору — обережніше")

    def test_no_direction(self):
        regimes = {"BTCUSDT": "range", "ETHUSDT": "compression"}
        self.assertEqual(market_context_line(regimes, "ETHUSDT"), "ринок без єдиного напрямку")


class ChecklistTests(unittest.TestCase):
    def test_short_checklist_names_missing_checks(self):
        line = _short_checklist_line(make_setup())
        self.assertIn("Готовність:</b> 2 з 4", line)
        self.assertIn("MACD", line)
        self.assertIn("підхід ціни", line)

    def test_full_message_keeps_all_rows_and_context(self):
        text = format_setup_message(make_setup(), market_context="BTC теж вниз")
        self.assertIn("Перевірки (2/4):", text)
        self.assertIn("· BTC теж вниз", text)

    def test_terminal_message_has_no_checklist(self):
        cancelled = make_setup(status=INVALIDATED)
        text = format_setup_message(cancelled)
        self.assertIn("ПЛАН СКАСОВАНО", text)
        self.assertNotIn("Перевірки", text)


class UpdateMessageTests(unittest.TestCase):
    def test_update_message_shows_both_levels_and_short_checklist(self):
        old = make_setup()
        new = make_setup(trigger_level=1857.0, entry_low=1850.0, entry_high=1857.0)
        text = format_update_message(old, new)
        self.assertIn("ПЛАН ОНОВЛЕНО", text)
        self.assertIn("1,865", text)
        self.assertIn("1,857", text)
        self.assertIn("без змін", text)
        self.assertIn("Готовність:", text)
        self.assertNotIn("Перевірки (", text)

    def test_direction_change_message_shows_full_checklist(self):
        old = make_setup()
        new = make_setup(direction="LONG", trigger_level=1880.0)
        text = format_direction_change_message(old, new)
        self.assertIn("НАПРЯМОК ЗМІНИВСЯ", text)
        self.assertIn("Було:", text)
        self.assertIn("Перевірки (", text)


class ComposeTests(unittest.TestCase):
    def test_pair_becomes_single_update(self):
        old = make_setup(status=INVALIDATED)
        new = make_setup(trigger_level=1857.0)
        msgs = compose_setup_messages([(old, True), (new, True)])
        self.assertEqual(len(msgs), 1)
        self.assertIn("ПЛАН ОНОВЛЕНО", msgs[0])

    def test_pair_with_new_direction_becomes_change_message(self):
        old = make_setup(status=INVALIDATED)
        new = make_setup(direction="LONG")
        msgs = compose_setup_messages([(old, True), (new, True)])
        self.assertEqual(len(msgs), 1)
        self.assertIn("НАПРЯМОК ЗМІНИВСЯ", msgs[0])

    def test_quiet_replacement_still_cancels_old_plan(self):
        old = make_setup(status=INVALIDATED)
        new = make_setup(status=WATCH, score=10.0)
        msgs = compose_setup_messages([(old, True), (new, False)])
        self.assertEqual(len(msgs), 1)
        self.assertIn("ПЛАН СКАСОВАНО", msgs[0])

    def test_single_events_flow_through(self):
        msgs = compose_setup_messages([(make_setup(), True), (make_setup(symbol="SOLUSDT"), False)])
        self.assertEqual(len(msgs), 1)


class ReconcileTextTests(unittest.TestCase):
    def test_replacement_pair_gets_concrete_reason(self):
        now = datetime(2026, 8, 2, 16, 0, tzinfo=timezone.utc)
        previous = make_setup(status=ARMED)
        candidate = make_setup(
            setup_id="ETHUSDT-breakout_retest-SHORT-def",
            event_id="new-event",
            trigger_level=1857.0,
        )
        from types import SimpleNamespace

        market = SimpleNamespace(symbol="ETHUSDT")
        events = reconcile_setup_state(candidate, [previous], market, now_utc=now)
        self.assertEqual(len(events), 2)
        cancelled = events[0]
        self.assertEqual(cancelled.status, INVALIDATED)
        self.assertIn("1,865", cancelled.reason)
        self.assertIn("1,857", cancelled.reason)
        self.assertNotIn("Система знайшла новий сценарій", cancelled.reason)


if __name__ == "__main__":
    unittest.main()
