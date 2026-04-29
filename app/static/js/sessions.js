import { clearChildren } from "./dom.js";
import { getAdminHeaders, requestJson } from "./api.js";
import { setActivePanel } from "./layout.js";
import {
  addMessage,
  getSessionId,
  resetMessages,
  updateCurrentSessionStatus,
} from "./chat.js";
import { loadRelationshipState } from "./relationship.js";

export function renderSessions(sessions) {
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

export async function loadSessions() {
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

export function selectSession(sessionId) {
  document.getElementById("sessionInput").value = sessionId;
  updateCurrentSessionStatus(sessionId);
  loadSessionMessages();
  loadRelationshipState();
  setActivePanel("chatPanel");
}

export async function loadSessionMessages() {
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

export async function clearSession() {
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

export function bindSessionEvents() {
  document.getElementById("loadSessionMessagesBtn").addEventListener("click", loadSessionMessages);
  document.getElementById("clearSessionBtn").addEventListener("click", clearSession);
  document.getElementById("loadSessionsBtn").addEventListener("click", loadSessions);
}
