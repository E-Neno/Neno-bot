import { formatErrorDetail } from "./dom.js";

export async function requestJson(url, options, errorPrefix) {
  const res = await fetch(url, options);
  const raw = await res.text();
  let data = {};

  try {
    data = raw ? JSON.parse(raw) : {};
  } catch {
    data = {};
  }

  if (!res.ok) {
    const detail = formatErrorDetail(data.detail || data.error || raw || res.statusText);
    if (res.status === 403) {
      throw new Error(`HTTP ${res.status}: ${detail || "Admin Token 不正确或未配置"}`);
    }
    throw new Error(`${errorPrefix}HTTP ${res.status}: ${detail}`);
  }

  return data;
}

export function getAdminToken() {
  const inputToken = document.getElementById("adminTokenInput")?.value.trim() || "";
  return inputToken || localStorage.getItem("neno_admin_token") || "";
}

export function getAdminHeaders() {
  const token = getAdminToken();
  return {
    "Content-Type": "application/json",
    "X-Admin-Token": token,
  };
}

export function updateAdminTokenStatus() {
  const status = document.getElementById("adminTokenStatus");
  const input = document.getElementById("adminTokenInput");
  const token = localStorage.getItem("neno_admin_token") || "";

  input.value = token;
  status.textContent = token ? "Admin Token 已保存" : "Admin Token 未设置";
}

export function saveAdminToken() {
  const token = document.getElementById("adminTokenInput").value.trim();
  const status = document.getElementById("adminTokenStatus");

  if (!token) {
    localStorage.removeItem("neno_admin_token");
    status.textContent = "Admin Token 未设置";
    return;
  }

  localStorage.setItem("neno_admin_token", token);
  status.textContent = "Admin Token 已保存";
}

export function clearAdminToken() {
  localStorage.removeItem("neno_admin_token");
  document.getElementById("adminTokenInput").value = "";
  document.getElementById("adminTokenStatus").textContent = "Admin Token 已清除";
}
