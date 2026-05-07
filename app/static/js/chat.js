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
let routingStatusNode = null;
let routingExplainNode = null;
let routingSourceHintNode = null;
let routingSourceSummaryNode = null;
let routingQueryBtn = null;
let routingSetBtn = null;
let routingClearBtn = null;
let routingAutofillBtn = null;

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
  if (metadata.ingress?.arrival_seq) {
    labels.push({ label: `arrival #${metadata.ingress.arrival_seq}`, tone: "muted" });
  }
  return labels;
}

function buildMessageSummary(message) {
  const metadata = message.metadata || {};
  const pipeline = metadata.pipeline || {};
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

  if (message.role === "user" && message.id) {
    row.dataset.messageId = String(message.id);
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
  renderedMessages = (messages || []).map((item) => normalizeMessage(item));
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
  clearChildren(document.getElementById("messages"));
  updateSessionMessageCount(0);
  updateRoutingSourceHint();
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
  clearChildren(box);

  const summary = document.createElement("div");
  summary.className = "chat-preview-summary";
  appendPreviewMetric(summary, "session", data?.session_id_label || "-");
  appendPreviewMetric(summary, "消息 ID", data?.message_id ?? "draft");
  appendPreviewMetric(summary, "模态", data?.message_type || metadata.message_type || "text");
  appendPreviewMetric(summary, "记忆", counts.memory_count ?? 0);
  appendPreviewMetric(summary, "历史", counts.recent_message_count ?? 0);
  appendPreviewMetric(summary, "final messages", counts.final_message_count ?? 0);
  box.appendChild(summary);

  if (mode === "message") {
    appendPreviewSection(
      box,
      "原始输入",
      metadata.raw_input || message.content || "",
      `${textLength(metadata.raw_input || message.content || "")} 字`
    );
    appendPreviewSection(
      box,
      "识别 / 理解结果",
      [
        metadata.pipeline?.asr?.text ? `ASR：${metadata.pipeline.asr.text}` : "",
        metadata.pipeline?.vision?.hit ? `Vision：${metadata.pipeline.vision.success === false ? "failed" : "hit"}` : "",
        metadata.pipeline?.normalization?.status ? `Normalize：${metadata.pipeline.normalization.status}` : "",
      ].filter(Boolean).join("\n") || "暂无",
      "链路命中情况"
    );
    appendPreviewSection(
      box,
      "归一化结果",
      metadata.normalized_input || preview.current_user_message || "",
      `${textLength(metadata.normalized_input || preview.current_user_message || "")} 字`
    );
    appendPreviewSection(
      box,
      "状态 / 失败点",
      formatJsonBlock(metadata.pipeline || {}),
      metadata.pipeline?.normalization?.failed_at ? `failed_at=${metadata.pipeline.normalization.failed_at}` : "success / bypass"
    );
    appendPreviewSection(
      box,
      "Routing Explain",
      [
        metadata.routing?.routing_key ? `routing_key=${metadata.routing.routing_key}` : "",
        metadata.routing?.auto_session_id ? `auto_session_id=${metadata.routing.auto_session_id}` : "",
        metadata.routing?.final_session_id ? `final_session_id=${metadata.routing.final_session_id}` : "",
        metadata.routing?.routing_mode ? `routing_mode=${metadata.routing.routing_mode}` : "",
        metadata.routing?.routing_reason ? `routing_reason=${metadata.routing.routing_reason}` : "",
        metadata.routing?.override_session_id ? `override_session_id=${metadata.routing.override_session_id}` : "",
      ].filter(Boolean).join("\n") || "暂无",
      metadata.routing?.routing_mode || "n/a"
    );
    appendPreviewSection(
      box,
      "Ingress / Gate",
      [
        metadata.ingress?.controller_mode ? `controller_mode=${metadata.ingress.controller_mode}` : "",
        metadata.ingress?.arrival_seq ? `arrival_seq=${metadata.ingress.arrival_seq}` : "",
        metadata.account_id ? `account_id=${metadata.account_id}` : "",
        metadata.platform ? `platform=${metadata.platform}` : "",
        metadata.user_id ? `user_id=${metadata.user_id}` : "",
        metadata.chat_type ? `chat_type=${metadata.chat_type}` : "",
        metadata.group_id ? `group_id=${metadata.group_id}` : "",
      ].filter(Boolean).join("\n") || "暂无",
      metadata.ingress?.controller_mode || "direct"
    );
    appendPreviewSection(
      box,
      "记忆候选",
      formatMemoryCandidate(metadata.memory_candidate_snapshot),
      metadata.memory_candidate_snapshot?.source_label || metadata.memory_candidate_snapshot?.source_modality || "无"
    );
    appendPreviewSection(
      box,
      "记忆决策",
      formatMemoryDecision(metadata.memory_candidate_decision),
      metadata.memory_auto_added ? "auto added" : "not auto added"
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
        metadata.arrival_seq ? `arrival=${metadata.arrival_seq}` : "",
        metadata.submit_seq ? `submit=${metadata.submit_seq}` : "",
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
  renderRoutingExplainFromMetadata(data?.message?.metadata || {});
}

async function deleteMessageTurn(message) {
  const scope = message.trace_id ? "该条输入及其本轮回复" : "该条消息";
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
  showContextMenu(event, [
    {
      label: "查看完整输入预览",
      onClick: async () => {
        try {
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
  updateRoutingSourceHint();
}
