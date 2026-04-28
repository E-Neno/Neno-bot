import {
  appendConfigLine,
  clearChildren,
  truncateText,
} from "./js/dom.js";
import {
  clearAdminToken,
  getAdminHeaders,
  getAdminToken,
  requestJson,
  saveAdminToken,
  updateAdminTokenStatus,
} from "./js/api.js";
import {
  buildConsoleLayout,
  setActivePanel,
  updateCurrentSessionStatus as setCurrentSessionStatus,
} from "./js/layout.js";
import {
  bindProactiveEvents,
  loadProactiveCandidates,
  loadProactiveConfig,
  loadProactiveEvents,
  loadProactiveStatus,
  loadProactiveTargets,
} from "./js/proactive.js";

let lastCandidate = null;
let onlyActive = false;
let input = null;
let sendBtn = null;

const relationshipStagePresets = {
  stranger: {
    stage: 0,
    conversation_count: 0,
    familiarity_score: 0,
    trust_score: 0,
    emotional_depth_score: 0,
    boundary_score: 0,
  },
  familiar: {
    stage: 1,
    conversation_count: 12,
    familiarity_score: 8,
    trust_score: 1,
    emotional_depth_score: 0,
    boundary_score: 2,
  },
  stable: {
    stage: 2,
    conversation_count: 45,
    familiarity_score: 28,
    trust_score: 8,
    emotional_depth_score: 5,
    boundary_score: 10,
  },
  close: {
    stage: 3,
    conversation_count: 130,
    familiarity_score: 60,
    trust_score: 30,
    emotional_depth_score: 25,
    boundary_score: 20,
  },
  deep: {
    stage: 4,
    conversation_count: 300,
    familiarity_score: 120,
    trust_score: 80,
    emotional_depth_score: 70,
    boundary_score: 40,
  },
};

function getSessionId() {
  const value = document.getElementById("sessionInput").value.trim();
  return value || "web-test";
}

function updateCurrentSessionStatus(sessionId) {
  setCurrentSessionStatus(sessionId, getSessionId());
}

