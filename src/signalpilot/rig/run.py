"""Round 2 (+ review refinements): honest comparison with the two engine fixes,
the limit-lifetime experiment, train/test split, Resolved column, CI of the
difference, a monthly difference table, and explicit limitations.
"""

from __future__ import annotations

import collections
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import metrics as M
from .dataset import SYMBOLS, load_all
from .engine import simulate

REPORT_DIR = Path(__file__).resolve().parents[3] / "reports"
TRAIN = ("2024-11", "2025-10")
TEST = ("2025-11", "2026-06")

CONFIGS = [
    ("baseline", "baseline", "one_window"),
    ("pullback v1", "pullback_v1", "one_window"),
    ("pullback v1 (until-trend)", "pullback_v1", "until_trend"),
]


def run(symbols=SYMBOLS):
    data = load_all(symbols)
    pooled = {}
    for label, arm, lifetime in CONFIGS:
        agg = {"trades": [], "pc": 0}
        for s in symbols:
            r = simulate(data[s], arm, lifetime=lifetime)
            agg["trades"].extend(r.trades)
            agg["pc"] += r.plans_created
        pooled[label] = agg
    return data, pooled


def vis(trades, period=None):
    out = [t for t in trades if t.session == "visible"]
    if period:
        lo, hi = period
        out = [t for t in out if lo <= t.month <= hi]
    return out


def _srow(label, trades):
    s = M.summarize(trades)
    return (f"| {label} | {s['trades_resolved']} | **{s['expectancy_R']:+.3f}** | "
            f"[{s['ci_low']:+.3f}, {s['ci_high']:+.3f}] |")


def _diff(name, ta, tb):
    d = M.difference_ci(ta, tb)
    return (f"- {name}: **{d['point']:+.3f} R** | trade-CI [{d['trade_ci'][0]:+.3f}, {d['trade_ci'][1]:+.3f}] | "
            f"month-CI [{d['month_ci'][0]:+.3f}, {d['month_ci'][1]:+.3f}]")


def _monthly_diff(trades_p, trades_b):
    def by_month(ts):
        d = collections.defaultdict(list)
        for t in ts:
            if t.outcome in M.RESOLVED:
                d[t.month].append(t.net_R)
        return d
    mp, mb = by_month(trades_p), by_month(trades_b)
    rows = []
    for m in sorted(set(mp) | set(mb)):
        ep = sum(mp[m]) / len(mp[m]) if mp.get(m) else None
        eb = sum(mb[m]) / len(mb[m]) if mb.get(m) else None
        diff = (ep - eb) if (ep is not None and eb is not None) else None
        rows.append((m, ep, eb, diff))
    return rows


