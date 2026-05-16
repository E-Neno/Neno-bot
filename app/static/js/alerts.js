import { getAdminHeaders, requestJson } from "./api.js";

const POLL_INTERVAL_MS = 30000;
const TOAST_DURATION_MS = 8000;

let lastAlertId = parseInt(localStorage.getItem("neno_last_alert_id") || "0", 10);
let pollTimer = null;

function createToastContainer() {
  const container = document.createElement("div");
  container.id = "criticalAlertContainer";
  container.setAttribute("role", "status");
  container.setAttribute("aria-live", "polite");
  document.body.appendChild(container);
  return container;
}

function showToast(event) {
  const container = document.getElementById("criticalAlertContainer") || createToastContainer();

  const toast = document.createElement("div");
  toast.className = "critical-alert-toast";

  const module = event.module || "-";
  const eventName = event.event || "-";
  const reason = event.reason || "";
  const createdAt = event.created_at || "";

  toast.innerHTML = `
    <div class="critical-alert-toast-icon">&#9888;</div>
    <div class="critical-alert-toast-body">
      <div class="critical-alert-toast-title">${module} / ${eventName}</div>
      ${reason ? `<div class="critical-alert-toast-reason">${reason}</div>` : ""}
      <div class="critical-alert-toast-time">${createdAt}</div>
    </div>
    <button class="critical-alert-toast-close" aria-label="关闭">&times;</button>
  `;

  const closeBtn = toast.querySelector(".critical-alert-toast-close");
  closeBtn.addEventListener("click", () => {
    toast.classList.add("critical-alert-toast-hiding");
    toast.addEventListener("transitionend", () => toast.remove());
  });

  container.appendChild(toast);

  setTimeout(() => {
    if (toast.parentNode) {
      toast.classList.add("critical-alert-toast-hiding");
      toast.addEventListener("transitionend", () => toast.remove());
    }
  }, TOAST_DURATION_MS);
}

async function pollAlerts() {
  try {
    const data = await requestJson(
      `/debug/alerts?after_id=${lastAlertId}`,
      { method: "GET", headers: getAdminHeaders() },
      "加载告警失败："
    );

    const events = data.events || [];
    for (const event of events) {
      const id = parseInt(event.id, 10);
      if (id > lastAlertId) {
        lastAlertId = id;
      }
      showToast(event);
    }

    if (events.length > 0) {
      localStorage.setItem("neno_last_alert_id", String(lastAlertId));
    }
  } catch {
    // silent — don't spam the user for polling failures
  }
}

export function startAlertPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(pollAlerts, POLL_INTERVAL_MS);
}

export function stopAlertPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}
