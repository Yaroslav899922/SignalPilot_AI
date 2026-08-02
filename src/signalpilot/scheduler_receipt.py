from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

from .apps_script_api import request as api_request


SCHEMA_VERSION = "scheduler-receipt/v1"
TERMINAL_STATUSES = frozenset({"success", "failure", "cancelled"})
RESPONSE_STATUSES = TERMINAL_STATUSES | {"running"}
REQUIRED_ENVIRONMENT = (
    "GITHUB_REPOSITORY",
    "GITHUB_WORKFLOW",
    "GITHUB_JOB",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_EVENT_NAME",
    "GITHUB_SHA",
    "SCHEDULER_MODE",
)


def build_receipt(
    phase: str,
    *,
    environ: Mapping[str, str] | None = None,
    observed_at: str | None = None,
) -> dict[str, object]:
    environment = os.environ if environ is None else environ
    if phase not in {"start", "finish"}:
        raise RuntimeError("scheduler receipt phase must be start or finish")

    values = {name: str(environment.get(name, "")).strip() for name in REQUIRED_ENVIRONMENT}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"missing scheduler environment: {', '.join(missing)}")

    run_attempt = values["GITHUB_RUN_ATTEMPT"]
    if not run_attempt.isdigit() or int(run_attempt) < 1:
        raise RuntimeError("GITHUB_RUN_ATTEMPT must be a positive integer")

    status = "running" if phase == "start" else str(
        environment.get("SCHEDULER_STATUS", "")
    ).strip()
    if phase == "finish" and status not in TERMINAL_STATUSES:
        raise RuntimeError("finish scheduler receipt requires a terminal status")

    steps = _steps_from_environment(environment)
    repository = values["GITHUB_REPOSITORY"]
    run_id = values["GITHUB_RUN_ID"]
    job = values["GITHUB_JOB"]
    server_url = str(environment.get("GITHUB_SERVER_URL", "https://github.com")).rstrip("/")
    run_key = f"{repository}:{run_id}:{run_attempt}:{job}"

    return {
        "schema_version": SCHEMA_VERSION,
        "run_key": run_key,
        "phase": phase,
        "status": status,
        "repository": repository,
        "workflow": values["GITHUB_WORKFLOW"],
        "job": job,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "event_name": values["GITHUB_EVENT_NAME"],
        "event_schedule": str(environment.get("EVENT_SCHEDULE", "")).strip(),
        "mode": values["SCHEDULER_MODE"],
        "commit_sha": values["GITHUB_SHA"],
        "run_url": f"{server_url}/{repository}/actions/runs/{run_id}",
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "steps": steps,
    }


def save_receipt(
    phase: str,
    *,
    environ: Mapping[str, str] | None = None,
    observed_at: str | None = None,
) -> dict[str, object]:
    receipt = build_receipt(phase, environ=environ, observed_at=observed_at)
    response = api_request("save_scheduler_receipt", {"receipt": receipt})
    _validate_response(response, receipt)
    return response


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persist a GitHub scheduler run receipt")
    parser.add_argument("phase", choices=("start", "finish"))
    args = parser.parse_args(argv)
    response = save_receipt(args.phase)
    print(json.dumps(response, sort_keys=True))
    return 0


def _steps_from_environment(environment: Mapping[str, str]) -> dict[str, object]:
    raw_steps = str(environment.get("SCHEDULER_STEPS_JSON", "")).strip()
    if not raw_steps:
        return {}
    try:
        steps = json.loads(raw_steps)
    except json.JSONDecodeError as error:
        raise RuntimeError("SCHEDULER_STEPS_JSON must contain valid JSON") from error
    if not isinstance(steps, dict):
        raise RuntimeError("SCHEDULER_STEPS_JSON must contain a JSON object")
    valid_results = {"", "success", "failure", "cancelled", "skipped"}
    for step_id, result in steps.items():
        if not isinstance(step_id, str) or not step_id:
            raise RuntimeError("scheduler step ids must be non-empty strings")
        if not isinstance(result, dict) or set(result) != {"outcome", "conclusion"}:
            raise RuntimeError("scheduler step results must contain outcome and conclusion")
        if any(not isinstance(result[field], str) for field in ("outcome", "conclusion")):
            raise RuntimeError("scheduler step outcome and conclusion must be strings")
        if any(result[field] not in valid_results for field in ("outcome", "conclusion")):
            raise RuntimeError("scheduler step outcome and conclusion are invalid")
    return steps


def _validate_response(response: dict[str, object], request_receipt: dict[str, object]) -> None:
    if response.get("run_key") != request_receipt["run_key"]:
        raise RuntimeError("scheduler receipt response run_key does not match the request")
    response_status = response.get("status")
    if response_status not in RESPONSE_STATUSES:
        raise RuntimeError("scheduler receipt response has an invalid status")
    if request_receipt["phase"] == "finish" and response_status != request_receipt["status"]:
        raise RuntimeError("scheduler finish receipt response status does not match the request")
    for field in ("inserted", "updated", "missing_start"):
        if not isinstance(response.get(field), bool):
            raise RuntimeError(f"scheduler receipt response field '{field}' must be boolean")


if __name__ == "__main__":
    raise SystemExit(main())
