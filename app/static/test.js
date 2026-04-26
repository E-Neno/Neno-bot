let lastCandidate = null;
let onlyActive = false;

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

const input = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");

input.addEventListener("keydown", function (event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

function getSessionId() {
  const value = document.getElementById("sessionInput").value.trim();
  return value || "web-test";
}

function clearChildren(element) {
  element.replaceChildren();
}

function addMessage(role, text) {
  const box = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = "msg " + (role === "user" ? "user" : "bot");
  div.innerText = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function resetMessages() {
  clearChildren(document.getElementById("messages"));
}

async function requestJson(url, options, errorPrefix) {
  const res = await fetch(url, options);
  const data = await res.json();

  if (!res.ok) {
    if (res.status === 403) {
      throw new Error("Admin Token 不正确或未配置");
    }
    throw new Error(errorPrefix + JSON.stringify(data, null, 2));
  }

  return data;
}

function getAdminToken() {
  const inputToken = document.getElementById("adminTokenInput")?.value.trim() || "";
  return inputToken || localStorage.getItem("neno_admin_token") || "";
}

function getAdminHeaders() {
  const token = getAdminToken();
  return {
    "Content-Type": "application/json",
    "X-Admin-Token": token,
  };
}

function updateAdminTokenStatus() {
  const status = document.getElementById("adminTokenStatus");
  const input = document.getElementById("adminTokenInput");
  const token = localStorage.getItem("neno_admin_token") || "";

  input.value = token;
  status.innerText = token ? "Admin Token 已保存" : "Admin Token 未设置";
}

function saveAdminToken() {
  const token = document.getElementById("adminTokenInput").value.trim();
  const status = document.getElementById("adminTokenStatus");

  if (!token) {
    localStorage.removeItem("neno_admin_token");
    status.innerText = "Admin Token 未设置";
    loadStatsSummary();
    loadProactiveCandidates();
    return;
  }

  localStorage.setItem("neno_admin_token", token);
  status.innerText = "Admin Token 已保存";
  loadStatsSummary();
  loadProactiveCandidates();
}

function clearAdminToken() {
  localStorage.removeItem("neno_admin_token");
  document.getElementById("adminTokenInput").value = "";
  document.getElementById("adminTokenStatus").innerText = "Admin Token 已清除";
  loadProactiveCandidates();
}

function truncateText(text, maxLength = 80) {
  const value = String(text || "");
  return value.length > maxLength ? value.slice(0, maxLength) + "..." : value;
}

function appendConfigLine(box, label, value) {
  const line = document.createElement("div");
  line.className = "config-line";

  const name = document.createElement("b");
  name.textContent = `${label}:`;

  line.append(name, ` ${value ?? ""}`);
  box.appendChild(line);
}

function renderCandidate() {
  const box = document.getElementById("candidateBox");
  const status = document.getElementById("candidateStatus");
  status.innerText = "";

  if (!lastCandidate) {
    box.innerText = "暂无候选记忆";
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
    box.innerText = "暂无命中";
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

  document.getElementById("relStageLabel").innerText = state.stage_label || "-";
  document.getElementById("relConversationCount").innerText = state.conversation_count ?? 0;
  document.getElementById("relFamiliarityScore").innerText = state.familiarity_score ?? 0;
  document.getElementById("relTrustScore").innerText = state.trust_score ?? 0;
  document.getElementById("relEmotionalDepthScore").innerText = state.emotional_depth_score ?? 0;
  document.getElementById("relBoundaryScore").innerText = state.boundary_score ?? 0;
}

function renderRelationshipContext(context) {
  const box = document.getElementById("relationshipContextBox");
  box.innerText = context || "暂无";
}

function renderSessions(sessions) {
  const list = document.getElementById("sessionList");

  if (sessions.length === 0) {
    list.innerText = "暂无会话";
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
    list.innerText = "暂无记忆";
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

function renderProactiveCandidates(candidates) {
  const list = document.getElementById("proactiveCandidateList");

  if (!candidates || candidates.length === 0) {
    list.textContent = "暂无候选";
    return;
  }

  clearChildren(list);

  for (const candidate of candidates) {
    const item = document.createElement("div");
    item.className = "memory-item";

    const tag = document.createElement("div");
    tag.className = "tag";
    tag.textContent = `${candidate.platform || "-"} · ${candidate.status || "-"} · ${candidate.target_label || "-"}`;

    const content = document.createElement("div");
    content.className = "memory-content";
    content.textContent = candidate.message || "";

    const reason = document.createElement("div");
    reason.className = "memory-meta";
    reason.textContent = candidate.reason || "";

    const meta = document.createElement("div");
    meta.className = "memory-meta";
    meta.textContent = `id=${candidate.id} · ${candidate.created_at || ""}`;

    const row = document.createElement("div");
    row.className = "row";

    const dismissButton = document.createElement("button");
    dismissButton.className = "secondary";
    dismissButton.textContent = "丢弃";
    dismissButton.disabled = candidate.status === "dismissed";
    dismissButton.addEventListener("click", () => dismissProactiveCandidate(candidate.id));

    if (candidate.status === "pending" && candidate.platform === "qq") {
      const dryRunButton = document.createElement("button");
      dryRunButton.className = "good";
      dryRunButton.textContent = "测试发送 QQ";
      dryRunButton.addEventListener("click", () => dryRunSendQqCandidate(candidate.id));
      row.appendChild(dryRunButton);

      const sendButton = document.createElement("button");
      sendButton.className = "danger";
      sendButton.textContent = "真实发送 QQ";
      sendButton.addEventListener("click", () => sendQqCandidate(candidate.id));
      row.appendChild(sendButton);
    }

    row.appendChild(dismissButton);
    item.append(tag, content, reason, meta, row);
    list.appendChild(item);
  }
}

function renderProactiveAutoStatus(data) {
  const box = document.getElementById("proactiveAutoStatus");
  if (!box) {
    return;
  }

  const config = data.config || {};
  const enabled = data.enabled ? "开启" : "关闭";
  const running = data.task_running ? "运行中" : "未运行";
  const lastSent = data.last_sent_at || "-";
  const lastCheck = data.last_check_at || "-";
  const today = data.today_sent_count ?? 0;
  const limit = config.daily_limit ?? "-";

  box.textContent = [
    `自动：${enabled} · ${running}`,
    `今日 ${today}/${limit}`,
    `最近发送 ${lastSent}`,
    `最近检查 ${lastCheck}`,
    `间隔 ${config.check_interval_seconds ?? "-"}s`,
    `时间窗 ${config.active_start || "-"}-${config.active_end || "-"}`,
  ].join(" · ");
}

async function loadProactiveStatus() {
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

async function loadProactiveConfig() {
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

async function saveProactiveConfig() {
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

async function loadProactiveCandidates() {
  const list = document.getElementById("proactiveCandidateList");
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();

  if (!token) {
    list.textContent = "需要 Admin Token";
    status.textContent = "";
    loadProactiveStatus();
    return;
  }

  list.textContent = "加载中...";
  status.textContent = "";

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
  }
}

async function generateProactiveCandidate() {
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();

  if (!token) {
    status.textContent = "需要 Admin Token";
    return;
  }

  const platform = document.getElementById("proactivePlatformSelect").value;
  const payload = platform ? { platform } : {};
  status.textContent = "生成中...";

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
      status.textContent = "已生成候选";
    }
    loadProactiveCandidates();
    loadProactiveStatus();
  } catch (err) {
    status.textContent = err.message;
  }
}

async function dismissProactiveCandidate(id) {
  const status = document.getElementById("proactiveCandidateStatus");
  status.textContent = "丢弃中...";

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
  } catch (err) {
    status.textContent = err.message;
  }
}

async function dryRunSendQqCandidate(id) {
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();

  if (!token) {
    status.textContent = "需要 Admin Token";
    return;
  }

  status.textContent = "测试中...";

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
  } catch (err) {
    status.textContent = err.message;
  }
}

async function sendQqCandidate(id) {
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();

  if (!token) {
    status.textContent = "需要 Admin Token";
    return;
  }

  const ok = confirm("确认发送这条主动消息到 QQ？这会真的发出去。");
  if (!ok) {
    return;
  }

  status.textContent = "真实发送中...";

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
  } catch (err) {
    status.textContent = err.message;
    loadProactiveCandidates();
    loadProactiveStatus();
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
  sendBtn.innerText = "发送中...";

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
    sendBtn.innerText = "发送";
  }
}

async function loadConfig() {
  const box = document.getElementById("configBox");
  const status = document.getElementById("configStatus");
  box.innerText = "加载中...";
  status.innerText = "";

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
    box.innerText = err.message;
  }
}

function setStatsText(id, value) {
  document.getElementById(id).innerText = value ?? "-";
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
    status.innerText = "设置 Admin Token 后可刷新状态";
    return;
  }

  status.innerText = "加载中...";

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
    status.innerText = "已刷新";
  } catch (err) {
    status.innerText = err.message;
  }
}

