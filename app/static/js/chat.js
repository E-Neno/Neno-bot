import { clearChildren, createElement, setBusyButton, setOptionalText, truncateText } from "./dom.js";
import { getAdminHeaders, requestJson } from "./api.js";
import {
  updateCurrentSessionStatus as setCurrentSessionStatus,
  updateSessionMessageCount,
} from "./layout.js";

let lastCandidate = null;
let lastCandidateDebug = null;
let lastCandidateDecision = null;
let input = null;
let sendBtn = null;
let previewBtn = null;
let relationshipStateRenderer = () => {};
let relationshipContextRenderer = () => {};
let reloadSessionMessages = async () => {};
let renderedMessages = [];
let selectedMessageId = null;
let previewedMessageId = null;
let routingStatusNode = null;
let routingExplainNode = null;
let routingSourceHintNode = null;
let routingSourceSummaryNode = null;
let routingQueryBtn = null;
let routingSetBtn = null;
let routingClearBtn = null;
let routingAutofillBtn = null;
let refreshSessionDebugBtn = null;

function ensureContextMenu() {
  let menu = document.getElementById("messageContextMenu");
  if (menu) {
    return menu;
  }
  menu = document.createElement("div");
  menu.id = "messageContextMenu";
  menu.className = "message-context-menu hidden";
  document.body.appendChild(menu);
  document.addEventListener("click", hideContextMenu);
  window.addEventListener("resize", hideContextMenu);
  document.getElementById("messages")?.addEventListener("scroll", hideContextMenu);
  return menu;
}

export function hideContextMenu() {
  const menu = document.getElementById("messageContextMenu");
  if (menu) {
    menu.classList.add("hidden");
    menu.replaceChildren();
  }
}

export function showContextMenu(event, actions = []) {
  event.preventDefault();
  const menu = ensureContextMenu();
  menu.replaceChildren();

  for (const action of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = action.label;
    if (action.className) {
      button.className = action.className;
    }
    button.addEventListener("click", async () => {
      hideContextMenu();
      await action.onClick?.();
    });
    menu.appendChild(button);
  }

  menu.classList.remove("hidden");
  const maxLeft = window.innerWidth - 220;
  const maxTop = window.innerHeight - 120;
  menu.style.left = `${Math.max(8, Math.min(event.clientX, maxLeft))}px`;
  menu.style.top = `${Math.max(8, Math.min(event.clientY, maxTop))}px`;
}

function normalizeMessage(messageOrRole, text) {
  if (typeof messageOrRole === "string") {
    return {
      role: messageOrRole === "user" ? "user" : "assistant",
      content: text || "",
      message_type: messageOrRole === "user" ? "text" : "assistant",
      metadata: messageOrRole === "user" ? buildTextInputRecord(text || "", "web") : null,
      has_preview: false,
    };
  }

  const role = messageOrRole?.role === "user" ? "user" : "assistant";
  return {
    role,
    content: messageOrRole?.content || "",
    id: messageOrRole?.id ?? null,
    trace_id: messageOrRole?.trace_id || null,
    created_at: messageOrRole?.created_at || null,
    message_type: messageOrRole?.message_type || (role === "user" ? "text" : "assistant"),
    source: messageOrRole?.source || "chat",
    metadata: messageOrRole?.metadata || null,
    has_preview: Boolean(messageOrRole?.has_preview),
  };
}

function setSelectedMessage(messageId) {
  selectedMessageId = messageId ?? null;
  for (const row of document.querySelectorAll("#messages .message-row")) {
    row.classList.toggle("is-selected", row.dataset.messageId === String(selectedMessageId));
  }
}

function clearMessageDebugPanel() {
  const status = document.getElementById("messageDebugStatus");
  if (status) {
    status.textContent = "尚未选择消息。";
  }
  const box = document.getElementById("messageDebugBox");
  if (box) {
    clearChildren(box);
    box.textContent = "右键任意 user / assistant 消息，查看该轮聚合与提交调试信息。";
  }
}

function clearPreviewPanel() {
  previewedMessageId = null;
  const status = document.getElementById("chatPreviewStatus");
  if (status) {
    status.textContent = "尚未预览；右键一条输入消息可直接查看真实链路。";
  }
  const box = document.getElementById("chatPreviewBox");
  if (box) {
    clearChildren(box);
  }
}

function findRenderedMessageById(messageId) {
  return renderedMessages.find((item) => item?.id === messageId) || null;
}

function renderSelectedMessageDebug(messageId) {
  const message = findRenderedMessageById(messageId);
  if (!message) {
    clearMessageDebugPanel();
    return;
  }
  renderMessageDebugPanel({
    trace_id: message.trace_id,
    message_id: message.id,
    message,
    preview_source_message_id: message.metadata?.preview_source_message_id || null,
    preview_source_role: message.metadata?.preview_source_message_id ? "user" : message.role,
    preview_source_metadata: message.metadata?.preview_source_metadata || {},
  });
}

function cloneValue(value) {
  if (value === null || value === undefined) {
    return value;
  }
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return value;
  }
}

