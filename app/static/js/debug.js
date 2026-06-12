import { getAdminHeaders, requestJson } from "./api.js";
import { clearChildren, createElement, setOptionalText, truncateText } from "./dom.js";

function readDebugFilters() {
  const params = new URLSearchParams();
  const module = document.getElementById("debugModuleInput")?.value.trim() || "";
  const event = document.getElementById("debugEventInput")?.value.trim() || "";
  const traceId = document.getElementById("debugTraceInput")?.value.trim() || "";
  const limit = document.getElementById("debugLimitInput")?.value.trim() || "100";

  params.set("limit", limit);
  if (module) {
    params.set("module", module);
  }
  if (event) {
    params.set("event", event);
  }
  if (traceId) {
    params.set("trace_id", traceId);
  }
  return params;
}

function eventStateClass(event) {
  if (event.level === "error" || event.success === false) {
    return "error";
  }
  if (event.skipped === true) {
    return "skipped";
  }
  if (event.success === true) {
    return "success";
  }
  return "";
}

function compactMetadata(metadata) {
  const entries = Object.entries(metadata || {})
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .slice(0, 8);
  if (entries.length === 0) {
    return "-";
  }
  return entries
    .map(([key, value]) => {
      const text = typeof value === "object" ? JSON.stringify(value) : String(value);
      return `${key}=${truncateText(text, 80)}`;
    })
    .join(" · ");
}

function levelLabel(level) {
  const labels = {
    ok: "正常",
    warn: "注意",
    error: "异常",
    info: "信息",
  };
  return labels[level] || level || "信息";
}

function createTextList(items) {
  const list = createElement("div", "diagnosis-list");
  const values = (items || []).filter(Boolean);
  if (values.length === 0) {
    list.appendChild(createElement("div", "", "-"));
    return list;
  }
  for (const item of values) {
    list.appendChild(createElement("div", "", `- ${item}`));
  }
  return list;
}

export function renderDebugDiagnosis(diagnosis) {
  const overallBox = document.getElementById("debugDiagnosisOverall");
  const cardsBox = document.getElementById("debugDiagnosisCards");
  if (!overallBox || !cardsBox) {
    return;
  }

  const overall = diagnosis?.overall || {};
  const overallLevel = overall.level || "info";
  overallBox.className = `diagnosis-overall ${overallLevel}`;

  let priorityCard = null;
  for (const card of diagnosis?.cards || []) {
    if (card.level === "error") {
      priorityCard = card;
      break;
    }
  }
  if (!priorityCard) {
    for (const card of diagnosis?.cards || []) {
      if (card.level === "warn") {
        priorityCard = card;
        break;
      }
    }
  }

  let suggestionHtml = "";
  if (priorityCard) {
    suggestionHtml = `<div style="margin-top: 8px; font-weight: normal; font-size: 0.9em; padding: 4px; background: var(--milk-surface-soft); border-radius: 4px;">👉 <strong>优先处理建议：</strong>请先查看下方 <b>「${priorityCard.title || priorityCard.id}」</b> 卡片解决 ${levelLabel(priorityCard.level)} 级问题。</div>`;
  } else {
    suggestionHtml = `<div style="margin-top: 8px; font-weight: normal; font-size: 0.9em; color: var(--milk-muted);">✅ 当前系统运转良好，暂无需要紧急处理的异常卡片。</div>`;
  }

  overallBox.innerHTML = `<strong>${overall.title || "诊断未加载"}：</strong>${overall.summary || "-"}${suggestionHtml}`;

  clearChildren(cardsBox);
  for (const card of diagnosis?.cards || []) {
    const level = card.level || "info";
    const item = createElement("div", `diagnosis-card ${level}`);
    const head = createElement("div", "diagnosis-card-head");
    head.append(
      createElement("div", "diagnosis-card-title", card.title || card.id || "-"),
      createElement("span", "tag", levelLabel(level))
    );

    const summary = createElement("div", "diagnosis-summary", card.summary || "-");
    const detailsTitle = createElement("div", "debug-event-meta", "详情");
    const details = createTextList(card.details || []);
    const suggestionsTitle = createElement("div", "debug-event-meta", "建议");
    const suggestions = createTextList(card.suggestions || []);
    item.append(head, summary, detailsTitle, details, suggestionsTitle, suggestions);
    cardsBox.appendChild(item);
  }
}

