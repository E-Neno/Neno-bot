import { getAdminHeaders, getAdminToken, requestJson } from "./api.js";
import { clearChildren, createElement, setBusyButton, setOptionalText } from "./dom.js";

export function renderProactiveCandidates(candidates) {
  const list = document.getElementById("proactiveCandidateList");
  const historyList = document.getElementById("proactiveHistoryList");
  const items = candidates || [];
  const pending = items.filter((candidate) => candidate.status === "pending");
  const history = sortProactiveHistory(
    items.filter((candidate) => candidate.status !== "pending")
  );
  const visibleHistory = history.slice(0, 5);

  renderProactiveCandidateList(list, pending, "暂无 pending 候选");
  renderProactiveCandidateList(historyList, visibleHistory, "暂无历史候选");
  if (historyList && history.length > visibleHistory.length) {
    const note = document.createElement("div");
    note.className = "history-note";
    note.textContent = "仅显示最近 5 条历史";
    historyList.appendChild(note);
  }
}

export function renderProactiveTargets(targets) {
  const list = document.getElementById("proactiveTargetList");
  const items = targets || [];
  if (!list) {
    return;
  }
  if (items.length === 0) {
    list.textContent = "暂无主动目标。请先通过 QQ 私聊给机器人发一条消息。";
    return;
  }

  clearChildren(list);
  const latestQq = items.find((target) => target.platform === "qq") || items[0];
  const title = createElement("div", "candidate-meta", "最近 QQ 主动目标");
  list.appendChild(title);
  list.appendChild(createProactiveTargetItem(latestQq));
}

function createProactiveTargetItem(target) {
  const item = document.createElement("div");
  item.className = "candidate-item";

  const tag = document.createElement("div");
  tag.className = `tag ${target.is_allowed ? "sent" : "failed"}`;
  tag.textContent = `${target.platform || "-"} · ${target.is_allowed ? "allowed" : "not allowed"}`;

  const label = document.createElement("div");
  label.className = "candidate-content";
  label.textContent = target.target_label || "-";

  const meta = document.createElement("div");
  meta.className = "candidate-meta";
  meta.textContent = [
    `last_seen_at=${target.last_seen_at || "-"}`,
    `session_id_saved=${target.session_id_saved === true ? "true" : "false"}`,
  ].join(" · ");

  item.append(tag, label, meta);
  return item;
}

function proactiveReasonText(reason) {
  const text = String(reason || "");
  const lower = text.toLowerCase();
  if (!text) return "-";
  if (lower.includes("random probability missed")) return "随机概率未命中";
  if (lower.includes("pending candidate exists") || lower.includes("pending qq candidate exists")) return "已有待处理候选";
  if (lower.includes("latest qq target is not whitelisted")) return "最近 QQ 目标未允许";
  if (lower.includes("outside active window")) return "不在允许时间段";
  if (lower.includes("recent chat exists") || lower.includes("qq user message seen") || lower.includes("user message seen")) return "最近刚聊过";
  if (lower.includes("daily limit reached") || lower.includes("daily sent limit reached")) return "今日已达上限";
  if (lower.includes("min interval not reached") || lower.includes("last sent is within")) return "距离上次主动消息还不够久";
  return text;
}

function proactiveEventStateClass(event) {
  if (event.success === false) return "failed";
  if (event.skipped === true) return "dismissed";
  if (event.success === true) return "sent";
  return "dismissed";
}

export function renderProactiveEvents(events) {
  const list = document.getElementById("proactiveEventList");
  const items = events || [];
  if (!list) {
    return;
  }
  if (items.length === 0) {
    list.textContent = "暂无调度事件";
    return;
  }

  clearChildren(list);
  for (const event of items) {
    list.appendChild(createProactiveEventItem(event));
  }
}

