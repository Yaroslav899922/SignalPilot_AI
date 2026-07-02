# SignalPilot — continuation prompt (на 2026-07-02): RIG-рука reversal_v1 (sweep + FVG + MSS)

Продовжуємо роботу над D:\Projects\SignalPilot.

Я не програміст — пояснюй простими словами, маленькими кроками. Без явного "погнали"/"працюємо" — спочатку тільки обговорення. Правки в ЖИВУ систему: тести → commit → push → ручний GitHub Actions → Telegram → перевірка логів. RIG — офлайн, push/Actions/Telegram НЕ потрібні.

БЕЗПЕЧНІ ДІЇ роби ОДРАЗУ, без запитань: локальний commit документів/continuation-prompt/RIG (commit = бекап). НІКОЛИ не push без явного дозволу. Повні правила — у `CLAUDE.md`.

---

## ЩО ЗРОБИЛИ ЦІЄЇ СЕСІЇ (02.07) — усе ОФЛАЙН, НЕ запушено

Побудували з нуля нову RIG-руку `reversal_v1` (price-action reversal: liquidity-sweep + FVG + MSS) за 6 комітів, кожен етап із тестами. **79 тестів зелені.**

1. **Spec-документ** (`SignalPilot-Reversal-Setup-Spec-2026-07-02.md`, коміт `ede7de5`) — механічні визначення 6 кроків, зафіксовані параметри, критерій воріт, план на 6 етапів.
2. **Етап 1 — детектор свінгів** `src/signalpilot/rig/structure.py` (`40850c2`): підтверджені pivot high/low з лагом N=2, без look-ahead (`confirmed_at=idx+N`).
3. **Етап 2 — детектор FVG** `src/signalpilot/rig/fvg.py` (`7741d92`): 3-свічковий розрив, фільтр `FVG_MIN_ATR=0.10`.
4. **Етап 3 — стан-машина** `src/signalpilot/rig/reversal.py` (`ca38fef`): даунтренд → range (RL/RH) → свіп під RL із поверненням усередину → fib-floor → бичачий FVG → MSS = вхід. Емітить на барі MSS. Вхід — ліміт у середині FVG; стоп — під свіпом; ціль — range high.
5. **Етап 4 — рука + режим ордера** `engine.py` (`549282f`): вбудували `reversal_v1` у `build_decisions`; додали lifetime-режим **`rest_bars`** (ліміт лежить до K 4h-барів). Адитивно, гейт по lifetime — інші руки (baseline/pullback/pifagor) НЕ зачеплені; є захисний тест.
6. **Етап 5 — звіт** `src/signalpilot/rig/reversal_report.py` + `reports/rig-reversal-2026-07-02.md` (`3f31e55`). Запуск: `python -m signalpilot.rig.reversal_report`.

**HEAD (локально) = `3f31e55`.** origin/main НЕ зрушений (нічого не пушили).

## ГОЛОВНА ЗНАХІДКА

Патерн працює механічно, але **рідкісний**: лише **24 сетапи** на BTC/ETH/SOL за 18 міс, філів 4 (one_window) / 9 (rest_bars). Expectancy **додатна** (rest_bars +0.21R, one_window +0.5R) — на відміну від baseline ≈ 0 і Pifagor у мінусі; `rest_bars` подвоїв fill-rate 17%→38%. АЛЕ вибірка замала для вироку.

**Вердикт: НЕ закрито і НЕ пройдено — відкладено до більшої вибірки.** Це «плану Б» зі spec: resolved < 30/символ → діагностика, розширювати символи.

### Одне відхилення від spec (свідоме, коректність)
range-high перевизначили як «найвищий swing high у вікні перед свіпом» (у діапазоні хай може бути й ДО лоу). Це НЕ підкрутка прибутку: число сетапів майже не залежить від ширини вікон (перевірено 12–40), підняло вибірку 13→24.

## ГОЛОВНА НАСТУПНА ЗАДАЧА — набрати вибірку

1. **Розширити символи** з 3 до 8–12 монет і перепрогнати `reversal_report`. Дані качати **локально** (`python -m signalpilot.rig.download` або `scripts/download-history.bat`): Binance із пісочниці заблокований (HTTP 451). Додати нові тикери у `dataset.py::SYMBOLS`.
2. Коли resolved ≥ ~30 у train і test — застосувати критерій воріт (month-CI > 0, стабільність по символах, підтвердження на test).

## PARKING LOT (не зараз, не губити)

- **SHORT-дзеркало reversal** (зараз лише LONG-ядро). Дзеркалити sweep над RH → ведмежий FVG → MSS вниз.
- **Варіації reversal:** вхід-лімит у різних точках FVG; ціль = fib-розширення вгору замість range high; STOP під fib замість під свіпом.
- **forward-audit табель живого брифу** (з 29.06): бриф пишеться в лог між маркерами; звести табель «порада → що сталося → тригер → ціль/стоп → висновок». Дані ринку — Kraken OHLC.
- **RIG / Pifagor 4h attribution sweep**; RIG для живої breakout_retest.
- Upgrade логування брифу A→B: файл-журнал `data/brief_log.jsonl` з commit-back.

## ТЕХНІЧНІ НОТАТКИ ОТОЧЕННЯ

- **Монт D:\ ГЛЮЧИТЬ:** інструмент редагування може вставити null-байти; git на монті лишає **стейл-локи** `.git/index.lock` і `.git/HEAD.lock`, які пісочниця НЕ може видалити (unlink заборонений). Цієї сесії коміти робили в обхід через git-плюмбінг: `GIT_INDEX_FILE=/tmp/gitidx git read-tree HEAD && git add … && tree=$(git write-tree) && commit=$(git commit-tree $tree -p HEAD -m …) && printf '%s\n' $commit > .git/refs/heads/main`. **Ярославе: видали `.git/index.lock` і `.git/HEAD.lock` на Windows, щоб твій власний git не спотикався.**
- Надійна робоча копія: `/tmp/sp` (`git archive HEAD | tar -x -C /tmp/sp`), синхронізувати назад через python `open('w', newline='')`, перевіряти `null bytes == 0`.
- Пісочниця Python 3.10 (проєкт 3.11): `PYTHONPATH=src python3 -m pytest tests/`. Залежності: `pip install "pandas>=2.2" "numpy>=1.24" tzdata pytest --break-system-packages`.
- Тести рушія рига колись прибрали (`test_rig_engine.py` — заглушка); є `test_rig_pifagor.py` і нові `test_rig_structure/fvg/reversal/rest_bars.py`.

## КЛЮЧОВІ КОМІТИ (локальні, НЕ запушені)
- `3f31e55` — reversal report vs baseline (stage 5)
- `549282f` — wire reversal_v1 + rest_bars lifetime (stage 4)
- `ca38fef` — reversal state machine (stage 3)
- `7741d92` — FVG detector (stage 2)
- `40850c2` — swing-pivot detector (stage 1)
- `ede7de5` — spec Reversal Setup

Не змінюй код без мого "погнали" або "працюємо".
