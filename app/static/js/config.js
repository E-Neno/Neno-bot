import { appendConfigLine, clearChildren } from "./dom.js";
import {
  clearAdminToken as clearStoredAdminToken,
  getAdminHeaders,
  getAdminToken,
  requestJson,
  saveAdminToken as saveStoredAdminToken,
  updateAdminTokenStatus,
} from "./api.js";

export { getAdminHeaders, getAdminToken, updateAdminTokenStatus };

export function saveAdminToken() {
  saveStoredAdminToken();
}

export function clearAdminToken() {
  clearStoredAdminToken();
}

export async function loadConfig() {
  const box = document.getElementById("configBox");
  const status = document.getElementById("configStatus");
  box.textContent = "加载中...";
  status.textContent = "";

  try {
    const data = await requestJson("/config", undefined, "加载失败：");
    clearChildren(box);
    appendConfigLine(box, "chat_model", data.chat_model);
    appendConfigLine(box, "memory_model", data.memory_model);
    appendConfigLine(box, "history_token_limit", data.history_token_limit);
    appendConfigLine(box, "memory_limit", data.memory_limit);
    document.getElementById("chatModelInput").value = data.chat_model || "";
    document.getElementById("memoryModelInput").value = data.memory_model || "";
    document.getElementById("historyTokenLimitInput").value = data.history_token_limit ?? "";
    document.getElementById("memoryLimitInput").value = data.memory_limit ?? "";
  } catch (err) {
    box.textContent = err.message;
  }
}

export async function saveConfig() {
  const status = document.getElementById("configStatus");
  status.textContent = "保存中...";

  const payload = {
    chat_model: document.getElementById("chatModelInput").value,
    memory_model: document.getElementById("memoryModelInput").value,
    history_token_limit: Number(document.getElementById("historyTokenLimitInput").value),
    memory_limit: Number(document.getElementById("memoryLimitInput").value),
  };

  if (!payload.chat_model.trim()) {
    delete payload.chat_model;
  }
  if (!payload.memory_model.trim()) {
    delete payload.memory_model;
  }
  if (Number.isNaN(payload.history_token_limit)) {
    delete payload.history_token_limit;
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

export function bindConfigEvents(options = {}) {
  document.getElementById("saveAdminTokenBtn").addEventListener("click", () => {
    saveAdminToken();
    options.onTokenSaved?.();
  });
  document.getElementById("clearAdminTokenBtn").addEventListener("click", () => {
    clearAdminToken();
    options.onTokenCleared?.();
  });
  document.getElementById("loadConfigBtn").addEventListener("click", loadConfig);
  document.getElementById("saveConfigBtn").addEventListener("click", saveConfig);
}
