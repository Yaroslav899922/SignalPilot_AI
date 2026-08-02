from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from html import escape

import pandas as pd

from .market_data import LiveMarketData, MarketFrame


WATCH = "WATCH"
ARMED = "ARMED"
TRIGGERED = "TRIGGERED"
INVALIDATED = "INVALIDATED"
TARGET_HIT = "TARGET_HIT"
STOPPED = "STOPPED"
EXPIRED = "EXPIRED"
TIMED_OUT = "TIMED_OUT"

ACTIVE_STATUSES = (WATCH, ARMED, TRIGGERED)
TERMINAL_STATUSES = (INVALIDATED, TARGET_HIT, STOPPED, EXPIRED, TIMED_OUT)


@dataclass(frozen=True)
class SetupCondition:
    code: str
    label: str
    met: bool
    detail: str = ""
    required: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SetupCondition":
        return cls(
            code=str(data.get("code", "")),
            label=str(data.get("label", "")),
            met=bool(data.get("met", False)),
            detail=str(data.get("detail", "")),
            required=bool(data.get("required", True)),
        )


@dataclass(frozen=True)
class ActionableSetup:
    setup_id: str
    symbol: str
    pattern: str
    direction: str
    status: str
    regime: str
    current_price: float
    trigger_level: float
    entry_low: float
    entry_high: float
    stop: float
    targets: tuple[float, ...]
    risk_reward: float
    score: float
    action: str
    reason: str
    invalidation: str
    conditions: tuple[SetupCondition, ...]
    created_at: str
    expires_at: str
    source: str = "actionable_setup"

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["targets"] = list(self.targets)
        data["conditions"] = [condition.to_dict() for condition in self.conditions]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ActionableSetup":
        raw_targets = data.get("targets", ())
        raw_conditions = data.get("conditions", ())
        return cls(
            setup_id=str(data.get("setup_id", "")),
            symbol=str(data.get("symbol", "")),
            pattern=str(data.get("pattern", "")),
            direction=str(data.get("direction", "")),
            status=str(data.get("status", WATCH)),
            regime=str(data.get("regime", "transition")),
            current_price=float(data.get("current_price", 0.0)),
            trigger_level=float(data.get("trigger_level", 0.0)),
            entry_low=float(data.get("entry_low", 0.0)),
            entry_high=float(data.get("entry_high", 0.0)),
            stop=float(data.get("stop", 0.0)),
            targets=tuple(float(value) for value in raw_targets if value not in (None, "")),
            risk_reward=float(data.get("risk_reward", 0.0)),
            score=float(data.get("score", 0.0)),
            action=str(data.get("action", "")),
            reason=str(data.get("reason", "")),
            invalidation=str(data.get("invalidation", "")),
            conditions=tuple(
                SetupCondition.from_dict(value)
                for value in raw_conditions
                if isinstance(value, dict)
            ),
            created_at=str(data.get("created_at", "")),
            expires_at=str(data.get("expires_at", "")),
            source=str(data.get("source", "actionable_setup")),
        )

    def with_status(self, status: str, *, action: str, reason: str, now_utc: datetime) -> "ActionableSetup":
        return replace(
            self,
            status=status,
            action=action,
            reason=reason,
            created_at=_iso(now_utc),
        )

    @property
    def fingerprint(self) -> str:
        condition_bits = "".join("1" if condition.met else "0" for condition in self.conditions)
        payload = (
            f"{self.setup_id}|{self.status}|{_price(self.entry_low)}|{_price(self.entry_high)}|"
            f"{_price(self.stop)}|{','.join(_price(value) for value in self.targets)}|{condition_bits}"
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def analyze_actionable_setup(
    market: LiveMarketData,
    now_utc: datetime | None = None,
) -> ActionableSetup | None:
    """Return the single clearest actionable scenario for a symbol.

    The engine deliberately separates context (4h), a concrete level (1h),
    and confirmation (15m).  A candidate can be WATCH/ARMED without being a
    trade.  Only TRIGGERED candidates are journalled as paper entries.
    """

    now = _aware(now_utc or datetime.now(timezone.utc))
    try:
        f15m = market.frame("15m")
        f1h = market.frame("1h")
        f4h = market.frame("4h")
    except KeyError:
        return None

    row15 = _ready_row(f15m, _CONFIRM_COLUMNS)
    row1h = _ready_row(f1h, _SETUP_COLUMNS)
    row4h = _ready_row(f4h, _REGIME_COLUMNS)
    if row15 is None or row1h is None or row4h is None:
        return None

    regime = _market_regime(f4h, f1h)
    candidates: list[ActionableSetup] = []

    false_breakout = _false_breakout_setup(market, row15, row1h, regime, now)
    if false_breakout is not None:
        candidates.append(false_breakout)

    directions = _allowed_breakout_directions(regime, row1h)
    for direction in directions:
        breakout = _breakout_setup(market, row15, row1h, regime, direction, now)
        if breakout is not None:
            candidates.append(breakout)

    if regime == "uptrend":
        pullback = _pullback_setup(market, row15, row1h, regime, "LONG", now)
        if pullback is not None:
            candidates.append(pullback)
    elif regime == "downtrend":
        pullback = _pullback_setup(market, row15, row1h, regime, "SHORT", now)
        if pullback is not None:
            candidates.append(pullback)

    if regime in {"range", "compression", "transition"}:
        range_setup = _range_edge_setup(market, row15, row1h, regime, now)
        if range_setup is not None:
            candidates.append(range_setup)

    if not candidates:
        return None

    priority = {TRIGGERED: 3, ARMED: 2, WATCH: 1}
    return max(candidates, key=lambda item: (priority.get(item.status, 0), item.score))


def reconcile_setup_state(
    candidate: ActionableSetup | None,
    previous_setups: list[ActionableSetup],
    market: LiveMarketData,
    now_utc: datetime | None = None,
) -> list[ActionableSetup]:
    """Return only state changes that should be persisted and announced."""

    now = _aware(now_utc or datetime.now(timezone.utc))
    symbol_history = [setup for setup in previous_setups if setup.symbol == market.symbol]
    previous = max(symbol_history, key=lambda item: item.created_at, default=None)

    if previous is None:
        return [] if candidate is None else [candidate]

    # A confirmed entry is one paper trade.  If the same level/pattern later
    # appears again, do not resurrect it and count/announce a second entry.
    if candidate is not None and any(
        setup.setup_id == candidate.setup_id
        and setup.status in {TRIGGERED, TARGET_HIT, STOPPED, EXPIRED}
        for setup in symbol_history
    ):
        candidate = None

    if previous.status in TERMINAL_STATUSES:
        if candidate is None or candidate.setup_id == previous.setup_id:
            return []
        return [candidate]

    if previous.status == TRIGGERED:
        terminal = _triggered_terminal_event(previous, market, now)
        if terminal is not None:
            return [terminal]
        if _expired(previous, now):
            return [
                previous.with_status(
                    TIMED_OUT,
                    action="Тестовий вхід завершено за часом; новий вхід за ним не робити.",
                    reason="Після підтвердженого входу ціна не торкнулася ні цілі, ні стопа у відведений час.",
                    now_utc=now,
                )
            ]
        return []

    if _expired(previous, now):
        return [
            previous.with_status(
                EXPIRED,
                action="Не входити: час цього плану минув.",
                reason="Сценарій не активувався у відведений час.",
                now_utc=now,
            )
        ]

    if candidate is None:
        return [
            previous.with_status(
                INVALIDATED,
                action="Не входити за старим планом.",
                reason="Ринкові умови більше не підтримують цей сценарій.",
                now_utc=now,
            )
        ]

    if candidate.setup_id == previous.setup_id:
        return [] if candidate.status == previous.status else [candidate]

    cancelled = previous.with_status(
        INVALIDATED,
        action="Не входити за старим планом; рівень або напрямок змінився.",
        reason="Система знайшла новий сценарій замість попереднього.",
        now_utc=now,
    )
    replacement = replace(candidate, created_at=_iso(now + timedelta(microseconds=1)))
    return [cancelled, replacement]


def should_notify_setup_event(
    event: ActionableSetup,
    previous_setups: list[ActionableSetup],
) -> bool:
    """Keep routine WATCH churn quiet while preserving actionable changes."""

    if event.status == ARMED:
        return event.score >= 75.0
    if event.status in {TRIGGERED, TARGET_HIT, STOPPED, TIMED_OUT}:
        return True
    if event.status == WATCH:
        return False
    prior_same = [setup for setup in previous_setups if setup.setup_id == event.setup_id]
    previous = max(prior_same, key=lambda item: item.created_at, default=None)
    return previous is not None and (
        previous.status == TRIGGERED
        or (previous.status == ARMED and previous.score >= 75.0)
    )


def setup_to_signal(setup: ActionableSetup):
    from .signals import Signal

    return Signal(
        symbol=setup.symbol,
        interval="15m",
        direction=setup.direction,
        market_regime=setup.regime,
        close_price=setup.current_price,
        funding_rate=None,
        open_interest=None,
        long_short_ratio=None,
        spread_pct=None,
        entry_zone=f"{_price(setup.entry_low)}-{_price(setup.entry_high)}",
        stop=setup.stop,
        targets=setup.targets,
        risk_reward=setup.risk_reward,
        confidence="high" if setup.score >= 80 else "medium",
        invalidation=setup.invalidation,
        reasons=(setup.reason, *tuple(condition.label for condition in setup.conditions if condition.met)),
        created_at=setup.created_at,
        trailing_plan="Після першої цілі перенести захист у зону входу.",
        pattern=setup.pattern,
        setup_score=setup.score,
        source="actionable_alert",
        entry_low=setup.entry_low,
        entry_high=setup.entry_high,
        setup_id=setup.setup_id,
        setup_status=setup.status,
        expires_at=setup.expires_at,
    )


def _triggered_terminal_event(
    setup: ActionableSetup,
    market: LiveMarketData,
    now: datetime,
) -> ActionableSetup | None:
    try:
        candles = _closed_candles_since(
            market.frame("15m").candles,
            setup.created_at,
            setup.expires_at,
            now,
        )
    except KeyError:
        return None
    if candles.empty or not {"high", "low"}.issubset(candles.columns):
        return None
    for _, candle in candles.iterrows():
        status = _terminal_status(setup, high=float(candle["high"]), low=float(candle["low"]))
        if status == STOPPED:
            return setup.with_status(
                STOPPED,
                action="Тестовий план завершено. Новий вхід за ним не робити.",
                reason="Ціна торкнулася рівня виходу зі збитком.",
                now_utc=now,
            )
        if status == TARGET_HIT:
            return setup.with_status(
                TARGET_HIT,
                action="Перша ціль досягнута; тестовий план завершено.",
                reason="Ціна дійшла до першої запланованої цілі.",
                now_utc=now,
            )
    return None


def _closed_candles_since(
    candles: pd.DataFrame,
    created_at: str,
    expires_at: str,
    now: datetime,
) -> pd.DataFrame:
    if candles.empty:
        return candles
    triggered_at = pd.to_datetime(created_at, utc=True, errors="coerce")
    if pd.isna(triggered_at):
        return candles.tail(1)
    now_ts = pd.Timestamp(now)
    expires = pd.to_datetime(expires_at, utc=True, errors="coerce")
    window_end = now_ts if pd.isna(expires) else min(now_ts, expires)
    if "open_time" in candles.columns:
        open_times = pd.to_datetime(candles["open_time"], utc=True, errors="coerce")
        eligible_mask = (open_times >= triggered_at) & (open_times < window_end)
        if "close_time" in candles.columns:
            close_times = pd.to_datetime(candles["close_time"], utc=True, errors="coerce")
            eligible_mask &= close_times <= now_ts
        eligible = candles.loc[eligible_mask].copy()
        return eligible.assign(_event_time=open_times.loc[eligible.index]).sort_values("_event_time").drop(
            columns="_event_time"
        )
    if "close_time" in candles.columns:
        close_times = pd.to_datetime(candles["close_time"], utc=True, errors="coerce")
        eligible = candles.loc[(close_times > triggered_at) & (close_times <= window_end)].copy()
        return eligible.assign(_event_time=close_times.loc[eligible.index]).sort_values("_event_time").drop(
            columns="_event_time"
        )
    return candles.tail(1)


def _terminal_status(setup: ActionableSetup, *, high: float, low: float) -> str | None:
    target = setup.targets[0]
    if setup.direction == "LONG":
        if low <= setup.stop:
            return STOPPED
        if high >= target:
            return TARGET_HIT
    else:
        if high >= setup.stop:
            return STOPPED
        if low <= target:
            return TARGET_HIT
    return None


def _expired(setup: ActionableSetup, now: datetime) -> bool:
    try:
        expires = datetime.fromisoformat(setup.expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return _aware(expires) <= now


def format_setup_message(setup: ActionableSetup) -> str:
    symbol = setup.symbol.replace("USDT", "")
    status_icon, status_label = _status_text(setup.status)
    direction = "КУПІВЛЯ (LONG)" if setup.direction == "LONG" else "ПРОДАЖ (SHORT)"
    pattern = _pattern_label(setup.pattern)
    regime = _regime_label(setup.regime)
    met = sum(condition.met for condition in setup.conditions)
    total = len(setup.conditions)

    lines = [
        f"{status_icon} <b>{escape(symbol)} — {status_label}</b>",
        f"<b>Напрямок:</b> {direction}",
        f"<b>Сценарій:</b> {escape(pattern)}",
        f"<b>Ринок 4h:</b> {escape(regime)}",
        "",
        f"<b>Що відбувається:</b> {escape(setup.reason)}",
        f"<b>Що робити зараз:</b> {escape(setup.action)}",
        "",
        f"<b>Рівень, за яким стежимо:</b> {_price(setup.trigger_level)}",
        f"<b>Зона входу:</b> {_price(setup.entry_low)}–{_price(setup.entry_high)}",
        f"<b>Вихід зі збитком:</b> {_price(setup.stop)}",
    ]
    for index, target in enumerate(setup.targets, start=1):
        lines.append(f"<b>Ціль {index}:</b> {_price(target)}")
    lines.extend(
        [
            f"<b>Потенціал цілі 1:</b> {setup.risk_reward:.1f} до 1 відносно ризику",
            "<b>Ризик тесту:</b> не більш як 0.5% умовного рахунку",
            "",
            f"<b>Перевірки ({met}/{total}):</b>",
        ]
    )
    for condition in setup.conditions:
        marker = "✅" if condition.met else "⏳"
        detail = f" — {escape(condition.detail)}" if condition.detail else ""
        lines.append(f"{marker} {escape(condition.label)}{detail}")
    lines.extend(
        [
            "",
            f"<b>План скасовано, якщо:</b> {escape(setup.invalidation)}",
            f"<b>План діє до:</b> {_kyiv_time(setup.expires_at)}",
            "",
            "<i>Це тестова підказка. SignalPilot не відкриває угоду автоматично.</i>",
        ]
    )
    return "\n".join(lines)


def format_action_brief(
    markets: list[LiveMarketData],
    setups: list[ActionableSetup],
    *,
    now_utc: datetime | None = None,
    session_label: str | None = None,
) -> str:
    now = _aware(now_utc or datetime.now(timezone.utc))
    setup_by_symbol = {setup.symbol: setup for setup in setups}
    session = session_label or "Ринковий контроль"
    lines = [
        "📍 <b>SignalPilot — короткий план ринку</b>",
        f"{now.astimezone(_kyiv_zone()).strftime('%d.%m · %H:%M Київ')} · {escape(session)}",
        "",
    ]
    for market in markets:
        symbol = market.symbol.replace("USDT", "")
        setup = setup_by_symbol.get(market.symbol)
        if setup is None:
            lines.extend(
                [
                    f"⚪ <b>{escape(symbol)} — нового сценарію немає</b>",
                    "Зараз не входити. Система продовжує тихо стежити за рівнями.",
                    "",
                ]
            )
            continue
        icon, label = _status_text(setup.status)
        lines.extend(
            [
                f"{icon} <b>{escape(symbol)} — {label}</b>",
                f"{escape(_pattern_label(setup.pattern))} · {escape(_regime_label(setup.regime))}",
                f"{escape(setup.action)}",
                f"Рівень: {_price(setup.trigger_level)} · вхід: {_price(setup.entry_low)}–{_price(setup.entry_high)}",
                "",
            ]
        )
    lines.append("Окремий детальний алерт прийде лише коли сценарій змінить стан.")
    return "\n".join(lines)


def _breakout_setup(
    market: LiveMarketData,
    row15: pd.Series,
    row1h: pd.Series,
    regime: str,
    direction: str,
    now: datetime,
) -> ActionableSetup | None:
    close = float(row1h["close"])
    atr = float(row1h["atr14"])
    if atr <= 0:
        return None
    level = float(row1h["recent_high20"] if direction == "LONG" else row1h["recent_low20"])
    distance = abs(close - level) / atr
    crossed = close > level if direction == "LONG" else close < level
    if not crossed and distance > 1.75:
        return None

    # A confirmed 1h breakout commonly closes 0.5-0.8 ATR beyond the old
    # boundary.  The former 0.45 ATR cap rejected otherwise clean breakouts
    # (including the BTC 2026-07-18 example) after every confirmation passed.
    # 0.85 ATR still rejects an extended candle while leaving room for a
    # normal close/retest entry.
    width = 0.85 * atr
    if direction == "LONG":
        entry_low, entry_high = level, level + width
        stop = level - 0.8 * atr
        retest = float(row1h["low"]) <= level + 0.35 * atr and close >= level
        confirm = float(row15["close"]) > float(row15["ema20"]) and float(row15["close"]) >= level
        momentum = _macd_turn(row15, market.frame("15m"), "LONG")
        not_chasing = float(row15["close"]) <= entry_high
    else:
        entry_low, entry_high = level - width, level
        stop = level + 0.8 * atr
        retest = float(row1h["high"]) >= level - 0.35 * atr and close <= level
        confirm = float(row15["close"]) < float(row15["ema20"]) and float(row15["close"]) <= level
        momentum = _macd_turn(row15, market.frame("15m"), "SHORT")
        not_chasing = float(row15["close"]) >= entry_low

    volume_ratio = _volume_ratio(row1h)
    volume = volume_ratio is not None and volume_ratio >= 1.2
    conditions = (
        SetupCondition("level_break", "1h закрилася за ключовим рівнем", crossed, _price(close)),
        SetupCondition("retest", "Повернення до рівня втрималося", retest),
        SetupCondition(
            "confirm_15m",
            "15m тримається з правильного боку короткої середньої (EMA20)",
            confirm,
        ),
        SetupCondition(
            "momentum",
            "Сила руху підтверджує напрямок (MACD)",
            momentum,
            required=False,
        ),
        SetupCondition(
            "volume",
            "Обсяг підтримує рух",
            volume,
            "немає даних" if volume_ratio is None else f"{volume_ratio:.1f}x середнього",
            required=False,
        ),
        SetupCondition("not_chasing", "Ціна ще в допустимій зоні входу", not_chasing),
    )
    core = crossed and retest and confirm and not_chasing
    triggered = core and (momentum or volume)
    # Approaching the level belongs in the scheduled brief.  A separate
    # ARMED alert starts only after the 1h level has actually been crossed.
    near = crossed
    status = TRIGGERED if triggered else ARMED if near else WATCH
    pattern = "compression_breakout" if regime == "compression" else "breakout_retest"
    reason = (
        "Пробій і повернення до рівня підтверджені."
        if triggered
        else "Ціна біля рівня пробою, але не всі підтвердження виконані."
        if near
        else "Ціна наближається до рівня можливого пробою."
    )
    action = _action_for_status(status, direction, entry_low, entry_high)
    return _make_setup(
        market=market,
        pattern=pattern,
        direction=direction,
        status=status,
        regime=regime,
        current_price=float(row15["close"]),
        trigger_level=level,
        entry_low=entry_low,
        entry_high=entry_high,
        stop=stop,
        conditions=conditions,
        action=action,
        reason=reason,
        invalidation=(
            f"1h закриється нижче {_price(level)} або ціна піде нижче {_price(stop)}"
            if direction == "LONG"
            else f"1h закриється вище {_price(level)} або ціна піде вище {_price(stop)}"
        ),
        now=now,
    )


def _pullback_setup(
    market: LiveMarketData,
    row15: pd.Series,
    row1h: pd.Series,
    regime: str,
    direction: str,
    now: datetime,
) -> ActionableSetup | None:
    close = float(row1h["close"])
    atr = float(row1h["atr14"])
    ema20 = float(row1h["ema20"])
    if atr <= 0:
        return None
    if direction == "LONG":
        level = max(ema20, float(row1h["recent_low20"]))
    else:
        level = min(ema20, float(row1h["recent_high20"]))
    distance = abs(close - level) / atr
    if distance > 1.5:
        return None

    width = 0.35 * atr
    if direction == "LONG":
        entry_low, entry_high = level - 0.1 * atr, level + width
        stop = level - 0.9 * atr
        touch = float(row1h["low"]) <= level + 0.35 * atr and close >= level
        confirm = float(row15["close"]) > float(row15["ema20"])
        not_chasing = float(row15["close"]) <= entry_high
    else:
        entry_low, entry_high = level - width, level + 0.1 * atr
        stop = level + 0.9 * atr
        touch = float(row1h["high"]) >= level - 0.35 * atr and close <= level
        confirm = float(row15["close"]) < float(row15["ema20"])
        not_chasing = float(row15["close"]) >= entry_low
    momentum = _macd_turn(row15, market.frame("15m"), direction)
    volume_ratio = _volume_ratio(row1h)
    volume_ok = volume_ratio is None or volume_ratio >= 0.8
    conditions = (
        SetupCondition("trend", "4h підтримує цей напрямок", True),
        SetupCondition("touch", "1h повернулася до робочої зони", touch),
        SetupCondition("confirm_15m", "15m повернулася у напрямку тренду", confirm),
        SetupCondition("momentum", "Сила руху розвертається у потрібний бік (MACD)", momentum),
        SetupCondition(
            "volume",
            "Обсяг не суперечить руху",
            volume_ok,
            "немає даних" if volume_ratio is None else f"{volume_ratio:.1f}x середнього",
            required=False,
        ),
        SetupCondition("not_chasing", "Ціна ще в допустимій зоні входу", not_chasing),
    )
    triggered = touch and confirm and momentum and not_chasing
    near = touch
    status = TRIGGERED if triggered else ARMED if near else WATCH
    return _make_setup(
        market=market,
        pattern="trend_pullback",
        direction=direction,
        status=status,
        regime=regime,
        current_price=float(row15["close"]),
        trigger_level=level,
        entry_low=entry_low,
        entry_high=entry_high,
        stop=stop,
        conditions=conditions,
        action=_action_for_status(status, direction, entry_low, entry_high),
        reason=(
            "Відкат за основним напрямком отримав підтвердження 15m."
            if triggered
            else "Ціна повертається до робочої зони за основним напрямком."
        ),
        invalidation=(
            f"1h закриється нижче {_price(stop)}" if direction == "LONG" else f"1h закриється вище {_price(stop)}"
        ),
        now=now,
    )


def _range_edge_setup(
    market: LiveMarketData,
    row15: pd.Series,
    row1h: pd.Series,
    regime: str,
    now: datetime,
) -> ActionableSetup | None:
    close = float(row1h["close"])
    atr = float(row1h["atr14"])
    support = float(row1h["recent_low20"])
    resistance = float(row1h["recent_high20"])
    if atr <= 0 or resistance <= support:
        return None
    support_distance = abs(close - support)
    resistance_distance = abs(resistance - close)
    direction = "LONG" if support_distance <= resistance_distance else "SHORT"
    level = support if direction == "LONG" else resistance
    if abs(close - level) / atr > 1.2:
        return None

    width = 0.35 * atr
    if direction == "LONG":
        entry_low, entry_high = support, support + width
        stop = support - 0.65 * atr
        touch = float(row1h["low"]) <= support + 0.25 * atr and close > support
        confirm = float(row15["close"]) > float(row15["ema20"])
        not_chasing = float(row15["close"]) <= entry_high
        room = resistance - ((entry_low + entry_high) / 2.0)
    else:
        entry_low, entry_high = resistance - width, resistance
        stop = resistance + 0.65 * atr
        touch = float(row1h["high"]) >= resistance - 0.25 * atr and close < resistance
        confirm = float(row15["close"]) < float(row15["ema20"])
        not_chasing = float(row15["close"]) >= entry_low
        room = ((entry_low + entry_high) / 2.0) - support
    momentum = _macd_turn(row15, market.frame("15m"), direction)
    risk = abs(((entry_low + entry_high) / 2.0) - stop)
    room_ok = risk > 0 and room / risk >= 1.5
    conditions = (
        SetupCondition("edge", "Ціна біля межі, а не посередині діапазону", True),
        SetupCondition("rejection", "1h показує відбій від межі", touch),
        SetupCondition("confirm_15m", "15m підтверджує відбій", confirm),
        SetupCondition("momentum", "Сила руху повертається всередину діапазону (MACD)", momentum),
        SetupCondition("room", "До наступної перешкоди достатньо місця", room_ok),
        SetupCondition("not_chasing", "Ціна ще в допустимій зоні входу", not_chasing),
    )
    triggered = touch and confirm and momentum and room_ok and not_chasing
    status = TRIGGERED if triggered else ARMED if touch else WATCH
    return _make_setup(
        market=market,
        pattern="range_edge",
        direction=direction,
        status=status,
        regime=regime,
        current_price=float(row15["close"]),
        trigger_level=level,
        entry_low=entry_low,
        entry_high=entry_high,
        stop=stop,
        conditions=conditions,
        action=_action_for_status(status, direction, entry_low, entry_high),
        reason=(
            "Відбій від межі підтверджено."
            if triggered
            else "Ціна біля межі діапазону; чекаємо підтверджений відбій."
        ),
        invalidation=(
            f"1h закриється нижче {_price(stop)}" if direction == "LONG" else f"1h закриється вище {_price(stop)}"
        ),
        now=now,
        target_cap=(resistance if direction == "LONG" else support),
    )


def _false_breakout_setup(
    market: LiveMarketData,
    row15: pd.Series,
    row1h: pd.Series,
    regime: str,
    now: datetime,
) -> ActionableSetup | None:
    if regime not in {"range", "compression", "transition"}:
        return None
    close = float(row1h["close"])
    atr = float(row1h["atr14"])
    support = float(row1h["recent_low20"])
    resistance = float(row1h["recent_high20"])
    if atr <= 0:
        return None
    swept_low = float(row1h["low"]) < support and close > support
    swept_high = float(row1h["high"]) > resistance and close < resistance
    if not swept_low and not swept_high:
        return None
    direction = "LONG" if swept_low else "SHORT"
    level = support if direction == "LONG" else resistance
    width = 0.35 * atr
    if direction == "LONG":
        entry_low, entry_high = level, level + width
        stop = min(float(row1h["low"]) - 0.1 * atr, level - 0.65 * atr)
        confirm = float(row15["close"]) > float(row15["ema20"])
        not_chasing = float(row15["close"]) <= entry_high
        target_cap = resistance
    else:
        entry_low, entry_high = level - width, level
        stop = max(float(row1h["high"]) + 0.1 * atr, level + 0.65 * atr)
        confirm = float(row15["close"]) < float(row15["ema20"])
        not_chasing = float(row15["close"]) >= entry_low
        target_cap = support
    momentum = _macd_turn(row15, market.frame("15m"), direction)
    conditions = (
        SetupCondition("sweep", "1h вийшла за межу й повернулася назад", True),
        SetupCondition("confirm_15m", "15m підтверджує повернення", confirm),
        SetupCondition("momentum", "Сила руху підтверджує повернення (MACD)", momentum),
        SetupCondition("not_chasing", "Ціна ще в допустимій зоні входу", not_chasing),
    )
    triggered = confirm and momentum and not_chasing
    status = TRIGGERED if triggered else ARMED
    return _make_setup(
        market=market,
        pattern="false_breakout",
        direction=direction,
        status=status,
        regime=regime,
        current_price=float(row15["close"]),
        trigger_level=level,
        entry_low=entry_low,
        entry_high=entry_high,
        stop=stop,
        conditions=conditions,
        action=_action_for_status(status, direction, entry_low, entry_high),
        reason=(
            "Хибний пробій підтверджено; ціна повернулася всередину діапазону."
            if triggered
            else "Ціна повернулася за межу, але 15m ще не підтвердила вхід."
        ),
        invalidation=(
            f"ціна знову піде нижче {_price(stop)}" if direction == "LONG" else f"ціна знову піде вище {_price(stop)}"
        ),
        now=now,
        target_cap=target_cap,
    )


def _make_setup(
    *,
    market: LiveMarketData,
    pattern: str,
    direction: str,
    status: str,
    regime: str,
    current_price: float,
    trigger_level: float,
    entry_low: float,
    entry_high: float,
    stop: float,
    conditions: tuple[SetupCondition, ...],
    action: str,
    reason: str,
    invalidation: str,
    now: datetime,
    target_cap: float | None = None,
) -> ActionableSetup:
    low, high = sorted((float(entry_low), float(entry_high)))
    midpoint = (low + high) / 2.0
    reference = current_price if low <= current_price <= high else midpoint
    risk = abs(reference - stop)
    if direction == "LONG":
        target1 = reference + 1.5 * risk
        target2 = reference + 2.5 * risk
        if target_cap is not None and target_cap > reference:
            target1 = min(target1, target_cap)
            target2 = min(target2, target_cap)
    else:
        target1 = reference - 1.5 * risk
        target2 = reference - 2.5 * risk
        if target_cap is not None and target_cap < reference:
            target1 = max(target1, target_cap)
            target2 = max(target2, target_cap)
    target1_r = abs(target1 - reference) / risk if risk > 0 else 0.0
    if status == TRIGGERED and target1_r < 1.49:
        status = ARMED
        action = "Поки не входити: до найближчої перешкоди замало місця для безпечного плану."
        reason = "Умови руху виконані, але потенційна винагорода поки замала відносно ризику."
    met_ratio = sum(condition.met for condition in conditions) / max(len(conditions), 1)
    score = round(50.0 + met_ratio * 40.0 + (5.0 if status == TRIGGERED else 0.0), 1)
    expires = now + timedelta(hours=12)
    setup_id = _setup_id(market.symbol, pattern, direction, trigger_level, current_price)
    return ActionableSetup(
        setup_id=setup_id,
        symbol=market.symbol,
        pattern=pattern,
        direction=direction,
        status=status,
        regime=regime,
        current_price=round(current_price, 8),
        trigger_level=round(trigger_level, 8),
        entry_low=round(low, 8),
        entry_high=round(high, 8),
        stop=round(float(stop), 8),
        targets=(round(float(target1), 8), round(float(target2), 8)),
        risk_reward=round(target1_r, 2),
        score=score,
        action=action,
        reason=reason,
        invalidation=invalidation,
        conditions=conditions,
        created_at=_iso(now),
        expires_at=_iso(expires),
    )


def _market_regime(f4h: MarketFrame, f1h: MarketFrame) -> str:
    row4h = f4h.candles.iloc[-1]
    close = _number(row4h, "close")
    ema50 = _number(row4h, "ema50")
    atr = _number(row4h, "atr14")
    previous_ema = _number(f4h.candles.iloc[-4], "ema50") if len(f4h.candles) >= 4 else None
    if None in (close, ema50, atr, previous_ema) or atr <= 0:
        return "transition"
    structure = _four_hour_structure(f4h.candles)
    if structure == "mixed" and _is_compressing(f4h.candles):
        return "compression"
    slope = ema50 - previous_ema
    if close > ema50 and slope > 0 and structure != "down":
        return "uptrend"
    if close < ema50 and slope < 0 and structure != "up":
        return "downtrend"
    if structure == "mixed" and abs(slope) <= 0.35 * atr:
        return "range"
    return "transition"


def _four_hour_structure(candles: pd.DataFrame) -> str:
    if len(candles) < 9 or not {"high", "low"}.issubset(candles.columns):
        return "unknown"
    # Only recent swings describe the current regime.  Capping this window
    # also keeps repeated 15m checks and historical replay inexpensive.
    candles = candles.tail(80).reset_index(drop=True)
    highs: list[float] = []
    lows: list[float] = []
    for index in range(2, len(candles) - 2):
        window = candles.iloc[index - 2 : index + 3]
        high = float(candles.iloc[index]["high"])
        low = float(candles.iloc[index]["low"])
        if high > float(window.drop(index=candles.index[index])["high"].max()):
            highs.append(high)
        if low < float(window.drop(index=candles.index[index])["low"].min()):
            lows.append(low)
    if len(highs) < 2 or len(lows) < 2:
        return "unknown"
    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "up"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "down"
    return "mixed"


def _is_compressing(candles: pd.DataFrame) -> bool:
    rows = candles.dropna(subset=["high", "low"]).tail(12)
    if len(rows) < 10:
        return False
    split = len(rows) // 2
    early = rows.iloc[:split]
    late = rows.iloc[split:]
    early_width = float(early["high"].max() - early["low"].min())
    late_width = float(late["high"].max() - late["low"].min())
    if early_width <= 0:
        return False
    return late_width <= 0.85 * early_width


def _allowed_breakout_directions(regime: str, row1h: pd.Series) -> tuple[str, ...]:
    if regime == "uptrend":
        return ("LONG",)
    if regime == "downtrend":
        return ("SHORT",)
    close = float(row1h["close"])
    support = float(row1h["recent_low20"])
    resistance = float(row1h["recent_high20"])
    return ("LONG",) if abs(resistance - close) <= abs(close - support) else ("SHORT",)


def _macd_turn(row15: pd.Series, frame15: MarketFrame, direction: str) -> bool:
    current = _number(row15, "macd_hist")
    ready = frame15.candles.dropna(subset=["macd_hist"]).tail(2)
    if current is None or len(ready) < 2:
        return False
    previous = float(ready.iloc[-2]["macd_hist"])
    if direction == "LONG":
        return current > 0 and current >= previous
    return current < 0 and current <= previous


def _volume_ratio(row: pd.Series) -> float | None:
    volume = _number(row, "volume")
    average = _number(row, "volume_avg20")
    if volume is None or average is None or average <= 0:
        return None
    return volume / average


def _ready_row(frame: MarketFrame, columns: tuple[str, ...]) -> pd.Series | None:
    if not set(columns).issubset(frame.candles.columns):
        return None
    rows = frame.candles.dropna(subset=list(columns)).tail(1)
    return None if rows.empty else rows.iloc[0]


def _number(row: pd.Series, key: str) -> float | None:
    if key not in row.index or pd.isna(row[key]):
        return None
    return float(row[key])


def _setup_id(symbol: str, pattern: str, direction: str, level: float, price: float) -> str:
    del price
    absolute = abs(level)
    if absolute >= 10_000:
        step = 100.0
    elif absolute >= 1_000:
        step = 10.0
    elif absolute >= 100:
        step = 1.0
    elif absolute >= 10:
        step = 0.1
    elif absolute >= 1:
        step = 0.01
    else:
        step = 0.001
    bucket = round(level / step)
    digest = hashlib.sha1(f"{symbol}|{pattern}|{direction}|{bucket}".encode("utf-8")).hexdigest()[:10]
    return f"{symbol}-{pattern}-{direction}-{digest}"


def _action_for_status(status: str, direction: str, low: float, high: float) -> str:
    if status == TRIGGERED:
        return f"Вхід підтверджено. Можна розглядати тестовий вхід лише в зоні {_price(low)}–{_price(high)}; вище/нижче не наздоганяти."
    if status == ARMED:
        return "Поки не входити. Ціна вже біля робочої зони; чекаємо завершення невиконаних перевірок."
    side = "покупки" if direction == "LONG" else "продажу"
    return f"Зараз не входити. Стежимо за сценарієм {side} й чекаємо наближення до рівня."


def _status_text(status: str) -> tuple[str, str]:
    return {
        WATCH: ("👀", "СПОСТЕРІГАЄМО"),
        ARMED: ("🟠", "ГОТУЄМОСЯ"),
        TRIGGERED: ("🟢", "ВХІД ПІДТВЕРДЖЕНО"),
        INVALIDATED: ("❌", "СЦЕНАРІЙ СКАСОВАНО"),
        TARGET_HIT: ("🎯", "ЦІЛЬ ДОСЯГНУТА"),
        STOPPED: ("🛑", "ВИХІД ЗІ ЗБИТКОМ"),
        EXPIRED: ("⌛", "ЧАС ПЛАНУ МИНУВ"),
        TIMED_OUT: ("⏱️", "ВХІД ЗАВЕРШЕНО ЗА ЧАСОМ"),
    }.get(status, ("ℹ️", status))


def _pattern_label(pattern: str) -> str:
    return {
        "trend_pullback": "відкат за основним напрямком",
        "breakout_retest": "пробій і повернення до рівня",
        "compression_breakout": "вихід зі стискання/трикутника",
        "range_edge": "відбій від межі діапазону",
        "false_breakout": "хибний пробій і повернення",
    }.get(pattern, pattern)


def _regime_label(regime: str) -> str:
    return {
        "uptrend": "перевага покупців",
        "downtrend": "перевага продавців",
        "range": "рух між підтримкою та опором",
        "compression": "стискання перед можливим рухом",
        "transition": "перехідний стан",
    }.get(regime, regime)


def _price(value: float) -> str:
    if abs(value) >= 1000:
        return f"${value:,.0f}"
    if abs(value) >= 100:
        return f"${value:,.2f}"
    return f"${value:,.3f}".rstrip("0").rstrip(".")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return _aware(value).astimezone(timezone.utc).isoformat()


def _kyiv_zone():
    from zoneinfo import ZoneInfo

    return ZoneInfo("Europe/Kyiv")


def _kyiv_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(_kyiv_zone()).strftime("%d.%m · %H:%M Київ")
    except ValueError:
        return value


_CONFIRM_COLUMNS = ("close", "ema20", "macd_hist")
_SETUP_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "ema20",
    "ema50",
    "atr14",
    "macd_hist",
    "recent_high20",
    "recent_low20",
    "volume",
    "volume_avg20",
)
_REGIME_COLUMNS = ("high", "low", "close", "ema50", "atr14")