function shortBatchLabel(batchId) {
  const text = String(batchId || "").trim();
  if (!text) {
    return "";
  }
  const match = text.match(/#batch-(\d+)$/);
  if (match) {
    return `Batch #${match[1]}`;
  }
  return text.length > 18 ? `${text.slice(0, 8)}...${text.slice(-6)}` : text;
}

function getAggregationMetadata(message) {
  const metadata = message?.metadata || {};
  if (metadata.aggregation) {
    return metadata.aggregation;
  }
  if (metadata.preview_source_metadata?.aggregation) {
    return metadata.preview_source_metadata.aggregation;
  }
  return null;
}

function getSubmitDebugMetadata(message) {
  const metadata = message?.metadata || {};
  if (metadata.submit_debug) {
    return metadata.submit_debug;
  }
  if (metadata.preview_source_metadata?.submit_debug) {
    return metadata.preview_source_metadata.submit_debug;
  }
  return null;
}

function inferAggregationState(message) {
  const aggregation = getAggregationMetadata(message) || {};
  const submitDebug = getSubmitDebugMetadata(message) || {};
  if (aggregation.batch_state) {
    return aggregation.batch_state;
  }
  if (submitDebug.submit_state === "waiting_for_turn") {
    return "waiting_for_turn";
  }
  if (submitDebug.submit_state === "completed") {
    return "completed";
  }
  if (submitDebug.submit_state === "failed") {
    return "failed";
  }
  return aggregation.is_aggregated === false ? "single_submit" : "";
}

function buildTraceContextMap(messages) {
  const traceMap = new Map();
  for (const message of messages || []) {
    const traceId = String(message?.trace_id || "").trim();
    if (!traceId || message?.role !== "user") {
      continue;
    }
    const metadata = cloneValue(message.metadata || {}) || {};
    const existing = traceMap.get(traceId) || {
      firstUserId: message.id ?? null,
      previewSourceMessageId: message.id ?? null,
      aggregation: null,
      submitDebug: null,
      ingress: null,
      userCount: 0,
      arrivalSeqs: [],
      sourceMessageIds: [],
    };
    existing.userCount += 1;
    if (metadata.aggregation && !existing.aggregation) {
      existing.aggregation = cloneValue(metadata.aggregation);
    }
    if (metadata.submit_debug && !existing.submitDebug) {
      existing.submitDebug = cloneValue(metadata.submit_debug);
    }
    if (metadata.ingress && !existing.ingress) {
      existing.ingress = cloneValue(metadata.ingress);
    }
    if (metadata.ingress?.arrival_seq) {
      existing.arrivalSeqs.push(metadata.ingress.arrival_seq);
    }
    if (message.id) {
      existing.sourceMessageIds.push(message.id);
    }
    traceMap.set(traceId, existing);
  }
  return traceMap;
}

function applyDerivedTraceContext(messages) {
  const normalized = (messages || []).map((item) => normalizeMessage(item));
  const traceMap = buildTraceContextMap(normalized);
  return normalized.map((message) => {
    if (message.role !== "assistant") {
      return message;
    }
    const traceId = String(message.trace_id || "").trim();
    const context = traceMap.get(traceId);
    if (!context) {
      return message;
    }
    const metadata = cloneValue(message.metadata || {}) || {};
    if (context.aggregation && !metadata.aggregation) {
      metadata.aggregation = cloneValue(context.aggregation);
    }
    if (context.submitDebug && !metadata.submit_debug) {
      metadata.submit_debug = cloneValue(context.submitDebug);
    }
    if (context.ingress && !metadata.ingress) {
      metadata.ingress = cloneValue(context.ingress);
    }
    metadata.preview_source_message_id = context.previewSourceMessageId;
    metadata.source_message_count = context.userCount;
    metadata.source_arrival_seqs = context.arrivalSeqs;
    metadata.source_message_ids = context.sourceMessageIds;
    return {
      ...message,
      metadata,
    };
  });
}

function buildTextInputRecord(text, source = "web") {
  return {
    source,
    message_type: "text",
    raw_input: text,
    normalized_input: text,
    pipeline: {
      vision: { hit: false, success: null },
      asr: { hit: false, success: null },
      normalization: { status: "bypassed", failed_at: null },
    },
  };
}

function getRoutingFormValues() {
  return {
    platform: document.getElementById("routingPlatformInput")?.value.trim() || "",
    account_id: document.getElementById("routingAccountInput")?.value.trim() || "",
    user_id: document.getElementById("routingUserInput")?.value.trim() || "",
    chat_type: document.getElementById("routingChatTypeInput")?.value.trim() || "",
    group_id: document.getElementById("routingGroupInput")?.value.trim() || "",
    session_id: document.getElementById("routingOverrideSessionInput")?.value.trim() || "",
  };
}

function setRoutingFormValues(values = {}) {
  const fieldMap = {
    routingPlatformInput: values.platform || "",
    routingAccountInput: values.account_id || "",
    routingUserInput: values.user_id || "",
    routingChatTypeInput: values.chat_type || "",
    routingGroupInput: values.group_id || "",
    routingOverrideSessionInput: values.session_id || "",
  };
  for (const [id, value] of Object.entries(fieldMap)) {
    const node = document.getElementById(id);
    if (node) {
      node.value = value;
    }
  }
}

function setRoutingSourceFields(source = {}) {
  setRoutingFormValues({
    platform: source.platform || "",
    account_id: source.account_id || "",
    user_id: source.user_id || "",
    chat_type: source.chat_type || "",
    group_id: source.group_id || "",
    session_id: document.getElementById("routingOverrideSessionInput")?.value.trim() || "",
  });
}

function latestPlatformSourceFromMessages() {
  for (let index = renderedMessages.length - 1; index >= 0; index -= 1) {
    const message = renderedMessages[index];
    if (message?.role !== "user") {
      continue;
    }
    const metadata = message.metadata || {};
    if (!String(metadata.source || "").startsWith("platform:")) {
      continue;
    }
    if (!metadata.platform || !metadata.user_id || !metadata.chat_type) {
      continue;
    }
    return {
      platform: metadata.platform,
      account_id: metadata.account_id || "default",
      user_id: metadata.user_id,
      chat_type: metadata.chat_type,
      group_id: metadata.group_id || "",
      session_id: metadata.routing?.final_session_id || message.session_id || "",
      message_id: message.id || "",
      trace_id: message.trace_id || "",
    };
  }
  return null;
}

function renderRoutingSourceSummary(source) {
  if (!routingSourceSummaryNode) {
    return;
  }
  if (!source) {
    routingSourceSummaryNode.textContent = "当前来源摘要：当前会话未找到可用于自动带入的平台入站消息来源。";
    return;
  }
  routingSourceSummaryNode.textContent = [
    "当前来源摘要",
    source.platform === "wx" ? "微信" : source.platform || "平台未知",
    source.chat_type === "group" ? "群聊" : "私聊",
    `user_id=${source.user_id}`,
    source.group_id ? `group_id=${source.group_id}` : "",
    `account_id=${source.account_id || "default"}`,
  ].filter(Boolean).join(" · ");
}

function updateRoutingSourceHint() {
  const source = latestPlatformSourceFromMessages();
  if (!routingSourceHintNode) {
    return;
  }
  if (!source) {
    setRoutingSourceFields({});
    routingSourceHintNode.textContent = "自动带入状态：当前会话未找到可用于自动带入的微信/平台入站消息。";
    renderRoutingSourceSummary(null);
    renderRoutingExplain({
      routing_key: "-",
      auto_session_id: "-",
      final_session_id: "-",
      routing_mode: "-",
      routing_reason: "当前会话尚无平台入站消息",
      override: {
        exists: false,
        active: false,
      },
    });
    return;
  }
  setRoutingSourceFields(source);
  routingSourceHintNode.textContent = [
    "自动带入状态：已从当前会话最近一条平台入站消息自动带入",
    `platform=${source.platform}`,
    `user_id=${source.user_id}`,
    source.trace_id ? `trace=${source.trace_id}` : "",
  ].filter(Boolean).join(" · ");
  renderRoutingSourceSummary(source);
  for (let index = renderedMessages.length - 1; index >= 0; index -= 1) {
    const message = renderedMessages[index];
    if (message?.role === "user" && String(message?.metadata?.source || "").startsWith("platform:")) {
      renderRoutingExplainFromMetadata(message.metadata || {});
      break;
    }
  }
}

function autofillRoutingSource() {
  const source = latestPlatformSourceFromMessages();
  if (!source) {
    if (routingStatusNode) {
      routingStatusNode.textContent = "当前会话未找到可用于自动带入的微信/平台入站消息。";
    }
    return;
  }
  setRoutingSourceFields(source);
  if (routingStatusNode) {
    routingStatusNode.textContent = `已从当前会话最近一条平台入站消息自动带入：${source.platform}/${source.user_id}`;
  }
}

function renderRoutingExplain(explain) {
  const override = explain?.override || {};
  setOptionalText("routingKeyValue", explain?.routing_key || "-");
  setOptionalText("routingAutoSessionValue", explain?.auto_session_id || "-");
  setOptionalText("routingFinalSessionValue", explain?.final_session_id || "-");
  setOptionalText("routingModeValue", explain?.routing_mode || "-");
  setOptionalText("routingReasonValue", explain?.routing_reason || "-");
  setOptionalText("routingOverrideActiveValue", override.exists ? (override.active ? "true" : "false") : "none");
  if (routingExplainNode) {
    routingExplainNode.textContent = [
      explain?.platform ? `platform=${explain.platform}` : "",
      explain?.account_id ? `account_id=${explain.account_id}` : "",
      explain?.user_id ? `user_id=${explain.user_id}` : "",
      explain?.chat_type ? `chat_type=${explain.chat_type}` : "",
      explain?.group_id ? `group_id=${explain.group_id}` : "",
      override.session_id ? `override_session_id=${override.session_id}` : "",
      override.operator ? `operator=${override.operator}` : "",
      override.reason ? `reason=${override.reason}` : "",
      override.updated_at ? `updated_at=${override.updated_at}` : "",
      explain?.effective_scope ? `scope=${explain.effective_scope}` : "",
    ].filter(Boolean).join("\n") || "尚无 explain";
  }
}

function renderRoutingExplainFromMetadata(metadata = {}) {
  const routing = metadata.routing || {};
  const ingress = metadata.ingress || {};
  if (!routing.routing_key && !routing.final_session_id) {
    return;
  }
  renderRoutingExplain({
    platform: metadata.platform || "",
    account_id: metadata.account_id || "default",
    user_id: metadata.user_id || "",
    chat_type: metadata.chat_type || "",
    group_id: metadata.group_id || "",
    routing_key: routing.routing_key || "",
    auto_session_id: routing.auto_session_id || "",
    final_session_id: routing.final_session_id || "",
    routing_mode: routing.routing_mode || "",
    routing_reason: routing.routing_reason || "",
    override: {
      exists: Boolean(routing.override_session_id || routing.override_updated_at || routing.override_operator),
      active: routing.routing_mode === "override",
      session_id: routing.override_session_id || "",
      operator: routing.override_operator || "",
      updated_at: routing.override_updated_at || "",
      reason: routing.routing_reason || "",
    },
    effective_scope: ingress.controller_mode ? `future inbound messages only · ingress=${ingress.controller_mode}` : "future inbound messages only",
  });
}

async function queryRoutingExplain() {
  const values = getRoutingFormValues();
  if (!values.platform || !values.user_id || !values.chat_type) {
    if (routingStatusNode) {
      routingStatusNode.textContent = "查询前至少填写 platform / user_id / chat_type。";
    }
    return;
  }
  const restore = setBusyButton(routingQueryBtn, "查询中...");
  if (routingStatusNode) {
    routingStatusNode.textContent = "正在查询 routing explain...";
  }
  try {
    const params = new URLSearchParams();
    params.set("platform", values.platform);
    params.set("user_id", values.user_id);
    params.set("chat_type", values.chat_type);
    if (values.account_id) params.set("account_id", values.account_id);
    if (values.group_id) params.set("group_id", values.group_id);
    const data = await requestJson(
      `/platform/session-routing?${params.toString()}`,
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "查询 routing 失败："
    );
    renderRoutingExplain(data.explain || {});
    if (routingStatusNode) {
      routingStatusNode.textContent = `已刷新 routing 状态：${data.explain?.routing_mode || "-"}`;
    }
  } catch (err) {
    if (routingStatusNode) {
      routingStatusNode.textContent = err.message;
    }
  } finally {
    restore();
  }
}

async function setRoutingOverride() {
  const values = getRoutingFormValues();
  if (!values.platform || !values.user_id || !values.chat_type || !values.session_id) {
    if (routingStatusNode) {
      routingStatusNode.textContent = "设置 override 需要填写 platform / user_id / chat_type / session_id。";
    }
    return;
  }
  const restore = setBusyButton(routingSetBtn, "设置中...");
  if (routingStatusNode) {
    routingStatusNode.textContent = "正在设置 routing override...";
  }
  try {
    const data = await requestJson(
      "/platform/session-routing/override",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({
          platform: values.platform,
          account_id: values.account_id || null,
          user_id: values.user_id,
          chat_type: values.chat_type,
          group_id: values.group_id || null,
          session_id: values.session_id,
          operator: "chat-debug-ui",
          reason: "manual override from test console",
        }),
      },
      "设置 override 失败："
    );
    renderRoutingExplain(data.explain || {});
    if (routingStatusNode) {
      routingStatusNode.textContent = `已设置 override → ${data.explain?.final_session_id || values.session_id}`;
    }
  } catch (err) {
    if (routingStatusNode) {
      routingStatusNode.textContent = err.message;
    }
  } finally {
    restore();
  }
}

