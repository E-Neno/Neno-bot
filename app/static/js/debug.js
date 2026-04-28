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
  for (const id of ["debugModuleInput", "debugEventInput", "debugTraceInput", "debugLimitInput"]) {
    document.getElementById(id)?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        loadDebugEvents();
      }
    });
  }
}
