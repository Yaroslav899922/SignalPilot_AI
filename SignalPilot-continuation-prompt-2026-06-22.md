# SignalPilot — continuation prompt (на 2026-06-22): Pifagor attribution sweep + RIG для breakout_retest

Продовжуємо роботу над D:\Projects\SignalPilot.

Я не програміст — пояснюй простими словами, маленькими кроками. Якщо я не кажу прямо "погнали", "працюємо" або не прошу внести правки — спочатку тільки обговорення. Якщо правки внесені в ЖИВУ систему — тести → commit → push → ручний GitHub Actions → Telegram → перевірка логів. Зміни в RIG — офлайн, для них push/Actions/Telegram НЕ потрібні.

БЕЗПЕЧНІ ДІЇ роби ОДРАЗУ, без запитань: локальний commit документів/continuation-prompt/RIG-змін (commit = бекап). НІКОЛИ не push без явного дозволу.

ЯКЩО ХАЛЕПА (файл зламався): останній чистий файл — `git show HEAD:<шлях>`; повернути — з git history (на монті `git checkout` може падати через заборонений unlink → перезаписати через python `open('w')` з git-вмісту); надійна робоча копія — `/tmp/sp`. Повні правила — у `CLAUDE.md` в корені проєкту.

---

## ПРАВИЛО ПРОЄКТУ (зафіксувати в README і тут)

```
Rule: no strategy arm is considered working until it has a reproducible RIG
report against baseline. Reports must separate signal quality, fill mechanics,
and exit geometry where applicable.
```

Українською: жодна торгова "рука" не вважається робочою, поки немає відтворюваного RIG-звіту проти baseline. Звіти мають розділяти якість сигналу, механіку філа і геометрію виходу.

---

## ПОТОЧНИЙ СТАН ЖИВОЇ СИСТЕМИ (минулого разу НЕ чіпали)

- Активний workflow: `.github/workflows/market-brief.yml`.
- Telegram Market Brief за київськими сесіями: 03:07, 11:07, 12:07, 17:07, 19:07, 00:07 (у GitHub cron записані в UTC, бо Actions не підтримує timezone).
- Move Alert ±1.5% за останню закриту 15m-свічку по BTC/ETH/SOL; сценарій "Готуватись до LONG/SHORT".
- Антиспам Move Alert СВІДОМО відкладено: спостерігаємо ~3 дні (з 21.06), потім рішення про "один alert на монету/напрямок за сесію".
- Telegram HTML: символи `>` і `<` писати як `&gt;` / `&lt;`, інакше HTTP 400.

---

## ЩО ЗРОБИЛИ МИНУЛОЇ СЕСІЇ (21.06, RIG + Pifagor)

Контекст: хотіли полірувати стратегії, спершу перевірили мірило (RIG, `src/signalpilot/rig/`).

- Виявили: RIG був СВІДОМО вимкнений у коміті `301f15e` ("Live analyst: cleanup old logic") — вихолостили його тести ("rig module is no longer part of SignalPilot"), видалили стару стратегію `build_signal`, а код RIG лишили на диску → він не запускався (битий імпорт).
- Оживили RIG: прибрали мертву breakout-руку.
- Додали руку `pifagor_s1` (`src/signalpilot/rig/plans.py`): імпульс із 2 свічок (друга оновлює екстремум, але не коригує далі 50% першої) → фіба LOY..HAI → лімітний вхід 50%, тейк 38.2%, стоп трохи за 61.8%. БЕЗ ladder, БЕЗ "ракети".
- Додали раннер `src/signalpilot/rig/compare.py` і тест `tests/test_rig_pifagor.py`.
- Тести: 64/64 OK. Звіт: `reports/rig-pifagor-2026-06-21.md`.
- Закомітили ЛОКАЛЬНО (НЕ push): `9e2d2c1` "Revive RIG, add Pifagor S1 arm and comparison".

ВИСНОВОК БЕКТЕСТУ: механічне ядро Pifagor S1 на 4h СТАБІЛЬНО програє baseline.
- Train: pifagor −0.280R vs baseline −0.037R → різниця −0.244R, month-CI [−0.384, −0.081].
- Test: pifagor −0.488R vs baseline −0.018R → різниця −0.471R, month-CI [−0.666, −0.265].
- По символах на test усі в мінусі. Win-rate 48–55% (НЕ 92% із вебінару). Дрібний тейк 38.2% = погане RR.
- Діагноз (наша спільна рамка): Pifagor S1 4h програє через КОМБІНАЦІЮ adverse selection на limit-fill + погану payoff-структуру. Це ДВА окремі механізми, плюс третій (сам сигнал).

---

## ТЕХНІЧНІ НОТАТКИ ПРО ОТОЧЕННЯ (важливо!)