async function clearRoutingOverride() {
  const values = getRoutingFormValues();
  if (!values.platform || !values.user_id || !values.chat_type) {
    if (routingStatusNode) {
      routingStatusNode.textContent = "清除 override 需要填写 platform / user_id / chat_type。";
    }
    return;
  }
  const restore = setBusyButton(routingClearBtn, "清除中...");
  if (routingStatusNode) {
    routingStatusNode.textContent = "正在清除 routing override...";
  }
  try {
    const data = await requestJson(
      "/platform/session-routing/clear",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({
          platform: values.platform,
          account_id: values.account_id || null,
          user_id: values.user_id,
          chat_type: values.chat_type,
          group_id: values.group_id || null,
          operator: "chat-debug-ui",
          reason: "clear override from test console",
        }),
      },
      "清除 override 失败："
    );
    renderRoutingExplain(data.explain || {});
    if (routingStatusNode) {
      routingStatusNode.textContent = `已清除 override，当前回到 ${data.explain?.routing_mode || "auto"}`;
    }
  } catch (err) {
    if (routingStatusNode) {
      routingStatusNode.textContent = err.message;
    }
  } finally {
    restore();
  }
}

export function getSessionId() {
  const value = document.getElementById("sessionInput").value.trim();
  return value || "web-test";
}

export function updateCurrentSessionStatus(sessionId) {
  setCurrentSessionStatus(sessionId, getSessionId());
}

function formatTimeLabel(value) {
  if (!value) {
    return "";
  }
  return String(value).replace("T", " ").slice(0, 19);
}

function appendBadgeRow(container, labels, extraClass = "") {
  if (!labels.length) {
    return;
  }
  const row = document.createElement("div");
  row.className = `message-badges ${extraClass}`.trim();
  for (const item of labels) {
    const badge = document.createElement("span");
    badge.className = `message-badge ${item.tone || ""}`.trim();
    badge.textContent = item.label;
    row.appendChild(badge);
  }
  container.appendChild(row);
}

function buildMessageBadges(message) {
  const metadata = message.metadata || {};
  const pipeline = metadata.pipeline || {};
  const submitDebug = getSubmitDebugMetadata(message) || {};
  const aggregation = getAggregationMetadata(message) || {};
  const labels = [];
  const modality = String(message.message_type || metadata.message_type || "text").toLowerCase();
  const modalityLabelMap = {
    text: "Text",
    image: "Image",
    voice: "Voice",
    assistant: "Assistant",
  };
  labels.push({ label: modalityLabelMap[modality] || modality, tone: "modality" });

  const normalization = pipeline.normalization || {};
  if (normalization.status === "success") {
    labels.push({ label: "Normalize ok", tone: "ok" });
  } else if (normalization.status === "failed") {
    labels.push({ label: "Normalize failed", tone: "danger" });
  } else if (normalization.status === "bypassed") {
    labels.push({ label: "Normalize bypass", tone: "muted" });
  }

  const vision = pipeline.vision || {};
  if (vision.hit) {
    labels.push({ label: vision.success === false ? "Vision failed" : "Vision hit", tone: vision.success === false ? "danger" : "ok" });
  }

  const asr = pipeline.asr || {};
  if (asr.hit) {
    labels.push({ label: asr.success === false ? "ASR failed" : "ASR hit", tone: asr.success === false ? "danger" : "ok" });
  }

  if (message.has_preview) {
    labels.push({ label: "Preview ready", tone: "info" });
  }
  if (metadata.routing?.routing_mode) {
    labels.push({ label: `Route ${metadata.routing.routing_mode}`, tone: metadata.routing.routing_mode === "override" ? "info" : "muted" });
  }
  if (metadata.ingress?.controller_mode === "session_serial_submit") {
    labels.push({ label: "Gate serial", tone: "ok" });
  }
  if (metadata.ingress?.controller_mode === "session_aggregate_then_submit") {
    labels.push({ label: "Gate aggregate", tone: "info" });
  }
  if (metadata.ingress?.arrival_seq) {
    labels.push({ label: `arrival #${metadata.ingress.arrival_seq}`, tone: "muted" });
  }
  if (aggregation.batch_id) {
    labels.push({ label: shortBatchLabel(aggregation.batch_id), tone: "info" });
  }
  if (aggregation.source_count > 1 || aggregation.source_message_count > 1) {
    labels.push({ label: `${aggregation.source_count || aggregation.source_message_count} in batch`, tone: "muted" });
  }
  const aggregationState = inferAggregationState(message);
  if (aggregationState) {
    const tone = aggregationState.includes("failed")
      ? "danger"
      : aggregationState === "batch_completed" || aggregationState === "completed"
        ? "ok"
        : aggregationState === "batch_submitting" || aggregationState === "waiting_for_turn"
          ? "info"
          : "muted";
    labels.push({ label: aggregationState.replace("batch_", ""), tone });
  }
  if (submitDebug.submit_state) {
    const tone = submitDebug.submit_state === "failed"
      ? "danger"
      : submitDebug.submit_state === "fallback_completed"
        ? "info"
        : submitDebug.submit_state === "completed"
          ? "ok"
          : "muted";
    labels.push({ label: `Submit ${submitDebug.submit_state}`, tone });
  }
  return labels;
}

function buildMessageSummary(message) {
  const metadata = message.metadata || {};
  const pipeline = metadata.pipeline || {};
  const submitDebug = getSubmitDebugMetadata(message) || {};
  const aggregation = getAggregationMetadata(message) || {};
  const parts = [];

  if (metadata.raw_input && metadata.raw_input !== message.content) {
    parts.push(`原始输入：${truncateText(metadata.raw_input, 60)}`);
  }
  if ((pipeline.asr || {}).text) {
    parts.push(`ASR：${truncateText(pipeline.asr.text, 60)}`);
  }
  if ((pipeline.normalization || {}).failed_at) {
    parts.push(`失败点：${pipeline.normalization.failed_at}`);
  } else if ((pipeline.normalization || {}).status === "success") {
    parts.push("已归一化进入主链");
  }
  if (metadata.routing?.final_session_id) {
    parts.push(`route=${metadata.routing.routing_mode || "auto"} → ${truncateText(metadata.routing.final_session_id, 36)}`);
  }
  if (metadata.ingress?.arrival_seq) {
    parts.push(`arrival_seq=${metadata.ingress.arrival_seq}`);
  }
  if (aggregation.batch_id) {
    parts.push(`batch=${shortBatchLabel(aggregation.batch_id)}`);
  }
  if ((aggregation.source_count || aggregation.source_message_count || 0) > 1) {
    parts.push(`batch_sources=${aggregation.source_count || aggregation.source_message_count}`);
  }
  if (aggregation.batch_state) {
    parts.push(`batch_state=${aggregation.batch_state}`);
  }
  if (submitDebug.submit_state) {
    parts.push(`submit=${submitDebug.submit_state}`);
  }
  if (submitDebug.blocked_by_seq) {
    parts.push(`blocked_by=${submitDebug.blocked_by_seq}`);
  }
  if (aggregation.source_arrival_seqs?.length && message.role === "assistant") {
    parts.push(`source_arrivals=${aggregation.source_arrival_seqs.join(",")}`);
  }
  if (submitDebug.failed_phase) {
    parts.push(`failed_phase=${submitDebug.failed_phase}`);
  }
  return parts.join(" · ");
}

