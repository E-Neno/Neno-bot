import { clearChildren, truncateText } from "./dom.js";
import { requestJson } from "./api.js";
import { updateCurrentSessionStatus as setCurrentSessionStatus } from "./layout.js";

let lastCandidate = null;
let input = null;
let sendBtn = null;
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

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });

  sendBtn.addEventListener("click", sendMessage);
}
