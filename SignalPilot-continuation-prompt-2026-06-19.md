# Промт продовження роботи над SignalPilot (на 2026-06-19)

Продовжуємо роботу над `D:\Projects\SignalPilot`.

Я не програміст — пояснюй простими словами, маленькими кроками, один крок за раз; я пишу «готово» / «погнали». **Поки я прямо не скажу «погнали» — лишайся в режимі обговорення, нічого не будуй.**

## Де ми зараз

Система повністю відновлена і запущена:
- **Telegram працює** — бот надсилає сигнали LONG/SHORT, мовчить при NO TRADE.
- **GitHub Actions** — workflow `live-paper-test.yml` запускається **автоматично щогодини** і вручну.
- **Klines** — тягнуться через `data-api.binance.vision` (Binance публічний endpoint без гео-блоку).
- **Futures context** (funding rate, OI, L/S ratio, spread) — **недоступний** з GitHub Actions, бо `fapi.binance.com` повертає HTTP 451 з US-серверів. Відображається як `-` в Telegram. Не блокує сигнали (вже виправлено — `None` = нейтрально).

## Що вирішили сьогодні

Було два аварійних стопи в коді (залишились з минулого разу щоб зупинити спам):
1. `__main__.py` — замість запуску програми просто виводив `{"signalpilot": "disabled"}` і виходив.
2. `telegram.py` → `_post_telegram` — одразу повертав заглушку замість реального HTTP запиту.

Обидва видалили. Також:
- Додали fallback на `data-api.binance.vision` при HTTP 451 в `binance.py`.
- Виправили `_context_allows` в `patterns.py`: тепер блокує тільки коли дані є і погані, не коли недоступні.
- Додали щогодинний schedule в `.github/workflows/live-paper-test.yml`.

## Наступний крок (почати звідси)

**Завдання: підключити CoinGlass API для отримання futures context даних.**

Мета: щоб funding rate, open interest, long/short ratio і spread були реальними, а не `null`.

CoinGlass має безкоштовний публічний API, який не заблокований з GitHub Actions.

### Що обговорити перед початком:
1. Зайти на [coinglass.com/api](https://coinglass.com/api) і подивитись які ендпоїнти доступні безкоштовно.
2. Чи потрібен API ключ для безкоштовного tier?
3. Які саме ендпоїнти нам потрібні: funding rate, open interest, long/short ratio.
4. Оновити `market_data.py` і `binance.py` — додати `coinglass.py` як новий модуль.

**Поки не кажеш «погнали» — тільки обговорення.**

## Дисципліна розробки

- Зміни — маленькими кроками, тести після кожної.
- Новий модуль → не чіпаємо існуючий `binance.py` без потреби.
- Перевіряємо через GitHub Actions (реальний environment) а не тільки локально.
- Спочатку `--notify-no-trade` для тесту, потім прибираємо.

## Файли для довідки

- `src/signalpilot/binance.py` — функції fetch_klines, fetch_funding_rate і т.д.
- `src/signalpilot/market_data.py` — `fetch_futures_context`, `_safe_fetch`
- `src/signalpilot/patterns.py` — `_context_allows`
- `.github/workflows/live-paper-test.yml` — CI/CD pipeline
- `RIG-REVIEW-NOTES.md` — загальний контекст проєкту