function scrollMessagesToBottom() {
  const box = document.getElementById("messages");
  if (box) {
    box.scrollTop = box.scrollHeight;
  }
}

function renderMessageNode(message) {
  const box = document.getElementById("messages");
  const row = document.createElement("div");
  row.className = `message-row ${message.role === "user" ? "is-user" : "is-bot"}`;

  const meta = document.createElement("div");
  meta.className = "message-meta-line";
  meta.textContent = message.role === "user" ? "输入消息" : "回复消息";
  if (message.created_at) {
    meta.textContent += ` · ${formatTimeLabel(message.created_at)}`;
  }
  if (message.id) {
    meta.textContent += ` · #${message.id}`;
  }

  const bubble = document.createElement("div");
  bubble.className = `msg ${message.role === "user" ? "user" : "bot"}`;
  bubble.textContent = message.content || "";

  appendBadgeRow(bubble, buildMessageBadges(message));

  const summary = buildMessageSummary(message);
  if (summary) {
    const summaryLine = document.createElement("div");
    summaryLine.className = "message-summary";
    summaryLine.textContent = summary;
    bubble.appendChild(summaryLine);
  }

  if (message.id) {
    row.dataset.messageId = String(message.id);
    row.classList.toggle("is-selected", selectedMessageId === message.id);
    row.addEventListener("contextmenu", (event) => showMessageContextMenu(event, message));
  }

  row.append(meta, bubble);
  box.appendChild(row);
}

function renderMessages() {
  const box = document.getElementById("messages");
  clearChildren(box);

  if (renderedMessages.length === 0) {
    updateSessionMessageCount(0);
    renderMessageNode(normalizeMessage("assistant", "当前会话还没有历史。"));
    return;
  }

  for (const message of renderedMessages) {
    renderMessageNode(message);
  }
  updateSessionMessageCount(renderedMessages.length);
  scrollMessagesToBottom();
}

export function setMessages(messages) {
  renderedMessages = applyDerivedTraceContext(messages || []);
  renderMessages();
  updateRoutingSourceHint();
}

export function addMessage(messageOrRole, text) {
  const message = normalizeMessage(messageOrRole, text);
  renderedMessages.push(message);
  updateSessionMessageCount(renderedMessages.length);
  renderMessageNode(message);
  scrollMessagesToBottom();
}

export function resetMessages() {
  renderedMessages = [];
  selectedMessageId = null;
  clearChildren(document.getElementById("messages"));
  updateSessionMessageCount(0);
  updateRoutingSourceHint();
  clearPreviewPanel();
  clearMessageDebugPanel();
}

export function showChatEmptyState(message = "当前没有可用会话。") {
  renderedMessages = [];
  const box = document.getElementById("messages");
  clearChildren(box);
  updateSessionMessageCount(0);
  renderMessageNode(normalizeMessage("assistant", message));
}

export function getCandidateMemory() {
  if (lastCandidateDecision?.action !== "needs_confirm") {
    return null;
  }
  return lastCandidate;
}

export function clearCandidateMemory() {
  lastCandidate = null;
  lastCandidateDebug = null;
  lastCandidateDecision = null;
  renderCandidateMemories();
}

export function clearChatDebugState(options = {}) {
  const {
    previewStatus = "尚未预览；右键一条输入消息可直接查看真实链路。",
    previewBoxText = "",
    candidateStatus = "",
    relationshipContext = "暂无",
    messageDebugStatus = "尚未选择消息。",
    sessionDebugStatus = "还没加载",
  } = options;

  lastCandidate = null;
  lastCandidateDebug = null;
  lastCandidateDecision = null;
  renderCandidateMemories();
  renderUsedMemories([]);

  const previewStatusNode = document.getElementById("chatPreviewStatus");
  if (previewStatusNode) {
    previewStatusNode.textContent = previewStatus;
  }

  const previewBox = document.getElementById("chatPreviewBox");
  if (previewBox) {
    clearChildren(previewBox);
    if (previewBoxText) {
      previewBox.textContent = previewBoxText;
    }
  }

  const messageDebugStatusNode = document.getElementById("messageDebugStatus");
  if (messageDebugStatusNode) {
    messageDebugStatusNode.textContent = messageDebugStatus;
  }
  const messageDebugBox = document.getElementById("messageDebugBox");
  if (messageDebugBox) {
    clearChildren(messageDebugBox);
    messageDebugBox.textContent = "右键任意 user / assistant 消息，查看该轮聚合与提交调试信息。";
  }

  const sessionDebugStatusNode = document.getElementById("sessionDebugStatus");
  if (sessionDebugStatusNode) {
    sessionDebugStatusNode.textContent = sessionDebugStatus;
  }
  const sessionDebugBox = document.getElementById("sessionDebugBox");
  if (sessionDebugBox) {
    clearChildren(sessionDebugBox);
    sessionDebugBox.textContent = "点击刷新查看当前 session 的 batch / gate 状态。";
  }

  const candidateStatusNode = document.getElementById("candidateStatus");
  if (candidateStatusNode) {
    candidateStatusNode.textContent = candidateStatus;
  }

  const relationshipContextBox = document.getElementById("relationshipContextBox");
  if (relationshipContextBox) {
    relationshipContextBox.textContent = relationshipContext;
  }
}

export function renderCandidateMemories() {
  const box = document.getElementById("candidateBox");
  const status = document.getElementById("candidateStatus");
  status.textContent = "";

  if (!lastCandidateDebug && !lastCandidateDecision) {
    box.textContent = "暂无候选记忆";
    return;
  }

  clearChildren(box);

  const candidate = lastCandidateDebug || lastCandidate;
  const decision = lastCandidateDecision || {};
  const source = String(candidate?.source_label || candidate?.source_modality || decision?.source_modality || "text");
  const action = String(decision?.action || "");
  const riskLevel = String(decision?.risk_level || "");

  const tag = document.createElement("div");
  tag.className = "tag";
  tag.textContent = `${candidate?.memory_type || "general"} · ${source}`;

  const content = document.createElement("div");
  content.className = "memory-content";
  content.textContent = candidate?.content || "本轮未产生可展示的候选内容";

  const meta = document.createElement("div");
  meta.className = "memory-meta";
  meta.textContent = [
    action ? `action=${action}` : "",
    riskLevel ? `risk=${riskLevel}` : "",
  ].filter(Boolean).join(" · ") || "暂无决策信息";

  const reason = document.createElement("div");
  reason.className = "memory-meta";
  reason.textContent = decision?.reason || candidate?.reason || "";

  box.append(tag, content, meta);
  if (reason.textContent) {
    box.appendChild(reason);
  }
}

export function renderUsedMemories(memories) {
  const box = document.getElementById("usedMemories");
  const items = (memories || []).slice(0, 5);

  if (items.length === 0) {
    box.textContent = "暂无命中";
    return;
  }

  clearChildren(box);

  for (const mem of items) {
    const item = document.createElement("div");
    item.className = "used-memory-item";

    const content = document.createElement("div");
    content.className = "memory-content";
    content.textContent = `[${mem.memory_type || "general"}] ${truncateText(mem.content, 80)}`;

    const score = document.createElement("div");
    score.className = "used-memory-score";
    score.textContent = `score=${mem.score ?? 0}`;

    item.append(content, score);
    box.appendChild(item);
  }
}

function textLength(value) {
  return String(value || "").length;
}

function appendPreviewMetric(box, label, value) {
  const item = document.createElement("div");
  item.className = "status-item";

  const labelNode = document.createElement("div");
  labelNode.className = "status-label";
  labelNode.textContent = label;

  const valueNode = document.createElement("div");
  valueNode.className = "status-value";
  valueNode.textContent = String(value ?? "-");

  item.append(labelNode, valueNode);
  box.appendChild(item);
}