function createProactiveEventItem(event) {
  const item = document.createElement("div");
  item.className = "candidate-item";

  const tag = document.createElement("div");
  tag.className = `tag ${proactiveEventStateClass(event)}`;
  tag.textContent = event.event_type || "-";

  const action = document.createElement("div");
  action.className = "candidate-content";
  action.textContent = event.action || "-";

  const meta = document.createElement("div");
  meta.className = "candidate-meta";
  meta.textContent = [
    event.created_at || "-",
    `candidate_id=${event.candidate_id ?? "-"}`,
    `target=${event.target_label || "-"}`,
  ].join(" · ");

  const reason = document.createElement("div");
  reason.className = "candidate-meta";
  reason.textContent = proactiveReasonText(event.reason);

  item.append(tag, action, meta, reason);
  return item;
}

function sortProactiveHistory(candidates) {
  return candidates.slice().sort((a, b) => {
    const aTime = Date.parse(a.updated_at || a.sent_at || a.created_at || "");
    const bTime = Date.parse(b.updated_at || b.sent_at || b.created_at || "");
    if (!Number.isNaN(aTime) && !Number.isNaN(bTime) && aTime !== bTime) {
      return bTime - aTime;
    }
    return (b.id || 0) - (a.id || 0);
  });
}

function renderProactiveCandidateList(list, candidates, emptyText) {
  if (!list) {
    return;
  }
  if (!candidates || candidates.length === 0) {
    list.textContent = emptyText;
    return;
  }
  clearChildren(list);
  for (const candidate of candidates) {
    list.appendChild(createProactiveCandidateItem(candidate));
  }
}

function candidateStatusLabel(status) {
  if (status === "pending") return "pending";
  if (status === "sent") return "sent";
  if (status === "dismissed") return "dismissed";
  if (status === "failed") return "failed";
  return status || "-";
}

function createProactiveCandidateItem(candidate) {
  const item = document.createElement("div");
  item.className = "candidate-item";

  const tag = document.createElement("div");
  tag.className = `tag ${candidate.status || ""}`;
  tag.textContent = `${candidate.platform || "-"} · ${candidateStatusLabel(candidate.status)} · ${candidate.target_label || "-"}`;

  const content = document.createElement("div");
  content.className = "candidate-content";
  content.textContent = candidate.message || "";

  const reason = document.createElement("div");
  reason.className = "candidate-meta";
  reason.textContent = candidate.reason || "";

  const meta = document.createElement("div");
  meta.className = "candidate-meta";
  meta.textContent = `id=${candidate.id} · ${candidate.created_at || ""}`;

  const row = document.createElement("div");
  row.className = "row";

  if (candidate.status === "pending") {
    if (candidate.platform === "qq") {
      appendQqSendButtons(row, candidate);
    } else {
      appendCandidateStatusText(row, "非 QQ 候选");
    }
    appendDismissButton(row, candidate);
  } else if (candidate.status === "dismissed") {
    appendCandidateStatusText(row, "已丢弃");
  } else if (candidate.status === "sent") {
    appendCandidateStatusText(row, "已发送");
  } else if (candidate.status === "failed") {
    appendCandidateStatusText(row, "发送失败");
  } else {
    appendCandidateStatusText(row, candidate.status || "未知状态");
  }

  item.append(tag, content, reason, meta, row);
  return item;
}

function appendCandidateStatusText(row, text) {
  const statusText = document.createElement("span");
  statusText.className = "candidate-state-text";
  statusText.textContent = text;
  row.appendChild(statusText);
}

function appendDismissButton(row, candidate) {
  const dismissButton = document.createElement("button");
  dismissButton.className = candidate.status === "pending" ? "danger" : "";
  dismissButton.textContent = "丢弃";
  dismissButton.addEventListener("click", () => dismissProactiveCandidate(candidate.id, dismissButton));
  row.appendChild(dismissButton);
}

