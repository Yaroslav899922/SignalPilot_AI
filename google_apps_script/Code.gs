const SIGNALS_SHEET_NAME = "signals";
const SETUPS_SHEET_NAME = "setup_events";
const SIGNAL_COLUMNS = [
  "id",
  "created_at",
  "symbol",
  "interval",
  "direction",
  "market_regime",
  "close_price",
  "funding_rate",
  "open_interest",
  "long_short_ratio",
  "spread_pct",
  "entry_zone",
  "stop",
  "targets_json",
  "risk_reward",
  "confidence",
  "invalidation",
  "reasons_json",
  "evaluated_at",
  "outcome",
  "max_favorable_price",
  "max_adverse_price",
  "trailing_plan",
  "pattern",
  "setup_score",
  "source",
  "result_R",
  "baseline_R",
  "edge_R",
  "entry_low",
  "entry_high",
  "activated_at",
  "setup_id",
  "setup_status",
  "expires_at",
  "event_id",
  "policy_version",
  "detected_at",
  "triggered_at",
  "market_source",
];
const SETUP_COLUMNS = [
  "setup_id",
  "symbol",
  "pattern",
  "direction",
  "status",
  "regime",
  "current_price",
  "trigger_level",
  "entry_low",
  "entry_high",
  "stop",
  "targets_json",
  "risk_reward",
  "score",
  "action",
  "reason",
  "invalidation",
  "conditions_json",
  "created_at",
  "expires_at",
  "source",
  "fingerprint",
  "event_id",
  "policy_version",
  "detected_at",
  "triggered_at",
  "market_source",
  "funding_rate",
  "open_interest",
  "long_short_ratio",
  "spread_pct",
];

function doPost(e) {
  const payload = parsePayload_(e);
  if (payload.action === "tradingview_alert" || payload.source === "tradingview") {
    return handleTradingViewWebhook_(payload);
  }
  if (payload.action) {
    return handleJournalApi_(payload);
  }
  return handleTelegramWebhook_(payload, e);
}

function handleJournalApi_(payload) {
  if (payload.token !== getProperty_("JOURNAL_API_TOKEN")) {
    return jsonResponse_({ ok: false, error: "unauthorized" });
  }

  if (payload.action === "save_signal") {
    return jsonResponse_(saveSignal_(payload.signal));
  }
  if (payload.action === "load_evaluable_signals") {
    return jsonResponse_({ ok: true, signals: loadEvaluableSignals_() });
  }
  if (payload.action === "update_signal_evaluation") {
    updateSignalEvaluation_(payload);
    return jsonResponse_({ ok: true });
  }
  if (payload.action === "summarize_journal") {
    return jsonResponse_({ ok: true, summary: summarizeJournal_() });
  }
  if (payload.action === "save_setup_event") {
    return jsonResponse_(saveSetupEvent_(payload.setup, payload.fingerprint));
  }
  if (payload.action === "load_latest_setups") {
    return jsonResponse_({ ok: true, setups: loadLatestSetups_() });
  }
  return jsonResponse_({ ok: false, error: "unknown action" });
}

function handleTelegramWebhook_(update, e) {
  const expectedSecret = getProperty_("WEBHOOK_SECRET");
  if (expectedSecret && (!e.parameter || e.parameter.secret !== expectedSecret)) {
    return jsonResponse_({ ok: false, error: "bad webhook secret" });
  }

  const message = update.message || {};
  const chat = message.chat || {};
  const chatId = chat.id;
  const text = String(message.text || "").trim();
  if (!chatId || !text) {
    return jsonResponse_({ ok: true });
  }

  const command = parseCommand_(text);
  if (command === "help") {
    sendTelegramMessage_(chatId, helpMessage_());
  } else if (command === "report") {
    sendTelegramMessage_(chatId, reportMessage_(summarizeJournal_()));
  } else if (command === "status") {
    sendTelegramMessage_(chatId, statusMessage_());
  } else if (command === "market") {
    sendTelegramMessage_(chatId, "<b>Перевіряю ринок...</b>\nGitHub запустить SignalPilot і надішле результат сюди.");
    dispatchMarketCheck_(chatId);
  } else {
    sendTelegramMessage_(chatId, "<b>Не зрозумів команду.</b>\nНапиши <b>допомога</b>.");
  }

  return jsonResponse_({ ok: true });
}