function formatMessages(messages) {
  const items = Array.isArray(messages) ? messages : [];
  if (items.length === 0) {
    return "暂无";
  }
  return items
    .map((item, index) => {
      const role = item?.role || "-";
      const content = item?.content || "";
      return `#${index + 1} ${role} (${textLength(content)} 字)\n${content}`;
    })
    .join("\n\n");
}

function formatSelectedMemories(memories) {
  const items = Array.isArray(memories) ? memories : [];
  if (items.length === 0) {
    return "暂无";
  }
  return items
    .map((item, index) => {
      const layer = item?.context_layer || "-";
      const score = item?.score ?? 0;
      const content = item?.context || item?.content || "";
      return `#${index + 1} ${layer} score=${score}\n${content}`;
    })
    .join("\n\n");
}

function formatJsonBlock(value) {
  if (!value) {
    return "暂无";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatMemoryCandidate(candidate) {
  if (!candidate) {
    return "暂无";
  }
  return [
    `source=${candidate.source_label || candidate.source_modality || "text"}`,
    `memory_type=${candidate.memory_type || "-"}`,
    `should_store=${candidate.should_store === true ? "true" : "false"}`,
    candidate.content ? `content=${candidate.content}` : "",
    candidate.reason ? `reason=${candidate.reason}` : "",
  ].filter(Boolean).join("\n");
}

function formatMemoryDecision(decision) {
  if (!decision) {
    return "暂无";
  }
  return [
    `source=${decision.source_modality || "text"}`,
    `action=${decision.action || "-"}`,
    `risk_level=${decision.risk_level || "-"}`,
    `confidence=${decision.confidence ?? "-"}`,
    decision.reason ? `reason=${decision.reason}` : "",
  ].filter(Boolean).join("\n");
}

function appendPreviewSection(box, title, content, meta) {
  const section = document.createElement("div");
  section.className = "chat-preview-section";

  const head = document.createElement("div");
  head.className = "chat-preview-head";

  const titleNode = document.createElement("span");
  titleNode.textContent = title;

  const metaNode = document.createElement("span");
  metaNode.className = "chat-preview-meta";
  metaNode.textContent = meta;

  const body = document.createElement("pre");
  body.className = "chat-preview-pre";
  body.textContent = content || "暂无";

  head.append(titleNode, metaNode);
  section.append(head, body);
  box.appendChild(section);
}

function appendDebugMiniCard(box, title, content, meta = "") {
  const section = document.createElement("div");
  section.className = "debug-mini-card";

  const head = document.createElement("div");
  head.className = "debug-mini-head";

  const titleNode = document.createElement("span");
  titleNode.textContent = title;

  const metaNode = document.createElement("span");
  metaNode.className = "debug-mini-meta";
  metaNode.textContent = meta;

  const body = document.createElement("div");
  body.className = "debug-mini-body";
  body.textContent = content || "暂无";

  head.append(titleNode, metaNode);
  section.append(head, body);
  box.appendChild(section);
}

function formatTimeValue(value) {
  return value ? String(value).replace("T", " ").slice(0, 19) : "-";
}

function formatAggregationDebug(metadata = {}, message = {}) {
  const aggregation = getAggregationMetadata({ metadata }) || {};
  const submitDebug = getSubmitDebugMetadata({ metadata }) || {};
  const sourceCount = aggregation.source_count || aggregation.source_message_count || metadata.source_message_count || 1;
  const lines = [
    aggregation.batch_id ? `batch_id=${aggregation.batch_id}` : "batch_id=-",
    `is_aggregated=${sourceCount > 1 ? "true" : "false"}`,
    aggregation.batch_state ? `batch_state=${aggregation.batch_state}` : "batch_state=single_submit",
    aggregation.source_arrival_seqs?.length ? `source_arrival_seqs=${aggregation.source_arrival_seqs.join(",")}` : "",
    aggregation.source_message_ids?.length ? `source_message_ids=${aggregation.source_message_ids.join(",")}` : "",
    aggregation.source_trace_ids?.length ? `source_trace_ids=${aggregation.source_trace_ids.join(",")}` : "",
    `source_message_count=${sourceCount}`,
    submitDebug.blocked_by_seq ? `blocked_by_seq=${submitDebug.blocked_by_seq}` : "",
    aggregation.opened_at ? `opened_at=${formatTimeValue(aggregation.opened_at)}` : "",
    aggregation.sealed_at ? `sealed_at=${formatTimeValue(aggregation.sealed_at)}` : "",
    submitDebug.ready_at ? `ready_at=${formatTimeValue(submitDebug.ready_at)}` : "",
    submitDebug.submit_started_at ? `submit_started_at=${formatTimeValue(submitDebug.submit_started_at)}` : "",
    submitDebug.completed_at ? `completed_at=${formatTimeValue(submitDebug.completed_at)}` : "",
    submitDebug.failed_at ? `failed_at=${formatTimeValue(submitDebug.failed_at)}` : "",
    submitDebug.failed_phase ? `failure_stage=${submitDebug.failed_phase}` : "",
    submitDebug.submit_state ? `completion_state=${submitDebug.submit_state}` : "",
  ].filter(Boolean);

  if (message.role === "assistant" && aggregation.aggregated_message) {
    lines.push("", "aggregated_message:", aggregation.aggregated_message);
  }
  return lines.join("\n") || "Not aggregated";
}

function renderMessageDebugPanel(data = {}) {
  const status = document.getElementById("messageDebugStatus");
  const box = document.getElementById("messageDebugBox");
  if (!status || !box) {
    return;
  }
  clearChildren(box);

  const message = data.message || {};
  const metadata = message.metadata || {};
  const previewSourceMetadata = data.preview_source_metadata || {};
  const effectiveMetadata = {
    ...cloneValue(metadata || {}),
    preview_source_metadata: cloneValue(previewSourceMetadata || {}),
  };
  const aggregation = getAggregationMetadata({ metadata: effectiveMetadata }) || {};
  const submitDebug = getSubmitDebugMetadata({ metadata: effectiveMetadata }) || {};
  const isAggregated = (aggregation.source_count || aggregation.source_message_count || 0) > 1;
  const batchMeta = aggregation.batch_state || submitDebug.submit_state || (isAggregated ? "aggregated" : "single_submit");

  appendDebugMiniCard(
    box,
    "Message Link",
    [
      message.id ? `message_id=${message.id}` : "",
      message.role ? `role=${message.role}` : "",
      data.trace_id ? `trace_id=${data.trace_id}` : "",
      data.preview_source_message_id ? `preview_source_message_id=${data.preview_source_message_id}` : "",
      data.preview_source_role ? `preview_source_role=${data.preview_source_role}` : "",
    ].filter(Boolean).join("\n") || "暂无",
    batchMeta
  );
  appendDebugMiniCard(
    box,
    "Aggregation",
    formatAggregationDebug(effectiveMetadata, message),
    isAggregated ? "aggregated" : "not aggregated"
  );
  appendDebugMiniCard(
    box,
    "Submit",
    [
      submitDebug.submit_state ? `submit_state=${submitDebug.submit_state}` : "submit_state=-",
      submitDebug.phase ? `phase=${submitDebug.phase}` : "",
      submitDebug.blocked_by_seq ? `blocked_by_seq=${submitDebug.blocked_by_seq}` : "",
      submitDebug.submit_seq ? `submit_seq=${submitDebug.submit_seq}` : "",
      submitDebug.queue_wait_ms !== undefined && submitDebug.queue_wait_ms !== null ? `queue_wait_ms=${submitDebug.queue_wait_ms}` : "",
      submitDebug.submit_latency_ms !== undefined && submitDebug.submit_latency_ms !== null ? `submit_latency_ms=${submitDebug.submit_latency_ms}` : "",
      submitDebug.error_type ? `error_type=${submitDebug.error_type}` : "",
      submitDebug.error_message ? `error_message=${submitDebug.error_message}` : "",
    ].filter(Boolean).join("\n") || "暂无",
    submitDebug.submit_state || "n/a"
  );

  status.textContent = [
    message.role === "assistant" ? "当前选中的是 assistant reply。" : "当前选中的是原始消息。",
    isAggregated ? "这轮回复来自聚合 batch。" : "这轮回复是普通单条 submit。",
    aggregation.batch_state ? `batch_state=${aggregation.batch_state}` : "",
    submitDebug.blocked_by_seq ? `blocked_by_seq=${submitDebug.blocked_by_seq}` : "",
  ].filter(Boolean).join(" ");
}

function renderSessionDebugPanel(sessionId, submitSnapshot = {}, aggregationSnapshot = {}) {
  const status = document.getElementById("sessionDebugStatus");
  const box = document.getElementById("sessionDebugBox");
  if (!status || !box) {
    return;
  }
  clearChildren(box);

  const activeBatch = (aggregationSnapshot.active_batches || [])[0] || null;
  const recentBatch = (aggregationSnapshot.recent_batches || [])[0] || null;
  const activeSubmit = (submitSnapshot.active || [])[0] || null;
  const recentSubmit = (submitSnapshot.recent || [])[0] || null;

  appendDebugMiniCard(
    box,
    "Aggregation Live",
    [
      activeBatch?.batch_id ? `open_batch=${activeBatch.batch_id}` : "open_batch=-",
      activeBatch?.batch_state ? `batch_state=${activeBatch.batch_state}` : recentBatch?.batch_state ? `last_batch_state=${recentBatch.batch_state}` : "",
      activeBatch?.source_count !== undefined ? `source_count=${activeBatch.source_count}` : "",
      activeBatch?.source_arrival_seqs?.length ? `source_arrival_seqs=${activeBatch.source_arrival_seqs.join(",")}` : "",
      activeBatch?.ready_count !== undefined ? `ready_count=${activeBatch.ready_count}` : "",
      activeBatch?.terminal_count !== undefined ? `terminal_count=${activeBatch.terminal_count}` : "",
      activeBatch?.sealed_at ? `sealed_at=${formatTimeValue(activeBatch.sealed_at)}` : "",
    ].filter(Boolean).join("\n") || "暂无 active batch",
    activeBatch?.batch_state || recentBatch?.batch_state || "idle"
  );
  appendDebugMiniCard(
    box,
    "Submit Live",
    [
      activeSubmit?.arrival_seq ? `active_arrival_seq=${activeSubmit.arrival_seq}` : "active_arrival_seq=-",
      activeSubmit?.submit_state ? `submit_state=${activeSubmit.submit_state}` : recentSubmit?.submit_state ? `last_submit_state=${recentSubmit.submit_state}` : "",
      activeSubmit?.blocked_by_seq ? `blocked_by_seq=${activeSubmit.blocked_by_seq}` : "",
      activeSubmit?.submit_seq ? `submit_seq=${activeSubmit.submit_seq}` : recentSubmit?.submit_seq ? `last_submit_seq=${recentSubmit.submit_seq}` : "",
      activeSubmit?.queue_wait_ms !== undefined && activeSubmit?.queue_wait_ms !== null ? `queue_wait_ms=${activeSubmit.queue_wait_ms}` : "",
      activeSubmit?.submit_started_at ? `submit_started_at=${formatTimeValue(activeSubmit.submit_started_at)}` : "",
      activeSubmit?.completed_at ? `completed_at=${formatTimeValue(activeSubmit.completed_at)}` : recentSubmit?.completed_at ? `last_completed_at=${formatTimeValue(recentSubmit.completed_at)}` : "",
    ].filter(Boolean).join("\n") || "暂无 active submit",
    activeSubmit?.submit_state || recentSubmit?.submit_state || "idle"
  );
  appendDebugMiniCard(
    box,
    "Recent Batches",
    ((aggregationSnapshot.recent_batches || []).slice(0, 3).map((item) => {
      return [
        shortBatchLabel(item.batch_id),
        item.batch_state || "-",
        item.source_arrival_seqs?.length ? `arrivals=${item.source_arrival_seqs.join(",")}` : "",
      ].filter(Boolean).join(" · ");
    }).join("\n")) || "暂无 recent batch",
    `${aggregationSnapshot.recent_batch_count || 0} recent`
  );

  status.textContent = [
    `session=${sessionId}`,
    activeBatch?.batch_state ? `batch=${activeBatch.batch_state}` : "batch=idle",
    activeSubmit?.submit_state ? `submit=${activeSubmit.submit_state}` : recentSubmit?.submit_state ? `submit=${recentSubmit.submit_state}` : "submit=idle",
  ].join(" · ");
}

export async function loadCurrentSessionDebug(options = {}) {
  const { silent = false } = options;
  const sessionId = getSessionId();
  const status = document.getElementById("sessionDebugStatus");
  if (!silent && status) {
    status.textContent = `正在加载 ${sessionId} 的 live session debug...`;
  }
  try {
    const [submitSnapshot, aggregationSnapshot] = await Promise.all([
      requestJson(
        `/debug/session-submit?session_id=${encodeURIComponent(sessionId)}`,
        { method: "GET", headers: getAdminHeaders() },
        "加载 session submit 状态失败："
      ),
      requestJson(
        `/debug/session-aggregation?session_id=${encodeURIComponent(sessionId)}`,
        { method: "GET", headers: getAdminHeaders() },
        "加载 session aggregation 状态失败："
      ),
    ]);
    renderSessionDebugPanel(sessionId, submitSnapshot, aggregationSnapshot);
  } catch (err) {
    if (status) {
      status.textContent = err.message;
    }
  }
}

function renderChatPreview(data, mode = "draft") {
  const box = document.getElementById("chatPreviewBox");
  const status = document.getElementById("chatPreviewStatus");
  if (!box || !status) {
    return;
  }

  const preview = data?.preview || {};
  const counts = preview.counts || {};
  const message = data?.message || {};
  const metadata = message?.metadata || {};
  const previewSourceMetadata = data?.preview_source_metadata || {};
  const baseMetadata = message?.role === "assistant" && Object.keys(previewSourceMetadata).length
    ? previewSourceMetadata
    : metadata;
  const effectiveMetadata = {
    ...cloneValue(metadata || {}),
    preview_source_metadata: cloneValue(previewSourceMetadata || {}),
  };
  const aggregation = getAggregationMetadata({ metadata: effectiveMetadata }) || {};
  const submitDebug = getSubmitDebugMetadata({ metadata: effectiveMetadata }) || {};
  clearChildren(box);

  const summary = document.createElement("div");
  summary.className = "chat-preview-summary";
  appendPreviewMetric(summary, "session", data?.session_id_label || "-");
  appendPreviewMetric(summary, "消息 ID", data?.message_id ?? "draft");
  appendPreviewMetric(summary, "模态", data?.message_type || metadata.message_type || "text");
  appendPreviewMetric(summary, "记忆", counts.memory_count ?? 0);
  appendPreviewMetric(summary, "历史", counts.recent_message_count ?? 0);
  appendPreviewMetric(summary, "final messages", counts.final_message_count ?? 0);
  if (mode === "message") {
    appendPreviewMetric(summary, "Batch", shortBatchLabel(aggregation.batch_id) || "single");
    appendPreviewMetric(summary, "聚合", (aggregation.source_count || aggregation.source_message_count || 0) > 1 ? "true" : "false");
    appendPreviewMetric(summary, "状态", aggregation.batch_state || submitDebug.submit_state || "-");
  }
  box.appendChild(summary);

  if (mode === "message") {
    appendPreviewSection(
      box,
      "原始输入",
      baseMetadata.raw_input || message.content || "",
      `${textLength(baseMetadata.raw_input || message.content || "")} 字`
    );
    appendPreviewSection(
      box,
      "识别 / 理解结果",
      [
        baseMetadata.pipeline?.asr?.text ? `ASR：${baseMetadata.pipeline.asr.text}` : "",
        baseMetadata.pipeline?.vision?.hit ? `Vision：${baseMetadata.pipeline.vision.success === false ? "failed" : "hit"}` : "",
        baseMetadata.pipeline?.normalization?.status ? `Normalize：${baseMetadata.pipeline.normalization.status}` : "",
      ].filter(Boolean).join("\n") || "暂无",
      "链路命中情况"
    );
    appendPreviewSection(
      box,
      "归一化结果",
      baseMetadata.normalized_input || preview.current_user_message || "",
      `${textLength(baseMetadata.normalized_input || preview.current_user_message || "")} 字`
    );
    appendPreviewSection(
      box,
      "状态 / 失败点",
      formatJsonBlock(baseMetadata.pipeline || {}),
      baseMetadata.pipeline?.normalization?.failed_at ? `failed_at=${baseMetadata.pipeline.normalization.failed_at}` : "success / bypass"
    );
    appendPreviewSection(
      box,
      "Routing Explain",
      [
        baseMetadata.routing?.routing_key ? `routing_key=${baseMetadata.routing.routing_key}` : "",
        baseMetadata.routing?.auto_session_id ? `auto_session_id=${baseMetadata.routing.auto_session_id}` : "",
        baseMetadata.routing?.final_session_id ? `final_session_id=${baseMetadata.routing.final_session_id}` : "",
        baseMetadata.routing?.routing_mode ? `routing_mode=${baseMetadata.routing.routing_mode}` : "",
        baseMetadata.routing?.routing_reason ? `routing_reason=${baseMetadata.routing.routing_reason}` : "",
        baseMetadata.routing?.override_session_id ? `override_session_id=${baseMetadata.routing.override_session_id}` : "",
      ].filter(Boolean).join("\n") || "暂无",
      baseMetadata.routing?.routing_mode || "n/a"
    );
    appendPreviewSection(
      box,
      "Ingress / Gate",
      [
        effectiveMetadata.ingress?.controller_mode ? `controller_mode=${effectiveMetadata.ingress.controller_mode}` : "",
        effectiveMetadata.ingress?.arrival_seq ? `arrival_seq=${effectiveMetadata.ingress.arrival_seq}` : "",
        effectiveMetadata.ingress?.received_at ? `received_at=${effectiveMetadata.ingress.received_at}` : "",
        effectiveMetadata.account_id ? `account_id=${effectiveMetadata.account_id}` : "",
        effectiveMetadata.platform ? `platform=${effectiveMetadata.platform}` : "",
        effectiveMetadata.user_id ? `user_id=${effectiveMetadata.user_id}` : "",
        effectiveMetadata.chat_type ? `chat_type=${effectiveMetadata.chat_type}` : "",
        effectiveMetadata.group_id ? `group_id=${effectiveMetadata.group_id}` : "",
      ].filter(Boolean).join("\n") || "暂无",
      effectiveMetadata.ingress?.controller_mode || "direct"
    );
    appendPreviewSection(
      box,
      "Aggregation",
      [
        aggregation.batch_id ? `batch_id=${aggregation.batch_id}` : "batch_id=-",
        `is_aggregated=${(aggregation.source_count || aggregation.source_message_count || 0) > 1 ? "true" : "false"}`,
        aggregation.batch_state ? `batch_state=${aggregation.batch_state}` : "batch_state=single_submit",
        aggregation.source_count ? `source_count=${aggregation.source_count}` : aggregation.source_message_count ? `source_count=${aggregation.source_message_count}` : "",
        aggregation.source_arrival_seqs?.length ? `source_arrival_seqs=${aggregation.source_arrival_seqs.join(",")}` : "",
        aggregation.source_message_ids?.length ? `source_message_ids=${aggregation.source_message_ids.join(",")}` : "",
        aggregation.source_trace_ids?.length ? `source_trace_ids=${aggregation.source_trace_ids.join(",")}` : "",
        aggregation.opened_at ? `opened_at=${aggregation.opened_at}` : "",
        aggregation.deadline_at ? `deadline_at=${aggregation.deadline_at}` : "",
        aggregation.sealed_at ? `sealed_at=${aggregation.sealed_at}` : "",
        aggregation.aggregated_message ? `aggregated_message=\n${aggregation.aggregated_message}` : "",
      ].filter(Boolean).join("\n") || "Not aggregated",
      aggregation.batch_state || ((aggregation.source_count || aggregation.source_message_count || 0) > 1 ? "aggregated" : "single")
    );
    appendPreviewSection(
      box,
      "Submit Debug",
      [
        submitDebug.submit_state ? `submit_state=${submitDebug.submit_state}` : "",
        submitDebug.phase ? `phase=${submitDebug.phase}` : "",
        submitDebug.blocked_by_seq ? `blocked_by_seq=${submitDebug.blocked_by_seq}` : "",
        submitDebug.submit_seq ? `submit_seq=${submitDebug.submit_seq}` : "",
        submitDebug.ready_at ? `ready_at=${submitDebug.ready_at}` : "",
        submitDebug.waiting_started_at ? `waiting_started_at=${submitDebug.waiting_started_at}` : "",
        submitDebug.submit_started_at ? `submit_started_at=${submitDebug.submit_started_at}` : "",
        submitDebug.completed_at ? `completed_at=${submitDebug.completed_at}` : "",
        submitDebug.fallback_completed_at ? `fallback_completed_at=${submitDebug.fallback_completed_at}` : "",
        submitDebug.failed_at ? `failed_at=${submitDebug.failed_at}` : "",
        submitDebug.failed_phase ? `failed_phase=${submitDebug.failed_phase}` : "",
        submitDebug.queue_wait_ms !== undefined && submitDebug.queue_wait_ms !== null ? `queue_wait_ms=${submitDebug.queue_wait_ms}` : "",
        submitDebug.submit_latency_ms !== undefined && submitDebug.submit_latency_ms !== null ? `submit_latency_ms=${submitDebug.submit_latency_ms}` : "",
        submitDebug.error_type ? `error_type=${submitDebug.error_type}` : "",
        submitDebug.error_message ? `error_message=${submitDebug.error_message}` : "",
      ].filter(Boolean).join("\n") || "暂无",
      submitDebug.submit_state || "n/a"
    );
    appendPreviewSection(
      box,
      "记忆候选",
      formatMemoryCandidate(baseMetadata.memory_candidate_snapshot),
      baseMetadata.memory_candidate_snapshot?.source_label || baseMetadata.memory_candidate_snapshot?.source_modality || "无"
    );
    appendPreviewSection(
      box,
      "记忆决策",
      formatMemoryDecision(baseMetadata.memory_candidate_decision),
      baseMetadata.memory_auto_added ? "auto added" : "not auto added"
    );
  }

  appendPreviewSection(
    box,
    "system prompt",
    preview.system_prompt || "",
    `${textLength(preview.system_prompt)} 字`
  );
  appendPreviewSection(
    box,
    "时间上下文",
    preview.time_context || "",
    `${textLength(preview.time_context)} 字`
  );
  if (preview.relationship_context) {
    appendPreviewSection(
      box,
      "关系上下文",
      preview.relationship_context,
      `${textLength(preview.relationship_context)} 字`
    );
  }
  appendPreviewSection(
    box,
    "记忆",
    formatSelectedMemories(preview.selected_memories),
    `${(preview.memory_contexts || []).length} 条上下文`
  );
  appendPreviewSection(
    box,
    "最近历史",
    formatMessages(preview.recent_messages),
    `${(preview.recent_messages || []).length} 条`
  );
  appendPreviewSection(
    box,
    "最终送入主链的当前输入",
    preview.current_user_message || "",
    `${textLength(preview.current_user_message)} 字`
  );
  appendPreviewSection(
    box,
    "最终 messages",
    JSON.stringify(preview.final_messages || [], null, 2),
    `${(preview.final_messages || []).length} 条`
  );
  if (mode === "message" && preview._platform_trace_section) {
    appendPreviewSection(
      box,
      preview._platform_trace_section.title || "Routing / Gate Trace",
      preview._platform_trace_section.content || "暂无",
      preview._platform_trace_section.meta || "-"
    );
  }

  status.textContent = mode === "message"
    ? "已按真实消息载入完整输入预览。"
    : "这是当前输入框的草稿预览；未调用模型，未写入会话。";
}

function buildTraceEventSection(events = []) {
  const items = (events || []).filter((item) => item?.module === "platform");
  if (items.length < 1) {
    return null;
  }
  const lines = items
    .filter((item) => [
      "session_aggregation_batch_opened",
      "session_aggregation_ingress_allocated",
      "session_aggregation_source_ready",
      "session_aggregation_batch_sealed",
      "session_routing_resolved",
      "session_submit_ingress_allocated",
      "session_submit_ready",
      "session_submit_start",
      "session_submit_finished",
      "session_submit_failed",
    ].includes(item.event))
    .map((item) => {
      const metadata = item.metadata || {};
      const parts = [
        item.event,
        metadata.routing_mode ? `routing_mode=${metadata.routing_mode}` : "",
        metadata.auto_session_id ? `auto=${metadata.auto_session_id}` : "",
        metadata.final_session_id ? `final=${metadata.final_session_id}` : "",
        metadata.batch_id ? `batch=${shortBatchLabel(metadata.batch_id)}` : "",
        metadata.batch_state ? `batch_state=${metadata.batch_state}` : "",
        metadata.arrival_seq ? `arrival=${metadata.arrival_seq}` : "",
        metadata.submit_seq ? `submit=${metadata.submit_seq}` : "",
        metadata.blocked_by_seq ? `blocked_by=${metadata.blocked_by_seq}` : "",
        metadata.queue_wait_ms !== undefined ? `wait=${metadata.queue_wait_ms}ms` : "",
        metadata.queued_remaining !== undefined ? `remaining=${metadata.queued_remaining}` : "",
        metadata.error_type ? `error=${metadata.error_type}` : "",
      ].filter(Boolean);
      return parts.join(" · ");
    });
  if (lines.length < 1) {
    return null;
  }
  return {
    title: "Routing / Gate Trace",
    content: lines.join("\n"),
    meta: `${lines.length} 条平台事件`,
  };
}

export async function previewChatInput() {
  const text = input.value.trim();
  const status = document.getElementById("chatPreviewStatus");
  if (!text) {
    if (status) {
      status.textContent = "请输入要预览的消息。";
    }
    return;
  }

  const restoreButton = setBusyButton(previewBtn, "预览中...");
  if (status) {
    status.textContent = "正在生成输入框草稿预览...";
  }

  try {
    const data = await requestJson(
      "/debug/chat-preview",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({
          session_id: getSessionId(),
          message: text,
        }),
      },
      "预览失败："
    );
    renderChatPreview(data, "draft");
  } catch (err) {
    if (status) {
      status.textContent = err.message;
    }
  } finally {
    restoreButton();
  }
}

async function openMessagePreview(messageId) {
  setSelectedMessage(messageId);
  previewedMessageId = messageId;
  const status = document.getElementById("chatPreviewStatus");
  if (status) {
    status.textContent = `正在加载消息 #${messageId} 的真实预览...`;
  }
  const data = await requestJson(
    `/debug/chat-preview/message?message_id=${encodeURIComponent(messageId)}`,
    {
      method: "GET",
      headers: getAdminHeaders(),
    },
    "加载消息预览失败："
  );
  if (data?.trace_id) {
    try {
      const traceData = await requestJson(
        `/debug/events?trace_id=${encodeURIComponent(data.trace_id)}&module=platform&limit=20`,
        {
          method: "GET",
          headers: getAdminHeaders(),
        },
        "加载平台 trace 失败："
      );
      const traceSection = buildTraceEventSection(traceData.events || []);
      if (traceSection) {
        data.preview = {
          ...(data.preview || {}),
          _platform_trace_section: traceSection,
        };
      }
    } catch {
      // Keep preview usable even if trace lookup fails.
    }
  }
  renderChatPreview(data, "message");
  renderMessageDebugPanel(data);
  renderRoutingExplainFromMetadata(data?.preview_source_metadata || data?.message?.metadata || {});
  await loadCurrentSessionDebug({ silent: true });
}

async function deleteMessageTurn(message) {
  const scope = message.trace_id
    ? (message.role === "assistant" ? "该轮聚合输入及回复" : "该条输入及其本轮回复")
    : "该条消息";
  if (!confirm(`确定删除${scope}吗？`)) {
    return;
  }

  await requestJson(
    "/session/delete-message",
    {
      method: "POST",
      headers: getAdminHeaders(),
      body: JSON.stringify({ message_id: message.id }),
    },
    "删除失败："
  );

  const status = document.getElementById("chatPreviewStatus");
  if (status) {
    status.textContent = `已删除消息 #${message.id} 对应的${scope}。`;
  }
  await reloadSessionMessages();
}

function showMessageContextMenu(event, message) {
  const isSelected = selectedMessageId === message.id;
  const isPreviewOpen = previewedMessageId === message.id;
  showContextMenu(event, [
    {
      label: isSelected ? "取消选中这条消息" : "选中这条消息",
      onClick: async () => {
        if (isSelected) {
          setSelectedMessage(null);
          clearMessageDebugPanel();
        } else {
          setSelectedMessage(message.id);
          renderSelectedMessageDebug(message.id);
        }
        await loadCurrentSessionDebug({ silent: true });
      },
    },
    {
      label: isPreviewOpen
        ? "取消选中并清空完整输入预览"
        : (message.role === "assistant" ? "查看完整输入预览（该轮回复）" : "查看完整输入预览"),
      onClick: async () => {
        try {
          if (isPreviewOpen) {
            setSelectedMessage(null);
            clearPreviewPanel();
            clearMessageDebugPanel();
            await loadCurrentSessionDebug({ silent: true });
            return;
          }
          await openMessagePreview(message.id);
        } catch (err) {
          document.getElementById("chatPreviewStatus").textContent = err.message;
        }
      },
    },
    {
      label: message.trace_id ? "删除该条输入（含回复）" : "删除该条消息",
      className: "danger",
      onClick: async () => {
        try {
          await deleteMessageTurn(message);
        } catch (err) {
          document.getElementById("chatPreviewStatus").textContent = err.message;
        }
      },
    },
  ]);
}

export async function sendMessage() {
  const text = input.value.trim();
  if (!text) {
    return;
  }

  input.value = "";
  sendBtn.disabled = true;
  sendBtn.textContent = "发送中...";

  try {
    const data = await requestJson(
      "/chat",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: getSessionId(),
          message: text,
        }),
      },
      "出错了："
    );
    addMessage({
      id: data.user_message_id,
      role: "user",
      content: text,
      trace_id: data.trace_id,
      message_type: data.message_type || "text",
      source: data.source || "web",
      metadata: {
        ...buildTextInputRecord(text, data.source || "web"),
        memory_candidate_snapshot: data.candidate_memory_debug || null,
        memory_candidate_decision: data.candidate_memory_decision || null,
        memory_auto_added: Boolean(data.auto_added),
      },
      has_preview: Boolean(data.user_message_id),
      created_at: new Date().toISOString(),
    });
    addMessage({
      id: data.assistant_message_id,
      role: "assistant",
      content: data.reply || "",
      trace_id: data.trace_id,
      message_type: "assistant",
      source: data.source || "web",
      created_at: new Date().toISOString(),
    });
    lastCandidate = data.candidate_memory || null;
    lastCandidateDebug = data.candidate_memory_debug || null;
    lastCandidateDecision = data.candidate_memory_decision || null;
    renderCandidateMemories();
    const candidateStatus = document.getElementById("candidateStatus");
    if (candidateStatus && data.candidate_memory_decision) {
      const source = data.candidate_memory_decision.source_modality || data.candidate_memory_debug?.source_label || "text";
      candidateStatus.textContent = `本轮记忆决策：${data.candidate_memory_decision.action || "-"} · ${source} · ${data.candidate_memory_decision.reason || ""}`.trim();
    }
    renderUsedMemories(data.used_memories || []);
    relationshipStateRenderer(data.relationship_state);
    relationshipContextRenderer(data.relationship_context);
    updateRoutingSourceHint();
    await loadCurrentSessionDebug({ silent: true });
  } catch (err) {
    addMessage("assistant", err.message);
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = "发送";
  }
}

