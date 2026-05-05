import { getAdminHeaders, getAdminToken, requestJson } from "./api.js";
import { clearChildren, setBusyButton } from "./dom.js";
import { loadProactiveCandidates } from "./proactiveCandidates.js";
import { renderProactiveChecks, loadProactiveStatus } from "./proactiveStatus.js";

let lastEvents = [];

function currentEventPlatformFilter() {
  return document.getElementById("proactiveEventPlatformFilter")?.value || "";
}

function matchesPlatformFilter(platform, filterValue) {
  return !filterValue || String(platform || "").toLowerCase() === filterValue;
}

function proactiveReasonText(reason) {
  const text = String(reason || "");
  const lower = text.toLowerCase();
  if (!text) return "-";
  if (lower.includes("random probability missed")) return "随机概率未命中";
  if (lower.includes("pending candidate exists")) return "已有待处理候选";
  if (lower.includes("latest qq target is not whitelisted")) return "最近 QQ 目标未允许";
  if (lower.includes("latest wx target is not allowed")) return "最近微信目标未通过权限校验";
  if (lower.includes("no auto target found")) return "没有可用主动目标";
  if (lower.includes("outside active window")) return "不在允许时间段";
  if (lower.includes("recent chat exists") || lower.includes("user message seen")) return "最近刚聊过";
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
  lastEvents = events || [];
  const list = document.getElementById("proactiveEventList");
  const items = lastEvents.filter((event) => matchesPlatformFilter(event.platform, currentEventPlatformFilter()));
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
  tag.textContent = `${String(event.platform || "-").toUpperCase()} · ${event.event_type || "-"}`;

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

  result.innerHTML = "";

  const panel = document.createElement("div");
  panel.style.padding = "10px";
  panel.style.background = "#f9f9f9";
  panel.style.border = "1px solid #ddd";
  panel.style.borderRadius = "4px";
  panel.style.marginTop = "8px";

  const actionLabel = proactiveRunActionLabel(data.action);
  const targetLabel = data.target_label ? `${String(data.platform || "").toUpperCase()} / ${data.target_label}` : "无特定目标";
  const reasonText = data.reason || "无";
  const scopeLabel = data.auto_scheduler_scope_label || "QQ-first";
  const scopeSummary = data.auto_scheduler_summary || "自动调度当前按 QQ-first 收口。";

  let suggestion = "请等待下次自动调度。";
  if (data.action === "failed") suggestion = "检查网络日志，或确认目标平台的服务桥接是否在线。";
  if (data.action === "skipped") suggestion = "由于冷却、频率或时间窗限制未发送。如需强发，可勾选“忽略XXX规则”再次执行。";
  if (data.action === "dry_run_ok") suggestion = "演习通过，说明当前收口范围内的调度与发送链路可继续观察；不要据此认定 WX auto 已完成平台化。";
  if (data.action === "generated_pending") suggestion = "已生成在“待处理候选”区，可去手动点击发送测试。";

  panel.innerHTML = `
    <div style="margin-bottom: 6px;"><strong>📌 当前收口：</strong>${scopeLabel}</div>
    <div style="margin-bottom: 6px;"><strong>🎯 本次目标：</strong>${targetLabel}</div>
    <div style="margin-bottom: 6px;"><strong>🚦 执行结果：</strong>${actionLabel} <span style="color:#888;font-size:0.9em;">(dry_run_only: ${data.dry_run_only})</span></div>
    <div style="margin-bottom: 6px;"><strong>🛑 详细/阻塞：</strong>${reasonText}</div>
    <div style="margin-bottom: 6px;"><strong>🧭 能力边界：</strong>${scopeSummary}</div>
    <div style="color: #444; font-size: 0.95em; border-top: 1px dashed #ccc; padding-top: 6px; margin-top: 6px;"><strong>💡 下一步建议：</strong>${suggestion}</div>
  `;

  result.appendChild(panel);

  if (Array.isArray(data.checks)) {
    renderProactiveChecks(data.checks);
  }
}

export function rerenderProactiveEventViews() {
  renderProactiveEvents(lastEvents);
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

  status.textContent = "手动执行自动调度检查中...";
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
    status.textContent = `手动自动调度检查：${proactiveRunActionLabel(data.action)}`;
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
