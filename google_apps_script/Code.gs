const SIGNALS_SHEET_NAME = "signals";
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
      stop: numberOrNull_(row.stop),
      targets_json: row.targets_json || "[]",
    }));
}

function updateSignalEvaluation_(payload) {
  const sheet = getSignalsSheet_();
  const values = sheet.getDataRange().getValues();
  const idColumn = SIGNAL_COLUMNS.indexOf("id");
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
  return {
    signals: rows.length,
    long: rows.filter((row) => row.direction === "LONG").length,
    short: rows.filter((row) => row.direction === "SHORT").length,
    no_trade: rows.filter((row) => row.direction === "NO TRADE").length,
    pending: rows.filter((row) => ["LONG", "SHORT"].includes(row.direction) && (!row.outcome || row.outcome === "not_enough_data")).length,
    target_hit: targetHit,
    stop_hit: stopHit,
    no_result: rows.filter((row) => row.outcome === "no_result").length,
    win_rate: resolved ? targetHit / resolved : null,
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
  dispatchSignalPilotWorkflow_(chatId, "", "");
}

function dispatchSignalPilotWorkflow_(chatId, symbols, tradingViewPayload) {
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
        chat_id: String(chatId),
        symbols: String(symbols || ""),
        tradingview_payload: String(tradingViewPayload || ""),
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
  dispatchSignalPilotWorkflow_(chatId, symbol, JSON.stringify(redactTradingViewPayload_(payload)));
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
  const winRate = summary.win_rate === null || summary.win_rate === undefined ? "-" : `${(summary.win_rate * 100).toFixed(1)}%`;
  return [
    "<b>Звіт SignalPilot</b>",
    "",
    `<b>Всього записів:</b> ${summary.signals || 0}`,
    `<b>LONG:</b> ${summary.long || 0}`,
    `<b>SHORT:</b> ${summary.short || 0}`,
    `<b>НЕ ВХОДИТИ:</b> ${summary.no_trade || 0}`,
    `<b>Очікують оцінки:</b> ${summary.pending || 0}`,
    "",
    `<b>Target hit:</b> ${summary.target_hit || 0}`,
    `<b>Stop hit:</b> ${summary.stop_hit || 0}`,
    `<b>No result:</b> ${summary.no_result || 0}`,
    `<b>Win rate:</b> ${winRate}`,
    "",
    "Це paper-test статистика. SignalPilot не відкриває угоди.",
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

function ensureSignalColumns_(sheet, headers) {
  const existing = headers.map((value) => String(value)).filter((value) => value);
  const missing = SIGNAL_COLUMNS.filter((column) => !existing.includes(column));
  if (!missing.length) {
    return;
  }
  const startColumn = existing.length + 1;
  sheet.getRange(1, startColumn, 1, missing.length).setValues([missing]);
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
  return rows.some((row) =>
    row.symbol === signal.symbol &&
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

function jsonResponse_(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
