from __future__ import annotations

import os
from pathlib import Path

from . import apps_script_journal, journal
from .signals import Signal


BACKEND_ENV = "SIGNALPILOT_JOURNAL_BACKEND"
SQLITE_BACKEND = "sqlite"
APPS_SCRIPT_BACKEND = "apps_script"


def save_signal(signal: Signal, db_path: str | Path) -> bool:
    return _backend().save_signal(signal, db_path)


def load_evaluable_signals(db_path: str | Path) -> list[dict[str, object]]:
    return _backend().load_evaluable_signals(db_path)


def update_signal_evaluation(
    db_path: str | Path,
    signal_id: int,
    outcome: str,
    max_favorable_price: float | None,
    max_adverse_price: float | None,
    evaluated_at: str | None = None,
) -> None:
    _backend().update_signal_evaluation(
        db_path=db_path,
        signal_id=signal_id,
        outcome=outcome,
        max_favorable_price=max_favorable_price,
        max_adverse_price=max_adverse_price,
        evaluated_at=evaluated_at,
    )


def summarize_journal(db_path: str | Path) -> dict[str, object]:
    return _backend().summarize_journal(db_path)


def current_backend_name() -> str:
    return os.environ.get(BACKEND_ENV, SQLITE_BACKEND).strip().lower() or SQLITE_BACKEND


def _backend():
    backend_name = current_backend_name()
    if backend_name == SQLITE_BACKEND:
        return journal
    if backend_name == APPS_SCRIPT_BACKEND:
        return apps_script_journal
    raise RuntimeError(f"Unsupported {BACKEND_ENV}: {backend_name}")