async function saveConfig() {
  const status = document.getElementById("configStatus");
  status.innerText = "保存中...";

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
    status.innerText = "已保存，执行 nereboot 后生效。";
  } catch (err) {
    status.innerText = err.message;
  }
}

async function loadSessions() {
  const list = document.getElementById("sessionList");
  list.innerText = "加载中...";

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
    list.innerText = err.message;
  }
}

function selectSession(sessionId) {
  document.getElementById("sessionInput").value = sessionId;
  loadSessionMessages();
  loadRelationshipState();
}

async function loadSessionMessages() {
  const sessionId = getSessionId();
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
    addMessage("bot", err.message);
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
  status.innerText = "加载中...";

  try {
    const data = await requestJson(
      `/relationship/state?session_id=${encodeURIComponent(getSessionId())}`,
      undefined,
      "加载失败："
    );
    renderRelationshipState(data);
    status.innerText = "已刷新";
  } catch (err) {
    status.innerText = err.message;
  }
}

async function resetRelationshipState() {
  const sessionId = getSessionId();

  if (!confirm(`确定重置 ${sessionId} 的关系状态吗？`)) {
    return;
  }

  const status = document.getElementById("relationshipStatus");
  status.innerText = "重置中...";

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
    status.innerText = "已重置";
  } catch (err) {
    status.innerText = err.message;
  }
}

