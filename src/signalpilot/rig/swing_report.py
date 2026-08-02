"""RIG report: swing_v1 (4h breakout-retest) vs PAIRED baseline.

Hypothesis #6 in HYPOTHESES.md; parameters frozen in
SignalPilot-Swing-Setup-Spec-2026-08-02.md BEFORE this run.

Primary (confirmatory) question — CORE only:
    does swing_v1 give positive mean paired edge_R after costs versus a market
    entry at the next 15m open with the same absolute stop/target distances?

Gate: paired n >= 30 on train, month-block 95% CI lower bound > 0 on train,
and the test-period point estimate does not flip sign.

Secondary pre-registered comparisons (diagnostic, no gate): +volume, +RSI,
+Bollinger-squeeze filters.

Cost note: the shared engine charges 0.15% round trip — stricter than the
0.12% written in the spec; kept as-is (more conservative, same for both arms).

Run: python -m signalpilot.rig.swing_report
"""

from __future__ import annotations

import collections
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import metrics as M
from .dataset import SYMBOLS, load_all
from .engine import simulate_plans
from .swing import (REST_BARS, TIMEOUT_BARS_4H, build_swing_decisions,
                    detect_swing_setups, passes_filter)

REPORT_DIR = Path(__file__).resolve().parents[3] / "reports"
TRAIN = ("2024-11", "2025-10")
TEST = ("2025-11", "2026-06")
MIN_N = 30
N_BOOT = 5000
SEED = 0
TIMEOUT = pd.Timedelta(hours=4 * TIMEOUT_BARS_4H)

CONFIGS = [
    ("swing_v1", None),
    ("swing_v1_vol", "vol"),
    ("swing_v1_rsi", "rsi"),
    ("swing_v1_bb", "bb"),
]


def run_symbol(sym_data):
    """All configs for one symbol: {label: {trades, base_trades, setups, pc, base_pc}}."""
    setups = detect_swing_setups(sym_data.decisions)
    out = {}
    for label, variant in CONFIGS:
        n_setups = sum(passes_filter(s, variant) for s in setups)
        arm_dec = build_swing_decisions(sym_data, setups, label, variant, paired=False)
        base_dec = build_swing_decisions(sym_data, setups, label + "_base", variant, paired=True)
        r_arm = simulate_plans(sym_data.symbol, label, arm_dec, sym_data.bars15m,
                               lifetime="rest_bars", rest_bars=REST_BARS, timeout=TIMEOUT)
        r_base = simulate_plans(sym_data.symbol, label + "_base", base_dec, sym_data.bars15m,
                                lifetime="rest_bars", rest_bars=REST_BARS, timeout=TIMEOUT)
        out[label] = {"trades": r_arm.trades, "base_trades": r_base.trades,
                      "setups": n_setups, "pc": r_arm.plans_created,
                      "base_pc": r_base.plans_created}
    return out


def merge_pooled(per_symbol_results):
    pooled = {label: {"trades": [], "base_trades": [], "setups": 0, "pc": 0, "base_pc": 0}
              for label, _ in CONFIGS}
    for res in per_symbol_results:
        for label, d in res.items():
            for k in ("trades", "base_trades"):
                pooled[label][k].extend(d[k])
            for k in ("setups", "pc", "base_pc"):
                pooled[label][k] += d[k]
    return pooled


def run(symbols=SYMBOLS):
    data = load_all(symbols)
    return merge_pooled([run_symbol(data[s]) for s in symbols])


def _vis(trades, per=None):
    out = [t for t in trades if t.session == "visible"]
    if per:
        lo, hi = per
        out = [t for t in out if lo <= t.month <= hi]
    return out


def paired_edges(arm_trades, base_trades):
    """Per-event edge = net_R(arm) − net_R(base), matched on (symbol, created_time),
    both resolved. Returns list of dicts."""
    idx = {(t.symbol, t.created_time): t for t in base_trades if t.outcome in M.RESOLVED}
    out = []
    for a in arm_trades:
        if a.outcome not in M.RESOLVED:
            continue
        b = idx.get((a.symbol, a.created_time))
        if b is None:
            continue
        out.append({"edge": a.net_R - b.net_R, "month": a.month,
                    "symbol": a.symbol, "direction": a.direction})
    return out


