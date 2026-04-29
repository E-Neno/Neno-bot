import { clearChildren } from "./dom.js";
import { getAdminHeaders, requestJson } from "./api.js";
import {
  clearCandidateMemory,
  getCandidateMemory,
  renderCandidateMemories,
} from "./chat.js";

let onlyActive = false;

export function renderMemories(memories) {
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

export async function confirmCandidateMemory() {
  const status = document.getElementById("candidateStatus");
  const lastCandidate = getCandidateMemory();

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
    clearCandidateMemory();
    loadMemories();
  } catch (err) {
    status.textContent = err.message;
  }
}

export function clearCandidate() {
  clearCandidateMemory();
  document.getElementById("candidateStatus").textContent = "已忽略";
}

export async function loadMemories() {
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

export async function disableMemory(id) {
  await updateMemoryState("/memory/disable", { memory_id: id });
}

export async function enableMemory(id) {
  await updateMemoryState("/memory/enable", { id });
}

export async function deleteMemory(id) {
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

export async function editMemory(id, currentContent, currentType) {
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

export function toggleOnlyActive() {
  onlyActive = !onlyActive;
  loadMemories();
}

export function refreshCandidateMemoryBox() {
  renderCandidateMemories();
}

export function bindMemoryEvents() {
  document.getElementById("confirmCandidateBtn").addEventListener("click", confirmCandidateMemory);
  document.getElementById("clearCandidateBtn").addEventListener("click", clearCandidate);
  document.getElementById("loadMemoriesBtn").addEventListener("click", loadMemories);
  document.getElementById("toggleOnlyActiveBtn").addEventListener("click", toggleOnlyActive);
}