function saveSignal_(signal) {
  const sheet = getSignalsSheet_();
  const rows = readRows_(sheet);
  const targetsJson = JSON.stringify(signal.targets || []);
  const reasonsJson = JSON.stringify(signal.reasons || []);
  if (signalExists_(rows, signal, targetsJson)) {
    return { ok: true, inserted: false };
  }

  const nextId = nextId_(rows);
  sheet.appendRow([
    nextId,
    signal.created_at || new Date().toISOString(),
    signal.symbol || "",
    signal.interval || "",
    signal.direction || "",
    signal.market_regime || "",
    nullable_(signal.close_price),
    nullable_(signal.funding_rate),
    nullable_(signal.open_interest),
    nullable_(signal.long_short_ratio),
    nullable_(signal.spread_pct),
    signal.entry_zone || "",
    nullable_(signal.stop),
    targetsJson,
    nullable_(signal.risk_reward),
    signal.confidence || "",
    signal.invalidation || "",
    reasonsJson,
    "",
    "",
    "",
    "",
    signal.trailing_plan || "",
    signal.pattern || "",
    nullable_(signal.setup_score),
    signal.source || "signalpilot",
    "",
    "",
    "",
    nullable_(signal.entry_low),
    nullable_(signal.entry_high),
    "",
    signal.setup_id || "",
    signal.setup_status || "",
    signal.expires_at || "",
    signal.event_id || "",
    signal.policy_version || "legacy_unversioned",
    signal.detected_at || "",
    signal.triggered_at || "",
    signal.market_source || "",
  ]);
  return { ok: true, inserted: true, id: nextId };
}

function loadEvaluableSignals_() {
  return readRows_(getSignalsSheet_())
    .filter((row) => ["LONG", "SHORT"].includes(row.direction))
    .filter((row) => !row.outcome || row.outcome === "not_enough_data")
    .map((row) => ({
      id: Number(row.id),
      created_at: row.created_at,
      symbol: row.symbol,
      interval: row.interval,
      direction: row.direction,
      close_price: numberOrNull_(row.close_price),
      entry_low: numberOrNull_(row.entry_low),
      entry_high: numberOrNull_(row.entry_high),
      stop: numberOrNull_(row.stop),
      targets_json: row.targets_json || "[]",
      source: row.source || "",
      expires_at: row.expires_at || "",
      event_id: row.event_id || row.setup_id || "",
      policy_version: row.policy_version || "legacy_unversioned",
      detected_at: row.detected_at || row.created_at || "",
      triggered_at: row.triggered_at || "",
      market_source: row.market_source || "",
    }));
}

function updateSignalEvaluation_(payload) {
  const sheet = getSignalsSheet_();
  const values = sheet.getDataRange().getValues();
  const idColumn = SIGNAL_COLUMNS.indexOf("id");
  const activatedAtColumn = SIGNAL_COLUMNS.indexOf("activated_at");
  const evaluatedAtColumn = SIGNAL_COLUMNS.indexOf("evaluated_at");
  const outcomeColumn = SIGNAL_COLUMNS.indexOf("outcome");
  const maxFavorableColumn = SIGNAL_COLUMNS.indexOf("max_favorable_price");
  const maxAdverseColumn = SIGNAL_COLUMNS.indexOf("max_adverse_price");
  const resultRColumn = SIGNAL_COLUMNS.indexOf("result_R");
  const baselineRColumn = SIGNAL_COLUMNS.indexOf("baseline_R");
  const edgeRColumn = SIGNAL_COLUMNS.indexOf("edge_R");

  for (let index = 1; index < values.length; index += 1) {
    if (Number(values[index][idColumn]) === Number(payload.signal_id)) {
      const rowNumber = index + 1;
      sheet.getRange(rowNumber, activatedAtColumn + 1).setValue(payload.activated_at || "");
      sheet.getRange(rowNumber, evaluatedAtColumn + 1).setValue(payload.evaluated_at || new Date().toISOString());
      sheet.getRange(rowNumber, outcomeColumn + 1).setValue(payload.outcome || "");
      sheet.getRange(rowNumber, maxFavorableColumn + 1).setValue(nullable_(payload.max_favorable_price));
      sheet.getRange(rowNumber, maxAdverseColumn + 1).setValue(nullable_(payload.max_adverse_price));
      sheet.getRange(rowNumber, resultRColumn + 1).setValue(nullable_(payload.result_R));
      sheet.getRange(rowNumber, baselineRColumn + 1).setValue(nullable_(payload.baseline_R));
      sheet.getRange(rowNumber, edgeRColumn + 1).setValue(nullable_(payload.edge_R));
      return;
    }
  }
}