function addMessage(role, text) {
  const box = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = "msg " + (role === "user" ? "user" : "bot");
  div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function resetMessages() {
  clearChildren(document.getElementById("messages"));
}

function renderCandidate() {
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

function renderUsedMemories(memories) {
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

function renderRelationshipState(state) {
  if (!state) {
    return;
  }

  document.getElementById("relStageLabel").textContent = state.stage_label || "-";
  document.getElementById("relConversationCount").textContent = state.conversation_count ?? 0;
  document.getElementById("relFamiliarityScore").textContent = state.familiarity_score ?? 0;
  document.getElementById("relTrustScore").textContent = state.trust_score ?? 0;
  document.getElementById("relEmotionalDepthScore").textContent = state.emotional_depth_score ?? 0;
  document.getElementById("relBoundaryScore").textContent = state.boundary_score ?? 0;
}

function renderRelationshipContext(context) {
  const box = document.getElementById("relationshipContextBox");
  box.textContent = context || "暂无";
}

function renderSessions(sessions) {
  const list = document.getElementById("sessionList");

  if (sessions.length === 0) {
    list.textContent = "暂无会话";
    return;
  }

  clearChildren(list);

  for (const session of sessions) {
    const item = document.createElement("div");
    item.className = "session-item";

    const title = document.createElement("div");
    title.className = "session-title";
    title.textContent = session.session_id || "";

    const meta = document.createElement("div");
    meta.className = "session-meta";
    meta.textContent = `${session.message_count ?? 0} 条消息 · ${session.last_message_at || ""}`;

    const row = document.createElement("div");
    row.className = "row";

    const openButton = document.createElement("button");
    openButton.textContent = "打开";
    openButton.addEventListener("click", () => selectSession(session.session_id || "default"));

    row.appendChild(openButton);
    item.append(title, meta, row);
    list.appendChild(item);
  }
}

function renderMemories(memories) {
  const list = document.getElementById("memoryList");

  if (memories.length === 0) {
    list.textContent = "暂无记忆";
    return;
  }

  clearChildren(list);

  for (const mem of memories) {
    const item = document.createElement("div");
    item.className = "memory-item";

    const tag = document.createElement("div");
    tag.className = "tag";
    tag.textContent = `${mem.memory_type || "general"} · ${mem.is_active ? "启用" : "停用"}`;

    const content = document.createElement("div");
    content.className = "memory-content";
    content.textContent = mem.content || "";

    const meta = document.createElement("div");
    meta.className = "memory-meta";
    meta.textContent = `id=${mem.id} · ${mem.created_at || ""}`;

    const row = document.createElement("div");
    row.className = "row";

    const editButton = document.createElement("button");
    editButton.className = "secondary";
    editButton.textContent = "编辑";
    editButton.addEventListener("click", () => editMemory(mem.id, mem.content || "", mem.memory_type || "general"));

    const stateButton = document.createElement("button");
    stateButton.className = mem.is_active ? "danger" : "good";
    stateButton.textContent = mem.is_active ? "停用" : "启用";
    stateButton.addEventListener("click", () => {
      if (mem.is_active) {
        disableMemory(mem.id);
      } else {
        enableMemory(mem.id);
      }
    });

    const deleteButton = document.createElement("button");
    deleteButton.className = "danger";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => deleteMemory(mem.id));

    row.append(editButton, stateButton, deleteButton);
    item.append(tag, content, meta, row);
    list.appendChild(item);
  }
}

async function sendMessage() {
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
    renderCandidate();
    renderUsedMemories(data.used_memories || []);
    renderRelationshipState(data.relationship_state);
    renderRelationshipContext(data.relationship_context);
  } catch (err) {
    addMessage("bot", err.message);
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = "发送";
  }
}

async function loadConfig() {
  const box = document.getElementById("configBox");
  const status = document.getElementById("configStatus");
  box.textContent = "加载中...";
  status.textContent = "";

  try {
    const data = await requestJson("/config", undefined, "加载失败：");
    clearChildren(box);
    appendConfigLine(box, "chat_model", data.chat_model);
    appendConfigLine(box, "memory_model", data.memory_model);
    appendConfigLine(box, "history_limit", data.history_limit);
    appendConfigLine(box, "memory_limit", data.memory_limit);
    document.getElementById("chatModelInput").value = data.chat_model || "";
    document.getElementById("memoryModelInput").value = data.memory_model || "";
    document.getElementById("historyLimitInput").value = data.history_limit ?? "";
    document.getElementById("memoryLimitInput").value = data.memory_limit ?? "";
  } catch (err) {
    box.textContent = err.message;
  }
}

function setStatsText(id, value) {
  document.getElementById(id).textContent = value ?? "-";
}

function renderStatsSummary(summary) {
  setStatsText("statsToday", summary.today_messages);
  setStatsText("stats24h", summary.last_24h_messages);
  setStatsText("statsErrors", summary.last_24h_errors);
  setStatsText("statsLatency", `${summary.avg_latency_ms_24h || 0} ms`);
  setStatsText("statsLastMessage", summary.last_message_at || "-");
  setStatsText("statsLastQq", summary.last_qq_message_at || "-");
  setStatsText("statsBackend", summary.backend_ok ? "正常" : "异常");
  setStatsText("statsOpenClaw", summary.openclaw_gateway_maybe_online ? "近期有 QQ" : "无近期 QQ");
  setStatsText("statsModel", summary.current_model || "-");
}

async function loadStatsSummary() {
  const status = document.getElementById("statsStatus");
  const token = getAdminToken();

  if (!token) {
    status.textContent = "设置 Admin Token 后可刷新状态";
    return;
  }

  status.textContent = "加载中...";

  try {
    const data = await requestJson(
      "/stats/summary",
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载失败："
    );
    renderStatsSummary(data.summary || {});
    status.textContent = "已刷新";
  } catch (err) {
    status.textContent = err.message;
  }
}

async function saveConfig() {
  const status = document.getElementById("configStatus");
  status.textContent = "保存中...";

  const payload = {
    chat_model: document.getElementById("chatModelInput").value,
    memory_model: document.getElementById("memoryModelInput").value,
    history_limit: Number(document.getElementById("historyLimitInput").value),
    memory_limit: Number(document.getElementById("memoryLimitInput").value),
  };

  if (!payload.chat_model.trim()) {
    delete payload.chat_model;
  }
  if (!payload.memory_model.trim()) {
    delete payload.memory_model;
  }
  if (Number.isNaN(payload.history_limit)) {
    delete payload.history_limit;
  }
  if (Number.isNaN(payload.memory_limit)) {
    delete payload.memory_limit;
  }

  try {
    await requestJson(
      "/config/update",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify(payload),
      },
      "保存失败："
    );
    status.textContent = "已保存，执行 nereboot 后生效。";
  } catch (err) {
    status.textContent = err.message;
  }
}

