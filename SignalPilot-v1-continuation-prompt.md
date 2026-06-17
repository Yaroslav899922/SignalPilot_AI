# Prompt to continue SignalPilot v1 work

Продовжуємо роботу над `D:\Projects\SignalPilot`.

Контекст: ми провели брейнсторм і зафіксували фінальний документ `SignalPilot-v1-Measurement-Spec-4h-Pullback-Plans.md`. Не починай із Telegram, UX, long/short ratio, funding/OI або деплою. Спершу треба побудувати мінімальний evaluation rig, щоб чесно перевірити, чи v1-ідея має сенс.

Головний продуктовий зсув:

- старий бот реагує на breakout і каже "заходь зараз";
- новий v1 має кожні 4 години давати торговий план із limit-зоною або чесно казати "плану немає";
- ціль не "зробити прибуткового бота на віру", а перевірити, чи pullback-план дає перевагу над простим входом у бік 4h-тренду.

Фінальна v1-ідея:

- trend: `4h close > EMA50 > EMA200` для LONG, дзеркально для SHORT;
- pullback mean: `4h EMA50`;
- ATR: `4h ATR`;
- зона: `EMA50 +/- 0.25 * ATR`;
- entry: midpoint зони, тобто приблизно EMA50;
- stop: `1.0 * ATR` за дальнім краєм зони;
- target: `1.5 * ATR` від entry;
- risk приблизно `1.25 * ATR`, target приблизно `1.2R` до комісій;
- timeout: 12 4h-свічок;
- fees+slippage: стартово `0.15% round-trip`, песимістично;
- visible hours: `07:00-23:00 Kyiv`;
- одна активна угода на символ;
- новий 4h-план скасовує старий pending-план;
- злам 4h-тренду скасовує pending-план, але не закриває open trade;
- open trade живе тільки по stop / target / timeout.

Мінімальний rig:

`data -> plan -> fill/no-fill -> trade result -> metrics -> comparison table`

Порівняти:

1. current breakout logic;
2. pullback v1;
3. dumb baseline.

Baseline:

- кожні 4 години, якщо є 4h trend і немає open trade;
- вхід по next open / market;
- без зони;
- stop = `1.25 * ATR` від entry;
- target = `1.5 * ATR` від entry;
- той самий timeout / fees / одна угода на символ.

Метрики:

- головна: `net expectancy in R`;
- також: plans, trades filled, win_rate, avg_win_R, avg_loss_R, expectancy_R, profit_factor, timeout_rate, stop_rate, tp_rate, avg_hold_bars, net_after_fees;
- окремо `research_all_sessions` і `live_visible_sessions`;
- рішення "чи користуватись ботом" приймати тільки по `live_visible_sessions`;
- розбивка по місяцях/періодах;
- bootstrap CI або хоча б чесна похибка результату;
- `missed_move`: plan not filled AND price moved in plan direction >= `1.0 * 4h ATR` from plan creation close before plan expiry. Це діагностика, не P&L;
- `zone_pierce`: fill happened AND stop hit in the same 15m candle as fill. Це входить у P&L і рахується окремо як pierce-rate.

Принципи:

- жодного підгляду в майбутнє;
- зона заморожена на момент плану;
- MFE/MAE для підбору параметрів тільки на train-зрізі, test не чіпати;
- не оптимізувати багато ручок одразу;
- якщо pullback не б'є dumb baseline, ідею не мучимо.

Почни з читання існуючого коду, тестів і документа зі специфікацією. Потім запропонуй або реалізуй мінімальний rig, залежно від мого наступного запиту. Якщо я прямо не скажу "кодимо" або "погнали будувати", лишайся в режимі обговорення.
