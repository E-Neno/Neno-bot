import { getAdminHeaders, getAdminToken, requestJson } from "./api.js";
import { clearChildren, setBusyButton, setOptionalText } from "./dom.js";
import { loadProactiveEvents } from "./proactiveTimeline.js";

function formatCheckState(ok) {
  if (ok === true) {
    return "通过";
  }
  if (ok === false) {
    return "未通过";
  }
  return "不参与判断";
}

export function renderProactiveChecks(checks) {
  const list = document.getElementById("proactiveCheckNowChecks");
  if (!list) {
    return;
  }
  if (!checks || checks.length === 0) {
    list.textContent = "没有检查结果";
    return;
  }

  clearChildren(list);
  for (const check of checks) {
    const item = document.createElement("div");
    item.className = "check-item";

    const tag = document.createElement("div");
    const okClass = check.ok === true ? "sent" : check.ok === false ? "failed" : "dismissed";
    tag.className = `tag ${okClass}`;
    tag.textContent = formatCheckState(check.ok);

    const name = document.createElement("div");
    name.className = "check-name";
    name.textContent = check.name || "-";

    const detail = document.createElement("div");
    detail.className = "check-detail";
    detail.textContent = check.detail || "";

    item.append(tag, name, detail);
    list.appendChild(item);
  }
}

export function renderProactiveDecision(data) {
  const canSend = data?.can_send ?? data?.can_send_now?.can_send ?? data?.can_send_now?.boolean;
  const reason = data?.reason ?? data?.can_send_now?.reason ?? "-";
  const scopeLabel = data?.auto_scheduler_scope_label || "QQ-first";
  setOptionalText(
    "proactiveCanSendNow",
    canSend === true
      ? `自动调度规则允许继续判断（当前收口：${scopeLabel}）`
      : `自动调度当前不会发送（当前收口：${scopeLabel}）`
  );
  setOptionalText("proactiveCanSendReason", reason);
  if (Array.isArray(data?.checks)) {
    renderProactiveChecks(data.checks);
  }
}

function renderProactiveRulesSummary(items) {
  const box = document.getElementById("proactiveRulesSummary");
  if (!box) {
    return;
  }
  if (!items || items.length === 0) {
    box.textContent = "规则摘要未加载";
    return;
  }
  box.textContent = items.map((item) => `- ${item}`).join("\n");
}

function renderProactiveLastResult(result) {
  const box = document.getElementById("proactiveLastResult");
  if (!box) {
    return;
  }
  if (!result) {
    box.textContent = "上次检查结果：暂无";
    return;
  }

  const parts = [];
  if (result.action) {
    parts.push(result.action);
  } else if (result.skipped === true) {
    parts.push("已跳过");
  } else if (result.sent === true) {
    parts.push("已发送");
  } else if (result.success === false) {
    parts.push("失败");
  } else {
    parts.push("已检查");
  }
  if (result.reason) {
    parts.push(result.reason);
  }
  if (result.candidate_id) {
    parts.push(`candidate id=${result.candidate_id}`);
  }
  box.textContent = `上次检查结果：${parts.join(" · ")}`;
}

