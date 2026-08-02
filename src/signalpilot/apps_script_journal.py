from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .signals import Signal
from .actionable import ActionableSetup


API_URL_ENV = "SIGNALPILOT_JOURNAL_API_URL"
API_TOKEN_ENV = "SIGNALPILOT_JOURNAL_API_TOKEN"
MAX_REQUEST_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 0.5


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
    api_url = os.environ.get(API_URL_ENV)
    api_token = os.environ.get(API_TOKEN_ENV)
    if not api_url or not api_token:
        raise RuntimeError(f"{API_URL_ENV} and {API_TOKEN_ENV} must be set for apps_script journal backend")

    payload = {"action": action, "token": api_token, **body}
    encoded_payload = json.dumps(payload).encode("utf-8")
    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        request = Request(
            url=api_url,
            data=encoded_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw_response = response.read()
        except HTTPError as error:
            if _retryable_http_status(error.code) and attempt < MAX_REQUEST_ATTEMPTS:
                _wait_before_retry(attempt)
                continue
            raise RuntimeError(f"Apps Script journal API HTTP {error.code}") from error
        except (TimeoutError, URLError) as error:
            if attempt < MAX_REQUEST_ATTEMPTS:
                _wait_before_retry(attempt)
                continue
            raise RuntimeError("Apps Script journal API network request failed") from error

        try:
            data = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("Apps Script journal API returned invalid JSON") from error
        if not isinstance(data, dict):
            raise RuntimeError("Apps Script journal API returned a non-object response")
        if data.get("ok") is not True:
            message = str(data.get("error", "response must contain ok=true"))
            if data.get("retryable") is True and attempt < MAX_REQUEST_ATTEMPTS:
                _wait_before_retry(attempt)
                continue
            raise RuntimeError(message)
        return data

    raise RuntimeError("Apps Script journal API request failed after retries")


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


def _retryable_http_status(status_code: int) -> bool:
    return status_code in {408, 429} or 500 <= status_code < 600


def _wait_before_retry(attempt: int) -> None:
    time.sleep(RETRY_DELAY_SECONDS * attempt)