function appendQqSendButtons(row, candidate) {
  const dryRunButton = document.createElement("button");
  dryRunButton.className = "good";
  dryRunButton.textContent = "测试发送 QQ";
  dryRunButton.addEventListener("click", () => dryRunSendQqCandidate(candidate.id, dryRunButton));
  row.appendChild(dryRunButton);

  const sendButton = document.createElement("button");
  sendButton.className = "danger";
  sendButton.textContent = "真实发送 QQ";
  sendButton.addEventListener("click", () => sendQqCandidate(candidate.id, sendButton));
  row.appendChild(sendButton);
}

function formatCheckState(ok) {
  if (ok === true) {
    return "通过";
  }
  if (ok === false) {
    return "未通过";
  }
  return "不参与判断";
}

export function renderProactiveChecks(checks) {
  const list = document.getElementById("proactiveCheckNowChecks");
  if (!list) {
    return;
  }
  if (!checks || checks.length === 0) {
    list.textContent = "没有检查结果";
    return;
  }

  clearChildren(list);
  for (const check of checks) {
    const item = document.createElement("div");
    item.className = "check-item";

    const tag = document.createElement("div");
    const okClass = check.ok === true ? "sent" : check.ok === false ? "failed" : "dismissed";
    tag.className = `tag ${okClass}`;
    tag.textContent = formatCheckState(check.ok);

    const name = document.createElement("div");
    name.className = "check-name";
    name.textContent = check.name || "-";

    const detail = document.createElement("div");
    detail.className = "check-detail";
    detail.textContent = check.detail || "";

    item.append(tag, name, detail);
    list.appendChild(item);
  }
}

function renderProactiveDecision(data) {
  const canSend = data?.can_send ?? data?.can_send_now?.can_send ?? data?.can_send_now?.boolean;
  const reason = data?.reason ?? data?.can_send_now?.reason ?? "-";
  setOptionalText("proactiveCanSendNow", canSend === true ? "自动调度规则允许发送" : "自动调度当前不会发送");
  setOptionalText("proactiveCanSendReason", reason);
  if (Array.isArray(data?.checks)) {
    renderProactiveChecks(data.checks);
  }
}

function renderProactiveRulesSummary(items) {
  const box = document.getElementById("proactiveRulesSummary");
  if (!box) {
    return;
  }
  if (!items || items.length === 0) {
    box.textContent = "规则摘要未加载";
    return;
  }
  box.textContent = items.map((item) => `- ${item}`).join("\n");
}

function renderProactiveLastResult(result) {
  const box = document.getElementById("proactiveLastResult");
  if (!box) {
    return;
  }
  if (!result) {
    box.textContent = "上次检查结果：暂无";
    return;
  }

  const parts = [];
  if (result.action) {
    parts.push(result.action);
  } else if (result.skipped === true) {
    parts.push("已跳过");
  } else if (result.sent === true) {
    parts.push("已发送");
  } else if (result.success === false) {
    parts.push("失败");
  } else {
    parts.push("已检查");
  }
  if (result.reason) {
    parts.push(result.reason);
  }
  if (result.candidate_id) {
    parts.push(`candidate id=${result.candidate_id}`);
  }
  box.textContent = `上次检查结果：${parts.join(" · ")}`;
}

