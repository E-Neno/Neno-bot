import { getAdminHeaders, getAdminToken, requestJson } from "./api.js";
import { clearChildren, setBusyButton } from "./dom.js";
import { loadProactiveCandidates } from "./proactiveCandidates.js";
import { renderProactiveChecks, loadProactiveStatus } from "./proactiveStatus.js";

function proactiveReasonText(reason) {
  const text = String(reason || "");
  const lower = text.toLowerCase();
  if (!text) return "-";
  if (lower.includes("random probability missed")) return "随机概率未命中";
  if (lower.includes("pending candidate exists") || lower.includes("pending qq candidate exists")) return "已有待处理候选";
  if (lower.includes("latest qq target is not whitelisted")) return "最近 QQ 目标未允许";
  if (lower.includes("outside active window")) return "不在允许时间段";
  if (lower.includes("recent chat exists") || lower.includes("qq user message seen") || lower.includes("user message seen")) return "最近刚聊过";
  if (lower.includes("daily limit reached") || lower.includes("daily sent limit reached")) return "今日已达上限";
  if (lower.includes("min interval not reached") || lower.includes("last sent is within")) return "距离上次主动消息还不够久";
  return text;
}

function proactiveEventStateClass(event) {
  if (event.success === false) return "failed";
  if (event.skipped === true) return "dismissed";
  if (event.success === true) return "sent";
  return "dismissed";
}

export function renderProactiveEvents(events) {
  const list = document.getElementById("proactiveEventList");
  const items = events || [];
  if (!list) {
    return;
  }
  if (items.length === 0) {
    list.textContent = "暂无调度事件";
    return;
  }

  clearChildren(list);
  for (const event of items) {
    list.appendChild(createProactiveEventItem(event));
  }
}

function createProactiveEventItem(event) {
  const item = document.createElement("div");
  item.className = "candidate-item";

  const tag = document.createElement("div");
  tag.className = `tag ${proactiveEventStateClass(event)}`;
  tag.textContent = event.event_type || "-";

  const action = document.createElement("div");
  action.className = "candidate-content";
  action.textContent = event.action || "-";

  const meta = document.createElement("div");
  meta.className = "candidate-meta";
  meta.textContent = [
    event.created_at || "-",
    `candidate_id=${event.candidate_id ?? "-"}`,
    `target=${event.target_label || "-"}`,
  ].join(" · ");

  const reason = document.createElement("div");
  reason.className = "candidate-meta";
  reason.textContent = proactiveReasonText(event.reason);

  item.append(tag, action, meta, reason);
  return item;
}

export async function loadProactiveEvents(triggerButton) {
  const list = document.getElementById("proactiveEventList");
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
      "/proactive/events?limit=30",
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载时间线失败："
    );
    renderProactiveEvents(data.events || []);
    if (status) {
      status.textContent = "调度时间线已刷新";
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

function checkboxValue(id) {
  return document.getElementById(id)?.checked === true;
}

function proactiveRunActionLabel(action) {
  if (action === "generated_pending") return "已生成 pending 候选";
  if (action === "dry_run_ok") return "dry_run 通过";
  if (action === "observed") return "已观察";
  if (action === "skipped") return "已跳过";
  if (action === "failed") return "失败";
  return action || "-";
}

function renderProactiveRunOnceResult(data) {
  const result = document.getElementById("proactiveRunOnceResult");
  if (!result) {
    return;
  }

  const parts = [
    proactiveRunActionLabel(data.action),
    data.reason || "",
    data.candidate_id ? `candidate_id=${data.candidate_id}` : "",
    data.dry_run_only ? "dry_run_only=true" : "dry_run_only=false",
  ].filter(Boolean);
  result.textContent = parts.join(" · ");
  if (Array.isArray(data.checks)) {
    renderProactiveChecks(data.checks);
  }
}

export async function runProactiveOnce(triggerButton) {
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!token) {
    status.textContent = "需要 Admin Token";
    resetButton();
    return;
  }

  const payload = {
    ignore_random: checkboxValue("proactiveRunIgnoreRandomInput"),
    ignore_recent_chat: checkboxValue("proactiveRunIgnoreRecentChatInput"),
    ignore_active_window: checkboxValue("proactiveRunIgnoreActiveWindowInput"),
    force: checkboxValue("proactiveRunForceInput"),
    dry_run_only: checkboxValue("proactiveRunDryRunOnlyInput"),
  };

  status.textContent = "手动执行自动调度中...";
  try {
    const data = await requestJson(
      "/proactive/run-once",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify(payload),
      },
      "执行失败："
    );
    renderProactiveRunOnceResult(data);
    status.textContent = `手动自动调度：${proactiveRunActionLabel(data.action)}`;
    loadProactiveCandidates();
    loadProactiveStatus();
    loadProactiveEvents();
  } catch (err) {
    status.textContent = err.message;
    const result = document.getElementById("proactiveRunOnceResult");
    if (result) {
      result.textContent = err.message;
    }
  } finally {
    resetButton();
  }
}
