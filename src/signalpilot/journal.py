from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .signals import Signal


def save_signal(signal: Signal, db_path: str | Path) -> bool:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    try:
        ensure_schema(connection)
        inserted = _save_signal_on_connection(connection, signal)
        connection.commit()
        return inserted
    finally:
        connection.close()


def _save_signal_on_connection(connection: sqlite3.Connection, signal: Signal) -> bool:
    targets_json = json.dumps(signal.targets)
    if _signal_exists(connection, signal, targets_json):
        return False

    connection.execute(
        """
        INSERT INTO signals (
            created_at, symbol, interval, direction, market_regime, close_price,
            funding_rate, open_interest, long_short_ratio, spread_pct, entry_zone, stop, targets_json,
            entry_low, entry_high, risk_reward, confidence, invalidation, reasons_json,
            trailing_plan, pattern, setup_score, source, setup_id, setup_status, expires_at,
            event_id, policy_version, detected_at, triggered_at, market_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal.created_at,
            signal.symbol,
            signal.interval,
            signal.direction,
            signal.market_regime,
            signal.close_price,
            signal.funding_rate,
            signal.open_interest,
            signal.long_short_ratio,
            signal.spread_pct,
            signal.entry_zone,
            signal.stop,
            targets_json,
            signal.entry_low,
            signal.entry_high,
            signal.risk_reward,
            signal.confidence,
            signal.invalidation,
            json.dumps(signal.reasons),
            signal.trailing_plan,
            signal.pattern,
            signal.setup_score,
            signal.source,
            signal.setup_id,
            signal.setup_status,
            signal.expires_at,
            signal.event_id,
            signal.policy_version,
            signal.detected_at,
            signal.triggered_at,
            signal.market_source,
        ),
    )
    return True


def load_evaluable_signals(db_path: str | Path) -> list[dict[str, object]]:
    path = Path(db_path)
    if not path.exists():
        return []

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT id, created_at, symbol, interval, direction, close_price, entry_low, entry_high,
                   stop, targets_json, source, expires_at, event_id, policy_version,
                   detected_at, triggered_at, market_source
            FROM signals
            WHERE direction IN ('LONG', 'SHORT')
              AND (outcome IS NULL OR outcome = 'not_enough_data')
            ORDER BY created_at ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def load_signal_rows(db_path: str | Path, limit: int = 500) -> list[dict[str, object]]:
    path = Path(db_path)
    if not path.exists():
        return []

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT id, created_at, symbol, interval, direction, market_regime, close_price,
                   funding_rate, open_interest, long_short_ratio, spread_pct, entry_zone, stop,
                   targets_json, entry_low, entry_high, risk_reward, confidence, invalidation, reasons_json,
                   activated_at, evaluated_at, outcome, max_favorable_price, max_adverse_price,
                   trailing_plan, pattern, setup_score, source,
                   result_R, baseline_R, edge_R, setup_id, setup_status, expires_at,
                   event_id, policy_version, detected_at, triggered_at, market_source
            FROM signals
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_decode_signal_row(row) for row in rows]
    finally:
        connection.close()


def summarize_journal(db_path: str | Path) -> dict[str, object]:
    path = Path(db_path)
    if not path.exists():
        return _empty_summary()

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        ensure_schema(connection)
        total = int(connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0])
        if total == 0:
            return _empty_summary()

        direction_counts = _counts_by_column(connection, "direction")
        outcome_counts = _counts_by_column(connection, "outcome")
        pending = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM signals
                WHERE direction IN ('LONG', 'SHORT')
                  AND (outcome IS NULL OR outcome = 'not_enough_data')
                """
            ).fetchone()[0]
        )
        target_hit = outcome_counts.get("target_hit", 0)
        stop_hit = outcome_counts.get("stop_hit", 0)
        resolved = target_hit + stop_hit
        actionable_rows = connection.execute(
            """
            SELECT direction, outcome, result_R, baseline_R, edge_R
            FROM signals
            WHERE source = 'actionable_alert'
            """
        ).fetchall()
        actionable_target = sum(row["outcome"] == "target_hit" for row in actionable_rows)
        actionable_stop = sum(row["outcome"] == "stop_hit" for row in actionable_rows)
        actionable_resolved = actionable_target + actionable_stop
        barrier_rows = [
            row for row in actionable_rows if row["outcome"] in ("target_hit", "stop_hit")
        ]
        timeout_rows = [row for row in actionable_rows if row["outcome"] == "no_result"]
        terminal_rows = barrier_rows + timeout_rows
        paired_rows = [
            row
            for row in terminal_rows
            if row["result_R"] is not None and row["baseline_R"] is not None
        ]
        barrier_paired = [row for row in paired_rows if row["outcome"] in ("target_hit", "stop_hit")]
        timeout_paired = [row for row in paired_rows if row["outcome"] == "no_result"]
        actionable_pending = sum(
            row["direction"] in ("LONG", "SHORT")
            and (row["outcome"] is None or row["outcome"] == "not_enough_data")
            for row in actionable_rows
        )
        legacy_market_brief = int(
            connection.execute("SELECT COUNT(*) FROM signals WHERE source = 'market_brief'").fetchone()[0]
        )

        return {
            "signals": total,
            "long": direction_counts.get("LONG", 0),
            "short": direction_counts.get("SHORT", 0),
            "no_trade": direction_counts.get("NO TRADE", 0),
            "pending": pending,
            "target_hit": target_hit,
            "stop_hit": stop_hit,
            "no_result": outcome_counts.get("no_result", 0),
            "not_activated": outcome_counts.get("not_activated", 0),
            "win_rate": target_hit / resolved if resolved else None,
            "confirmed_entries": len(actionable_rows),
            "confirmed_pending": actionable_pending,
            "confirmed_target_hit": actionable_target,
            "confirmed_stop_hit": actionable_stop,
            "confirmed_barrier_resolved": actionable_resolved,
            "confirmed_timed_out": len(timeout_rows),
            "confirmed_terminal": len(terminal_rows),
            "confirmed_no_result": len(timeout_rows),
            "confirmed_unpaired_terminal": len(terminal_rows) - len(paired_rows),
            "confirmed_win_rate": actionable_target / actionable_resolved if actionable_resolved else None,
            "confirmed_barrier_result_R": _sum_optional(barrier_rows, "result_R"),
            "confirmed_timed_out_result_R": _sum_optional(timeout_rows, "result_R"),
            "confirmed_barrier_paired_n": len(barrier_paired),
            "confirmed_timed_out_paired_n": len(timeout_paired),
            "confirmed_paired_n": len(paired_rows),
            "confirmed_paired_result_R": _sum_optional(paired_rows, "result_R"),
            "confirmed_paired_baseline_R": _sum_optional(paired_rows, "baseline_R"),
            "confirmed_paired_edge_R": _sum_paired_edge(paired_rows),
            # Compatibility aliases retain their historical populations for one cycle.
            "confirmed_result_R": _sum_optional(actionable_rows, "result_R"),
            "confirmed_baseline_R": _sum_optional(actionable_rows, "baseline_R"),
            "confirmed_edge_R": _sum_optional(actionable_rows, "edge_R"),
            "legacy_market_brief_rows": legacy_market_brief,
        }
    finally:
        connection.close()


def update_signal_evaluation(
    db_path: str | Path,
    signal_id: int,
    outcome: str,
    max_favorable_price: float | None,
    max_adverse_price: float | None,
    evaluated_at: str | None = None,
    result_R: float | None = None,
    baseline_R: float | None = None,
    edge_R: float | None = None,
    activated_at: str | None = None,
) -> None:
    connection = sqlite3.connect(Path(db_path))
    try:
        ensure_schema(connection)
        connection.execute(
            """
            UPDATE signals
            SET activated_at = ?,
                evaluated_at = ?,
                outcome = ?,
                max_favorable_price = ?,
                max_adverse_price = ?,
                result_R = ?,
                baseline_R = ?,
                edge_R = ?
            WHERE id = ?
            """,
            (
                activated_at,
                evaluated_at or datetime.now(timezone.utc).isoformat(),
                outcome,
                max_favorable_price,
                max_adverse_price,
                result_R,
                baseline_R,
                edge_R,
                signal_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            direction TEXT NOT NULL,
            market_regime TEXT NOT NULL,
            close_price REAL,
            funding_rate REAL,
            open_interest REAL,
            long_short_ratio REAL,
            spread_pct REAL,
            entry_zone TEXT NOT NULL,
            stop REAL,
            targets_json TEXT NOT NULL,
            entry_low REAL,
            entry_high REAL,
            risk_reward REAL,
            confidence TEXT NOT NULL,
            invalidation TEXT NOT NULL,
            reasons_json TEXT NOT NULL,
            activated_at TEXT,
            evaluated_at TEXT,
            outcome TEXT,
            max_favorable_price REAL,
            max_adverse_price REAL,
            trailing_plan TEXT NOT NULL DEFAULT '',
            pattern TEXT NOT NULL DEFAULT '',
            setup_score REAL,
            source TEXT NOT NULL DEFAULT 'signalpilot',
            result_R REAL,
            baseline_R REAL,
            edge_R REAL,
            setup_id TEXT NOT NULL DEFAULT '',
            setup_status TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL DEFAULT '',
            event_id TEXT NOT NULL DEFAULT '',
            policy_version TEXT NOT NULL DEFAULT 'legacy_unversioned',
            detected_at TEXT NOT NULL DEFAULT '',
            triggered_at TEXT NOT NULL DEFAULT '',
            market_source TEXT NOT NULL DEFAULT ''
        )
        """
    )
    existing_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(signals)").fetchall()
    }
    for column_name, column_definition in _ADDED_COLUMNS.items():
        if column_name not in existing_columns:
            connection.execute(f"ALTER TABLE signals ADD COLUMN {column_definition}")


_ADDED_COLUMNS = {
    "market_regime": "market_regime TEXT NOT NULL DEFAULT 'unknown'",
    "close_price": "close_price REAL",
    "funding_rate": "funding_rate REAL",
    "open_interest": "open_interest REAL",
    "long_short_ratio": "long_short_ratio REAL",
    "spread_pct": "spread_pct REAL",
    "entry_low": "entry_low REAL",
    "entry_high": "entry_high REAL",
    "activated_at": "activated_at TEXT",
    "evaluated_at": "evaluated_at TEXT",
    "outcome": "outcome TEXT",
    "max_favorable_price": "max_favorable_price REAL",
    "max_adverse_price": "max_adverse_price REAL",
    "trailing_plan": "trailing_plan TEXT NOT NULL DEFAULT ''",
    "pattern": "pattern TEXT NOT NULL DEFAULT ''",
    "setup_score": "setup_score REAL",
    "source": "source TEXT NOT NULL DEFAULT 'signalpilot'",
    "result_R": "result_R REAL",
    "baseline_R": "baseline_R REAL",
    "edge_R": "edge_R REAL",
    "setup_id": "setup_id TEXT NOT NULL DEFAULT ''",
    "setup_status": "setup_status TEXT NOT NULL DEFAULT ''",
    "expires_at": "expires_at TEXT NOT NULL DEFAULT ''",
    "event_id": "event_id TEXT NOT NULL DEFAULT ''",
    "policy_version": "policy_version TEXT NOT NULL DEFAULT 'legacy_unversioned'",
    "detected_at": "detected_at TEXT NOT NULL DEFAULT ''",
    "triggered_at": "triggered_at TEXT NOT NULL DEFAULT ''",
    "market_source": "market_source TEXT NOT NULL DEFAULT ''",
}


def _decode_signal_row(row: sqlite3.Row) -> dict[str, object]:
    data = dict(row)
    data["targets"] = json.loads(str(data["targets_json"]))
    data["reasons"] = json.loads(str(data["reasons_json"]))
    return data


def _signal_exists(connection: sqlite3.Connection, signal: Signal, targets_json: str) -> bool:
    if signal.event_id:
        row = connection.execute(
            """
            SELECT 1
            FROM signals
            WHERE COALESCE(NULLIF(event_id, ''), setup_id) = ?
            LIMIT 1
            """,
            (signal.event_id,),
        ).fetchone()
        return row is not None
    if signal.setup_id:
        row = connection.execute(
            "SELECT 1 FROM signals WHERE setup_id = ? LIMIT 1",
            (signal.setup_id,),
        ).fetchone()
        return row is not None
    if signal.source == "market_brief":
        row = connection.execute(
            """
            SELECT 1
            FROM signals
            WHERE symbol = ?
              AND created_at = ?
              AND interval = ?
              AND direction = ?
              AND (close_price = ? OR (close_price IS NULL AND ? IS NULL))
              AND entry_zone = ?
              AND (stop = ? OR (stop IS NULL AND ? IS NULL))
              AND targets_json = ?
              AND pattern = ?
            LIMIT 1
            """,
            (
                signal.symbol,
                signal.created_at,
                signal.interval,
                signal.direction,
                signal.close_price,
                signal.close_price,
                signal.entry_zone,
                signal.stop,
                signal.stop,
                targets_json,
                signal.pattern,
            ),
        ).fetchone()
        return row is not None
    row = connection.execute(
        """
        SELECT 1
        FROM signals
        WHERE symbol = ?
          AND interval = ?
          AND direction = ?
          AND (close_price = ? OR (close_price IS NULL AND ? IS NULL))
          AND entry_zone = ?
          AND (stop = ? OR (stop IS NULL AND ? IS NULL))
          AND targets_json = ?
          AND pattern = ?
        LIMIT 1
        """,
        (
            signal.symbol,
            signal.interval,
            signal.direction,
            signal.close_price,
            signal.close_price,
            signal.entry_zone,
            signal.stop,
            signal.stop,
            targets_json,
            signal.pattern,
        ),
    ).fetchone()
    return row is not None


def _counts_by_column(connection: sqlite3.Connection, column: str) -> dict[str, int]:
    rows = connection.execute(
        f"""
        SELECT {column} AS value, COUNT(*) AS count
        FROM signals
        WHERE {column} IS NOT NULL
        GROUP BY {column}
        """
    ).fetchall()
    return {str(row["value"]): int(row["count"]) for row in rows}


def _empty_summary() -> dict[str, object]:
    return {
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
    }


def _sum_optional(rows: list[sqlite3.Row], column: str) -> float | None:
    values = [float(row[column]) for row in rows if row[column] is not None]
    return round(sum(values), 4) if values else None


def _sum_paired_edge(rows: list[sqlite3.Row]) -> float | None:
    if not rows:
        return None
    return round(
        sum(float(row["result_R"]) - float(row["baseline_R"]) for row in rows),
        4,
    )