function summarizeJournal_() {
  const rows = readRows_(getSignalsSheet_());
  const targetHit = rows.filter((row) => row.outcome === "target_hit").length;
  const stopHit = rows.filter((row) => row.outcome === "stop_hit").length;
  const resolved = targetHit + stopHit;
  const confirmedRows = rows.filter((row) => row.source === "actionable_alert");
  const confirmedTarget = confirmedRows.filter((row) => row.outcome === "target_hit").length;
  const confirmedStop = confirmedRows.filter((row) => row.outcome === "stop_hit").length;
  const confirmedResolved = confirmedTarget + confirmedStop;
  return {
    signals: rows.length,
    long: rows.filter((row) => row.direction === "LONG").length,
    short: rows.filter((row) => row.direction === "SHORT").length,
    no_trade: rows.filter((row) => row.direction === "NO TRADE").length,
    pending: rows.filter((row) => ["LONG", "SHORT"].includes(row.direction) && (!row.outcome || row.outcome === "not_enough_data")).length,
    target_hit: targetHit,
    stop_hit: stopHit,
    no_result: rows.filter((row) => row.outcome === "no_result").length,
    not_activated: rows.filter((row) => row.outcome === "not_activated").length,
    win_rate: resolved ? targetHit / resolved : null,
    confirmed_entries: confirmedRows.length,
    confirmed_pending: confirmedRows.filter((row) => !row.outcome || row.outcome === "not_enough_data").length,
    confirmed_target_hit: confirmedTarget,
    confirmed_stop_hit: confirmedStop,
    confirmed_no_result: confirmedRows.filter((row) => row.outcome === "no_result").length,
    confirmed_win_rate: confirmedResolved ? confirmedTarget / confirmedResolved : null,
    confirmed_result_R: sumOptional_(confirmedRows, "result_R"),
    confirmed_baseline_R: sumOptional_(confirmedRows, "baseline_R"),
    confirmed_edge_R: sumOptional_(confirmedRows, "edge_R"),
    legacy_market_brief_rows: rows.filter((row) => row.source === "market_brief").length,
  };
}

function parseCommand_(text) {
  const normalized = text.toLowerCase().trim().replace(/[?!.,:;]/g, "").replace(/\s+/g, " ");
  if (["/start", "/help", "help", "допомога", "команди"].includes(normalized)) {
    return "help";
  }
  if (["звіт", "звит", "надай звіт", "надай звит", "дай звіт", "дай звит", "статистика"].includes(normalized)) {
    return "report";
  }
  if (normalized === "статус") {
    return "status";
  }
  if (["перевір ринок", "перевірити ринок", "перевир ринок"].includes(normalized)) {
    return "market";
  }
  if (normalized.includes("торгов") && normalized.includes("ситуац")) {
    return "market";
  }
  return "unknown";
}

function dispatchMarketCheck_(chatId) {
  dispatchSignalPilotWorkflow_(chatId, "", "", "brief");
}

