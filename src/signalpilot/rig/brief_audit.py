"""Forward-audit табель живого брифу: порада -> що сталося (offline, RIG-культура).

Правила оцінки зафіксовано ДО першого прогону (2026-07-04):

- Джерело цін: ті самі Binance USD-M 15m-бари (data/ohlcv/*_15m.csv), що й у брифів.
- Оцінка кожного сценарію незалежна, вікно = HORIZON_H годин від часу брифу.
- EL/ES (ранній від підтримки/опору): активація = торкання зони (low<=z2 для LONG,
  high>=z1 для SHORT), потім 15m close за conf-рівнем у бік сценарію. Якщо до
  активації close пробиває інвалідацію — сценарій скасовано (cancelled).
- CL/CS (консервативний пробій): активація = 1h close за рівнем пробою (z1);
  інвалідація після входу = 15m close назад за рівень пробою (припущення,
  у тексті брифу цей стоп не заданий).
- Після входу перший з: ціль t1 (touch high/low) чи інвалідація (15m close) чи
  таймаут. Якщо в одному 15m-барі і ціль, і інвалідація — рахуємо інвалідацію
  (консервативно, як stop-first у RIG).
- Вхід = ціна close бару підтвердження (без комісій; це табель, не бектест PnL).
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BRIEFS_CSV = ROOT / "data" / "brief_audit" / "briefs-parsed.csv"
DATA_DIR = ROOT / "data" / "ohlcv"
REPORT = ROOT / "reports" / f"brief-audit-{datetime.now(timezone.utc):%Y-%m-%d}.md"
HORIZON_H = 48
SCEN = ("EL", "CL", "ES", "CS")


def load_bars(sym):
    rows = []
    with open(DATA_DIR / f"{sym}USDT_15m.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = datetime.fromisoformat(r["open_time"].replace("Z", "+00:00"))
            rows.append((t, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
    rows.sort(key=lambda x: x[0])
    return rows


def f(v):
    return float(v) if v not in ("", None) else None


def eval_scenario(kind, row, bars, t0):
    long_side = kind in ("EL", "CL")
    early = kind in ("EL", "ES")
    z1, z2 = f(row[f"{kind}_z1"]), f(row[f"{kind}_z2"])
    conf, t1, inv = f(row[f"{kind}_conf"]), f(row[f"{kind}_t1"]), f(row[f"{kind}_inv"])
    if early and (z1 is None or conf is None or t1 is None or inv is None):
        return {"status": "no_data"}
    if not early:
        if z1 is None or t1 is None:
            return {"status": "no_data"}
        inv = z1  # припущення: стоп консервативного пробою = рівень пробою
    end = t0 + timedelta(hours=HORIZON_H)
    win = [b for b in bars if t0 < b[0] <= end]
    if not win or win[-1][0] < t0 + timedelta(hours=1):
        return {"status": "no_bars"}
    touched, entry, hour_close = False, None, {}
    for t, o, h, lo, c in win:
        if entry is None:
            if early:
                if (c < inv if long_side else c > inv):
                    return {"status": "cancelled"}
                if (lo <= z2 if long_side else h >= z1):
                    touched = True
                if touched and (c > conf if long_side else c < conf):
                    entry = (t, c)
            else:
                hour = t.replace(minute=0, second=0)
                hour_close[hour] = c
                if t.minute == 45 and (c > z1 if long_side else c < z1):
                    entry = (t, c)
            continue
        hit_inv = (c < inv if long_side else c > inv)
        hit_t1 = (h >= t1 if long_side else lo <= t1)
        if hit_inv:
            return {"status": "inv", "entry": entry, "at": t}
        if hit_t1:
            return {"status": "t1", "entry": entry, "at": t}
    return {"status": "timeout", "entry": entry} if entry else {"status": "not_activated"}


def main():
    briefs = list(csv.DictReader(open(BRIEFS_CSV, encoding="utf-8"), delimiter=";"))
    syms = sorted({r["sym"] for r in briefs})
    bars = {s: load_bars(s) for s in syms}
    last = min(b[-1][0] for b in bars.values())
    first_brief = min(r["started"] for r in briefs)
    t_first = datetime.fromisoformat(first_brief.replace("Z", "+00:00"))
    if last < t_first:
        sys.exit(f"15m-дані закінчуються {last}, раніше за перший бриф {first_brief}. Онови data/ohlcv (download-history.bat).")
    results = []
    for r in briefs:
        t0 = datetime.fromisoformat(r["started"].replace("Z", "+00:00"))
        for k in SCEN:
            res = eval_scenario(k, r, bars[r["sym"]], t0)
            results.append({"run": r["run"], "started": r["started"], "label": r["label"], "sym": r["sym"], "scen": k, **res})
    L = [f"# SignalPilot — Forward-audit живого брифу\n",
         f"*Згенеровано {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Брифи: {len(briefs)//len(syms)} (з логів GitHub Actions), "
         f"символи: {', '.join(syms)}. Дані: Binance USD-M 15m до {last:%Y-%m-%d %H:%M} UTC. Горизонт {HORIZON_H}h.*\n",
         "Правила зафіксовані в docstring `rig/brief_audit.py` ДО прогону. Вхід без комісій; "
         "таймаут = сценарій активувався, але ні ціль-1, ні інвалідація не настали у вікні.\n"]
    for k, name in [("EL", "Ранній LONG від підтримки"), ("CL", "Консервативний LONG (пробій)"),
                    ("ES", "Ранній SHORT від опору"), ("CS", "Консервативний SHORT (пробій)")]:
        sub = [x for x in results if x["scen"] == k]
        c = Counter(x["status"] for x in sub)
        act = c["t1"] + c["inv"] + c["timeout"]
        hit = f"{c['t1']}/{c['t1']+c['inv']}" if (c["t1"] + c["inv"]) else "—"
        L.append(f"## {name}\n")
        L.append(f"| Сценаріїв | Активовано | Ціль-1 перша | Інвалідація перша | Таймаут | Скасовано до входу | Не активовано |\n|--:|--:|--:|--:|--:|--:|--:|\n"
                 f"| {len(sub)} | {act} | {c['t1']} | {c['inv']} | {c['timeout']} | {c['cancelled']} | {c['not_activated']} |\n")
        L.append(f"Ціль-1 vs інвалідація (по активованих із результатом): **{hit}**\n")
    L.append("## Активовані сценарії — журнал\n")
    L.append("| Бриф (UTC) | Сесія | Символ | Сценарій | Вхід | Результат | Коли |\n|---|---|---|---|--:|---|---|\n")
    for x in results:
        if x["status"] in ("t1", "inv", "timeout"):
            e = x.get("entry")
            at = x.get("at")
            L.append(f"| {x['started'][:16]} | {x['label'].split('·', 2)[-1].strip()} | {x['sym']} | {x['scen']} | "
                     f"{e[1] if e else ''} | {x['status']} | {at.strftime('%m-%d %H:%M') if at else ''} |\n")
    L.append("\n## Обмеження (чесно)\n"
             "- Вибірка крихітна (дні, не місяці) — це табель для спостереження, не статистичний вирок.\n"
             "- Сценарії оцінюються незалежно; наступний бриф не скасовує попередній план.\n"
             "- Стоп для CL/CS не заданий у брифі — взято рівень пробою (припущення).\n"
             "- GitHub губить частину планових ранів, тому брифів менше, ніж 6/день.\n"
             "- Два брифи 04.07 (13:22 і 13:57) — дублікати за даними (запізнілі рани поспіль).\n")
    REPORT.write_text("".join(L), encoding="utf-8", newline="")
    print(f"OK: звіт -> {REPORT}; рядків-оцінок: {len(results)}")


if __name__ == "__main__":
    main()
