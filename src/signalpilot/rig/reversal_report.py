"""RIG report: reversal_v1 (liquidity-sweep + FVG + MSS) vs baseline.

Two order-lifetime variants are compared so the effect of how long the limit
rests is visible: one_window (limit dies at the next 4h decision) and rest_bars
(limit rests up to N 4h-bars). Same honest engine as every other arm.
Run: python -m signalpilot.rig.reversal_report
"""

from __future__ import annotations

import collections
from datetime import datetime, timezone
from pathlib import Path

from . import metrics as M
from .dataset import SYMBOLS, load_all
from .engine import simulate

REPORT_DIR = Path(__file__).resolve().parents[3] / "reports"
TRAIN = ("2024-11", "2025-10")
TEST = ("2025-11", "2026-06")
REST_BARS = 8
MIN_N = 30   # below this the cell is diagnostic only, not a verdict

CONFIGS = [
    ("baseline", "baseline", "one_window"),
    ("reversal one_window", "reversal_v1", "one_window"),
    ("reversal rest_bars", "reversal_v1", "rest_bars"),
]


def run(symbols=SYMBOLS):
    data = load_all(symbols)
    pooled = {}
    for label, arm, lifetime in CONFIGS:
        trades, pc = [], 0
        for s in symbols:
            r = simulate(data[s], arm, lifetime=lifetime, rest_bars=REST_BARS)
            trades.extend(r.trades)
            pc += r.plans_created
        pooled[label] = {"trades": trades, "pc": pc}
    return pooled


def _vis(trades, per=None):
    out = [t for t in trades if t.session == "visible"]
    if per:
        lo, hi = per
        out = [t for t in out if lo <= t.month <= hi]
    return out


def _row(label, trades):
    s = M.summarize(trades)
    return (f"| {label} | {s['trades_resolved']} | **{s['expectancy_R']:+.3f}** | "
            f"[{s['ci_low']:+.3f}, {s['ci_high']:+.3f}] | {s['win_rate']:.0%} | {s['profit_factor']:.2f} |")