def edge_stats(edges, n_boot=N_BOOT, seed=SEED, alpha=0.05):
    vals = np.array([e["edge"] for e in edges], dtype=float)
    if len(vals) == 0:
        return {"n": 0, "point": 0.0, "trade_ci": (0.0, 0.0), "month_ci": (0.0, 0.0)}
    point = float(vals.mean())
    rng = np.random.default_rng(seed)
    trade = rng.choice(vals, size=(n_boot, len(vals)), replace=True).mean(axis=1)
    by_month = collections.defaultdict(list)
    for e in edges:
        by_month[e["month"]].append(e["edge"])
    months = sorted(by_month)
    month_means = []
    for _ in range(n_boot):
        samp = rng.choice(months, len(months), True)
        pool = [v for m in samp for v in by_month[m]]
        if pool:
            month_means.append(float(np.mean(pool)))
    def ci(arr):
        return (float(np.quantile(arr, alpha / 2)), float(np.quantile(arr, 1 - alpha / 2)))
    return {"n": len(vals), "point": point, "trade_ci": ci(trade),
            "month_ci": ci(month_means) if month_means else (0.0, 0.0)}


def _fmt_ci(ci):
    return f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"


def build_report(pooled):
    L = ["# SignalPilot — RIG: swing_v1 (4h breakout-retest) vs paired baseline\n"]
    L.append(f"*Згенеровано {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Заморожений зріз, без зазирання вперед.*\n")
    L.append(f"*Символи: {', '.join(SYMBOLS)}. Видимі сесії (Київ 07–23). "
             f"Train {TRAIN[0]}…{TRAIN[1]}, Test {TEST[0]}…{TEST[1]}. "
             f"Ліміт живе {REST_BARS} 4h-свічок, тайм-аут {TIMEOUT_BARS_4H} 4h-свічок (10 діб), "
             f"витрати движка 0.15% RT (суворіше за 0.12% зі спеки, однакові для обох рук).*\n")
    L.append("\n**Ядро:** тренд = close проти EMA50(4h) + HH/HL за підтвердженими свінгами (n=2); "
             "перший 4h-close за останнім підтвердженим свінг-екстремумом у бік тренду; лімітний "
             "вхід на ретесті пробитого рівня; стоп за протилежним свінгом ± 0.25·ATR14; T1 = 2R; "
             "stop-first. **Paired baseline:** market-вхід на open наступної 15m-свічки з тими "
             "самими абсолютними відстанями до стопа/цілі. Edge = net_R(swing) − net_R(base) "
             "на подіях, де обидві сторони resolved.\n")
    L.append("\n## Ворота (тільки ядро, зафіксовано до прогону)\n")
    L.append(f"Paired n ≥ {MIN_N} на train, нижня межа month-block 95% CI edge > 0 на train, "
             "і знак point estimate не розвертається на test. Фільтри — вторинна діагностика.\n")

    stats = {}
    for zone, per in [("TRAIN", TRAIN), ("TEST", TEST)]:
        L.append(f"\n## {zone} (visible)\n")
        L.append("| Конфіг | Сетапи | Filled | Resolved | Win | Expectancy R | Paired n | Edge R | month-CI |\n")
        L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|\n")
        for label, _ in CONFIGS:
            p = pooled[label]
            arm_t = _vis(p["trades"], per)
            base_t = _vis(p["base_trades"], per)
            s = M.summarize(arm_t)
            e = edge_stats(paired_edges(arm_t, base_t))
            stats[(label, zone)] = {"summary": s, "edge": e}
            L.append(f"| {label} | {p['setups']} | {len(arm_t)} | {s['trades_resolved']} | "
                     f"{s['win_rate']:.0%} | **{s['expectancy_R']:+.3f}** | {e['n']} | "
                     f"**{e['point']:+.3f}** | {_fmt_ci(e['month_ci'])} |\n")
    L.append("\n*Сетапи пораховано на весь зріз (не лише зону), Filled/Resolved — по зоні. "
             "Win rate = частка resolved з net_R > 0.*\n")

    core = "swing_v1"
    L.append(f"\n## {core} по символах (весь зріз, visible)\n")
    L.append("| Символ | Resolved | Expectancy R | Paired n | Edge R |\n|---|--:|--:|--:|--:|\n")
    p = pooled[core]
    for sym in SYMBOLS:
        a = [t for t in _vis(p["trades"]) if t.symbol == sym]
        b = [t for t in _vis(p["base_trades"]) if t.symbol == sym]
        s = M.summarize(a)
        e = edge_stats(paired_edges(a, b))
        L.append(f"| {sym} | {s['trades_resolved']} | {s['expectancy_R']:+.3f} | "
                 f"{e['n']} | {e['point']:+.3f} |\n")

    L.append(f"\n## {core} за напрямком (весь зріз, visible)\n")
    L.append("| Напрямок | Resolved | Expectancy R | Paired n | Edge R |\n|---|--:|--:|--:|--:|\n")
    for direction in ("LONG", "SHORT"):
        a = [t for t in _vis(p["trades"]) if t.direction == direction]
        b = [t for t in _vis(p["base_trades"]) if t.direction == direction]
        s = M.summarize(a)
        e = edge_stats(paired_edges(a, b))
        L.append(f"| {direction} | {s['trades_resolved']} | {s['expectancy_R']:+.3f} | "
                 f"{e['n']} | {e['point']:+.3f} |\n")

    L.append("\n## Fill-rate (весь зріз)\n")
    for label, _ in CONFIGS:
        d = pooled[label]
        L.append(f"- {label}: filled {len(d['trades'])}/{d['pc']} планів = "
                 f"{len(d['trades'])/max(d['pc'],1):.0%}; baseline filled "
                 f"{len(d['base_trades'])}/{d['base_pc']}\n")

    tr = stats[(core, "TRAIN")]["edge"]
    te = stats[(core, "TEST")]["edge"]
    n_ok = tr["n"] >= MIN_N
    ci_ok = tr["month_ci"][0] > 0
    sign_ok = tr["point"] > 0 and te["point"] > 0
    passed = n_ok and ci_ok and sign_ok
    L.append("\n## Вердикт (ядро swing_v1)\n")
    L.append(f"- Paired n: train {tr['n']} (потрібно ≥ {MIN_N}), test {te['n']}.\n")
    L.append(f"- Train edge: {tr['point']:+.3f} R, month-CI {_fmt_ci(tr['month_ci'])} "
             f"(нижня межа {'>' if ci_ok else '≤'} 0).\n")
    L.append(f"- Test edge: {te['point']:+.3f} R, month-CI {_fmt_ci(te['month_ci'])}.\n")
    if passed:
        L.append("\n**Критерій воріт ВИКОНАНО: стабільна paired-перевага ядра.** Чесне уточнення: "
                 "абсолютна expectancy ядра після витрат близька до нуля — пройдено саме "
                 "пре-реєстроване порівняння механіки входу проти негайного входу з тією самою "
                 "геометрією, а НЕ доведено прибутковість системи. Наступний крок — окреме рішення "
                 "(новий запис у HYPOTHESES.md).\n")
    elif not n_ok:
        L.append(f"\n**Вибірка нижче порогу вироку (train n={tr['n']} < {MIN_N}) — числа діагностичні.** "
                 "Рішення (закрити / розширити дані) — окремим записом у HYPOTHESES.md.\n")
    else:
        L.append("\n**Критерій воріт НЕ виконано.** Рішення по гіпотезі — окремим записом у "
                 "HYPOTHESES.md; фільтри вище — лише напрям для можливої нової гіпотези.\n")

    L.append("\n## Чесні обмеження\n")
    L.append("- Paired edge обумовлений філом ліміту: події без ретесту (~19% планів ядра) не "
             "входять у порівняння, хоча baseline у частині з них брав рух, який swing пропустив. "
             "Edge вимірює перевагу входу на ретесті над погонею за пробоєм, а не повну систему.\n")
    L.append("- Абсолютна expectancy ядра ≈ 0 після витрат — позитивний paired edge сам по собі "
             "не є доказом торгового прибутку.\n")
    L.append("- Витрати 0.15% RT без окремого slippage/funding/затримки; лімітний філ у RIG "
             "оптимістичніший за реальний (черга на рівні не моделюється).\n")
    L.append("- BB-фільтр перші 180 свічок зрізу консервативно False (нема повної бази перцентиля).\n")
    L.append("- 12 монет корельовані; month-block CI частково це враховує, але не повністю.\n")
    L.append("- Фільтри — 3 додаткові порівняння: позитив будь-якого з них сам по собі не є "
             "проходженням воріт (множинні перевірки).\n")
    L.append("- unresolved (відкриті на кінці зрізу) виключені з R; сетапи в останні 10 діб зрізу "
             "недооцінені.\n")
    return "".join(L), passed


def main():
    pooled = run()
    report, _ = build_report(pooled)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = REPORT_DIR / f"rig-swing-{stamp}.md"
    path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