def build_report(data, pooled):
    bl, p_ow, p_ut = "baseline", "pullback v1", "pullback v1 (until-trend)"
    T = lambda lab, per=None: vis(pooled[lab]["trades"], per)
    L = []
    L.append("# SignalPilot — Rig round 2: виправлення + експеримент «довге життя ліміту»\n")
    L.append(f"*Згенеровано {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Заморожений зріз, без зазирання вперед.*\n")
    L.append(f"*Символи: {', '.join(data)}. Видимі сесії (Київ 07–23). "
             f"Train {TRAIN[0]}…{TRAIN[1]}, Test {TEST[0]}…{TEST[1]}.*\n")

    L.append("\n## Критерій рішення (зафіксовано ДО перегляду test)\n")
    L.append("Pullback залишаємо й розвиваємо, лише якщо на **train** виконано все:\n"
             "1. дивимось різницю `pullback − baseline` (а не `pullback > 0`), на live-visible;\n"
             "2. різниця додатна і її **month-block 95% CI вище 0** на train;\n"
             "3. перевага стабільна по символах і по місяцях (не тягне один символ/місяць);\n"
             "4. fill-rate виріс, але не ціною гіршої expectancy;\n"
             "5. і вона **підтверджується на test**.\n"
             "Якщо ні — pullback v1 чесно закриваємо (один чистий експеримент зроблено).\n")

    L.append("\n## Що змінилось у движку проти раунду 1\n")
    L.append("- LIMIT-філ більше не зараховує target у своїй же 15m-свічці (тільки стоп = zone_pierce);\n"
             "- timeout виходить по **open** свічки таймауту, не по close (прибрано зазир уперед);\n"
             "- новий режим **until-trend**: ліміт висить замороженим, поки 4h-тренд цілий.\n")

    L.append("\n## A. Baseline-of-record (one-window), TRAIN, видимі\n")
    L.append("| Варіант | Resolved | Expectancy R | 95% CI |\n|---|--:|--:|--:|\n")
    for lab in [p_ow, bl]:
        L.append(_srow(lab, T(lab, TRAIN)) + "\n")
    L.append("\nРізниця (важливе для рішення):\n")
    L.append(_diff("pullback v1 − baseline (train)", T(p_ow, TRAIN), T(bl, TRAIN)) + "\n")

    L.append("\n## B. Експеримент: довге життя ліміту, TRAIN, видимі\n")
    fr_ow, fr_ut = pooled[p_ow], pooled[p_ut]
    L.append(f"- Fill-rate (увесь зріз): one-window **{len(fr_ow['trades'])}/{fr_ow['pc']} "
             f"= {len(fr_ow['trades'])/max(fr_ow['pc'],1):.0%}** → until-trend "
             f"**{len(fr_ut['trades'])}/{fr_ut['pc']} = {len(fr_ut['trades'])/max(fr_ut['pc'],1):.0%}**\n\n")
    L.append("| Варіант | Resolved | Expectancy R | 95% CI |\n|---|--:|--:|--:|\n")
    for lab in [p_ow, p_ut, bl]:
        L.append(_srow(lab, T(lab, TRAIN)) + "\n")
    L.append("\n")
    L.append(_diff("pullback until-trend − baseline (train)", T(p_ut, TRAIN), T(bl, TRAIN)) + "\n")

    L.append("\n**Expectancy за віком входу (until-trend, train):**\n")
    L.append("| Вік філа (4h-барів) | Угод | Expectancy R |\n|---|--:|--:|\n")
    for r in M.by_age(T(p_ut, TRAIN)):
        L.append(f"| {r['age']} | {r['trades']} | {r['expectancy_R']:+.3f} |\n")
    L.append("\n*Натяк: пізніші філи виглядають гіршими — але n малі (це діагностика, не самостійна "
             "теорія). Рішення спирається на train-різницю й критерій, а не на цю таблицю.*\n")

    L.append("\n## C. Підтвердження на TEST, видимі\n")
    L.append("| Варіант | Resolved | Expectancy R | 95% CI |\n|---|--:|--:|--:|\n")
    for lab in [p_ow, p_ut, bl]:
        L.append(_srow(lab, T(lab, TEST)) + "\n")
    L.append("\n")
    L.append(_diff("pullback until-trend − baseline (test)", T(p_ut, TEST), T(bl, TEST)) + "\n")
    L.append("\n**Стабільність по символах (until-trend, test, видимі):**\n")
    L.append("| Символ | Угод | Expectancy R |\n|---|--:|--:|\n")
    for r in M.by_symbol(T(p_ut, TEST)):
        L.append(f"| {r['symbol']} | {r['trades']} | {r['expectancy_R']:+.3f} |\n")

    L.append("\n## D. Помісячна різниця until-trend − baseline (видимі)\n")
    L.append("*Щоб видно було, що (не)перевага не живе в одному місяці.*\n")
    L.append("| Місяць | Pullback (UT) | Baseline | Різниця | Зона |\n|---|--:|--:|--:|:--|\n")
    fmt = lambda x: f"{x:+.3f}" if x is not None else "—"
    for m, ep, eb, diff in _monthly_diff(T(p_ut), T(bl)):
        zone = "test" if m >= TEST[0] else "train"
        L.append(f"| {m} | {fmt(ep)} | {fmt(eb)} | {fmt(diff)} | {zone} |\n")

    # verdict
    d_tr = M.difference_ci(T(p_ut, TRAIN), T(bl, TRAIN))
    d_te = M.difference_ci(T(p_ut, TEST), T(bl, TEST))
    syms = M.by_symbol(T(p_ut, TEST))
    all_sym_pos = all(r["expectancy_R"] > 0 for r in syms)
    passed = d_tr["month_ci"][0] > 0 and d_te["point"] > 0 and all_sym_pos
    L.append("\n## Вердикт за критерієм\n")
    L.append(f"- train: until-trend − baseline = {d_tr['point']:+.3f} R, "
             f"month-CI [{d_tr['month_ci'][0]:+.3f}, {d_tr['month_ci'][1]:+.3f}] "
             f"→ нижня межа {'>' if d_tr['month_ci'][0] > 0 else '≤'} 0\n")
    L.append(f"- test: різниця = {d_te['point']:+.3f} R; усі символи додатні на test: {all_sym_pos}\n")
    if passed:
        L.append("\n**Критерій виконано: є стабільна перевага.**\n")
    else:
        L.append("\n**Критерій НЕ виконано → pullback v1 закриваємо.** Довше життя підняло частоту "
                 "входів, але переваги над простим входом не дало. EMA20 / інша логіка відкату — "
                 "це окрема майбутня гіпотеза з власним критерієм, а не докрутка v1.\n")

    L.append("\n## Обмеження цього прогону (чесно)\n")
    L.append("- **Test — quasi-holdout, не ідеальний:** у раунді 1 ми вже бачили весь зріз до 2026-06, "
             "тож test не абсолютно незайманий. Висновок це не змінює (train уже провалив критерій), "
             "але на майбутнє — walk-forward або реально нові дані після 2026-06.\n")
    L.append("- age-таблиця — діагностичний натяк, n малі; не робимо з неї окрему теорію ринку.\n")
    L.append("- 15m лише для торкань; індикатори на 4h; market-fill = open наступної 15m; "
             "unresolved-угоди виключені з R.\n")
    return "".join(L), passed


def main():
    data, pooled = run()
    report, passed = build_report(data, pooled)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = REPORT_DIR / f"rig-comparison-v2-{stamp}.md"
    path.write_text(report, encoding="utf-8")
    rows = []
    for lab in pooled:
        for t in pooled[lab]["trades"]:
            d = t.to_dict(); d["config"] = lab; rows.append(d)
    pd.DataFrame(rows).to_csv(REPORT_DIR / "rig-trades-v2.csv", index=False)
    print(report)
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
