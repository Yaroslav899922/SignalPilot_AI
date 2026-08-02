# SignalPilot

SignalPilot is an MVP trading-signal assistant for manual crypto trading decisions.
It analyzes Binance market candles and futures context, calculates basic
indicators, emits a structured LONG / SHORT / NO TRADE signal, and stores every
signal in a local SQLite journal or, for the free server setup, a Google Sheet.

This project does not place orders, does not trade automatically, and does not
provide any financial guarantee.

The canonical forward-measurement rules are frozen in
[`SignalPilot-v3.1-Measurement-Protocol-2026-08-02.md`](SignalPilot-v3.1-Measurement-Protocol-2026-08-02.md).
The evidence, current Sheet diagnostics, root causes, and action plan are in
[`SignalPilot-Deep-Audit-2026-08-02.md`](SignalPilot-Deep-Audit-2026-08-02.md).
The v3.1 fixes are currently committed locally but **not deployed**. Historical
Google Sheet rows remain diagnostic; the comparable v3.1 cohort starts only
after a verified cutover and a recorded `measurement_start_utc`.

## Current MVP Scope

- Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT` by default.
- Timeframes: `15m`, `1h`, `4h` by default. Actionable scenarios use `4h` and
  `1h` for context, then a closed `15m` candle for confirmation and evaluation.
  The older single-timeframe path remains a separate legacy `1h` mode.
- Market candles: only closed candles are used; the default kline limit is
  `500` to give EMA 200 enough warmup.
- Futures context: latest funding rate, current open interest, global
  long/short account ratio, and top-of-book spread.
- Indicators: EMA 20/50/200, RSI 14, ATR 14, recent high/low.
- Signal fields: direction, entry zone, stop, targets, risk/reward, confidence,
  invalidation rule, trailing plan, pattern name, setup score, market regime,
  close price, futures context, liquidity context, and reasons.
- Live chart analyst: modular `market_data -> patterns -> trade_plan -> Signal`
  flow. The first modular pattern is `breakout_retest`; it only alerts
  when 4h/1h/15m context, futures filters, stop, target, and minimum setup
  quality agree.
- Journal: SQLite table for local runs, or Google Sheets through Apps Script for
  the free GitHub + Google server setup. A structural `setup_id` may recur, but
  each independent market event has an `event_id`; state changes preserve that
  identity and the same structural level cannot re-arm until 12 hours after a
  terminal event.
- Measurement loop: actionable alerts store `result_R`, `baseline_R`, and
  paired `edge_R`. The baseline enters in the same direction at the first fully
  eligible 15m candle open with the same absolute stop/T1 geometry. Barrier win
  rate excludes timed-out events, while expectancy and edge use the same paired
  terminal population. The fixed paper cost is 0.12% round trip.
- Report: compact CLI summary of live paper-test journal results.
- Scheduler: GitHub Actions sends three market briefs per day and up to 92 quiet
  setup checks per day. Each job attempts start/finish receipts in
  `scheduler_runs`; this detects failed, stale, and unfinished runs only among
  receipts that reached Apps Script. Independent absence monitoring is still
  required.
- Dashboard: optional Streamlit view for the SQLite signal journal.
- Historical paper backtest: scans past `1h` candles for rule-based LONG/SHORT
  signals and reports target/stop/no-result statistics. It is explicitly
  `rule_only_neutral`: it does not reconstruct historical funding, open
  interest, long/short ratio, or spread, so it is not live-equivalent and should
  not be treated as trading proof.

## RIG Strategy Gate

Rule: no strategy arm is considered working until it has a reproducible RIG
report against baseline. Reports must separate signal quality, fill mechanics,
and exit geometry where applicable.

For paired strategy comparisons, report `delta_R = strategy_R -
context_baseline_R` by independent event. Correlated BTC/ETH/SOL rows must not
be treated as i.i.d. observations. Historical RIG reports use their documented
month-block fields; the actionable v3.1 hypothesis uses the exact joint 7-day
time-block algorithm and single endpoint frozen in the canonical protocol.

The current CLI/Telegram summary is an operational all-time view. It does not
yet filter by `measurement_start_utc` or calculate the confirmatory bootstrap
gate, so it must not be read as the v3.1 hypothesis verdict.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m signalpilot --market-status --symbols BTCUSDT ETHUSDT SOLUSDT
python -m signalpilot --live-analyst --symbols BTCUSDT ETHUSDT SOLUSDT
```

