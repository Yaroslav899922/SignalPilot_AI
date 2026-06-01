# SignalPilot

SignalPilot is an MVP trading-signal assistant for manual crypto trading decisions.
It analyzes Binance market candles and futures context, calculates basic
indicators, emits a structured LONG / SHORT / NO TRADE signal, and stores every
signal in a SQLite journal.

This project does not place orders, does not trade automatically, and does not
provide any financial guarantee.

## Current MVP Scope

- Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT` by default.
- Timeframes: `15m`, `1h`, `4h` by default. The `1h` setup remains the signal
  and paper-evaluation interval.
- Market candles: only closed candles are used; the default kline limit is
  `500` to give EMA 200 enough warmup.
- Futures context: latest funding rate, current open interest, global
  long/short account ratio, and top-of-book spread.
- Indicators: EMA 20/50/200, RSI 14, ATR 14, recent high/low.
- Signal fields: direction, entry zone, stop, targets, risk/reward, confidence,
  invalidation rule, market regime, close price, futures context, liquidity
  context, and reasons.
- Journal: SQLite table with one row per generated signal and paper evaluation
  fields for directional signals. Repeated identical live signals are skipped so
  rerunning the same market state does not inflate paper-test statistics.
- Report: compact CLI summary of live paper-test journal results.
- Scheduler: optional live paper-test loop that regularly collects signals,
  evaluates older directional signals, and prints a journal report.
- Dashboard: optional Streamlit view for the SQLite signal journal.
- Historical paper backtest: scans past `1h` candles for rule-based LONG/SHORT
  signals and reports target/stop/no-result statistics. It is explicitly
  `rule_only_neutral`: it does not reconstruct historical funding, open
  interest, long/short ratio, or spread, so it is not live-equivalent and should
  not be treated as trading proof.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m signalpilot --symbols BTCUSDT ETHUSDT SOLUSDT
```

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

Щоб це запустити на сервері, проєкт спочатку треба покласти в Git-репозиторій
на GitHub, GitLab або Bitbucket. Поточна локальна папка ще не є Git-репозиторієм,
тому серверний деплой прямо зараз із цієї папки завершити не можна.

Простий шлях для сервера:

1. Створити Git-репозиторій для SignalPilot і завантажити туди код.
2. Підключити цей репозиторій до Render як Blueprint.
3. Додати в Render змінні:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Запустити worker.

Бот все одно не торгує автоматично. Він тільки відповідає на команди і публікує
сигнали для ручного аналізу.

Run the older single-timeframe mode when needed:

```powershell
python -m signalpilot --symbols BTCUSDT ETHUSDT SOLUSDT --interval 1h
```

Evaluate logged LONG / SHORT signals after a lookahead window:

```powershell
python -m signalpilot --evaluate --lookahead-candles 6
```

View a compact paper-test journal report:

```powershell
python -m signalpilot --report
```

Daily live paper-test workflow:

```powershell
python -m signalpilot --symbols BTCUSDT ETHUSDT SOLUSDT
python -m signalpilot --evaluate --lookahead-candles 6
python -m signalpilot --report
```

Run the live paper-test workflow automatically every 60 minutes:

```powershell
python -m signalpilot --paper-loop --symbols BTCUSDT ETHUSDT SOLUSDT --run-every-minutes 60
```

Stop the loop with `Ctrl+C`.

Run one scheduler cycle for a quick smoke test:

```powershell
python -m signalpilot --paper-loop --symbols BTCUSDT ETHUSDT SOLUSDT --max-runs 1
```

Send generated signals to Telegram:

```powershell
$env:TELEGRAM_BOT_TOKEN = "123456:your-bot-token"
$env:TELEGRAM_CHAT_ID = "123456789"
python -m signalpilot --symbols BTCUSDT ETHUSDT SOLUSDT --notify
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
python -m unittest discover -s tests
```

The default journal path is `data/signals.sqlite3`.
