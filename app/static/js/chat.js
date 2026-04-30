import { clearChildren, setBusyButton, truncateText } from "./dom.js";
import { getAdminHeaders, requestJson } from "./api.js";
import { updateCurrentSessionStatus as setCurrentSessionStatus } from "./layout.js";

let lastCandidate = null;
let input = null;
let sendBtn = null;
let previewBtn = null;
let relationshipStateRenderer = () => {};
let relationshipContextRenderer = () => {};

export function getSessionId() {
  const value = document.getElementById("sessionInput").value.trim();
  return value || "web-test";
}

export function updateCurrentSessionStatus(sessionId) {
  setCurrentSessionStatus(sessionId, getSessionId());
}

export function addMessage(role, text) {
  const box = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = "msg " + (role === "user" ? "user" : "bot");
  div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

export function resetMessages() {
  clearChildren(document.getElementById("messages"));
}

export function getCandidateMemory() {
  return lastCandidate;
}

export function clearCandidateMemory() {
  lastCandidate = null;
  renderCandidateMemories();
}

export function renderCandidateMemories() {
  const box = document.getElementById("candidateBox");
  const status = document.getElementById("candidateStatus");
  status.textContent = "";

  if (!lastCandidate) {
    box.textContent = "暂无候选记忆";
    return;
  }

  clearChildren(box);

  const tag = document.createElement("div");
  tag.className = "tag";
  tag.textContent = lastCandidate.memory_type || "general";

  const content = document.createElement("div");
  content.className = "memory-content";
  content.textContent = lastCandidate.content || "";

  box.append(tag, content);
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

function renderChatPreview(data) {
  const box = document.getElementById("chatPreviewBox");
  const status = document.getElementById("chatPreviewStatus");
  if (!box || !status) {
    return;
  }

  const preview = data?.preview || {};
  const counts = preview.counts || {};
  clearChildren(box);

  const summary = document.createElement("div");
  summary.className = "chat-preview-summary";
  appendPreviewMetric(summary, "session", data?.session_id_label || "-");
  appendPreviewMetric(summary, "记忆", counts.memory_count ?? 0);
  appendPreviewMetric(summary, "历史", counts.recent_message_count ?? 0);
  appendPreviewMetric(summary, "final messages", counts.final_message_count ?? 0);
  box.appendChild(summary);

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
    "当前输入",
    preview.current_user_message || "",
    `${textLength(preview.current_user_message)} 字`
  );
  appendPreviewSection(
    box,
    "最终 messages",
    JSON.stringify(preview.final_messages || [], null, 2),
    `${(preview.final_messages || []).length} 条`
  );

  status.textContent = "预览已加载；未调用模型，未写入会话。";
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
    status.textContent = "正在生成预览...";
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
    renderChatPreview(data);
  } catch (err) {
    if (status) {
      status.textContent = err.message;
    }
  } finally {
    restoreButton();
  }
}

export async function sendMessage() {
  const text = input.value.trim();
  if (!text) {
    return;
  }

  input.value = "";
  addMessage("user", text);
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
    addMessage("bot", data.reply || "");
    lastCandidate = data.candidate_memory || null;
    renderCandidateMemories();
    renderUsedMemories(data.used_memories || []);
    relationshipStateRenderer(data.relationship_state);
    relationshipContextRenderer(data.relationship_context);
  } catch (err) {
    addMessage("bot", err.message);
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = "发送";
  }
}

export function bindChatEvents(options = {}) {
  relationshipStateRenderer = options.renderRelationshipState || relationshipStateRenderer;
  relationshipContextRenderer = options.renderRelationshipContext || relationshipContextRenderer;
  input = document.getElementById("messageInput");
  sendBtn = document.getElementById("sendBtn");
  previewBtn = document.getElementById("previewChatBtn");

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });

  sendBtn.addEventListener("click", sendMessage);
  previewBtn?.addEventListener("click", previewChatInput);
}
