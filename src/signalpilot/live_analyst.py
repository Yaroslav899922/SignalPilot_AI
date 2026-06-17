from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .market_data import LiveMarketData
from .patterns import PatternSetup, detect_breakout_retest, explain_no_breakout_retest
from .signals import Signal
from .tradingview import TradingViewTrigger


@dataclass(frozen=True)
class AnalystResult:
    signal: Signal
    status: dict[str, object]
    trigger: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "signal": self.signal.to_dict(),
            "status": self.status,
            "trigger": self.trigger,
        }


def analyze_live_market(
    market: LiveMarketData,
    trigger: TradingViewTrigger | None = None,
) -> AnalystResult:
    setup = detect_breakout_retest(market)
    if setup is None:
        signal = _no_trade_signal(market, explain_no_breakout_retest(market), trigger)
    else:
        signal = setup_to_signal(setup, trigger)
    return AnalystResult(
        signal=signal,
        status=market.to_status_dict(),
        trigger=None if trigger is None else asdict(trigger),
    )


def setup_to_signal(setup: PatternSetup, trigger: TradingViewTrigger | None = None) -> Signal:
    trigger_reasons = _trigger_reasons(trigger)
    return Signal(
        symbol=setup.symbol,
        interval=setup.timeframe,
        direction=setup.direction,
        market_regime=setup.market_regime,
        close_price=setup.close_price,
        funding_rate=setup.futures_context.funding_rate,
        open_interest=setup.futures_context.open_interest,
        long_short_ratio=setup.futures_context.long_short_ratio,
        spread_pct=setup.futures_context.spread_pct,
        entry_zone=setup.plan.entry_zone,
        stop=setup.plan.stop,
        targets=setup.plan.targets,
        risk_reward=setup.plan.risk_reward,
        confidence=setup.quality,
        invalidation=setup.plan.invalidation,
        reasons=(*trigger_reasons, *setup.reasons),
        created_at=_now(),
        trailing_plan=setup.plan.trailing_plan,
        pattern=setup.pattern,
        setup_score=setup.score,
        source=setup.source,
    )


def format_market_status(result: AnalystResult) -> str:
    signal = result.signal
    status = result.status
    frames = status.get("frames", {})
    lines = [
        f"{signal.symbol}: live data status",
        f"source: {status.get('source', '-')}",
        f"decision: {signal.direction}",
        f"pattern: {signal.pattern or '-'}",
        f"score: {signal.setup_score if signal.setup_score is not None else '-'}",
    ]
    if isinstance(frames, dict):
        for interval in sorted(frames):
            frame = frames[interval]
            if isinstance(frame, dict):
                lines.append(
                    f"{interval}: rows={frame.get('rows')} close={frame.get('latest_close')} "
                    f"closed_at={frame.get('latest_closed_at')} indicators_ready={frame.get('indicators_ready')}"
                )
    return "\n".join(lines)


def _no_trade_signal(
    market: LiveMarketData,
    reasons: tuple[str, ...],
    trigger: TradingViewTrigger | None,
) -> Signal:
    close = None
    try:
        close = market.frame("1h").latest_close
    except KeyError:
        close = None
    return Signal(
        symbol=market.symbol,
        interval="1h",
        direction="NO TRADE",
        market_regime="live_analyst:no_setup",
        close_price=round(close, 2) if close is not None else None,
        funding_rate=market.futures_context.funding_rate,
        open_interest=market.futures_context.open_interest,
        long_short_ratio=market.futures_context.long_short_ratio,
        spread_pct=market.futures_context.spread_pct,
        entry_zone="",
        stop=None,
        targets=(),
        risk_reward=None,
        confidence="low",
        invalidation="Wait for a cleaner setup with a defined stop",
        reasons=(*_trigger_reasons(trigger), *reasons),
        created_at=_now(),
        trailing_plan="",
        pattern="breakout_retest",
        setup_score=0.0,
        source=market.source,
    )


def _trigger_reasons(trigger: TradingViewTrigger | None) -> tuple[str, ...]:
    if trigger is None:
        return ()
    compact = json.dumps(trigger.raw, ensure_ascii=False, sort_keys=True)
    return (
        f"TradingView trigger received from {trigger.indicator or 'unknown indicator'}",
        f"TradingView trigger payload: {compact[:500]}",
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