export function renderProactiveAutoStatus(data) {
  const box = document.getElementById("proactiveAutoStatus");
  const config = data.config || {};
  const enabled = data.enabled ? "开启" : "关闭";
  const running = data.task_running ? "运行中" : "未运行";
  const lastSent = data.last_sent_at || "-";
  const lastCheck = data.last_check_at || "-";
  const today = data.today_sent_count ?? 0;
  const limit = config.daily_limit ?? "-";
  const autoSend = data.auto_send_enabled ? "开启" : "关闭";
  const autoDryRun = data.auto_send_dry_run ? "开启" : "关闭";
  const requireAllowed = data.auto_send_require_allowed_target ? "是" : "否";
  const autoSentToday = data.auto_sent_today ?? 0;
  const autoSendLimit = data.auto_send_max_per_day ?? "-";
  const lastAction = data.last_result?.action || (data.last_result?.skipped ? "skipped" : "-");

  if (box) {
    box.textContent = [
      `自动：${enabled} · ${running}`,
      `今日 ${today}/${limit}`,
      `自动真实发送 ${autoSend}`,
      `自动 dry_run ${autoDryRun}`,
      `自动发送 ${autoSentToday}/${autoSendLimit}`,
      `目标必须 allowed ${requireAllowed}`,
      `最近自动结果 ${lastAction}`,
      `最近发送 ${lastSent}`,
      `最近检查 ${lastCheck}`,
      `间隔 ${config.check_interval_seconds ?? "-"}s`,
      `时间窗 ${config.active_start || "-"}-${config.active_end || "-"}`,
    ].join(" · ");
  }

  setOptionalText("proactiveStatusEnabled", enabled);
  setOptionalText("proactiveStatusRunning", running);
  setOptionalText("proactiveStatusToday", `${today}/${limit}`);
  setOptionalText("proactiveStatusAutoSend", autoSend);
  setOptionalText("proactiveStatusAutoDryRun", autoDryRun);
  setOptionalText("proactiveStatusAutoSentToday", `${autoSentToday}/${autoSendLimit}`);
  setOptionalText("proactiveStatusAutoRequireAllowed", requireAllowed);
  setOptionalText("proactiveStatusLastSent", lastSent);
  setOptionalText("proactiveStatusLastCheck", lastCheck);
  renderProactiveLastResult(data.last_result);
  renderProactiveRulesSummary(data.next_rules_summary || []);
  renderProactiveDecision(data);
}

export async function loadProactiveStatus() {
  const box = document.getElementById("proactiveAutoStatus");
  const token = getAdminToken();

  if (!box) {
    return;
  }
  if (!token) {
    box.textContent = "自动状态需要 Admin Token";
    return;
  }

  try {
    const data = await requestJson(
      "/proactive/status",
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载自动状态失败："
    );
    renderProactiveAutoStatus(data);
  } catch (err) {
    box.textContent = err.message;
  }
}

export async function checkProactiveNow(triggerButton) {
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!token) {
    status.textContent = "需要 Admin Token";
    resetButton();
    return;
  }

  status.textContent = "处理中...";
  try {
    const data = await requestJson(
      "/proactive/check-now",
      {
        method: "POST",
        headers: getAdminHeaders(),
      },
      "检查失败："
    );
    renderProactiveDecision(data);
    status.textContent = "自动调度当前判断已刷新";
    loadProactiveEvents();
  } catch (err) {
    status.textContent = err.message;
  } finally {
    resetButton();
  }
}

function setInputValue(id, value) {
  const input = document.getElementById(id);
  if (input) {
    input.value = value ?? "";
  }
}

function readNumberInput(id) {
  const value = document.getElementById(id).value;
  return Number(value);
}