async function loadSessions() {
  const list = document.getElementById("sessionList");
  list.textContent = "加载中...";

  try {
    const data = await requestJson(
      "/session/list",
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载失败："
    );
    renderSessions(data.sessions || []);
  } catch (err) {
    list.textContent = err.message;
  }
}

function selectSession(sessionId) {
  document.getElementById("sessionInput").value = sessionId;
  updateCurrentSessionStatus(sessionId);
  loadSessionMessages();
  loadRelationshipState();
  setActivePanel("chatPanel");
}

async function loadSessionMessages() {
  const sessionId = getSessionId();
  updateCurrentSessionStatus(sessionId);
  resetMessages();

  try {
    const data = await requestJson(
      `/session/messages?session_id=${encodeURIComponent(sessionId)}&limit=80`,
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载历史失败："
    );

    if (!data.messages || data.messages.length === 0) {
      addMessage("bot", `当前会话 ${sessionId} 还没有历史。`);
      return;
    }

    for (const msg of data.messages) {
      if (msg.role === "user" || msg.role === "assistant") {
        addMessage(msg.role === "user" ? "user" : "bot", msg.content);
      }
    }
  } catch (err) {
    addMessage("bot", `加载会话 ${sessionId} 失败：${err.message}`);
  }
}

async function clearSession() {
  const sessionId = getSessionId();

  if (!confirm(`确定清空会话 ${sessionId} 的聊天记录吗？`)) {
    return;
  }

  try {
    const data = await requestJson(
      "/session/clear",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({ session_id: sessionId }),
      },
      "清空失败："
    );
    resetMessages();
    addMessage("bot", `已清空 ${sessionId}，删除 ${data.deleted} 条记录。`);
  } catch (err) {
    addMessage("bot", err.message);
  }
}

async function loadRelationshipState() {
  const status = document.getElementById("relationshipStatus");
  status.textContent = "加载中...";

  try {
    const data = await requestJson(
      `/relationship/state?session_id=${encodeURIComponent(getSessionId())}`,
      undefined,
      "加载失败："
    );
    renderRelationshipState(data);
    status.textContent = "已刷新";
  } catch (err) {
    status.textContent = err.message;
  }
}

async function resetRelationshipState() {
  const sessionId = getSessionId();

  if (!confirm(`确定重置 ${sessionId} 的关系状态吗？`)) {
    return;
  }

  const status = document.getElementById("relationshipStatus");
  status.textContent = "重置中...";

  try {
    const data = await requestJson(
      "/relationship/reset",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({ session_id: sessionId }),
      },
      "重置失败："
    );
    renderRelationshipState(data);
    status.textContent = "已重置";
  } catch (err) {
    status.textContent = err.message;
  }
}

async function setRelationshipStagePreset(presetKey) {
  const preset = relationshipStagePresets[presetKey];
  const status = document.getElementById("relationshipStatus");

  if (!preset) {
    status.textContent = "未知关系阶段预设";
    return;
  }

  status.textContent = "设置中...";

  try {
    const data = await requestJson(
      "/relationship/update",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({
          session_id: getSessionId(),
          ...preset,
        }),
      },
      "设置失败："
    );
    renderRelationshipState(data);
    status.textContent = "已设置";
  } catch (err) {
    status.textContent = err.message;
  }
}

async function confirmCandidate() {
  const status = document.getElementById("candidateStatus");

  if (!lastCandidate || !lastCandidate.content) {
    status.textContent = "没有可确认的候选记忆";
    return;
  }

  try {
    const data = await requestJson(
      "/memory/confirm",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({
          content: lastCandidate.content,
          memory_type: lastCandidate.memory_type || "general",
        }),
      },
      "确认失败："
    );
    const duplicates = data.duplicate_candidates || [];
    const duplicateText = duplicates.length
      ? "\n\n可能重复：\n" + duplicates
          .map(
            (item) =>
              `- id=${item.id} [${item.memory_type}] ${item.content}`
          )
          .join("\n")
      : "";
    status.textContent = `${data.message || "确认完成"}${duplicateText}`;
    lastCandidate = null;
    renderCandidate();
    loadMemories();
  } catch (err) {
    status.textContent = err.message;
  }
}

