from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from urllib.request import urlopen

from .actionable import ActionableSetup
from .apps_script_api import API_TOKEN_ENV, API_URL_ENV, request as api_request
from .signals import Signal



def save_signal(signal: Signal, db_path: str | object = "") -> bool:
    payload = _request("save_signal", {"signal": signal.to_dict()})
    return _required_bool(payload, "inserted")


def load_evaluable_signals(db_path: str | object = "") -> list[dict[str, object]]:
    payload = _request("load_evaluable_signals", {})
    return _required_dict_list(payload, "signals")


def update_signal_evaluation(
    db_path: str | object,
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
    payload = _request(
        "update_signal_evaluation",
        {
            "signal_id": signal_id,
            "outcome": outcome,
            "max_favorable_price": max_favorable_price,
            "max_adverse_price": max_adverse_price,
            "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
            "result_R": result_R,
            "baseline_R": baseline_R,
            "edge_R": edge_R,
            "activated_at": activated_at,
        },
    )
    if not _required_bool(payload, "updated"):
        raise RuntimeError("Apps Script journal API did not update the requested signal")


def summarize_journal(db_path: str | object = "") -> dict[str, object]:
    payload = _request("summarize_journal", {})
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError("Apps Script journal API response field 'summary' must be an object")
    return summary


def save_setup_event(setup: ActionableSetup, db_path: str | object = "") -> bool:
    payload = _request("save_setup_event", {"setup": setup.to_dict(), "fingerprint": setup.fingerprint})
    return _required_bool(payload, "inserted")


def save_triggered_event(
    setup: ActionableSetup,
    signal: Signal,
    db_path: str | object = "",
) -> tuple[bool, bool]:
    payload = _request(
        "save_triggered_event",
        {
            "setup": setup.to_dict(),
            "signal": signal.to_dict(),
            "fingerprint": setup.fingerprint,
        },
    )
    return (
        _required_bool(payload, "signal_inserted"),
        _required_bool(payload, "setup_inserted"),
    )


def load_latest_setups(db_path: str | object = "") -> list[ActionableSetup]:
    payload = _request("load_latest_setups", {})
    rows = _required_dict_list(payload, "setups")
    return [ActionableSetup.from_dict(row) for row in rows]


def _request(action: str, body: dict[str, object]) -> dict[str, object]:
    return api_request(
        action,
        body,
        opener=urlopen,
        sleeper=time.sleep,
        environ=os.environ,
    )


def _required_bool(payload: dict[str, object], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise RuntimeError(f"Apps Script journal API response field '{field}' must be boolean")
    return value


def _required_dict_list(payload: dict[str, object], field: str) -> list[dict[str, object]]:
    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RuntimeError(
            f"Apps Script journal API response field '{field}' must be a list of objects"
        )
    return value