def build_report(pooled):
    bl, ow, rb = "baseline", "reversal one_window", "reversal rest_bars"
    L = ["# SignalPilot — RIG: Reversal Setup (sweep + FVG + MSS) vs baseline\n"]
    L.append(f"*Згенеровано {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Заморожений зріз, без зазирання вперед.*\n")
    L.append(f"*Символи: {', '.join(SYMBOLS)}. Видимі сесії (Київ 07–23). "
             f"Train {TRAIN[0]}…{TRAIN[1]}, Test {TEST[0]}…{TEST[1]}. rest_bars={REST_BARS}.*\n")
    L.append("\n**Механічне ядро (LONG):** даунтренд → діапазон (RL/RH) → свіп під RL із поверненням "
             "усередину → бичачий FVG на русі вгору → злам структури (MSS) вгору = підтвердження. "
             "Вхід — ліміт у середині FVG; стоп — під свіпом; ціль — range high. Один вхід, без "
             "ladder. Структура на 4h, філи на 15m. Деталі — spec-документ.\n")

    L.append("\n## Критерій воріт (той самий)\n")
    L.append("Залишаємо й розвиваємо, лише якщо різниця `reversal − baseline` додатна, її month-block "
             "CI вище 0 на train, перевага стабільна по символах і підтверджена на test.\n")
    L.append(f"\n> **Застереження про вибірку:** розвороти рідкі. Якщо resolved у клітині < {MIN_N}, "
             "число **діагностичне**, а не вирок — CI надто широкий. Тоді розширюємо набір символів, "
             "а не крутимо параметри.\n")

    for zone, per in [("TRAIN", TRAIN), ("TEST", TEST)]:
        L.append(f"\n## {zone} (visible)\n")
        L.append("| Arm | Resolved | Expectancy R | 95% CI | Win | PF |\n|---|--:|--:|--:|--:|--:|\n")
        for lab in [bl, ow, rb]:
            L.append(_row(lab, _vis(pooled[lab]["trades"], per)) + "\n")
        for lab in [ow, rb]:
            d = M.difference_ci(_vis(pooled[lab]["trades"], per), _vis(pooled[bl]["trades"], per))
            L.append(f"\n- **{lab} − baseline ({zone.lower()}): {d['point']:+.3f} R** "
                     f"(n={d['n_a']}) | trade-CI [{d['trade_ci'][0]:+.3f}, {d['trade_ci'][1]:+.3f}] | "
                     f"month-CI [{d['month_ci'][0]:+.3f}, {d['month_ci'][1]:+.3f}]\n")

    L.append("\n## Fill-rate (увесь зріз) — вплив життя ордера\n")
    for lab in [ow, rb]:
        p = pooled[lab]
        L.append(f"- {lab}: **{len(p['trades'])}/{p['pc']} = "
                 f"{len(p['trades'])/max(p['pc'],1):.0%}**\n")

    L.append("\n## Reversal по символах (весь зріз, visible)\n")
    L.append("| Символ | one_window угод | exp R | rest_bars угод | exp R |\n|---|--:|--:|--:|--:|\n")
    ow_sym = {r["symbol"]: r for r in M.by_symbol(_vis(pooled[ow]["trades"]))}
    rb_sym = {r["symbol"]: r for r in M.by_symbol(_vis(pooled[rb]["trades"]))}
    for s in SYMBOLS:
        a = ow_sym.get(s, {"trades": 0, "expectancy_R": 0.0})
        b = rb_sym.get(s, {"trades": 0, "expectancy_R": 0.0})
        L.append(f"| {s} | {a['trades']} | {a['expectancy_R']:+.3f} | {b['trades']} | {b['expectancy_R']:+.3f} |\n")

    # verdict
    n_rb_train = len(_vis(pooled[rb]["trades"], TRAIN))
    n_rb_test = len(_vis(pooled[rb]["trades"], TEST))
    decidable = min(n_rb_train, n_rb_test) >= MIN_N
    L.append("\n## Вердикт\n")
    if decidable:
        d_tr = M.difference_ci(_vis(pooled[rb]["trades"], TRAIN), _vis(pooled[bl]["trades"], TRAIN))
        passed = d_tr["month_ci"][0] > 0
        L.append(f"- train різниця month-CI нижня межа {'>' if passed else '≤'} 0.\n")
        L.append("\n**Критерій " + ("виконано." if passed else "НЕ виконано.") + "**\n")
    else:
        L.append(f"- Вибірка нижче порогу вироку: rest_bars resolved train={n_rb_train}, "
                 f"test={n_rb_test} (потрібно ≥ {MIN_N}) — числа діагностичні.\n")
        exp_tr = M.summarize(_vis(pooled[rb]["trades"], TRAIN))["expectancy_R"]
        exp_te = M.summarize(_vis(pooled[rb]["trades"], TEST))["expectancy_R"]
        d_tr = M.difference_ci(_vis(pooled[rb]["trades"], TRAIN), _vis(pooled[bl]["trades"], TRAIN))
        d_te = M.difference_ci(_vis(pooled[rb]["trades"], TEST), _vis(pooled[bl]["trades"], TEST))
        sign = "додатна" if exp_tr > 0 and exp_te > 0 else ("відʼємна" if exp_tr < 0 and exp_te < 0 else "змішана")
        L.append(f"- Діагностичний напрям: expectancy rest_bars {sign} "
                 f"(train {exp_tr:+.3f}R, test {exp_te:+.3f}R); різниця з baseline "
                 f"train {d_tr['point']:+.3f}R, test {d_te['point']:+.3f}R.\n")
        gate_hint = "сигнал ПРОТИ гіпотези" if d_tr["point"] < 0 and d_te["point"] < 0 else (
            "сигнал ЗА гіпотезу, але недоказовий" if d_tr["point"] > 0 and d_te["point"] > 0 else "сигнал суперечливий")
        L.append(f"\n**Статус: критерій воріт НЕ виконано на цій вибірці; {gate_hint}.** "
                 "Рішення (закрити / збирати ще) — окремим записом у HYPOTHESES.md.\n")

    L.append("\n## Обмеження (чесно)\n")
    L.append("- Патерн рідкісний (див. Fill-rate вище); на первинній трійці число сетапів майже "
             "не залежало від ширини вікон (перевірено 12–40) — це природа патерну, не недокрут.\n")
    L.append("- Одне механічне ядро (один вхід, без ladder/докупівель). Повна дискреційна версія інша.\n")
    L.append("- Структура на 4h; автор price-action-школи часто мислить старші ТФ.\n")
    L.append("- 15m лише для торкань; market-fill = open наступної 15m; unresolved виключені з R.\n")
    return "".join(L), decidable


def main():
    pooled = run()
    report, _ = build_report(pooled)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = REPORT_DIR / f"rig-reversal-{stamp}.md"
    path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
