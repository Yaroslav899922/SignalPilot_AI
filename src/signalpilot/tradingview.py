from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TradingViewTrigger:
    symbol: str
    interval: str | None
    direction: str | None
    indicator: str | None
    message: str | None
    raw: dict[str, Any]


def parse_tradingview_trigger(payload: str | dict[str, Any] | None) -> TradingViewTrigger | None:
    if payload is None or payload == "":
        return None
    data = json.loads(payload) if isinstance(payload, str) else dict(payload)
    if not isinstance(data, dict):
        raise ValueError("TradingView trigger must be a JSON object")

    symbol = _normalize_symbol(
        data.get("symbol")
        or data.get("ticker")
        or data.get("exchange_symbol")
        or data.get("syminfo.ticker")
    )
    if not symbol:
        raise ValueError("TradingView trigger is missing symbol/ticker")

    direction = data.get("direction") or data.get("side") or data.get("signal")
    return TradingViewTrigger(
        symbol=symbol,
        interval=_string_or_none(data.get("interval") or data.get("timeframe") or data.get("tf")),
        direction=_normalize_direction(direction),
        indicator=_string_or_none(data.get("indicator") or data.get("strategy") or data.get("name")),
        message=_string_or_none(data.get("message") or data.get("text")),
        raw=_redact_sensitive(data),
    )


def _normalize_symbol(value: object) -> str | None:
    text = _string_or_none(value)
    if not text:
        return None
    if ":" in text:
        text = text.split(":", 1)[1]
    for suffix in (".P", ".PERP"):
        if text.upper().endswith(suffix):
            text = text[: -len(suffix)]
    return text.replace("/", "").replace("-", "").upper()


def _normalize_direction(value: object) -> str | None:
    text = _string_or_none(value)
    if not text:
        return None
    normalized = text.strip().upper()
    if normalized in {"BUY", "LONG"}:
        return "LONG"
    if normalized in {"SELL", "SHORT"}:
        return "SHORT"
    return normalized


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _redact_sensitive(data: dict[str, Any]) -> dict[str, Any]:
    sensitive = {"secret", "token", "password", "api_key", "apikey", "apiSecret", "api_secret"}
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        if key in sensitive or key.lower() in {item.lower() for item in sensitive}:
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted
