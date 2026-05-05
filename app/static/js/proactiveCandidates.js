import { getAdminHeaders, getAdminToken, requestJson } from "./api.js";
import { loadDebugDiagnose } from "./debug.js";
import { clearChildren, setBusyButton } from "./dom.js";
import { loadProactiveStatus } from "./proactiveStatus.js";
import { loadProactiveEvents } from "./proactiveTimeline.js";

const candidateActionStates = new Map();

function normalizeCandidateInput(candidateOrId) {
  if (candidateOrId && typeof candidateOrId === "object") {
    return candidateOrId;
  }
  return { id: candidateOrId };
}

function candidateActionId(candidateOrId) {
  const candidate = normalizeCandidateInput(candidateOrId);
  return candidate.id === undefined || candidate.id === null ? "" : String(candidate.id);
}

function isCandidateAlreadyHandled(candidateOrId) {
  const candidate = normalizeCandidateInput(candidateOrId);
  return candidate.status !== undefined && candidate.status !== "pending";
}

function platformActionLabel(platform) {
  return String(platform || "").trim().toUpperCase() || "目标";
}

function candidateActionButtonText(action, platform = "") {
  const label = platformActionLabel(platform);
  if (action === "dry-run") return `测试发送 ${label}`;
  if (action === "send") return `真实发送 ${label}`;
  if (action === "dismiss") return "丢弃";
  return "";
}

function setCandidateActionState(candidateOrId, state) {
  const id = candidateActionId(candidateOrId);
  if (!id) {
    return;
  }
  if (state) {
    candidateActionStates.set(id, state);
  } else {
    candidateActionStates.delete(id);
  }
  updateRenderedCandidateActionRows(id);
}

function updateRenderedCandidateActionRows(id) {
  for (const row of document.querySelectorAll("[data-proactive-candidate-id]")) {
    if (row.dataset.proactiveCandidateId === id) {
      applyCandidateActionState(row, id);
    }
  }
}

function applyCandidateActionState(row, id) {
  const state = candidateActionStates.get(String(id));
  const platform = row.dataset.proactiveCandidatePlatform || "";
  for (const button of row.querySelectorAll("button")) {
    button.disabled = state?.busy === true;
    const label = candidateActionButtonText(button.dataset.candidateAction, platform);
    if (label) {
      button.textContent = label;
    }
    if (state?.busy === true && state.activeAction === button.dataset.candidateAction) {
      button.textContent = state.buttonText || state.message || "处理中...";
    }
  }

  let statusText = row.querySelector(".candidate-action-status");
  if (!state?.message) {
    statusText?.remove();
    return;
  }
  if (!statusText) {
    statusText = document.createElement("span");
    statusText.className = "candidate-state-text candidate-action-status";
    row.appendChild(statusText);
  }
  statusText.textContent = state.message;
}

function candidateAlreadyHandledMessage() {
  return "该候选已处理，不能重复发送";
}

function isAlreadyHandledError(err) {
  const text = String(err?.message || "").toLowerCase();
  return text.includes("only pending candidates can be sent") || text.includes("candidate is not pending");
}

function sendFailureMessage(err) {
  if (isAlreadyHandledError(err)) {
    return candidateAlreadyHandledMessage();
  }
  const reason = err?.message || "未知错误";
  if (String(reason).startsWith("发送失败：")) {
    return reason;
  }
  return `发送失败：${reason}`;
}

async function refreshAfterCandidateAction() {
  await Promise.allSettled([
    loadProactiveCandidates(),
    loadProactiveStatus(),
    loadProactiveEvents(),
    loadDebugDiagnose(),
  ]);
}

export function renderProactiveCandidates(candidates) {
  const list = document.getElementById("proactiveCandidateList");
  const historyList = document.getElementById("proactiveHistoryList");
  const items = candidates || [];
  const pending = items.filter((candidate) => candidate.status === "pending");
  const history = sortProactiveHistory(
    items.filter((candidate) => candidate.status !== "pending")
  );
  const visibleHistory = history.slice(0, 5);

  renderProactiveCandidateList(list, pending, "暂无 pending 候选");
  renderProactiveCandidateList(historyList, visibleHistory, "暂无历史候选");
  if (historyList && history.length > visibleHistory.length) {
    const note = document.createElement("div");
    note.className = "history-note";
    note.textContent = "仅显示最近 5 条历史";
    historyList.appendChild(note);
  }
}