function renderProactiveConfig(data) {
  const config = data.config || {};
  const hashesInput = document.getElementById("proactiveAllowedHashesInput");
  const hashesPreview = document.getElementById("proactiveAllowedHashesPreview");
  const labels = config.PROACTIVE_QQ_ALLOWED_TARGET_HASHES_LABELS || [];

  setInputValue("proactiveEnabledInput", config.PROACTIVE_ENABLED || "false");
  setInputValue("proactiveCheckIntervalInput", config.PROACTIVE_CHECK_INTERVAL_SECONDS);
  setInputValue("proactiveDailyLimitInput", config.PROACTIVE_DAILY_LIMIT);
  setInputValue("proactiveMinIntervalInput", config.PROACTIVE_MIN_INTERVAL_MINUTES);
  setInputValue("proactiveRecentSkipInput", config.PROACTIVE_RECENT_CHAT_SKIP_MINUTES);
  setInputValue("proactiveActiveStartInput", config.PROACTIVE_ACTIVE_START);
  setInputValue("proactiveActiveEndInput", config.PROACTIVE_ACTIVE_END);
  setInputValue("proactiveRandomProbabilityInput", config.PROACTIVE_RANDOM_PROBABILITY);
  setInputValue("proactiveAutoSendInput", config.PROACTIVE_AUTO_SEND || "false");
  setInputValue("proactiveAutoSendDryRunInput", config.PROACTIVE_AUTO_SEND_DRY_RUN || "false");
  setInputValue("proactiveAutoSendRequireAllowedInput", config.PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET || "true");
  setInputValue("proactiveAutoSendMaxPerDayInput", config.PROACTIVE_AUTO_SEND_MAX_PER_DAY || "1");
  setInputValue("proactiveBridgeUrlInput", config.NENO_BRIDGE_SEND_QQ_URL);

  if (hashesInput) {
    hashesInput.value = "";
    hashesInput.dataset.dirty = "false";
    hashesInput.placeholder = labels.length ? "留空保留当前白名单；输入逗号分隔 hash 覆盖" : "为空；输入逗号分隔 hash 覆盖";
  }

  if (hashesPreview) {
    hashesPreview.textContent = labels.length
      ? `当前白名单：${labels.join(", ")}`
      : "当前白名单为空";
  }
}

export async function loadProactiveConfig() {
  const status = document.getElementById("proactiveConfigStatus");
  const token = getAdminToken();

  if (!token) {
    status.textContent = "需要 Admin Token";
    return;
  }

  status.textContent = "加载配置中...";
  try {
    const data = await requestJson(
      "/proactive/config",
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载配置失败："
    );
    renderProactiveConfig(data);
    status.textContent = "配置已刷新";
    loadProactiveStatus();
  } catch (err) {
    status.textContent = err.message;
  }
}

export async function saveProactiveConfig() {
  const status = document.getElementById("proactiveConfigStatus");
  const token = getAdminToken();

  if (!token) {
    status.textContent = "需要 Admin Token";
    return;
  }

  const hashesInput = document.getElementById("proactiveAllowedHashesInput");
  const payload = {
    PROACTIVE_ENABLED: document.getElementById("proactiveEnabledInput").value === "true",
    PROACTIVE_CHECK_INTERVAL_SECONDS: readNumberInput("proactiveCheckIntervalInput"),
    PROACTIVE_DAILY_LIMIT: readNumberInput("proactiveDailyLimitInput"),
    PROACTIVE_MIN_INTERVAL_MINUTES: readNumberInput("proactiveMinIntervalInput"),
    PROACTIVE_RECENT_CHAT_SKIP_MINUTES: readNumberInput("proactiveRecentSkipInput"),
    PROACTIVE_ACTIVE_START: document.getElementById("proactiveActiveStartInput").value,
    PROACTIVE_ACTIVE_END: document.getElementById("proactiveActiveEndInput").value,
    PROACTIVE_RANDOM_PROBABILITY: Number(document.getElementById("proactiveRandomProbabilityInput").value),
    PROACTIVE_AUTO_SEND: document.getElementById("proactiveAutoSendInput").value === "true",
    PROACTIVE_AUTO_SEND_DRY_RUN: document.getElementById("proactiveAutoSendDryRunInput").value === "true",
    PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET: document.getElementById("proactiveAutoSendRequireAllowedInput").value === "true",
    PROACTIVE_AUTO_SEND_MAX_PER_DAY: readNumberInput("proactiveAutoSendMaxPerDayInput"),
    NENO_BRIDGE_SEND_QQ_URL: document.getElementById("proactiveBridgeUrlInput").value.trim(),
  };

  if (hashesInput?.dataset.dirty === "true") {
    payload.PROACTIVE_QQ_ALLOWED_TARGET_HASHES = hashesInput.value.trim();
  }

  status.textContent = "保存配置中...";
  try {
    await requestJson(
      "/proactive/config",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify(payload),
      },
      "保存配置失败："
    );
    await loadProactiveConfig();
    status.textContent = "已保存，需要执行 nereboot 或 sudo systemctl restart emotion-bot.service 生效。重启后刷新状态。";
  } catch (err) {
    status.textContent = err.message;
  }
}

