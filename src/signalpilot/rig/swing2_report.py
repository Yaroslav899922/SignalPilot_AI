"""RIG report for hypothesis #7: swing_v2 exits vs swing_v1 on the SAME entries.

Control = swing_v1 itself (fixed 2R, 60-bar timeout) re-simulated on the same
data. Per-event edge = net_R(v2) - net_R(v1) matched on (symbol, created_time):
the entries are identical, so the difference is purely the exit rule.

Gate (core swing_v2_trail only, frozen in the spec BEFORE this run):
paired n >= 30 on train; month-block 95% CI lower bound > 0 on train; the
test-period sign does not flip; AND absolute expectancy of the core after
costs > 0 on BOTH train and test.

Run: python -m signalpilot.rig.swing2_report
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import metrics as M
from .dataset import SYMBOLS, load_all
from .swing import REST_BARS, TIMEOUT_BARS_4H, build_swing_decisions, detect_swing_setups
from .swing_exits import (TRAIL_TIMEOUT_BARS_4H, StructureTrailer,
                          simulate_plans_exits)
from .swing_report import _vis, edge_stats, paired_edges, _fmt_ci

REPORT_DIR = Path(__file__).resolve().parents[3] / "reports"
TRAIN = ("2024-11", "2025-10")
TEST = ("2025-11", "2026-06")
MIN_N = 30
V1_TIMEOUT = pd.Timedelta(hours=4 * TIMEOUT_BARS_4H)
TRAIL_TIMEOUT = pd.Timedelta(hours=4 * TRAIL_TIMEOUT_BARS_4H)

CONFIGS = [
    ("swing_v1 (2R, контроль)", "v1"),
    ("swing_v2_trail (ядро)", "trail"),
    ("swing_v2_3R", "3R"),
    ("swing_v2_4R", "4R"),
]


def _retarget(plan, mult: float):
    """Fixed-target variant: same entry/stop, target at ``mult``x risk."""
    from dataclasses import replace
    risk = abs(plan.entry - plan.stop)
    sign = 1.0 if plan.direction == "LONG" else -1.0
    return replace(plan, target=plan.entry + sign * mult * risk)


def _detarget(plan):
    """Trail variant: no reachable fixed target (stop/cap exits only)."""
    from dataclasses import replace
    import math
    sign = 1.0 if plan.direction == "LONG" else -1.0
    return replace(plan, target=sign * math.inf)


def run_symbol(sym_data):
    setups = detect_swing_setups(sym_data.decisions)
    base = build_swing_decisions(sym_data, setups, "swing_v2", None, paired=False)
    trailer = StructureTrailer.from_decisions(sym_data.decisions)
    out = {}
    for label, kind in CONFIGS:
        if kind == "v1":
            decisions, timeout, trail = base, V1_TIMEOUT, None
        elif kind == "trail":
            decisions = [(t, _detarget(p) if p else None, tr) for t, p, tr in base]
            timeout, trail = TRAIL_TIMEOUT, trailer
        else:
            mult = 3.0 if kind == "3R" else 4.0
            decisions = [(t, _retarget(p, mult) if p else None, tr) for t, p, tr in base]
            timeout, trail = V1_TIMEOUT, None
        result = simulate_plans_exits(sym_data.symbol, label, decisions,
                                      sym_data.bars15m, rest_bars=REST_BARS,
                                      timeout=timeout, trailer=trail)
        out[label] = {"trades": result.trades, "pc": result.plans_created,
                      "blocked": result.plans_blocked}
    return out


def merge_pooled(per_symbol):
    pooled = {label: {"trades": [], "pc": 0, "blocked": 0} for label, _ in CONFIGS}
    for res in per_symbol:
        for label, d in res.items():
            pooled[label]["trades"].extend(d["trades"])
            pooled[label]["pc"] += d["pc"]
            pooled[label]["blocked"] += d["blocked"]
    return pooled


def run(symbols=SYMBOLS):
    data = load_all(symbols)
    return merge_pooled([run_symbol(data[s]) for s in symbols])


def build_report(pooled):
    control = CONFIGS[0][0]
    core = CONFIGS[1][0]
    L = ["# SignalPilot — RIG: swing_v2 (структурні виходи) vs swing_v1 на тих самих входах\n"]
    L.append(f"*Згенеровано {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Заморожений зріз (подовжений до 2026-08), без зазирання вперед.*\n")
    L.append(f"*Символи: {', '.join(SYMBOLS)}. Видимі сесії (Київ 07–23). Train {TRAIN[0]}…{TRAIN[1]}, "
             f"Test {TEST[0]}…{TEST[1]}. Вхід і початковий стоп ідентичні swing_v1; витрати 0.15% RT. "
             f"Ядро: трейлінг за підтвердженими 4h-свінгами (буфер 0.25·ATR14), без фіксованої цілі, "
             f"кап 30 діб. Варіанти: фіксовані цілі 3R і 4R (тайм-аут 10 діб).*\n")
    L.append("\n## Ворота (тільки ядро, зафіксовано до прогону)\n")
    L.append(f"Paired n ≥ {MIN_N} на train; нижня межа month-block 95% CI edge(v2−v1) > 0 на train; "
             "знак не розвертається на test; І додатково — абсолютна expectancy ядра після витрат > 0 "
             "на train і test.\n")

    stats = {}
    for zone, per in [("TRAIN", TRAIN), ("TEST", TEST)]:
        L.append(f"\n## {zone} (visible)\n")
        L.append("| Конфіг | Resolved | Win | Стоп | Тайм-аут | Expectancy R | Сер. тримання (4h барів) | Paired n | Edge vs v1 | month-CI |\n")
        L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|\n")
        control_trades = _vis(pooled[control]["trades"], per)
        for label, _kind in CONFIGS:
            trades = _vis(pooled[label]["trades"], per)
            s = M.summarize(trades)
            if label == control:
                e = {"n": 0, "point": 0.0, "month_ci": (0.0, 0.0)}
                edge_cell, ci_cell = "—", "—"
            else:
                e = edge_stats(paired_edges(trades, control_trades))
                edge_cell, ci_cell = f"**{e['point']:+.3f}**", _fmt_ci(e["month_ci"])
            stats[(label, zone)] = {"summary": s, "edge": e}
            L.append(f"| {label} | {s['trades_resolved']} | {s['win_rate']:.0%} | {s['stop_rate']:.0%} | "
                     f"{s['timeout_rate']:.0%} | **{s['expectancy_R']:+.3f}** | {s['avg_hold_bars']:.1f} | "
                     f"{e['n']} | {edge_cell} | {ci_cell} |\n")

    L.append("\n## Заблоковані плани (весь зріз) — ціна довшого тримання\n")
    for label, _kind in CONFIGS:
        d = pooled[label]
        L.append(f"- {label}: створено {d['pc']}, заблоковано відкритою угодою {d['blocked']}\n")

    tr = stats[(core, "TRAIN")]
    te = stats[(core, "TEST")]
    n_ok = tr["edge"]["n"] >= MIN_N
    ci_ok = tr["edge"]["month_ci"][0] > 0
    sign_ok = tr["edge"]["point"] > 0 and te["edge"]["point"] > 0
    exp_ok = tr["summary"]["expectancy_R"] > 0 and te["summary"]["expectancy_R"] > 0
    passed = n_ok and ci_ok and sign_ok and exp_ok
    L.append("\n## Вердикт (ядро swing_v2_trail)\n")
    L.append(f"- Paired n: train {tr['edge']['n']} (потрібно ≥ {MIN_N}), test {te['edge']['n']}.\n")
    L.append(f"- Train edge vs v1: {tr['edge']['point']:+.3f} R, month-CI {_fmt_ci(tr['edge']['month_ci'])} "
             f"(нижня межа {'>' if ci_ok else '≤'} 0).\n")
    L.append(f"- Test edge vs v1: {te['edge']['point']:+.3f} R.\n")
    L.append(f"- Expectancy ядра: train {tr['summary']['expectancy_R']:+.3f} R, "
             f"test {te['summary']['expectancy_R']:+.3f} R (вимога: обидва > 0 — "
             f"{'виконано' if exp_ok else 'НЕ виконано'}).\n")
    if passed:
        L.append("\n**УСІ умови воріт виконано: структурні виходи дають додатну expectancy і стабільну "
                 "перевагу над фіксованими 2R.** Наступний крок — окреме рішення про forward-інтеграцію.\n")
    else:
        misses = []
        if not n_ok: misses.append("замала вибірка")
        if not ci_ok: misses.append("CI накриває 0 на train")
        if not sign_ok: misses.append("знак edge нестабільний")
        if not exp_ok: misses.append("expectancy не додатна на обох періодах")
        L.append(f"\n**Критерій воріт НЕ виконано ({'; '.join(misses)}).** Рішення по гіпотезі №7 — "
                 "чесним записом у HYPOTHESES.md; 3R/4R — лише діагностика.\n")

    L.append("\n## Чесні обмеження\n")
    L.append("- Вхід успадковано від swing_v1, тому висновок стосується ЛИШЕ вихідної геометрії.\n")
    L.append("- Трейлінг тримає угоди довше → більше заблокованих планів і менше незалежних спостережень "
             "на місяць; month-CI це частково враховує.\n")
    L.append("- Дані подовжено до 2026-08, але train/test вікна ті самі, що у звіті swing_v1; кількість "
             "сетапів на весь зріз тому більша за перший звіт.\n")
    L.append("- unresolved на кінці зрізу виключені з R (для трейлінгу їх більше через 30-денний кап).\n")
    L.append("- Паритет симулятора з движком закріплено окремим тестом (fixed 2R = движок байт у байт).\n")
    return "".join(L), passed


def main():
    pooled = run()
    report, _ = build_report(pooled)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = REPORT_DIR / f"rig-swing2-{stamp}.md"
    path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