export function renderProactiveAutoStatus(data) {
  const box = document.getElementById("proactiveAutoStatus");
  const config = data.config || {};
  const mode = data.proactive_mode || config.proactive_mode || "off";
  const modeLabel = data.mode_label || mode;
  const modeDescription = data.mode_description || "-";
  const enabled = data.enabled ? "开启" : "关闭";
  const running = data.task_running ? "运行中" : "未运行";
  const lastSent = data.last_sent_at || "-";
  const lastCheck = data.last_check_at || "-";
  const today = data.today_sent_count ?? 0;
  const limit = config.daily_limit ?? "-";
  const autoSend = data.auto_send_enabled ? "开启" : "关闭";
  const autoDryRun = data.auto_send_dry_run ? "开启" : "关闭";
  const requireAllowed = data.auto_send_require_allowed_target ? "是" : "否";
  const autoSentToday = data.auto_sent_today ?? 0;
  const autoSendLimit = data.auto_send_max_per_day ?? "-";
  const scopeLabel = data.auto_scheduler_scope_label || "QQ-first";
  const scopeSummary = data.auto_scheduler_summary || "自动调度当前按 QQ-first 收口。";
  const hardCooldown = data.hard_cooldown_active
    ? `冷却中 / ${data.hard_cooldown_minutes ?? "-"} 分钟`
    : `未触发 / ${data.hard_cooldown_minutes ?? "-"} 分钟`;
  const failurePause = `${data.consecutive_auto_failures ?? 0}/${data.failure_pause_threshold ?? "-"}`;
  const lastAction = data.last_result?.action || (data.last_result?.skipped ? "skipped" : "-");
  const canSendPlatform = data.can_send_now?.platform ? String(data.can_send_now.platform).toUpperCase() : "-";
  const canSendTarget = data.can_send_now?.target_summary?.target_label || "-";
  const targetSummary = Array.isArray(data.latest_targets) && data.latest_targets.length
    ? data.latest_targets
        .map((item) => {
          const parts = [
            String(item.platform || "-").toUpperCase(),
            item.target_label || "-",
          ];
          if (item.platform === "qq") {
            parts.push(item.is_allowed ? "allowed" : "not allowed");
          }
          if (item.platform === "wx" && item.real_user_id_saved === true) {
            parts.push("real_user saved");
          }
          return parts.join(" / ");
        })
        .join(" · ")
    : "暂无";

  if (box) {
    box.innerHTML = "";

    const conclusion = document.createElement("div");
    conclusion.style.marginBottom = "8px";
    conclusion.style.padding = "8px";
    conclusion.style.backgroundColor = data.can_send_now?.can_send ? "rgba(74,150,112,0.16)" : "var(--milk-surface-soft)";
    conclusion.style.borderRadius = "8px";
    conclusion.style.border = data.can_send_now?.can_send ? "1px solid rgba(74,150,112,0.4)" : "1px solid var(--milk-border)";

    const statusText = data.can_send_now?.can_send ? "🟢 当前状态：规则允许继续判断" : "🟡 当前状态：阻塞（暂不调度发送）";
    const reasonText = data.can_send_now?.reason ? `因为：${data.can_send_now.reason}` : "";
    const targetText = canSendTarget !== "-" ? `${canSendPlatform} / ${canSendTarget}` : "无可用目标";

    conclusion.innerHTML = `
      <div style="font-weight: bold; margin-bottom: 4px;">${statusText}</div>
      <div style="margin-bottom: 4px;">📌 当前收口：${scopeLabel}</div>
      <div style="margin-bottom: 4px;">🎯 锁定目标：${targetText}</div>
      <div style="color: var(--milk-muted);">🛑 阻塞原因：${reasonText || "无"}</div>
    `;
    box.appendChild(conclusion);

    const details = document.createElement("div");
    details.style.color = "var(--milk-muted)";
    details.textContent = [
      `能力边界 ${scopeSummary}`,
      `当前模式 ${modeLabel}`,
      modeDescription,
      `自动：${enabled} · ${running}`,
      `今日 ${today}/${limit}`,
      `自动真实发送 ${autoSend}`,
      `自动 dry_run ${autoDryRun}`,
      `自动发送 ${autoSentToday}/${autoSendLimit}`,
      `硬冷却 ${hardCooldown}`,
      `连续失败 ${failurePause}`,
      `目标必须 allowed ${requireAllowed}`,
      `最近目标 ${targetSummary}`,
      `最近自动结果 ${lastAction}`,
      `最近发送 ${lastSent}`,
      `最近检查 ${lastCheck}`,
      `间隔 ${config.check_interval_seconds ?? "-"}s`,
      `时间窗 ${config.active_start || "-"}-${config.active_end || "-"}`,
    ].join(" · ");
    box.appendChild(details);
  }

  setOptionalText("proactiveStatusMode", modeLabel);
  setOptionalText("proactiveStatusEnabled", enabled);
  setOptionalText("proactiveStatusRunning", running);
  setOptionalText("proactiveStatusToday", `${today}/${limit}`);
  setOptionalText("proactiveStatusAutoSend", autoSend);
  setOptionalText("proactiveStatusAutoDryRun", autoDryRun);
  setOptionalText("proactiveStatusAutoSentToday", `${autoSentToday}/${autoSendLimit}`);
  setOptionalText("proactiveStatusHardCooldown", hardCooldown);
  setOptionalText("proactiveStatusFailurePause", failurePause);
  setOptionalText("proactiveStatusAutoRequireAllowed", requireAllowed);
  setOptionalText("proactiveStatusDecisionPlatform", canSendPlatform);
  setOptionalText("proactiveStatusDecisionTarget", canSendTarget);
  setOptionalText("proactiveStatusLatestTargets", targetSummary);
  setOptionalText("proactiveStatusLastSent", lastSent);
  setOptionalText("proactiveStatusLastCheck", lastCheck);
  renderProactiveLastResult(data.last_result);
  renderProactiveRulesSummary(data.next_rules_summary || []);
  renderProactiveDecision(data);
}

export async function loadProactiveStatus() {
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

export async function checkProactiveNow(triggerButton) {
  const status = document.getElementById("proactiveCandidateStatus");
  const token = getAdminToken();
  const resetButton = setBusyButton(triggerButton);

  if (!token) {
    status.textContent = "需要 Admin Token";
    resetButton();
    return;
  }

  status.textContent = "处理中...";
  try {
    const data = await requestJson(
      "/proactive/check-now",
      {
        method: "POST",
        headers: getAdminHeaders(),
      },
      "检查失败："
    );
    renderProactiveDecision(data);
    status.textContent = "自动调度当前判断已刷新";
    loadProactiveEvents();
  } catch (err) {
    status.textContent = err.message;
  } finally {
    resetButton();
  }
}