export async function loadProactiveCandidates(triggerButton) {
  const list = document.getElementById("proactiveCandidateList");
  const historyList = document.getElementById("proactiveHistoryList");
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!token) {
    list.textContent = "需要 Admin Token";
    if (historyList) {
      historyList.textContent = "需要 Admin Token";
    }
    status.textContent = "";
    loadProactiveStatus();
    resetButton();
    return;
  }

  list.textContent = "加载中...";
  if (historyList) {
    historyList.textContent = "加载中...";
  }
  status.textContent = "处理中...";

  try {
    const data = await requestJson(
      "/proactive/candidates",
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载失败："
    );
    renderProactiveCandidates(data.candidates || []);
    status.textContent = "已刷新";
    loadProactiveStatus();
  } catch (err) {
    list.textContent = err.message;
    if (historyList) {
      historyList.textContent = err.message;
    }
    status.textContent = err.message;
  } finally {
    resetButton();
  }
}

export async function loadProactiveTargets(triggerButton) {
  const list = document.getElementById("proactiveTargetList");
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!list) {
    resetButton();
    return;
  }
  if (!token) {
    list.textContent = "需要 Admin Token";
    if (status) {
      status.textContent = "";
    }
    resetButton();
    return;
  }

  list.textContent = "加载中...";
  try {
    const data = await requestJson(
      "/proactive/targets",
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载主动目标失败："
    );
    renderProactiveTargets(data.targets || []);
    if (status) {
      status.textContent = "主动目标已刷新";
    }
  } catch (err) {
    list.textContent = err.message;
    if (status) {
      status.textContent = err.message;
    }
  } finally {
    resetButton();
  }
}

export async function loadProactiveEvents(triggerButton) {
  const list = document.getElementById("proactiveEventList");
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!list) {
    resetButton();
    return;
  }
  if (!token) {
    list.textContent = "需要 Admin Token";
    if (status) {
      status.textContent = "";
    }
    resetButton();
    return;
  }

  list.textContent = "加载中...";
  try {
    const data = await requestJson(
      "/proactive/events?limit=30",
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载时间线失败："
    );
    renderProactiveEvents(data.events || []);
    if (status) {
      status.textContent = "调度时间线已刷新";
    }
  } catch (err) {
    list.textContent = err.message;
    if (status) {
      status.textContent = err.message;
    }
  } finally {
    resetButton();
  }
}

export async function generateProactiveCandidate(triggerButton) {
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!token) {
    status.textContent = "需要 Admin Token";
    resetButton();
    return;
  }

  const platform = document.getElementById("proactivePlatformSelect").value;
  const payload = platform ? { platform } : {};
  status.textContent = "处理中...";

  try {
    const data = await requestJson(
      "/proactive/generate",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify(payload),
      },
      "生成失败："
    );

    if (data.skipped) {
      status.textContent = `已跳过：${data.reason || ""}`;
    } else {
      status.textContent = "已按自动规则生成候选";
    }
    loadProactiveCandidates();
    loadProactiveStatus();
    loadProactiveTargets();
    loadProactiveEvents();
  } catch (err) {
    status.textContent = err.message;
  } finally {
    resetButton();
  }
}