export function renderProactiveTargets(targets) {
  const list = document.getElementById("proactiveTargetList");
  const items = targets || [];
  if (!list) {
    return;
  }
  if (items.length === 0) {
    list.textContent = "暂无主动目标。请先通过 QQ 或 WX 私聊给机器人发一条消息。";
    return;
  }

  clearChildren(list);
  const title = document.createElement("div");
  title.className = "candidate-meta";
  title.textContent = "最近主动目标";
  list.appendChild(title);
  for (const target of items.slice(0, 5)) {
    list.appendChild(createProactiveTargetItem(target));
  }
}

function createProactiveTargetItem(target) {
  const item = document.createElement("div");
  item.className = "candidate-item";

  const tag = document.createElement("div");
  tag.className = `tag ${target.is_allowed ? "sent" : "failed"}`;
  tag.textContent = `${target.platform || "-"} · ${target.is_allowed ? "allowed" : "not allowed"}`;

  const label = document.createElement("div");
  label.className = "candidate-content";
  label.textContent = target.target_label || "-";

  const meta = document.createElement("div");
  meta.className = "candidate-meta";
  meta.textContent = [
    `last_seen_at=${target.last_seen_at || "-"}`,
    `session_id_saved=${target.session_id_saved === true ? "true" : "false"}`,
  ].join(" · ");

  item.append(tag, label, meta);
  return item;
}

function sortProactiveHistory(candidates) {
  return candidates.slice().sort((a, b) => {
    const aTime = Date.parse(a.updated_at || a.sent_at || a.created_at || "");
    const bTime = Date.parse(b.updated_at || b.sent_at || b.created_at || "");
    if (!Number.isNaN(aTime) && !Number.isNaN(bTime) && aTime !== bTime) {
      return bTime - aTime;
    }
    return (b.id || 0) - (a.id || 0);
  });
}

function renderProactiveCandidateList(list, candidates, emptyText) {
  if (!list) {
    return;
  }
  if (!candidates || candidates.length === 0) {
    list.textContent = emptyText;
    return;
  }
  clearChildren(list);
  for (const candidate of candidates) {
    list.appendChild(createProactiveCandidateItem(candidate));
  }
}

function candidateStatusLabel(status) {
  if (status === "pending") return "pending";
  if (status === "sent") return "sent";
  if (status === "dismissed") return "dismissed";
  if (status === "failed") return "failed";
  return status || "-";
}

function createProactiveCandidateItem(candidate) {
  const item = document.createElement("div");
  item.className = "candidate-item";

  const tag = document.createElement("div");
  tag.className = `tag ${candidate.status || ""}`;
  tag.textContent = `${candidate.platform || "-"} · ${candidateStatusLabel(candidate.status)} · ${candidate.target_label || "-"}`;

  const content = document.createElement("div");
  content.className = "candidate-content";
  content.textContent = candidate.message || "";

  const reason = document.createElement("div");
  reason.className = "candidate-meta";
  reason.textContent = candidate.reason || "";

  const meta = document.createElement("div");
  meta.className = "candidate-meta";
  meta.textContent = `id=${candidate.id} · ${candidate.created_at || ""}`;

  const row = document.createElement("div");
  row.className = "row";
  row.dataset.proactiveCandidateId = candidateActionId(candidate);
  row.dataset.proactiveCandidatePlatform = candidate.platform || "";

  if (candidate.status === "pending") {
    if (candidate.platform === "qq" || candidate.platform === "wx") {
      appendSendButtons(row, candidate);
    } else {
      appendCandidateStatusText(row, "暂不支持该平台");
    }
    appendDismissButton(row, candidate);
  } else if (candidate.status === "dismissed") {
    appendCandidateStatusText(row, "已丢弃");
  } else if (candidate.status === "sent") {
    appendCandidateStatusText(row, "已发送");
  } else if (candidate.status === "failed") {
    appendCandidateStatusText(row, "发送失败");
  } else {
    appendCandidateStatusText(row, candidate.status || "未知状态");
  }

  applyCandidateActionState(row, candidateActionId(candidate));
  item.append(tag, content, reason, meta, row);
  return item;
}