## Live Chart Analyst

This is the new forward path. SignalPilot reads public Binance USD-M market
data, calculates indicators, checks the first modular pattern
`breakout_retest`, builds a trade plan, writes the idea to the journal, and
sends Telegram only for directional alerts by default.

No Binance trading permission is needed for this mode. The current data layer
uses public market endpoints. If an API key is ever added for private account
read-only work, create a separate key without trading enabled and without
withdrawal permissions.

Check live data health without journaling an idea:

```powershell
python -m signalpilot --market-status --symbols BTCUSDT ETHUSDT SOLUSDT
```

Run the live analyst and journal the result:

```powershell
python -m signalpilot --live-analyst --symbols BTCUSDT ETHUSDT SOLUSDT
```

Send only directional alerts that pass the configured filters to Telegram:

```powershell
$env:TELEGRAM_BOT_TOKEN = "123456:your-bot-token"
$env:TELEGRAM_CHAT_ID = "123456789"
python -m signalpilot --live-analyst --symbols BTCUSDT ETHUSDT SOLUSDT --notify
```

Also send NO TRADE analyses when debugging:

```powershell
python -m signalpilot --live-analyst --symbols BTCUSDT ETHUSDT SOLUSDT --notify --notify-no-trade
```

The Telegram alert contains the pattern, setup score, entry zone, stop, target,
invalidation, trailing plan, futures context, and the safety note that
SignalPilot does not place trades.

## TradingView Trigger

TradingView is treated as an external trigger, not as the source of truth. A
TradingView alert can say "my indicator saw something", but SignalPilot still
checks Binance candles and futures context before sending a Telegram alert.

Example payload:

```json
{
  "source": "tradingview",
  "secret": "your-tradingview-webhook-secret",
  "ticker": "BINANCE:BTCUSDT.P",
  "interval": "1h",
  "indicator": "My private indicator",
  "direction": "LONG",
  "message": "Potential retest"
}
```

Local check with a TradingView payload:

```powershell
$env:SIGNALPILOT_TRADINGVIEW_TRIGGER = '{"source":"tradingview","ticker":"BINANCE:BTCUSDT.P","interval":"1h","indicator":"My private indicator","direction":"LONG"}'
python -m signalpilot --live-analyst --notify
```

For the Google Apps Script webhook path, add this optional Script Property:

```text
TRADINGVIEW_WEBHOOK_SECRET = довгий секретний текст для TradingView
```

## Безкоштовний запуск: GitHub + Google

Це основний шлях без Render, без карти і без billing account.

Проста схема:

- GitHub Actions — це "будильник": він надсилає три огляди на добу та тихо
  перевіряє actionable-сценарії приблизно кожні 15 хвилин.
- Google Sheet - це журнал, куди пишуться сигнали.
- Google Apps Script - це маленький приймач команд Telegram і міст між
  Telegram, Google Sheet та GitHub Actions.

Render лишається тільки optional paid варіантом. Для безкоштовного режиму
потрібні Google Sheet, Apps Script і GitHub Secrets.

### 1. Створи Google Sheet

1. Відкрий Google Sheets.
2. Створи нову таблицю.
3. Назви її, наприклад: `SignalPilot Journal`.
4. Нічого вручну в таблиці заповнювати не треба. Apps Script сам створить листи
   `signals`, `setup_events`, `scheduler_runs` і потрібні колонки.

### 2. Додай Apps Script

1. У Google Sheet натисни `Extensions` -> `Apps Script`.
2. Відкрий файл `Code.gs`.
3. Видали стандартний код.
4. Встав код із файлу [google_apps_script/Code.gs](google_apps_script/Code.gs).
5. Натисни `Save`.

### 3. Додай Script Properties

У Apps Script відкрий `Project Settings` -> `Script properties` і додай:

```text
TELEGRAM_BOT_TOKEN = токен від BotFather
WEBHOOK_SECRET = довгий секретний текст, наприклад signalpilot-webhook-2026
JOURNAL_API_TOKEN = інший довгий секретний текст, наприклад signalpilot-journal-2026
GITHUB_TOKEN = GitHub personal access token для запуску workflow
GITHUB_OWNER = Yaroslav899922
GITHUB_REPO = SignalPilot_AI
GITHUB_WORKFLOW_FILE = market-brief.yml
```