function dispatchSignalPilotWorkflow_(chatId, symbols, tradingViewPayload, mode) {
  const owner = getProperty_("GITHUB_OWNER");
  const repo = getProperty_("GITHUB_REPO");
  const workflow = getProperty_("GITHUB_WORKFLOW_FILE");
  const token = getProperty_("GITHUB_TOKEN");
  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`;
  UrlFetchApp.fetch(url, {
    method: "post",
    contentType: "application/json",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    payload: JSON.stringify({
      ref: "main",
      inputs: {
        mode: mode || "brief",
        brief_session_key: "market",
      },
    }),
    muteHttpExceptions: true,
  });
}

function handleTradingViewWebhook_(payload) {
  const expectedSecret = getProperty_("TRADINGVIEW_WEBHOOK_SECRET");
  if (expectedSecret && payload.secret !== expectedSecret) {
    return jsonResponse_({ ok: false, error: "bad tradingview secret" });
  }

  const chatId = payload.chat_id || getProperty_("TELEGRAM_CHAT_ID");
  const symbol = normalizeTradingViewSymbol_(payload.symbol || payload.ticker || "");
  if (chatId) {
    sendTelegramMessage_(
      chatId,
      `<b>TradingView trigger отримано:</b> ${symbol || "невідомий символ"}\nSignalPilot перевірить Binance-дані перед алертом.`
    );
  }
  dispatchSignalPilotWorkflow_(chatId, symbol, JSON.stringify(redactTradingViewPayload_(payload)), "setup-check");
  return jsonResponse_({ ok: true, dispatched: true, symbol: symbol });
}

function setTelegramWebhook() {
  const token = getProperty_("TELEGRAM_BOT_TOKEN");
  const webAppUrl = getProperty_("SCRIPT_WEB_APP_URL");
  const secret = getProperty_("WEBHOOK_SECRET");
  const webhookUrl = secret ? `${webAppUrl}?secret=${encodeURIComponent(secret)}` : webAppUrl;
  const response = UrlFetchApp.fetch(`https://api.telegram.org/bot${token}/setWebhook`, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({ url: webhookUrl }),
    muteHttpExceptions: true,
  });
  Logger.log(response.getContentText());
}

function sendTelegramMessage_(chatId, text) {
  const token = getProperty_("TELEGRAM_BOT_TOKEN");
  UrlFetchApp.fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({
      chat_id: String(chatId),
      text: text,
      parse_mode: "HTML",
      disable_web_page_preview: true,
    }),
  });
}

function helpMessage_() {
  return [
    "<b>Команди SignalPilot</b>",
    "",
    "<b>надай звіт</b> - показати статистику журналу",
    "<b>є торгова ситуація?</b> - запустити перевірку BTC/ETH/SOL",
    "<b>перевір ринок</b> - те саме, швидка перевірка ринку",
    "<b>статус</b> - показати, що бот працює",
    "",
    "Бот не відкриває угоди. Він тільки дає підказку для ручного аналізу.",
  ].join("\n");
}

function statusMessage_() {
  return [
    "<b>Статус:</b> бот працює",
    "<b>Журнал:</b> Google Sheet",
    "<b>Режим:</b> GitHub Actions + Google Apps Script",
    "Напиши <b>надай звіт</b> або <b>є торгова ситуація?</b>.",
  ].join("\n");
}

function reportMessage_(summary) {
  const winRate = summary.confirmed_win_rate === null || summary.confirmed_win_rate === undefined
    ? "ще немає завершених входів"
    : `${(summary.confirmed_win_rate * 100).toFixed(1)}%`;
  return [
    "<b>Звіт SignalPilot</b>",
    "",
    "<b>Тільки підтверджені входи</b>",
    `<b>Входів:</b> ${summary.confirmed_entries || 0}`,
    `<b>Ціль спрацювала:</b> ${summary.confirmed_target_hit || 0}`,
    `<b>Захисний вихід:</b> ${summary.confirmed_stop_hit || 0}`,
    `<b>Ще перевіряються:</b> ${summary.confirmed_pending || 0}`,
    `<b>Без чіткого результату:</b> ${summary.confirmed_no_result || 0}`,
    `<b>Успішність завершених:</b> ${winRate}`,
    "",
    `<b>Результат входів:</b> ${formatR_(summary.confirmed_result_R)}`,
    `<b>Якби просто тримали:</b> ${formatR_(summary.confirmed_baseline_R)}`,
    `<b>Перевага сигналів:</b> ${formatR_(summary.confirmed_edge_R)}`,
    "",
    `<b>Старі оглядові плани (не входи):</b> ${summary.legacy_market_brief_rows || 0}`,
    "Це навчальна перевірка без реальних угод.",
  ].join("\n");
}