export async function loadDebugDiagnose() {
  const status = document.getElementById("debugDiagnosisStatus");
  if (status) {
    status.textContent = "诊断加载中...";
  }

  try {
    const data = await requestJson(
      "/debug/diagnose",
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载诊断失败："
    );
    renderDebugDiagnosis(data);
    if (status) {
      status.textContent = `已刷新 ${data.generated_at || ""}`.trim();
    }
  } catch (err) {
    if (status) {
      status.textContent = err.message;
    }
  }
}

export function renderDebugSummary(summary) {
  setOptionalText("debugTotalReturned", summary?.total_returned ?? 0);
  setOptionalText("debugLatestEventAt", summary?.latest_event_at || "-");
  setOptionalText("debugErrorCount", summary?.error_count ?? 0);
  setOptionalText("debugProactiveCount", summary?.proactive_count ?? 0);
  setOptionalText("debugPlatformCount", summary?.platform_count ?? 0);
  setOptionalText("debugChatCount", summary?.chat_count ?? 0);
  setOptionalText("debugOpenrouterCount", summary?.openrouter_count ?? 0);
}

export function renderDebugEvents(events) {
  const list = document.getElementById("debugEventList");
  if (!list) {
    return;
  }

  const items = events || [];
  if (items.length === 0) {
    list.textContent = "暂无日志事件";
    return;
  }

  clearChildren(list);
  for (const event of items) {
    const item = createElement("div", `debug-event-item ${eventStateClass(event)}`.trim());

    const head = createElement("div", "debug-event-head");
    for (const text of [
      event.created_at || "-",
      `trace=${event.trace_id || "-"}`,
      `level=${event.level || "info"}`,
    ]) {
      head.appendChild(createElement("span", "tag", text));
    }

    const main = createElement(
      "div",
      "debug-event-main",
      `${event.module || "-"} / ${event.event || "-"}`
    );

    const details = [
      event.action ? `action=${event.action}` : "",
      event.reason ? `reason=${truncateText(event.reason, 160)}` : "",
      event.candidate_id ? `candidate_id=${event.candidate_id}` : "",
      event.target_label ? `target_label=${event.target_label}` : "",
    ].filter(Boolean);

    const detailLine = createElement("div", "debug-event-meta", details.join(" · ") || "-");
    const metadataLine = createElement("div", "debug-event-meta", `metadata: ${compactMetadata(event.metadata)}`);

    item.append(head, main, detailLine, metadataLine);
    list.appendChild(item);
  }
}

export async function loadDebugEvents() {
  const status = document.getElementById("debugStatus");
  if (status) {
    status.textContent = "加载中...";
  }

  try {
    await loadDebugDiagnose();
    const data = await requestJson(
      `/debug/events?${readDebugFilters().toString()}`,
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载日志失败："
    );
    renderDebugSummary(data.summary || {});
    renderDebugEvents(data.events || []);
    if (status) {
      status.textContent = "已刷新";
    }
  } catch (err) {
    if (status) {
      status.textContent = err.message;
    }
  }
}

export function bindDebugEvents() {
  document.getElementById("loadDebugEventsBtn")?.addEventListener("click", loadDebugEvents);
  document.getElementById("loadDebugDiagnoseBtn")?.addEventListener("click", loadDebugDiagnose);
  for (const id of ["debugModuleInput", "debugEventInput", "debugTraceInput", "debugLimitInput"]) {
    document.getElementById(id)?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        loadDebugEvents();
      }
    });
  }
}