function appendCandidateStatusText(row, text) {
  const statusText = document.createElement("span");
  statusText.className = "candidate-state-text";
  statusText.textContent = text;
  row.appendChild(statusText);
}

function appendDismissButton(row, candidate) {
  const dismissButton = document.createElement("button");
  dismissButton.className = candidate.status === "pending" ? "danger" : "";
  dismissButton.dataset.candidateAction = "dismiss";
  dismissButton.textContent = "丢弃";
  dismissButton.addEventListener("click", () => dismissProactiveCandidate(candidate, dismissButton));
  row.appendChild(dismissButton);
}

function appendSendButtons(row, candidate) {
  const platform = candidate.platform || "";
  const label = platformActionLabel(platform);
  const dryRunButton = document.createElement("button");
  dryRunButton.className = "good";
  dryRunButton.dataset.candidateAction = "dry-run";
  dryRunButton.textContent = `测试发送 ${label}`;
  dryRunButton.addEventListener("click", () => dryRunSendCandidate(candidate, dryRunButton));
  row.appendChild(dryRunButton);

  const sendButton = document.createElement("button");
  sendButton.className = "danger";
  sendButton.dataset.candidateAction = "send";
  sendButton.textContent = `真实发送 ${label}`;
  sendButton.addEventListener("click", () => sendCandidate(candidate, sendButton));
  row.appendChild(sendButton);
}

export async function loadProactiveCandidates(triggerButton) {
  const list = document.getElementById("proactiveCandidateList");
  const historyList = document.getElementById("proactiveHistoryList");
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!token) {
    list.textContent = "需要 Admin Token";
    if (historyList) {
      historyList.textContent = "需要 Admin Token";
    }
    status.textContent = "";
    loadProactiveStatus();
    resetButton();
    return;
  }

  list.textContent = "加载中...";
  if (historyList) {
    historyList.textContent = "加载中...";
  }
  status.textContent = "处理中...";

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
    if (historyList) {
      historyList.textContent = err.message;
    }
    status.textContent = err.message;
  } finally {
    resetButton();
  }
}

export async function loadProactiveTargets(triggerButton) {
  const list = document.getElementById("proactiveTargetList");
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!list) {
    resetButton();
    return;
  }
  if (!token) {
    list.textContent = "需要 Admin Token";
    if (status) {
      status.textContent = "";
    }
    resetButton();
    return;
  }

  list.textContent = "加载中...";
  try {
    const data = await requestJson(
      "/proactive/targets",
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载主动目标失败："
    );
    renderProactiveTargets(data.targets || []);
    if (status) {
      status.textContent = "主动目标已刷新";
    }
  } catch (err) {
    list.textContent = err.message;
    if (status) {
      status.textContent = err.message;
    }
  } finally {
    resetButton();
  }
}

export async function generateProactiveCandidate(triggerButton) {
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!token) {
    status.textContent = "需要 Admin Token";
    resetButton();
    return;
  }

  const platform = document.getElementById("proactivePlatformSelect").value;
  const payload = platform ? { platform } : {};
  status.textContent = "处理中...";

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
      status.textContent = "已按自动规则生成候选";
    }
    loadProactiveCandidates();
    loadProactiveStatus();
    loadProactiveTargets();
    loadProactiveEvents();
  } catch (err) {
    status.textContent = err.message;
  } finally {
    resetButton();
  }
}

export async function generateProactiveTestCandidate(triggerButton, force) {
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!token) {
    status.textContent = "需要 Admin Token";
    resetButton();
    return;
  }

  status.textContent = force ? "强制生成测试候选中..." : "生成测试候选中...";

  try {
    const data = await requestJson(
      "/proactive/generate-test",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({ force }),
      },
      "生成测试候选失败："
    );
    const savedText = data.session_id_saved ? "，已保存 session_id" : "";
    status.textContent = `已生成测试候选${savedText}`;
    loadProactiveCandidates();
    loadProactiveStatus();
    loadProactiveTargets();
    loadProactiveEvents();
  } catch (err) {
    if (String(err.message || "").includes("409")) {
      status.textContent = "已有待处理候选，可先发送/丢弃，或使用强制生成测试候选。";
    } else {
      status.textContent = err.message;
    }
  } finally {
    resetButton();
  }
}

