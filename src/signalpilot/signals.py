from __future__ import annotations

from dataclasses import asdict, dataclass


FUNDING_OVERHEATED_ABS = 0.001
LONG_SHORT_RATIO_EXTREME_LOW = 0.5
LONG_SHORT_RATIO_EXTREME_HIGH = 2.0
MAX_SPREAD_PCT = 0.05
DEFAULT_TIMEFRAMES = ("15m", "1h", "4h")
CONFIRM_INTERVAL = "15m"
SETUP_INTERVAL = "1h"
TREND_INTERVAL = "4h"


@dataclass(frozen=True)
class Signal:
    symbol: str
    interval: str
    direction: str
    market_regime: str
    close_price: float | None
    funding_rate: float | None
    open_interest: float | None
    long_short_ratio: float | None
    spread_pct: float | None
    entry_zone: str
    stop: float | None
    targets: tuple[float, ...]
    risk_reward: float | None
    confidence: str
    invalidation: str
    reasons: tuple[str, ...]
    created_at: str
    trailing_plan: str = ""
    pattern: str = ""
    setup_score: float | None = None
    source: str = "signalpilot"

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["targets"] = list(self.targets)
        data["reasons"] = list(self.reasons)
        return data
