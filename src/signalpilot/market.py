from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FuturesContext:
    funding_rate: float | None = None
    open_interest: float | None = None
    long_short_ratio: float | None = None
    spread_pct: float | None = None
