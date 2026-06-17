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
        targets_json = json.dumps(signal.targets)
        if _signal_exists(connection, signal, targets_json):
            return False

        connection.execute(
            """
            INSERT INTO signals (
                created_at, symbol, interval, direction, market_regime, close_price,
                funding_rate, open_interest, long_short_ratio, spread_pct, entry_zone, stop, targets_json,
                risk_reward, confidence, invalidation, reasons_json,
                trailing_plan, pattern, setup_score, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                signal.risk_reward,
                signal.confidence,
                signal.invalidation,
                json.dumps(signal.reasons),
                signal.trailing_plan,
                signal.pattern,
                signal.setup_score,
                signal.source,
            ),
        )
        connection.commit()
        return True
    finally:
        connection.close()


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
            SELECT id, created_at, symbol, interval, direction, close_price, stop, targets_json
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
                   targets_json, risk_reward, confidence, invalidation, reasons_json,
                   evaluated_at, outcome, max_favorable_price, max_adverse_price,
                   trailing_plan, pattern, setup_score, source,
                   result_R, baseline_R, edge_R
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

        return {
            "signals": total,
            "long": direction_counts.get("LONG", 0),
            "short": direction_counts.get("SHORT", 0),
            "no_trade": direction_counts.get("NO TRADE", 0),
            "pending": pending,
            "target_hit": target_hit,
            "stop_hit": stop_hit,
            "no_result": outcome_counts.get("no_result", 0),
            "win_rate": target_hit / resolved if resolved else None,
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
) -> None:
    connection = sqlite3.connect(Path(db_path))
    try:
        ensure_schema(connection)
        connection.execute(
            """
            UPDATE signals
            SET evaluated_at = ?,
                outcome = ?,
                max_favorable_price = ?,
                max_adverse_price = ?,
                result_R = ?,
                baseline_R = ?,
                edge_R = ?
            WHERE id = ?
            """,
            (
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
            risk_reward REAL,
            confidence TEXT NOT NULL,
            invalidation TEXT NOT NULL,
            reasons_json TEXT NOT NULL,
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
            edge_R REAL
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
}


def _decode_signal_row(row: sqlite3.Row) -> dict[str, object]:
    data = dict(row)
    data["targets"] = json.loads(str(data["targets_json"]))
    data["reasons"] = json.loads(str(data["reasons_json"]))
    return data


def _signal_exists(connection: sqlite3.Connection, signal: Signal, targets_json: str) -> bool:
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
        "win_rate": None,
    }
