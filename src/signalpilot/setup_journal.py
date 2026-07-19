from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .actionable import ACTIVE_STATUSES, ActionableSetup


def save_setup_event(setup: ActionableSetup, db_path: str | Path) -> bool:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        ensure_schema(connection)
        latest = connection.execute(
            """
            SELECT status, fingerprint FROM setup_events
            WHERE setup_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (setup.setup_id,),
        ).fetchone()
        if latest is not None and latest[0] == setup.status and latest[1] == setup.fingerprint:
            return False
        connection.execute(
            """
            INSERT INTO setup_events (
                setup_id, symbol, pattern, direction, status, regime, current_price,
                trigger_level, entry_low, entry_high, stop, targets_json, risk_reward,
                score, action, reason, invalidation, conditions_json, created_at,
                expires_at, source, fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        connection.commit()
        return True
    finally:
        connection.close()


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
            WHERE id IN (SELECT MAX(id) FROM setup_events GROUP BY setup_id)
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
            fingerprint TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_setup_events_latest
        ON setup_events(setup_id, id)
        """
    )


def _row_to_setup(row: sqlite3.Row) -> ActionableSetup:
    data = dict(row)
    data["targets"] = json.loads(str(data.pop("targets_json")))
    data["conditions"] = json.loads(str(data.pop("conditions_json")))
    data.pop("id", None)
    data.pop("fingerprint", None)
    return ActionableSetup.from_dict(data)