function getSignalsSheet_() {
  const spreadsheetId = PropertiesService.getScriptProperties().getProperty("SPREADSHEET_ID");
  const spreadsheet = spreadsheetId ? SpreadsheetApp.openById(spreadsheetId) : SpreadsheetApp.getActiveSpreadsheet();
  let sheet = spreadsheet.getSheetByName(SIGNALS_SHEET_NAME);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(SIGNALS_SHEET_NAME);
  }
  const headers = sheet.getRange(1, 1, 1, SIGNAL_COLUMNS.length).getValues()[0];
  if (headers.join("") === "") {
    sheet.getRange(1, 1, 1, SIGNAL_COLUMNS.length).setValues([SIGNAL_COLUMNS]);
  } else {
    ensureSignalColumns_(sheet, headers);
  }
  return sheet;
}

function getSetupsSheet_() {
  const spreadsheetId = PropertiesService.getScriptProperties().getProperty("SPREADSHEET_ID");
  const spreadsheet = spreadsheetId ? SpreadsheetApp.openById(spreadsheetId) : SpreadsheetApp.getActiveSpreadsheet();
  let sheet = spreadsheet.getSheetByName(SETUPS_SHEET_NAME);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(SETUPS_SHEET_NAME);
  }
  const headers = sheet.getRange(1, 1, 1, SETUP_COLUMNS.length).getValues()[0];
  if (headers.join("") === "") {
    sheet.getRange(1, 1, 1, SETUP_COLUMNS.length).setValues([SETUP_COLUMNS]);
  } else {
    ensureColumns_(sheet, headers, SETUP_COLUMNS);
  }
  return sheet;
}

function ensureSignalColumns_(sheet, headers) {
  ensureColumns_(sheet, headers, SIGNAL_COLUMNS);
}

function ensureColumns_(sheet, headers, expectedColumns) {
  const existing = headers.map((value) => String(value)).filter((value) => value);
  const missing = expectedColumns.filter((column) => !existing.includes(column));
  if (!missing.length) {
    return;
  }
  const startColumn = existing.length + 1;
  sheet.getRange(1, startColumn, 1, missing.length).setValues([missing]);
}

function saveSetupEvent_(setup, fingerprint) {
  const sheet = getSetupsSheet_();
  const rows = readRows_(sheet);
  const eventId = setup.event_id || setup.setup_id || "";
  const sameSetupRows = rows.filter(
    (row) => String(row.event_id || row.setup_id || "") === String(eventId)
  );
  const latest = sameSetupRows.length ? sameSetupRows[sameSetupRows.length - 1] : null;
  const exists = latest &&
    String(latest.status) === String(setup.status || "") &&
    String(latest.fingerprint) === String(fingerprint || "");
  if (exists) {
    return { ok: true, inserted: false };
  }
  sheet.appendRow([
    setup.setup_id || "",
    setup.symbol || "",
    setup.pattern || "",
    setup.direction || "",
    setup.status || "",
    setup.regime || "",
    nullable_(setup.current_price),
    nullable_(setup.trigger_level),
    nullable_(setup.entry_low),
    nullable_(setup.entry_high),
    nullable_(setup.stop),
    JSON.stringify(setup.targets || []),
    nullable_(setup.risk_reward),
    nullable_(setup.score),
    setup.action || "",
    setup.reason || "",
    setup.invalidation || "",
    JSON.stringify(setup.conditions || []),
    setup.created_at || new Date().toISOString(),
    setup.expires_at || "",
    setup.source || "actionable_setup",
    fingerprint || "",
    eventId,
    setup.policy_version || "legacy_unversioned",
    setup.detected_at || setup.created_at || "",
    setup.triggered_at || "",
    setup.market_source || "",
    nullable_(setup.funding_rate),
    nullable_(setup.open_interest),
    nullable_(setup.long_short_ratio),
    nullable_(setup.spread_pct),
  ]);
  return { ok: true, inserted: true };
}

