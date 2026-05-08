import { clearChildren } from "./dom.js";
import { getAdminHeaders, requestJson } from "./api.js";
import { setActivePanel } from "./layout.js";
import {
  addMessage,
  clearChatDebugState,
  getSessionId,
  hideContextMenu,
  loadCurrentSessionDebug,
  resetMessages,
  setMessages,
  showChatEmptyState,
  showContextMenu,
  updateCurrentSessionStatus,
} from "./chat.js";
import { clearRelationshipState, loadRelationshipState } from "./relationship.js";

let cachedSessions = [];

function setSessionStatus(message) {
  const status = document.getElementById("chatPreviewStatus");
  if (status) {
    status.textContent = message;
  }
}

function applyEmptySessionState(message = "当前没有可用会话。") {
  document.getElementById("sessionInput").value = "";
  updateCurrentSessionStatus("无会话");
  showChatEmptyState("当前没有可用会话，你可以输入新的 session_id 开始测试。");
  clearChatDebugState({
    previewStatus: message,
    sessionDebugStatus: "当前没有可用 session。",
  });
  clearRelationshipState("暂无会话");
}

async function deleteSessionById(sessionId) {
  const currentSessionId = getSessionId();
  const sessionsBeforeDelete = [...cachedSessions];
  const fallbackSession = sessionsBeforeDelete.find((item) => item.session_id !== sessionId) || null;

  await requestJson(
    "/session/clear",
    {
      method: "POST",
      headers: getAdminHeaders(),
      body: JSON.stringify({ session_id: sessionId }),
    },
    "删除会话失败："
  );

  await loadSessions();

  if (currentSessionId !== sessionId) {
    setSessionStatus(`已删除会话 ${sessionId}。`);
    return;
  }

  if (fallbackSession?.session_id) {
    setSessionStatus(`已删除会话 ${sessionId}，已切换到 ${fallbackSession.session_id}。`);
    selectSession(fallbackSession.session_id);
    return;
  }

  applyEmptySessionState("已删除最后一个会话；当前没有可用会话。");
}

export function renderSessions(sessions) {
  const list = document.getElementById("sessionList");
  cachedSessions = Array.isArray(sessions) ? sessions : [];

  if (cachedSessions.length === 0) {
    list.textContent = "暂无会话";
    return;
  }

  clearChildren(list);

  for (const session of cachedSessions) {
    const item = document.createElement("div");
    item.className = "session-item";
    item.dataset.sessionId = session.session_id || "";
    item.addEventListener("contextmenu", (event) => {
      if (!session.session_id) {
        return;
      }
      showContextMenu(event, [
        {
          label: "删除整个会话",
          className: "danger",
          onClick: async () => {
            if (!confirm(`将删除该会话下的全部消息记录，此操作不可恢复。\n\n会话：${session.session_id}`)) {
              return;
            }
            await deleteSessionById(session.session_id);
          },
        },
      ]);
    });

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
  hideContextMenu();
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
    return data.sessions || [];
  } catch (err) {
    cachedSessions = [];
    list.textContent = err.message;
    return [];
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

    const messages = (data.messages || []).filter(
      (msg) => msg.role === "user" || msg.role === "assistant"
    );

    if (messages.length === 0) {
      setMessages([]);
      await loadCurrentSessionDebug({ silent: true });
      return;
    }

    setMessages(messages);
    await loadCurrentSessionDebug({ silent: true });
  } catch (err) {
    addMessage("assistant", `加载会话 ${sessionId} 失败：${err.message}`);
  }
}

export async function clearSession() {
  const sessionId = getSessionId();

  if (!confirm(`确定清空会话 ${sessionId} 的聊天记录吗？`)) {
    return;
  }

  try {
    await deleteSessionById(sessionId);
  } catch (err) {
    addMessage("assistant", err.message);
  }
}

export function bindSessionEvents() {
  document.getElementById("loadSessionMessagesBtn").addEventListener("click", loadSessionMessages);
  document.getElementById("clearSessionBtn").addEventListener("click", clearSession);
  document.getElementById("loadSessionsBtn").addEventListener("click", loadSessions);
}