export async function generateProactiveTestCandidate(triggerButton, force) {
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!token) {
    status.textContent = "需要 Admin Token";
    resetButton();
    return;
  }

  status.textContent = force ? "强制生成测试候选中..." : "生成测试候选中...";

  try {
    const data = await requestJson(
      "/proactive/generate-test",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({ force }),
      },
      "生成测试候选失败："
    );
    const savedText = data.session_id_saved ? "，已保存 session_id" : "";
    status.textContent = `已生成测试候选${savedText}`;
    loadProactiveCandidates();
    loadProactiveStatus();
    loadProactiveTargets();
    loadProactiveEvents();
  } catch (err) {
    if (String(err.message || "").includes("409")) {
      status.textContent = "已有待处理候选，可先发送/丢弃，或使用强制生成测试候选。";
    } else {
      status.textContent = err.message;
    }
  } finally {
    resetButton();
  }
}

export async function dismissProactiveCandidate(id, triggerButton) {
  const status = document.getElementById("proactiveCandidateStatus");
  const resetButton = setBusyButton(triggerButton);
  status.textContent = "处理中...";

  try {
    await requestJson(
      "/proactive/dismiss",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({ id }),
      },
      "丢弃失败："
    );
    status.textContent = "已丢弃";
    loadProactiveCandidates();
    loadProactiveStatus();
    loadProactiveEvents();
  } catch (err) {
    status.textContent = err.message;
  } finally {
    resetButton();
  }
}

export async function dryRunSendQqCandidate(id, triggerButton) {
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!token) {
    status.textContent = "需要 Admin Token";
    resetButton();
    return;
  }

  status.textContent = "处理中...";

  try {
    const data = await requestJson(
      "/proactive/send-qq",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({ id, dry_run: true }),
      },
      "测试失败："
    );
    status.textContent = `dry_run 通过：将发送到 ${data.target_label || "-"}`;
    loadProactiveCandidates();
    loadProactiveStatus();
    loadProactiveEvents();
  } catch (err) {
    status.textContent = err.message;
  } finally {
    resetButton();
  }
}

export async function sendQqCandidate(id, triggerButton) {
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!token) {
    status.textContent = "需要 Admin Token";
    resetButton();
    return;
  }

  const ok = confirm("确认发送这条主动消息到 QQ？这会真的发出去。");
  if (!ok) {
    resetButton();
    return;
  }

  status.textContent = "处理中...";

  try {
    const data = await requestJson(
      "/proactive/send-qq",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({ id, dry_run: false }),
      },
      "发送失败："
    );
    status.textContent = `已真实发送到 ${data.target_label || "-"}`;
    loadProactiveCandidates();
    loadProactiveStatus();
    loadProactiveEvents();
  } catch (err) {
    status.textContent = err.message;
    loadProactiveCandidates();
    loadProactiveStatus();
  } finally {
    resetButton();
  }
}

export function bindProactiveEvents() {
  document.getElementById("generateProactiveTestCandidateBtn").addEventListener("click", function () {
    generateProactiveTestCandidate(this, false);
  });
  document.getElementById("forceGenerateProactiveTestCandidateBtn").addEventListener("click", function () {
    generateProactiveTestCandidate(this, true);
  });
  document.getElementById("generateProactiveCandidateBtn").addEventListener("click", function () {
    generateProactiveCandidate(this);
  });
  document.getElementById("loadProactiveCandidatesBtn").addEventListener("click", function () {
    loadProactiveCandidates(this);
  });
  document.getElementById("loadProactiveTargetsBtn").addEventListener("click", function () {
    loadProactiveTargets(this);
  });
  document.getElementById("loadProactiveEventsBtn").addEventListener("click", function () {
    loadProactiveEvents(this);
  });
  document.getElementById("checkProactiveNowBtn").addEventListener("click", function () {
    checkProactiveNow(this);
  });
  document.getElementById("loadProactiveConfigBtn").addEventListener("click", loadProactiveConfig);
  document.getElementById("saveProactiveConfigBtn").addEventListener("click", saveProactiveConfig);
  document.getElementById("proactiveAllowedHashesInput").addEventListener("input", function () {
    this.dataset.dirty = "true";
  });
}