- Мережевий монт (D:\) ГЛЮЧИТЬ з інструментом редагування (Edit): три файли отримали null-байти й не імпортувались. Лікували: відновлення з git (`git show HEAD:path`) + перезапис чистим UTF-8 через bash python `open('w', newline='')`. УРОК: правки в `rig/` робити через bash, потім перевіряти `null bytes == 0` і проганяти тести. Можна працювати в локальній копії `/tmp/sp` (надійний Linux fs), потім синхронізувати на монт.
- Пісочниця має лише Python 3.10, проєкт просить 3.11 — `pip install -e .` не пройде; запускати через `PYTHONPATH=src python3 ...`. Залежності: `pip install "pandas>=2.2" "numpy>=1.24" tzdata --break-system-packages`.
- Видалення файлів на монті треба окремо дозволити (інструмент дозволу).
- RIG не встановлений як пакет; запуск: `PYTHONPATH=src python3 -m signalpilot.rig.compare`.

---

## МЕЖА RIG

RIG вирішує ТІЛЬКИ по 4h-свічці (індикатори на 4h, 15m лише для торкань входу/стопа/цілі). Жива стратегія `breakout_retest` — трьохрівнева (4h тренд / 1h сетап+ретест / 15m підтвердження). Тому RIG ЩЕ НЕ міряє живу стратегію — це окрема велика задача (див. нижче). Baseline і Pifagor (теж 4h) міряє чесно.

---

## ГОЛОВНА НАСТУПНА ЗАДАЧА #1 — Pifagor 4h attribution sweep

Мета: розчепити, ЩО САМЕ вбиває Pifagor S1, на три механізми:
1. Signal quality — чи сам імпульсний сигнал має edge.
2. Fill mechanics — чи чекання 50% відкату відбирає гірші сетапи (adverse selection).
3. Exit geometry — чи 38.2% TP проти дальшого стопа ламає математику навіть при нормальному сигналі.

### Одиниця виміру: SIGNAL-OPPORTUNITY (не filled trade!)
Інакше limit-рука з ~38% fill порівнюється нечесно (показує лише зручний підмножину).

### signal_id
`signal_id = symbol + timeframe + decision_time + direction`, де `decision_time` = момент закриття 4h-бару (`open_time + 4h`), без lookahead (це вже рахує `dataset.py`).

### Матриця рук (entry_mode × exit_mode)
| Signal | Entry | Exit |
|---|---|---|
| Pifagor impulse | limit 50% | fib 38.2 (поточна) |
| Pifagor impulse | limit 50% | 1R / 1.5R / 2R |
| Pifagor impulse | limit 50% | time-exit |
| Pifagor impulse | market | 1R / 1.5R / 2R |
| Pifagor impulse | market | time-exit |

`market × fib 38.2` ВИКИНУТО: для LONG ринковий вхід біля HAI, а fib-38.2 нижче нього → ціль "позаду" входу, рука невалідна.

### Спільні правила всіх рук
- Стоп (invalidation) ОДИН І ТОЙ САМИЙ для всіх рук: рівень трохи за 61.8% від імпульсу. Це єдиний invalidation, наперед відомий max-loss у R.
- `limit_lifetime = one_window` (одне 4h-вікно на філ), тримаємо фіксованим. `until_trend` — окремий пізніший експеримент, НЕ в цій хвилі.
- R-multiple цілі рахуються від ризику = |entry − stop| (для market entry — від фактичного fill).
- time-exit: конкретний горизонт N = 12 4h-барів (= нинішній timeout, спільний знаменник), явним параметром. Стоп активний усю дорогу; якщо стоп не зачеплено — вихід по CLOSE N-го бару. Це ОКРЕМИЙ режим виходу, НЕ той самий, що аварійний timeout движка (він виходить по open). Потім за бажання можна посвіпити N.

### Три результати на КОЖЕН signal_id
- `limit` — вхід 50%, стоп/вихід Pifagor; МІГ не філитись.
- `market` — той самий стоп/вихід, але вхід по ринку (next open); філиться завжди.
- `context_baseline` — звичайне baseline-правило (1.25 ATR стоп / 1.5 ATR ціль) застосоване ТІЛЬКИ на барах Pifagor-імпульсу (щоб ізолювати, чи додає сам імпульс щось понад "тренд вгору → тупий ринковий вхід" у той самий момент).
- ОКРЕМО лишається GLOBAL baseline (усі трендові 4h-бари) як стоячий еталон ринку — не плутати з context_baseline.

### Два зрізи у звіті
- `per filled trade` — якість реально виконаних limit-угод (умовна, на філах).
- `per signal opportunity` — весь потік сигналів, no-fill для limit = `0R`. ГОЛОВНА одиниця.
- Розрив між зрізами = прямий датчик adverse selection.