function loadLatestSetups_() {
  const latest = {};
  readRows_(getSetupsSheet_()).forEach((row) => {
    latest[String(row.event_id || row.setup_id)] = row;
  });
  return Object.keys(latest).map((setupId) => {
    const row = latest[setupId];
    return {
      setup_id: row.setup_id || "",
      symbol: row.symbol || "",
      pattern: row.pattern || "",
      direction: row.direction || "",
      status: row.status || "",
      regime: row.regime || "",
      current_price: numberOrNull_(row.current_price),
      trigger_level: numberOrNull_(row.trigger_level),
      entry_low: numberOrNull_(row.entry_low),
      entry_high: numberOrNull_(row.entry_high),
      stop: numberOrNull_(row.stop),
      targets: JSON.parse(row.targets_json || "[]"),
      risk_reward: numberOrNull_(row.risk_reward),
      score: numberOrNull_(row.score),
      action: row.action || "",
      reason: row.reason || "",
      invalidation: row.invalidation || "",
      conditions: JSON.parse(row.conditions_json || "[]"),
      created_at: row.created_at || "",
      expires_at: row.expires_at || "",
      source: row.source || "actionable_setup",
      event_id: row.event_id || row.setup_id || "",
      policy_version: row.policy_version || "legacy_unversioned",
      detected_at: row.detected_at || row.created_at || "",
      triggered_at: row.triggered_at || "",
      market_source: row.market_source || "",
      funding_rate: numberOrNull_(row.funding_rate),
      open_interest: numberOrNull_(row.open_interest),
      long_short_ratio: numberOrNull_(row.long_short_ratio),
      spread_pct: numberOrNull_(row.spread_pct),
    };
  });
}

function readRows_(sheet) {
  const values = sheet.getDataRange().getValues();
  if (values.length <= 1) {
    return [];
  }
  const headers = values[0].map((value) => String(value));
  return values.slice(1).filter((row) => row.join("") !== "").map((row) => {
    const item = {};
    headers.forEach((header, index) => {
      item[header] = row[index];
    });
    return item;
  });
}

function signalExists_(rows, signal, targetsJson) {
  if (signal.event_id) {
    return rows.some(
      (row) => String(row.event_id || row.setup_id || "") === String(signal.event_id)
    );
  }
  if (signal.setup_id) {
    return rows.some((row) => String(row.setup_id || "") === String(signal.setup_id));
  }
  return rows.some((row) =>
    row.symbol === signal.symbol &&
    ((signal.source || "") !== "market_brief" || String(row.created_at) === String(signal.created_at || "")) &&
    row.interval === signal.interval &&
    row.direction === signal.direction &&
    String(row.close_price) === String(nullable_(signal.close_price)) &&
    row.entry_zone === (signal.entry_zone || "") &&
    String(row.stop) === String(nullable_(signal.stop)) &&
    row.targets_json === targetsJson &&
    (row.pattern || "") === (signal.pattern || "")
  );
}

function normalizeTradingViewSymbol_(value) {
  let text = String(value || "").trim().toUpperCase();
  if (text.includes(":")) {
    text = text.split(":")[1];
  }
  return text.replace(".P", "").replace(".PERP", "").replace("/", "").replace("-", "");
}

function redactTradingViewPayload_(payload) {
  const copy = Object.assign({}, payload);
  ["secret", "token", "password", "api_key", "apikey", "apiSecret", "api_secret"].forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(copy, key)) {
      copy[key] = "<redacted>";
    }
  });
  return copy;
}

function nextId_(rows) {
  if (!rows.length) {
    return 1;
  }
  return Math.max(...rows.map((row) => Number(row.id) || 0)) + 1;
}

function parsePayload_(e) {
  if (!e || !e.postData || !e.postData.contents) {
    return {};
  }
  return JSON.parse(e.postData.contents);
}

function getProperty_(name) {
  return PropertiesService.getScriptProperties().getProperty(name) || "";
}

function nullable_(value) {
  return value === null || value === undefined ? "" : value;
}

function numberOrNull_(value) {
  if (value === "" || value === null || value === undefined) {
    return null;
  }
  return Number(value);
}

function sumOptional_(rows, column) {
  const values = rows
    .map((row) => row[column])
    .filter((value) => value !== "" && value !== null && value !== undefined)
    .map((value) => Number(value))
    .filter((value) => !Number.isNaN(value));
  if (!values.length) {
    return null;
  }
  return Math.round(values.reduce((total, value) => total + value, 0) * 10000) / 10000;
}

function formatR_(value) {
  if (value === null || value === undefined || value === "") {
    return "ще немає даних";
  }
  const number = Number(value);
  const sign = number > 0 ? "+" : "";
  return `${sign}${number.toFixed(2)}R`;
}

function jsonResponse_(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
