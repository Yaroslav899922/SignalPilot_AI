"""Compare candidate arms against the dumb baseline on the frozen slice.

Net expectancy in R on live-visible sessions, with bootstrap CIs, train/test
split, and the difference vs baseline (trade- and month-block). Same honest
engine as the pullback rounds. Run: python -m signalpilot.rig.compare
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import metrics as M
from .dataset import SYMBOLS, load_all
from .engine import simulate

REPORT_DIR = Path(__file__).resolve().parents[3] / "reports"
TRAIN = ("2024-11", "2025-10")
TEST = ("2025-11", "2026-06")
ARMS = ["baseline", "pifagor_s1", "pullback_v1"]


def run(symbols=SYMBOLS):
    data = load_all(symbols)
    pooled = {}
    for arm in ARMS:
        trades, pc = [], 0
        for s in symbols:
            r = simulate(data[s], arm)
            trades.extend(r.trades)
            pc += r.plans_created
        pooled[arm] = {"trades": trades, "pc": pc}
    return pooled


def _vis(trades, per=None):
    out = [t for t in trades if t.session == "visible"]
    if per:
        lo, hi = per
        out = [t for t in out if lo <= t.month <= hi]
    return out


def _row(arm, trades):
    s = M.summarize(trades)
    return (f"| {arm} | {s['trades_resolved']} | **{s['expectancy_R']:+.3f}** | "
            f"[{s['ci_low']:+.3f}, {s['ci_high']:+.3f}] | {s['win_rate']:.0%} | {s['profit_factor']:.2f} |")


def build_report(pooled):
    L = ["# SignalPilot — RIG: Pifagor Strategy 1 vs baseline\n"]
    L.append(f"*Згенеровано {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Заморожений зріз, без зазирання вперед.*\n")
    L.append(f"*Символи: {', '.join(SYMBOLS)}. Видимі сесії (Київ 07-23). "
             f"Train {TRAIN[0]}...{TRAIN[1]}, Test {TEST[0]}...{TEST[1]}.*\n")
    L.append("\n**Pifagor S1 (механічне ядро):** імпульс із 2 свічок (друга оновлює екстремум, "
             "але не коригує далі 50% першої) -> фіба LOY..HAI -> один лімітний вхід на 50%, "
             "тейк 38.2%, стоп трохи за 61.8%. БЕЗ ladder-входів і БЕЗ докупівлі проти руху "
             "(«ракети»). Це консервативне ядро ідеї, а не повна дискреційна версія з вебінару.\n")

    L.append("\n## Критерій (як для pullback)\n")
    L.append("Залишаємо й розвиваємо, лише якщо різниця `pifagor - baseline` додатна, її "
             "month-block CI вище 0 на train, перевага стабільна по символах і підтверджена на test.\n")

    for zone, per in [("TRAIN", TRAIN), ("TEST", TEST)]:
        L.append(f"\n## {zone} (visible)\n")
        L.append("| Arm | Resolved | Expectancy R | 95% CI | Win | PF |\n|---|--:|--:|--:|--:|--:|\n")
        for arm in ARMS:
            L.append(_row(arm, _vis(pooled[arm]["trades"], per)) + "\n")
        d = M.difference_ci(_vis(pooled["pifagor_s1"]["trades"], per),
                            _vis(pooled["baseline"]["trades"], per))
        L.append(f"\n- **pifagor - baseline ({zone.lower()}): {d['point']:+.3f} R** | "
                 f"trade-CI [{d['trade_ci'][0]:+.3f}, {d['trade_ci'][1]:+.3f}] | "
                 f"month-CI [{d['month_ci'][0]:+.3f}, {d['month_ci'][1]:+.3f}]\n")

    L.append("\n## Pifagor по символах (TEST, visible)\n")
    L.append("| Символ | Угод | Expectancy R |\n|---|--:|--:|\n")
    for r in M.by_symbol(_vis(pooled["pifagor_s1"]["trades"], TEST)):
        L.append(f"| {r['symbol']} | {r['trades']} | {r['expectancy_R']:+.3f} |\n")

    L.append("\n## Fill-rate (увесь зріз)\n")
    for arm in ARMS:
        p = pooled[arm]
        L.append(f"- {arm}: {len(p['trades'])}/{p['pc']} = {len(p['trades'])/max(p['pc'],1):.0%}\n")

    d_tr = M.difference_ci(_vis(pooled["pifagor_s1"]["trades"], TRAIN),
                           _vis(pooled["baseline"]["trades"], TRAIN))
    d_te = M.difference_ci(_vis(pooled["pifagor_s1"]["trades"], TEST),
                           _vis(pooled["baseline"]["trades"], TEST))
    syms = M.by_symbol(_vis(pooled["pifagor_s1"]["trades"], TEST))
    passed = d_tr["month_ci"][0] > 0 and d_te["point"] > 0 and all(r["expectancy_R"] > 0 for r in syms)
    L.append("\n## Вердикт\n")
    L.append(f"- train: pifagor - baseline = {d_tr['point']:+.3f} R, "
             f"month-CI [{d_tr['month_ci'][0]:+.3f}, {d_tr['month_ci'][1]:+.3f}]\n")
    L.append(f"- test: різниця = {d_te['point']:+.3f} R; усі символи додатні: "
             f"{all(r['expectancy_R'] > 0 for r in syms)}\n")
    if passed:
        L.append("\n**Критерій виконано: є стабільна перевага.**\n")
    else:
        L.append("\n**Критерій НЕ виконано -> це механічне ядро Pifagor S1 програє тупому входу.** "
                 "Заявлений у вебінарі win-rate тут не відтворюється, а дрібний тейк (38.2%) дає "
                 "погане співвідношення ризик/прибуток. Ladder + «ракета» можуть підняти win-rate, "
                 "але ціною ризику зливу — це окрема, небезпечніша гіпотеза.\n")
    L.append("\n## Чесні обмеження\n")
    L.append("- Спрощено: один вхід на 50% замість 3 ліміток; без «ракети». Повна версія інша.\n")
    L.append("- RIG вирішує по 4h; автор вебінару радив день/тиждень. Можливо, на старших ТФ інакше.\n")
    L.append("- 15m лише для торкань; market-fill = open наступної 15m; unresolved виключені з R.\n")
    return "".join(L), passed


def main():
    pooled = run()
    report, passed = build_report(pooled)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = REPORT_DIR / f"rig-pifagor-{stamp}.md"
    path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