export async function dismissProactiveCandidate(candidateOrId, triggerButton) {
  const candidate = normalizeCandidateInput(candidateOrId);
  const id = candidate.id;
  const status = document.getElementById("proactiveCandidateStatus");
  const message = "正在丢弃...";
  setCandidateActionState(candidate, {
    activeAction: "dismiss",
    buttonText: message,
    busy: true,
    message,
  });
  status.textContent = message;

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
    setCandidateActionState(candidate, {
      activeAction: "dismiss",
      busy: true,
      message: "已丢弃",
    });
    await Promise.allSettled([
      loadProactiveCandidates(),
      loadProactiveStatus(),
      loadProactiveEvents(),
    ]);
    setCandidateActionState(candidate, null);
    status.textContent = "已丢弃";
  } catch (err) {
    setCandidateActionState(candidate, {
      activeAction: "dismiss",
      busy: false,
      message: err.message,
    });
    status.textContent = err.message;
  }
}

export async function dryRunSendCandidate(candidateOrId, triggerButton) {
  const candidate = normalizeCandidateInput(candidateOrId);
  const id = candidate.id;
  const platform = platformActionLabel(candidate.platform);
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();

  if (!token) {
    status.textContent = "需要 Admin Token";
    return;
  }

  const message = `测试发送 ${platform} 中...`;
  setCandidateActionState(candidate, {
    activeAction: "dry-run",
    buttonText: message,
    busy: true,
    message,
  });
  status.textContent = message;

  try {
    const data = await requestJson(
      "/proactive/send",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({ id, dry_run: true }),
      },
      "测试失败："
    );
    const successMessage = `dry_run 通过：将发送到 ${data.target_label || "-"}`;
    setCandidateActionState(candidate, {
      activeAction: "dry-run",
      busy: true,
      message: successMessage,
    });
    await Promise.allSettled([
      loadProactiveCandidates(),
      loadProactiveStatus(),
      loadProactiveEvents(),
    ]);
    setCandidateActionState(candidate, {
      activeAction: "dry-run",
      busy: false,
      message: successMessage,
    });
    status.textContent = successMessage;
  } catch (err) {
    setCandidateActionState(candidate, {
      activeAction: "dry-run",
      busy: false,
      message: err.message,
    });
    status.textContent = err.message;
  }
}

export async function dryRunSendQqCandidate(candidateOrId, triggerButton) {
  return dryRunSendCandidate(candidateOrId, triggerButton);
}

export async function sendCandidate(candidateOrId, triggerButton) {
  const candidate = normalizeCandidateInput(candidateOrId);
  const id = candidate.id;
  const platform = platformActionLabel(candidate.platform);
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();

  if (!token) {
    status.textContent = "需要 Admin Token";
    return;
  }

  if (isCandidateAlreadyHandled(candidate)) {
    const message = candidateAlreadyHandledMessage();
    setCandidateActionState(candidate, {
      activeAction: "send",
      busy: false,
      message,
    });
    status.textContent = message;
    return;
  }

  const ok = confirm(`确认发送这条主动消息到 ${platform}？这会真的发出去。`);
  if (!ok) {
    return;
  }

  const sendingMessage = "正在发送...";
  setCandidateActionState(candidate, {
    activeAction: "send",
    buttonText: sendingMessage,
    busy: true,
    message: sendingMessage,
  });
  status.textContent = sendingMessage;

  try {
    await requestJson(
      "/proactive/send",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({ id, dry_run: false }),
      },
      "发送失败："
    );
    setCandidateActionState(candidate, {
      activeAction: "send",
      busy: true,
      message: "发送成功",
    });
    await refreshAfterCandidateAction();
    setCandidateActionState(candidate, null);
    status.textContent = "发送成功";
  } catch (err) {
    const message = sendFailureMessage(err);
    setCandidateActionState(candidate, {
      activeAction: "send",
      busy: false,
      message,
    });
    await refreshAfterCandidateAction();
    status.textContent = message;
  }
}

export async function sendQqCandidate(candidateOrId, triggerButton) {
  return sendCandidate(candidateOrId, triggerButton);
}
