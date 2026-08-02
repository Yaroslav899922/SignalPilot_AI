from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import journal as signal_journal
from .actionable import ACTIVE_STATUSES, ActionableSetup
from .signals import Signal


def save_setup_event(setup: ActionableSetup, db_path: str | Path) -> bool:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        ensure_schema(connection)
        inserted = _save_setup_event_on_connection(connection, setup)
        connection.commit()
        return inserted
    finally:
        connection.close()


def save_triggered_event(
    setup: ActionableSetup,
    signal: Signal,
    db_path: str | Path,
) -> tuple[bool, bool]:
    setup_event_key = setup.event_id or setup.setup_id
    signal_event_key = signal.event_id or signal.setup_id
    if not setup_event_key or setup_event_key != signal_event_key:
        raise ValueError("triggered signal/setup event_id mismatch")
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        signal_journal.ensure_schema(connection)
        ensure_schema(connection)
        signal_inserted = signal_journal._save_signal_on_connection(connection, signal)
        setup_inserted = _save_setup_event_on_connection(connection, setup)
        connection.commit()
        return signal_inserted, setup_inserted
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _save_setup_event_on_connection(
    connection: sqlite3.Connection,
    setup: ActionableSetup,
) -> bool:
    event_key = setup.event_id or setup.setup_id
    exists = connection.execute(
        """
        SELECT 1 FROM setup_events
        WHERE COALESCE(NULLIF(event_id, ''), setup_id) = ?
          AND status = ?
          AND fingerprint = ?
        LIMIT 1
        """,
        (event_key, setup.status, setup.fingerprint),
    ).fetchone()
    if exists is not None:
        return False
    connection.execute(
        """
        INSERT INTO setup_events (
            setup_id, symbol, pattern, direction, status, regime, current_price,
            trigger_level, entry_low, entry_high, stop, targets_json, risk_reward,
            score, action, reason, invalidation, conditions_json, created_at,
            expires_at, source, fingerprint, event_id, policy_version,
            detected_at, triggered_at, market_source, funding_rate, open_interest,
            long_short_ratio, spread_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            setup.setup_id,
            setup.symbol,
            setup.pattern,
            setup.direction,
            setup.status,
            setup.regime,
            setup.current_price,
            setup.trigger_level,
            setup.entry_low,
            setup.entry_high,
            setup.stop,
            json.dumps(setup.targets),
            setup.risk_reward,
            setup.score,
            setup.action,
            setup.reason,
            setup.invalidation,
            json.dumps([condition.to_dict() for condition in setup.conditions], ensure_ascii=False),
            setup.created_at,
            setup.expires_at,
            setup.source,
            setup.fingerprint,
            setup.event_id,
            setup.policy_version,
            setup.detected_at,
            setup.triggered_at,
            setup.market_source,
            setup.funding_rate,
            setup.open_interest,
            setup.long_short_ratio,
            setup.spread_pct,
        ),
    )
    return True


def load_latest_setups(db_path: str | Path) -> list[ActionableSetup]:
    path = Path(db_path)
    if not path.exists():
        return []
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT * FROM setup_events
            WHERE id IN (
                SELECT MAX(id)
                FROM setup_events
                GROUP BY COALESCE(NULLIF(event_id, ''), setup_id)
            )
            ORDER BY id ASC
            """
        ).fetchall()
        return [_row_to_setup(row) for row in rows]
    finally:
        connection.close()


def load_active_setups(db_path: str | Path) -> list[ActionableSetup]:
    return [setup for setup in load_latest_setups(db_path) if setup.status in ACTIVE_STATUSES]


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS setup_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setup_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            pattern TEXT NOT NULL,
            direction TEXT NOT NULL,
            status TEXT NOT NULL,
            regime TEXT NOT NULL,
            current_price REAL NOT NULL,
            trigger_level REAL NOT NULL,
            entry_low REAL NOT NULL,
            entry_high REAL NOT NULL,
            stop REAL NOT NULL,
            targets_json TEXT NOT NULL,
            risk_reward REAL NOT NULL,
            score REAL NOT NULL,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            invalidation TEXT NOT NULL,
            conditions_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            source TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            event_id TEXT NOT NULL DEFAULT '',
            policy_version TEXT NOT NULL DEFAULT 'legacy_unversioned',
            detected_at TEXT NOT NULL DEFAULT '',
            triggered_at TEXT NOT NULL DEFAULT '',
            market_source TEXT NOT NULL DEFAULT '',
            funding_rate REAL,
            open_interest REAL,
            long_short_ratio REAL,
            spread_pct REAL
        )
        """
    )
    existing_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(setup_events)").fetchall()
    }
    for column_name, column_definition in _ADDED_COLUMNS.items():
        if column_name not in existing_columns:
            connection.execute(f"ALTER TABLE setup_events ADD COLUMN {column_definition}")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_setup_events_latest
        ON setup_events(setup_id, id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_setup_events_event_latest
        ON setup_events(event_id, id)
        """
    )


_ADDED_COLUMNS = {
    "event_id": "event_id TEXT NOT NULL DEFAULT ''",
    "policy_version": "policy_version TEXT NOT NULL DEFAULT 'legacy_unversioned'",
    "detected_at": "detected_at TEXT NOT NULL DEFAULT ''",
    "triggered_at": "triggered_at TEXT NOT NULL DEFAULT ''",
    "market_source": "market_source TEXT NOT NULL DEFAULT ''",
    "funding_rate": "funding_rate REAL",
    "open_interest": "open_interest REAL",
    "long_short_ratio": "long_short_ratio REAL",
    "spread_pct": "spread_pct REAL",
}


def _row_to_setup(row: sqlite3.Row) -> ActionableSetup:
    data = dict(row)
    data["targets"] = json.loads(str(data.pop("targets_json")))
    data["conditions"] = json.loads(str(data.pop("conditions_json")))
    data.pop("id", None)
    data.pop("fingerprint", None)
    return ActionableSetup.from_dict(data)
