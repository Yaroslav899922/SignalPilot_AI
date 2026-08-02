from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL_ENV = "SIGNALPILOT_JOURNAL_API_URL"
API_TOKEN_ENV = "SIGNALPILOT_JOURNAL_API_TOKEN"
MAX_REQUEST_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 0.5


def request(
    action: str,
    body: Mapping[str, object],
    *,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], object] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Call the journal web app with strict receipts and bounded retries."""

    environment = os.environ if environ is None else environ
    api_url = environment.get(API_URL_ENV)
    api_token = environment.get(API_TOKEN_ENV)
    if not api_url or not api_token:
        raise RuntimeError(f"{API_URL_ENV} and {API_TOKEN_ENV} must be set")

    open_request = urlopen if opener is None else opener
    sleep = time.sleep if sleeper is None else sleeper
    payload = {**body, "action": action, "token": api_token}
    encoded_payload = json.dumps(payload).encode("utf-8")

    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        http_request = Request(
            url=api_url,
            data=encoded_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with open_request(http_request, timeout=30) as response:
                raw_response = response.read()
        except HTTPError as error:
            if _retryable_http_status(error.code) and attempt < MAX_REQUEST_ATTEMPTS:
                _wait_before_retry(sleep, attempt)
                continue
            raise RuntimeError(f"Apps Script journal API HTTP {error.code}") from error
        except (TimeoutError, URLError) as error:
            if attempt < MAX_REQUEST_ATTEMPTS:
                _wait_before_retry(sleep, attempt)
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
                _wait_before_retry(sleep, attempt)
                continue
            raise RuntimeError(message)
        return data

    raise RuntimeError("Apps Script journal API request failed after retries")


def _retryable_http_status(status_code: int) -> bool:
    return status_code in {408, 429} or 500 <= status_code < 600


def _wait_before_retry(sleeper: Callable[[float], object], attempt: int) -> None:
    sleeper(RETRY_DELAY_SECONDS * attempt)