export function bindChatEvents(options = {}) {
  relationshipStateRenderer = options.renderRelationshipState || relationshipStateRenderer;
  relationshipContextRenderer = options.renderRelationshipContext || relationshipContextRenderer;
  reloadSessionMessages = options.reloadSessionMessages || reloadSessionMessages;
  input = document.getElementById("messageInput");
  sendBtn = document.getElementById("sendBtn");
  previewBtn = document.getElementById("previewChatBtn");
  routingStatusNode = document.getElementById("routingStatus");
  routingExplainNode = document.getElementById("routingExplainBox");
  routingSourceHintNode = document.getElementById("routingSourceHint");
  routingSourceSummaryNode = document.getElementById("routingSourceSummary");
  routingQueryBtn = document.getElementById("routingQueryBtn");
  routingSetBtn = document.getElementById("routingSetBtn");
  routingClearBtn = document.getElementById("routingClearBtn");
  routingAutofillBtn = document.getElementById("routingAutofillBtn");
  refreshSessionDebugBtn = document.getElementById("refreshSessionDebugBtn");
  ensureContextMenu();

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });

  sendBtn.addEventListener("click", sendMessage);
  previewBtn?.addEventListener("click", previewChatInput);
  routingAutofillBtn?.addEventListener("click", autofillRoutingSource);
  routingQueryBtn?.addEventListener("click", queryRoutingExplain);
  routingSetBtn?.addEventListener("click", setRoutingOverride);
  routingClearBtn?.addEventListener("click", clearRoutingOverride);
  refreshSessionDebugBtn?.addEventListener("click", () => loadCurrentSessionDebug());
  updateRoutingSourceHint();
}
