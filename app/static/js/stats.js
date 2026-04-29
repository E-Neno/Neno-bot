import { getAdminHeaders, getAdminToken, requestJson } from "./api.js";

function setStatsText(id, value) {
  document.getElementById(id).textContent = value ?? "-";
}

export function renderStatsSummary(summary) {
  setStatsText("statsToday", summary.today_messages);
  setStatsText("stats24h", summary.last_24h_messages);
  setStatsText("statsErrors", summary.last_24h_errors);
  setStatsText("statsLatency", `${summary.avg_latency_ms_24h || 0} ms`);
  setStatsText("statsLastMessage", summary.last_message_at || "-");
  setStatsText("statsLastQq", summary.last_qq_message_at || "-");
  setStatsText("statsBackend", summary.backend_ok ? "正常" : "异常");
  setStatsText("statsOpenClaw", summary.openclaw_gateway_maybe_online ? "近期有 QQ" : "无近期 QQ");
  setStatsText("statsModel", summary.current_model || "-");
}

export async function loadStatsSummary() {
  const status = document.getElementById("statsStatus");
  const token = getAdminToken();

  if (!token) {
    status.textContent = "设置 Admin Token 后可刷新状态";
    return;
  }

  status.textContent = "加载中...";

  try {
    const data = await requestJson(
      "/stats/summary",
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载失败："
    );
    renderStatsSummary(data.summary || {});
    status.textContent = "已刷新";
  } catch (err) {
    status.textContent = err.message;
  }
}

export function bindStatsEvents() {
  document.getElementById("loadStatsSummaryBtn").addEventListener("click", loadStatsSummary);
}
