# SignalPilot — continuation prompt (на 2026-07-04): reversal_v1 сигнал ПРОТИ + аудит брифу v0

Продовжуємо роботу над D:\Projects\SignalPilot.

Я не програміст — пояснюй простими словами, маленькими кроками. Без явного "погнали"/"працюємо" — спочатку тільки обговорення. Жива система: тести → commit → push → ручний Actions → Telegram → логи. RIG — офлайн, push НЕ потрібен. БЕЗПЕЧНІ ДІЇ (локальні коміти документів/RIG) роби одразу. НІКОЛИ не push без дозволу. Повні правила — `CLAUDE.md`.

---

## ЩО ЗРОБИЛИ ЦІЄЇ СЕСІЇ (04.07) — усе ОФЛАЙН, НЕ запушено

1. **Git-гігієна:** видалені стейл-локи, `.gitattributes` (CRLF-шум зник), `git status` чистий.
2. **`HYPOTHESES.md`** — реєстр гіпотез зі статусами і правилами (нова гіпотеза вписується ДО прогону; закрита не відкривається).
3. **RIG: SYMBOLS 3→12** (`dataset.py`/`download.py`): +XRP, BNB, ADA, DOGE, LINK, AVAX, DOT, LTC, NEAR. Свіжий зріз до 04.07 (качав Ярослав через `download-history.bat`).
4. **reversal_v1 на 12 монетах — перевага ЗНИКЛА:** rest_bars expectancy train −0.123R / test −0.294R; різниця з baseline train −0.092R / test −0.281R; one_window test month-CI [−1.178, −0.237] — значуще гірше. На 3 первинних монетах плюс, на 8/9 нових мінус → перший результат був шумом вибору. Звіт `reports/rig-reversal-2026-07-04.md`. Вердикт звіту тепер data-driven (був захардкоджений оптимістичний текст).
5. **Forward-audit брифу v0:** `src/signalpilot/rig/brief_audit.py` (правила в docstring, зафіксовані до прогону) + `data/brief_audit/briefs-parsed.csv` (17 брифів 29.06–04.07 з логів Actions) + звіт `reports/brief-audit-2026-07-04.md`. Результати (висхідний тиждень!): ранній LONG 7/8 до цілі-1, пробійний LONG 26/41, **ранній SHORT 0/29**, пробійний SHORT 1/1.
6. Notion: запис у «Журнал розробки» від 04.07.

**HEAD (локально) = `c12064c` + цей prompt.** origin/main = `1dae15b` (не зрушений).

## ГОЛОВНЕ ВІДКРИТЕ РІШЕННЯ

**reversal_v1 (LONG-ядро): закрити чи збирати ще?** Критерій воріт НЕ виконано, сигнал проти. Формально resolved 22/21 < 30. Рекомендація Claude — закрити в поточній постановці. Статус у `HYPOTHESES.md` = «СИГНАЛ ПРОТИ — чекає рішення». Після рішення Ярослава — оновити рядок реєстру.

## НАСТУПНІ ЗАДАЧІ

1. Зафіксувати рішення по reversal_v1 у `HYPOTHESES.md`.
2. **Накопичувати табель брифу:** кожні кілька днів тягнути нові брифи з логів Actions (рецепт нижче), додавати в `briefs-parsed.csv`, перепроганяти `python -m signalpilot.rig.brief_audit`. Після 3–4 тижнів — висновки по сценаріях (особливо ранній SHORT проти тренду: активується легко, поки 0/29).
3. Довгостроково: `data/brief_log.jsonl` commit-back з Actions (жива система — потрібен push+дозвіл), щоб не залежати від 90 днів зберігання логів.
4. Розклад Actions: GitHub тротлить — 97 ранів/5.5 діб замість ~500 (мувалерти ходять рідко, брифів ~3/день замість 6). Обговорити спрощення cron.
5. Parking lot: SHORT-дзеркало reversal (лише якщо напрям живе), варіації FVG-входу, block-bootstrap, RIG для breakout_retest.

## РЕЦЕПТ: брифи з логів Actions без токена (через браузер Chrome MCP)

1. Відкрити github.com у вкладці (юзер залогінений). API-виклики робити fetch-ом ЗІ сторінки github.com (CSP пускає лише github-домени; api.kraken/binance — блок).
2. Список ранів: `api.github.com/repos/Yaroslav899922/SignalPilot_AI/actions/workflows/market-brief.yml/runs?per_page=100&created=>=DATE` (rate limit 60/год без токена).
3. Класифікація ран = бриф: `/runs/{id}/jobs` → крок "Send market brief" conclusion == "success".
4. Лог: same-origin fetch `/Yaroslav899922/SignalPilot_AI/commit/{head_sha}/checks/{job_id}/logs` (cookie-сесія) → блок між `===SIGNALPILOT-BRIEF-START/END===`.
5. Великі дані з браузера: рендер у `<article>` + get_page_text (ліміт ~24КБ/виклик); результат javascript_tool обрізається ~1КБ.
6. Парсер брифу → рядки CSV: див. формат `data/brief_audit/briefs-parsed.csv` (роздільник `;`, 37 колонок).

## ТЕХНІЧНІ НОТАТКИ ОТОЧЕННЯ (МОНТ D:\ ГЛЮЧИТЬ — 2 нові пастки!)

- **Кеш монта бреше:** після записів з Windows пісочниця може показувати СТАРІ версії файлів (mtime/вміст). dd iflag=direct і mv НЕ рятують. Обхід: Ярослав робить КОПІЇ файлів у Провіднику (нові inode) → з пісочниці `cp копія → канонічне ім'я` → видалити копії (видалення вже дозволене цієї сесії, у нових сесіях — питати).
- **`git add` великих файлів може вбити .git/index нулями** ("bad signature 0x00000000"). Лікування: `rm -f .git/index`, далі `GIT_INDEX_FILE=/tmp/gitidx git read-tree HEAD && git add … && tree=$(git write-tree) && c=$(git commit-tree $tree -p HEAD -m "…") && printf '%s\n' $c > .git/refs/heads/main`, у кінці `rm -f .git/index && git read-tree HEAD`.
- Код на монті правити через bash python `open('w', newline='')`, потім `null bytes == 0` + тести.
- Пісочниця Python 3.10: `PYTHONPATH=src python3 -m pytest tests/` (79 тестів зелені). Binance/Kraken із пісочниці заблоковані (451/403) — дані качати локально.

Не змінюй код без мого "погнали" або "працюємо".