async function setRelationshipStagePreset(presetKey) {
  const preset = relationshipStagePresets[presetKey];
  const status = document.getElementById("relationshipStatus");

  if (!preset) {
    status.innerText = "未知关系阶段预设";
    return;
  }

  status.innerText = "设置中...";

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
    status.innerText = "已设置";
  } catch (err) {
    status.innerText = err.message;
  }
}

async function confirmCandidate() {
  const status = document.getElementById("candidateStatus");

  if (!lastCandidate || !lastCandidate.content) {
    status.innerText = "没有可确认的候选记忆";
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
    status.innerText = `${data.message || "确认完成"}${duplicateText}`;
    lastCandidate = null;
    renderCandidate();
    loadMemories();
  } catch (err) {
    status.innerText = err.message;
  }
}

function clearCandidate() {
  lastCandidate = null;
  renderCandidate();
  document.getElementById("candidateStatus").innerText = "已忽略";
}

async function loadMemories() {
  const list = document.getElementById("memoryList");
  list.innerText = "加载中...";

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
    list.innerText = err.message;
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

function bindStaticActions() {
  document.getElementById("sendBtn").addEventListener("click", sendMessage);
  document.getElementById("loadSessionMessagesBtn").addEventListener("click", loadSessionMessages);
  document.getElementById("clearSessionBtn").addEventListener("click", clearSession);
  document.getElementById("loadSessionsBtn").addEventListener("click", loadSessions);
  document.getElementById("saveAdminTokenBtn").addEventListener("click", saveAdminToken);
  document.getElementById("clearAdminTokenBtn").addEventListener("click", clearAdminToken);
  document.getElementById("loadConfigBtn").addEventListener("click", loadConfig);
  document.getElementById("saveConfigBtn").addEventListener("click", saveConfig);
  document.getElementById("loadStatsSummaryBtn").addEventListener("click", loadStatsSummary);
  document.getElementById("generateProactiveCandidateBtn").addEventListener("click", generateProactiveCandidate);
  document.getElementById("loadProactiveCandidatesBtn").addEventListener("click", loadProactiveCandidates);
  document.getElementById("loadProactiveConfigBtn").addEventListener("click", loadProactiveConfig);
  document.getElementById("saveProactiveConfigBtn").addEventListener("click", saveProactiveConfig);
  document.getElementById("proactiveAllowedHashesInput").addEventListener("input", function () {
    this.dataset.dirty = "true";
  });
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

bindStaticActions();
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