### PAIRED порівняння (обов'язкове правило звіту)
Не лише `mean_R(strategy) vs mean_R(baseline)`, а для кожного `signal_id`:
`delta_R = strategy_R − context_baseline_R`,
і вже по цих delta_R рахувати mean / month-CI. Це прибирає шум режимів ринку (порівняння на тому самому барі/символі/напрямку).
У звіті поруч із month-CI обов'язково показувати `n_months_delta_CI` і `months_delta_CI`, щоб було видно, скільки month-blocks реально брали участь у похибці.
УВАГА реалізації: нинішній `metrics.difference_ci` — НЕПАРНИЙ (ресемплить дві вибірки незалежно). Треба НОВУ парну метрику: дельта на сигнал → bootstrap дельт + month-block CI.

### No-fill semantics
Для per-opportunity: no-fill limit = `0R`, а `delta_vs_context_baseline = 0R − baseline_R` (оцінюємо стратегію як "що вона дала на потоці сигналів", включно з missed opportunity).

### OHLC ambiguity policy
Якщо в одному 4h-барі зачеплено і стоп, і ціль — STOP-FIRST (консервативно). У движку ВЖЕ так (`_manage` перевіряє стоп перед ціллю; лімітний філ ховає ціль у своїй свічці = zone_pierce). НЕ міняти; задокументувати в README.

### Мінімальні колонки звіту
```
arm
entry_mode
exit_mode
n_signals
n_fills
fill_rate
mean_R_per_opportunity
mean_R_per_filled
mean_context_baseline_R
mean_delta_vs_context_baseline
month_CI_delta
n_months_delta_CI
months_delta_CI
```

### ЛОГІКА РІШЕННЯ (визначена НАПЕРЕД)
- market-руки оживають, limit — ні → винна МЕХАНІКА ФІЛА (adverse selection на відкаті).
- усі руки в мінусі при будь-якому виході → винен САМ СИГНАЛ, ідея мертва на 4h.
- якась R-рука виходить у плюс проти baseline (особливо market) → вбивав саме 38.2% TP, СИГНАЛ МАЄ ЖИТТЯ → тоді осмислені денний ТФ і laddered.

---

## ГОЛОВНА НАСТУПНА ЗАДАЧА #2 — навчити RIG міряти живу breakout_retest

Чому головна: baseline ≈ 0 означає, що ринок 4h не дає легкого edge нікому. Жива логіка `breakout_retest` цілком може бути єдиним, що реально б'є нуль — і тоді це СПРАВЖНЄ ЯДРО SignalPilot, його гріх не виміряти.
Ціна: треба чесно пронести 1h + 15m індикатори в точку рішення (робота з датасетом/движком, не пара рядків). Це хірургія `rig/dataset.py` + точка рішення.

---

## ПОРЯДОК РОБІТ (зафіксовано)

1. Pifagor 4h sweep: `limit/market × fib/R/time`, per-opportunity (+ fill_rate) + per-filled, paired delta vs context-baseline.
2. Читання результату за логікою рішення вище.
3. Якщо сигнал ЖИВИЙ → денний ТФ або laddered.
4. Якщо МЕРТВИЙ → закриваємо Pifagor 4h і беремось за RIG для `breakout_retest` (задача #2).

Прагматичний пріоритет: спершу дешевий sweep (закриває гіпотезу), ОДРАЗУ після — breakout_retest як головна задача. Денний ТФ і laddered — нижче, лише якщо sweep покаже життя сигналу.

---

## PARKING LOT (не губити, але не зараз)

- Денний ТФ для Pifagor — докачати денні дані; авторська ідея могла бути на іншу структуру шуму. Але результат 4h уже достатній, щоб НЕ торгувати наживо без нового тесту.
- Laddered-версія (3 входи) — ТІЛЬКИ з єдиним invalidation і наперед відомим max-loss у R. Execution-модель, а НЕ "докуплю поки стане правдою".
- "Ракету" НІКОЛИ не кодувати як кандидата. Максимум окремий risk-demo: показати, як росте win-rate і вибухає tail-risk.
- Futures context (CoinGlass або інше): funding rate, open interest, long/short ratio. Зараз недоступний з GitHub Actions (Binance Futures HTTP 451).
- Стиснути Market Brief, якщо задовгий на мобільному.
- Зимовий/літній час: GitHub cron у UTC; восени (Київ UTC+2) усі брифи зсунуться на годину — підправити.

---

## КЛЮЧОВІ КОМІТИ
- `9e2d2c1` — Revive RIG, add Pifagor S1 arm and comparison (лока