from __future__ import annotations

import os
from pathlib import Path

from . import apps_script_journal, setup_journal
from .actionable import ActionableSetup
from .journal_backend import APPS_SCRIPT_BACKEND, BACKEND_ENV, SQLITE_BACKEND
from .signals import Signal


def save_setup_event(setup: ActionableSetup, db_path: str | Path) -> bool:
    backend = _backend_name()
    if backend == SQLITE_BACKEND:
        return setup_journal.save_setup_event(setup, db_path)
    if backend == APPS_SCRIPT_BACKEND:
        return apps_script_journal.save_setup_event(setup, db_path)
    raise RuntimeError(f"Unsupported {BACKEND_ENV}: {backend}")


def save_triggered_event(
    setup: ActionableSetup,
    signal: Signal,
    db_path: str | Path,
) -> tuple[bool, bool]:
    backend = _backend_name()
    if backend == SQLITE_BACKEND:
        return setup_journal.save_triggered_event(setup, signal, db_path)
    if backend == APPS_SCRIPT_BACKEND:
        return apps_script_journal.save_triggered_event(setup, signal, db_path)
    raise RuntimeError(f"Unsupported {BACKEND_ENV}: {backend}")


def load_latest_setups(db_path: str | Path) -> list[ActionableSetup]:
    backend = _backend_name()
    if backend == SQLITE_BACKEND:
        return setup_journal.load_latest_setups(db_path)
    if backend == APPS_SCRIPT_BACKEND:
        return apps_script_journal.load_latest_setups(db_path)
    raise RuntimeError(f"Unsupported {BACKEND_ENV}: {backend}")


def _backend_name() -> str:
    return os.environ.get(BACKEND_ENV, SQLITE_BACKEND).strip().lower() or SQLITE_BACKEND