function clearCandidate() {
  lastCandidate = null;
  renderCandidate();
  document.getElementById("candidateStatus").textContent = "已忽略";
}

async function loadMemories() {
  const list = document.getElementById("memoryList");
  list.textContent = "加载中...";

  const url = onlyActive ? "/memory/list?active=1" : "/memory/list";

  try {
    const data = await requestJson(
      url,
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载失败："
    );
    renderMemories(data.memories || []);
  } catch (err) {
    list.textContent = err.message;
  }
}

async function updateMemoryState(url, payload) {
  await requestJson(
    url,
    {
      method: "POST",
      headers: getAdminHeaders(),
      body: JSON.stringify(payload),
    },
    "操作失败："
  );
  loadMemories();
}

async function disableMemory(id) {
  await updateMemoryState("/memory/disable", { memory_id: id });
}

async function enableMemory(id) {
  await updateMemoryState("/memory/enable", { id });
}

async function deleteMemory(id) {
  const ok = confirm(`确定彻底删除记忆 id=${id} 吗？删除后不能恢复。`);
  if (!ok) {
    return;
  }

  try {
    await requestJson(
      "/memory/delete",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({ id }),
      },
      "删除失败："
    );
    loadMemories();
  } catch (err) {
    alert(err.message);
  }
}

async function editMemory(id, currentContent, currentType) {
  const newContent = prompt("编辑 memory content", currentContent);
  if (newContent === null) {
    return;
  }

  const trimmedContent = newContent.trim();
  if (!trimmedContent) {
    alert("content 不能为空");
    return;
  }

  const newType = prompt("编辑 memory_type", currentType);
  if (newType === null) {
    return;
  }

  const trimmedType = newType.trim() || "general";

  try {
    await requestJson(
      "/memory/update",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({
          id,
          content: trimmedContent,
          memory_type: trimmedType,
        }),
      },
      "编辑失败："
    );
    loadMemories();
  } catch (err) {
    alert(err.message);
  }
}

function toggleOnlyActive() {
  onlyActive = !onlyActive;
  loadMemories();
}

function handleSaveAdminToken() {
  saveAdminToken();
  loadStatsSummary();
  loadProactiveCandidates();
}

function handleClearAdminToken() {
  clearAdminToken();
  loadProactiveCandidates();
}

function bindBaseEvents() {
  input = document.getElementById("messageInput");
  sendBtn = document.getElementById("sendBtn");

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });

  document.getElementById("sendBtn").addEventListener("click", sendMessage);
  document.getElementById("loadSessionMessagesBtn").addEventListener("click", loadSessionMessages);
  document.getElementById("clearSessionBtn").addEventListener("click", clearSession);
  document.getElementById("loadSessionsBtn").addEventListener("click", loadSessions);
  document.getElementById("saveAdminTokenBtn").addEventListener("click", handleSaveAdminToken);
  document.getElementById("clearAdminTokenBtn").addEventListener("click", handleClearAdminToken);
  document.getElementById("loadConfigBtn").addEventListener("click", loadConfig);
  document.getElementById("saveConfigBtn").addEventListener("click", saveConfig);
  document.getElementById("loadStatsSummaryBtn").addEventListener("click", loadStatsSummary);
  document.getElementById("loadRelationshipStateBtn").addEventListener("click", loadRelationshipState);
  document.getElementById("resetRelationshipStateBtn").addEventListener("click", resetRelationshipState);
  document.getElementById("confirmCandidateBtn").addEventListener("click", confirmCandidate);
  document.getElementById("clearCandidateBtn").addEventListener("click", clearCandidate);
  document.getElementById("loadMemoriesBtn").addEventListener("click", loadMemories);
  document.getElementById("toggleOnlyActiveBtn").addEventListener("click", toggleOnlyActive);

  for (const button of document.querySelectorAll("[data-stage-preset]")) {
    button.addEventListener("click", () => setRelationshipStagePreset(button.dataset.stagePreset));
  }
}

function init() {
  buildConsoleLayout();
  bindBaseEvents();
  bindProactiveEvents();
  loadConfig();
  loadSessions();
  loadMemories();
  loadSessionMessages();
  loadRelationshipState();
  renderUsedMemories([]);
  updateAdminTokenStatus();
  loadStatsSummary();
  loadProactiveStatus();
  loadProactiveConfig();
  loadProactiveCandidates();
  loadProactiveTargets();
  loadProactiveEvents();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