Після деплою Apps Script додай ще одну властивість:

```text
SCRIPT_WEB_APP_URL = URL твого Apps Script Web App
```

Якщо Apps Script створений прямо з Google Sheet, `SPREADSHEET_ID` можна не
додавати. Якщо скрипт створений окремо, додай:

```text
SPREADSHEET_ID = id Google таблиці
```

`GITHUB_TOKEN` - це не Telegram token. Його треба створити в GitHub:

1. GitHub -> `Settings` -> `Developer settings`.
2. `Personal access tokens` -> `Fine-grained tokens`.
3. Обери репозиторій `SignalPilot_AI`.
4. Дай доступ `Actions: Read and write`.
5. Скопіюй token і встав у `GITHUB_TOKEN`.

### 4. Задеплой Apps Script як Web App

1. В Apps Script натисни `Deploy` -> `New deployment`.
2. Тип вибери `Web app`.
3. `Execute as`: `Me`.
4. `Who has access`: `Anyone`.
5. Натисни `Deploy`.
6. Скопіюй `Web app URL`.
7. Додай цей URL у Script Property `SCRIPT_WEB_APP_URL`.

Після цього в Apps Script у списку функцій вибери `setTelegramWebhook` і натисни
`Run`. Google попросить дозволи - це нормально, бо скрипт має писати в таблицю
і відправляти запити в Telegram/GitHub.

Якщо все добре, у логах буде відповідь Telegram з `"ok":true`.

### 5. Додай GitHub Secrets

У GitHub репозиторії відкрий:

`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`

Додай:

```text
TELEGRAM_BOT_TOKEN = токен від BotFather
TELEGRAM_CHAT_ID = твій канал або chat id для звичайних hourly повідомлень
SIGNALPILOT_JOURNAL_API_URL = Apps Script Web App URL
SIGNALPILOT_JOURNAL_API_TOKEN = той самий текст, що JOURNAL_API_TOKEN в Apps Script
```

Для GitHub Actions backend вмикається так:

```text
SIGNALPILOT_JOURNAL_BACKEND = apps_script
```

Це вже прописано в активному workflow:

- `.github/workflows/market-brief.yml` — ручні режими `brief`, `setup-check`,
  `move-alert` та весь автоматичний розклад.

Старі `live-paper-test.yml` і `market-check.yml` лежать у
`.github/disabled-workflows/` лише як історія та не запускаються.

### 6. Перевір запуск

1. У GitHub відкрий `Actions`.
2. Вибери `SignalPilot Market Brief`.
3. Натисни `Run workflow` і вибери потрібний режим.
4. Дочекайся завершення.
5. Перевір Google Sheet: у `scheduler_runs` має бути завершений receipt цього
   запуску. Листи `signals` і `setup_events` створюються ліниво лише коли
   відповідний режим реально має що записати; їхню відсутність після порожньої
   перевірки не вважай помилкою.
6. Для режиму `brief` перевір Telegram. `setup-check` навмисно мовчить, якщо
   стан жодного сценарію не змінився.

Потім у приватному чаті з ботом перевір команди:

```text
статус
надай звіт
є торгова ситуація?
перевір ринок
допомога
```

Команди `статус` і `надай звіт` відповідають одразу з Google Sheet.
Команди `є торгова ситуація?` і `перевір ринок` запускають GitHub Action, тому
результат може прийти через 1-3 хвилини.

Важливо: SignalPilot не відкриває угоди. Він тільки аналізує ринок, пише
paper-test журнал і надсилає підказки для ручного рішення.

## Windows: запуск без довгих команд

Якщо не хочеш щоразу вводити довгі PowerShell-команди, користуйся файлами в
папці `scripts`:

1. Один раз запусти `scripts\setup-telegram-env.bat` і встав:
   - `TELEGRAM_BOT_TOKEN` від BotFather;
   - `TELEGRAM_CHAT_ID`, наприклад назву каналу типу `@your_channel`
     або числовий chat id.
2. Запусти `scripts\start-telegram-bot.bat`, щоб бот відповідав у приватному
   чаті. Вікно має залишатися відкритим. Якщо закрити вікно, бот перестане
   відповідати.
3. У приватному чаті з ботом напиши:

```text
надай звіт
є торгова ситуація?
перевір ринок
статус
допомога
```

