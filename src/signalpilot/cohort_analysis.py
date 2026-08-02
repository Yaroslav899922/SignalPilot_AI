"""Cohort extractor + confirmatory analyzer for measurement protocol v3.1.

This is the offline analysis artifact required by protocol section 10 step 8
(SignalPilot-v3.1-Measurement-Protocol-2026-08-02.md). It must exist and be
tested BEFORE ``measurement_start_utc`` is fixed, so the gate is never read
from ad-hoc all-time summaries.

  * Section 2 — inclusion: only actionable events first detected at or after
    ``measurement_start_utc``, with ``policy_version == "v3.1"`` and the full
    provenance set; legacy/unversioned rows never join the cohort.
  * Section 7 — populations are split exactly: pending / barrier_resolved /
    timed_out / terminal / paired_terminal (edge only on the pair).
  * Section 8 — one confirmatory look: joint 7-day circular moving-block
    bootstrap over UTC days of ``triggered_at``, NumPy PCG64 seed 20260802,
    50,000 valid replicas, 95% percentile CI, fixed concentration checks.

The module is pure computation over signal-row dicts (from the local journal
or a CSV export of the Google Sheet). It never talks to the network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

POLICY_VERSION = "v3.1"
SEED = 20260802
N_REPLICAS = 50_000
BLOCK_DAYS = 7
MIN_N = 30
PROVENANCE_FIELDS = ("event_id", "policy_version", "detected_at", "triggered_at", "market_source")
BARRIER_OUTCOMES = {"target", "stop"}
PENDING_OUTCOMES = {"", None, "not_enough_data"}
CORE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
MIN_PER_SYMBOL = 5
MIN_PER_DIRECTION = 10


def _parse_utc(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").to_pydatetime()


def _num(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


@dataclass
class Cohort:
    measurement_start: datetime
    paired: list = field(default_factory=list)   # dicts: edge, symbol, direction, day
    populations: dict = field(default_factory=dict)
    excluded: dict = field(default_factory=dict)
    edge_mismatches: int = 0


def extract_cohort(rows: list[dict], measurement_start_utc: str) -> Cohort:
    """Apply the section-2 inclusion rule and the section-7 population split."""
    start = _parse_utc(measurement_start_utc)
    if start is None:
        raise ValueError("measurement_start_utc must be a valid UTC timestamp")

    cohort = Cohort(measurement_start=start)
    pops = {"pending": 0, "barrier_resolved": 0, "timed_out": 0,
            "terminal": 0, "paired_terminal": 0, "unpaired_terminal": 0,
            "not_activated": 0}
    excluded = {"legacy_or_wrong_version": 0, "before_start": 0,
                "missing_provenance": 0, "not_actionable": 0}

    for row in rows:
        source = str(row.get("source") or "")
        if source and source not in {"actionable_alert", "actionable_setup"}:
            excluded["not_actionable"] += 1
            continue
        if str(row.get("policy_version") or "") != POLICY_VERSION:
            excluded["legacy_or_wrong_version"] += 1
            continue
        if any(row.get(f) in (None, "") for f in PROVENANCE_FIELDS):
            excluded["missing_provenance"] += 1
            continue
        detected = _parse_utc(row.get("detected_at"))
        if detected is None or detected < start:
            excluded["before_start"] += 1
            continue

        outcome = row.get("outcome")
        outcome = "" if outcome is None else str(outcome)
        if outcome == "not_activated":
            pops["not_activated"] += 1
            continue
        if outcome in PENDING_OUTCOMES:
            pops["pending"] += 1
            continue

        triggered = _parse_utc(row.get("triggered_at"))
        if outcome in BARRIER_OUTCOMES:
            pops["barrier_resolved"] += 1
        elif outcome == "no_result" and triggered is not None:
            pops["timed_out"] += 1
        else:
            pops["pending"] += 1
            continue
        pops["terminal"] += 1

        result_r = _num(row.get("result_R"))
        baseline_r = _num(row.get("baseline_R"))
        if result_r is None or baseline_r is None or triggered is None:
            pops["unpaired_terminal"] += 1
            continue
        pops["paired_terminal"] += 1
        edge = result_r - baseline_r
        stored = _num(row.get("edge_R"))
        if stored is not None and abs(stored - edge) > 1e-9:
            cohort.edge_mismatches += 1
        cohort.paired.append({
            "edge": edge,
            "symbol": str(row.get("symbol") or ""),
            "direction": str(row.get("direction") or ""),
            "day": triggered.astimezone(timezone.utc).date(),
        })

    cohort.populations = pops
    cohort.excluded = excluded
    return cohort


def block_bootstrap_ci(paired: list[dict], *, n_replicas: int = N_REPLICAS,
                       seed: int = SEED, block_days: int = BLOCK_DAYS,
                       alpha: float = 0.05) -> dict:
    """Exact section-8 resampling: circular moving blocks of 7 UTC days,
    all symbols/directions of a day stay together, event-weighted mean."""
    if not paired:
        return {"point": 0.0, "ci": (0.0, 0.0), "days": 0, "replicas": 0}
    days = sorted({event["day"] for event in paired})
    first, last = days[0], days[-1]
    total_days = (last - first).days + 1
    day_sum = np.zeros(total_days)
    day_cnt = np.zeros(total_days)
    for event in paired:
        idx = (event["day"] - first).days
        day_sum[idx] += event["edge"]
        day_cnt[idx] += 1

    point = float(day_sum.sum() / day_cnt.sum())
    rng = np.random.Generator(np.random.PCG64(seed))
    need_blocks = math.ceil(total_days / block_days)
    offsets = np.arange(block_days)

    means: list[np.ndarray] = []
    collected = 0
    while collected < n_replicas:
        batch = min(n_replicas - collected + 1024, 20_000)
        starts = rng.integers(0, total_days, size=(batch, need_blocks))
        # розгорнути блоки і обрізати до total_days днів
        idx = (starts[:, :, None] + offsets[None, None, :]) % total_days
        idx = idx.reshape(batch, -1)[:, :total_days]
        sums = day_sum[idx].sum(axis=1)
        cnts = day_cnt[idx].sum(axis=1)
        valid = cnts > 0
        batch_means = sums[valid] / cnts[valid]
        means.append(batch_means)
        collected += int(valid.sum())
    all_means = np.concatenate(means)[:n_replicas]
    lo = float(np.quantile(all_means, alpha / 2))
    hi = float(np.quantile(all_means, 1 - alpha / 2))
    return {"point": point, "ci": (lo, hi), "days": total_days,
            "replicas": int(len(all_means))}


def concentration_checks(paired: list[dict]) -> dict:
    """Fixed section-8 robustness checks; each entry is (passed, detail)."""
    checks: dict[str, tuple[bool, str]] = {}
    by_symbol = {s: [e["edge"] for e in paired if e["symbol"] == s] for s in CORE_SYMBOLS}
    for symbol in CORE_SYMBOLS:
        n = len(by_symbol[symbol])
        checks[f"n_{symbol}"] = (n >= MIN_PER_SYMBOL, f"{n} подій (потрібно ≥ {MIN_PER_SYMBOL})")
    for direction in ("LONG", "SHORT"):
        edges = [e["edge"] for e in paired if e["direction"] == direction]
        n_ok = len(edges) >= MIN_PER_DIRECTION
        mean = float(np.mean(edges)) if edges else 0.0
        checks[f"n_{direction}"] = (n_ok, f"{len(edges)} подій (потрібно ≥ {MIN_PER_DIRECTION})")
        checks[f"edge_{direction}"] = (bool(edges) and mean > 0, f"середній edge {mean:+.4f}R")
    for symbol in CORE_SYMBOLS:
        rest = [e["edge"] for e in paired if e["symbol"] != symbol]
        mean = float(np.mean(rest)) if rest else 0.0
        checks[f"excl_{symbol}"] = (bool(rest) and mean > 0,
                                    f"без {symbol}: середній edge {mean:+.4f}R")
    return checks


def confirmatory_verdict(cohort: Cohort, *, n_replicas: int = N_REPLICAS) -> dict:
    """Single pre-registered look. Returns verdict + everything the report needs."""
    paired = cohort.paired
    n = len(paired)
    if n < MIN_N:
        return {"verdict": "insufficient_data", "n": n, "bootstrap": None, "checks": {}}
    boot = block_bootstrap_ci(paired, n_replicas=n_replicas)
    checks = concentration_checks(paired)
    ci_low, ci_high = boot["ci"]
    if ci_low > 0 and all(passed for passed, _ in checks.values()):
        verdict = "passed"
    elif ci_high < 0:
        verdict = "closed"
    else:
        verdict = "inconclusive"
    return {"verdict": verdict, "n": n, "bootstrap": boot, "checks": checks}


def build_report(cohort: Cohort, result: dict, *, analyzer_sha: str = "TBD") -> str:
    pops = cohort.populations
    lines = [
        "# SignalPilot — cohort report v3.1 (confirmatory)\n",
        f"*Згенеровано {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. "
        f"Analyzer SHA: {analyzer_sha}. Seed {SEED}, блок {BLOCK_DAYS} діб.*\n",
        f"\n`measurement_start_utc` = {cohort.measurement_start.isoformat()}\n",
        "\n## Популяції (розділ 7 протоколу)\n",
        f"- pending: {pops.get('pending', 0)}\n",
        f"- barrier_resolved: {pops.get('barrier_resolved', 0)}\n",
        f"- timed_out: {pops.get('timed_out', 0)}\n",
        f"- terminal: {pops.get('terminal', 0)}\n",
        f"- paired_terminal: {pops.get('paired_terminal', 0)}\n",
        f"- unpaired_terminal: {pops.get('unpaired_terminal', 0)}\n",
        f"- not_activated (поза terminal): {pops.get('not_activated', 0)}\n",
        "\n## Виключено з когорти (розділ 2)\n",
    ]
    for key, count in cohort.excluded.items():
        lines.append(f"- {key}: {count}\n")
    if cohort.edge_mismatches:
        lines.append(f"\n⚠️ Невідповідностей збереженого edge_R: {cohort.edge_mismatches} — перевірити журнал.\n")
    lines.append("\n## Confirmatory результат (розділ 8)\n")
    if result["verdict"] == "insufficient_data":
        lines.append(f"- n = {result['n']} < {MIN_N} → **insufficient_data**, CI-вердикт не читається.\n")
        return "".join(lines)
    boot = result["bootstrap"]
    lines.append(f"- paired n = {result['n']}, днів D = {boot['days']}, валідних реплік = {boot['replicas']}\n")
    lines.append(f"- point estimate = {boot['point']:+.4f}R\n")
    lines.append(f"- 95% CI = [{boot['ci'][0]:+.4f}, {boot['ci'][1]:+.4f}]\n")
    lines.append("\n### Перевірки концентрації\n")
    for name, (passed, detail) in result["checks"].items():
        lines.append(f"- {'✅' if passed else '❌'} {name}: {detail}\n")
    lines.append(f"\n## Вердикт: **{result['verdict']}**\n")
    lines.append("\nЦе єдиний confirmatory look для v3.1. Продовження після inconclusive "
                 "потребує нової пререєстрації. Жоден результат не дозволяє автоматичну "
                 "торгівлю або реальні кошти.\n")
    return "".join(lines)
