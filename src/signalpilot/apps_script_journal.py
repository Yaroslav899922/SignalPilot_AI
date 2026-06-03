from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from .signals import Signal


API_URL_ENV = "SIGNALPILOT_JOURNAL_API_URL"
API_TOKEN_ENV = "SIGNALPILOT_JOURNAL_API_TOKEN"


def save_signal(signal: Signal, db_path: str | object = "") -> bool:
    payload = _request("save_signal", {"signal": signal.to_dict()})
    return bool(payload.get("inserted", True))


def load_evaluable_signals(db_path: str | object = "") -> list[dict[str, object]]:
    payload = _request("load_evaluable_signals", {})
    signals = payload.get("signals", [])
    return signals if isinstance(signals, list) else []


def update_signal_evaluation(
    db_path: str | object,
    signal_id: int,
    outcome: str,
    max_favorable_price: float | None,
    max_adverse_price: float | None,
    evaluated_at: str | None = None,
) -> None:
    _request(
        "update_signal_evaluation",
        {
            "signal_id": signal_id,
            "outcome": outcome,
            "max_favorable_price": max_favorable_price,
            "max_adverse_price": max_adverse_price,
            "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
        },
    )


def summarize_journal(db_path: str | object = "") -> dict[str, object]:
    payload = _request("summarize_journal", {})
    summary = payload.get("summary", {})
    return summary if isinstance(summary, dict) else {}


def _request(action: str, body: dict[str, object]) -> dict[str, object]:
    api_url = os.environ.get(API_URL_ENV)
    api_token = os.environ.get(API_TOKEN_ENV)
    if not api_url or not api_token:
        raise RuntimeError(f"{API_URL_ENV} and {API_TOKEN_ENV} must be set for apps_script journal backend")

    payload = {"action": action, "token": api_token, **body}
    request = Request(
        url=api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    if not isinstance(data, dict):
        raise RuntimeError("Apps Script journal API returned a non-object response")
    if data.get("ok") is False:
        raise RuntimeError(str(data.get("error", "Apps Script journal API request failed")))
    return data