Інші готові файли запуску:

- `scripts\send-signals-once.bat` один раз перевіряє BTC/ETH/SOL і постить у Telegram.
- `scripts\evaluate-and-report.bat` оцінює старі сигнали в журналі і показує звіт.
- `scripts\show-report.bat` показує поточний звіт журналу.
- `scripts\start-hourly-paper-test.bat` запускає перевірку щогодини з Telegram-повідомленнями.
- `scripts\run-tests.bat` запускає тести.

Перший запуск сам створить `.venv` і встановить SignalPilot локально, тому не
треба вручну писати `PYTHONPATH`.

## Серверний режим

`render.yaml` містить налаштування Render worker, щоб Telegram-бот працював на
сервері з постійним SQLite-журналом у `/var/data/signals.sqlite3`.

Важливо: Render background worker не є безкоштовним `free`-сервісом. У
`render.yaml` використано `plan: starter`, тому перед запуском перевір вартість
у Render Dashboard.

Щоб це запустити на сервері, проєкт має бути в Git-репозиторії на GitHub, GitLab
або Bitbucket. Поточний репозиторій уже завантажений у GitHub:
`https://github.com/Yaroslav899922/SignalPilot_AI`.

Простий шлях для сервера:

1. Створити Git-репозиторій для SignalPilot і завантажити туди код.
2. Підключити цей репозиторій до Render як Blueprint.
3. Додати в Render змінні:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Запустити worker.

Бот все одно не торгує автоматично. Він тільки відповідає на команди і публікує
сигнали для ручного аналізу.

## Legacy local tools

The commands below remain useful for diagnostics and the older single-timeframe
paper loop. Their rows and summaries must not be mixed with the canonical
actionable v3.1 cohort.

Run the older single-timeframe mode when needed:

```powershell
python -m signalpilot --symbols BTCUSDT ETHUSDT SOLUSDT --interval 1h
```

Evaluate logged LONG / SHORT signals after a lookahead window:

```powershell
python -m signalpilot --evaluate --lookahead-candles 12
```

View a compact paper-test journal report:

```powershell
python -m signalpilot --report
```

Daily live paper-test workflow:

```powershell
python -m signalpilot --live-analyst --symbols BTCUSDT ETHUSDT SOLUSDT
python -m signalpilot --evaluate --lookahead-candles 12
python -m signalpilot --report
```

Run the live paper-test workflow automatically every 60 minutes:

```powershell
python -m signalpilot --paper-loop --live-analyst --symbols BTCUSDT ETHUSDT SOLUSDT --run-every-minutes 60
```

Stop the loop with `Ctrl+C`.

Run one scheduler cycle for a quick smoke test:

```powershell
python -m signalpilot --paper-loop --live-analyst --symbols BTCUSDT ETHUSDT SOLUSDT --max-runs 1
```

Send generated signals to Telegram:

```powershell
$env:TELEGRAM_BOT_TOKEN = "123456:your-bot-token"
$env:TELEGRAM_CHAT_ID = "123456789"
python -m signalpilot --live-analyst --symbols BTCUSDT ETHUSDT SOLUSDT --notify
```

Run the Telegram command bot for private chat replies:

```powershell
python -m signalpilot --telegram-bot
```

Keep that PowerShell window open while you want the bot to answer. In a private
chat with the bot, use:

```text
надай звіт
є торгова ситуація?
перевір ринок
статус
допомога
```

The bot only analyzes and reports. It does not place trades.

Open the journal dashboard:

```powershell
python -m pip install -e ".[dashboard]"
python -m streamlit run src/signalpilot/dashboard.py
```

Run a historical paper backtest and collect up to 50 directional signals:

```powershell
python -m signalpilot --backtest --symbols BTCUSDT ETHUSDT SOLUSDT --interval 1h --backtest-limit 1000 --target-signals 50 --lookahead-candles 6
```

Backtest mode prints one summary JSON object per symbol.
Each summary includes `futures_context_mode` and `uses_live_futures_filters` so
rule-only historical statistics are not confused with live forward-test results.

Future backtest work should add historical funding, open-interest, and
long/short-ratio context where Binance exposes it. Historical top-of-book spread
cannot be fully reconstructed through the current REST path, so live-valid
statistics should still come from the forward paper journal.

Run tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

The default journal path is `data/signals.sqlite3`.
