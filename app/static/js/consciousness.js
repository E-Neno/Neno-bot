import { getAdminHeaders, requestJson } from "./api.js";
import { clearChildren, setBusyButton, setOptionalText } from "./dom.js";

let _desireInterval = null;

// ── State rendering ───────────────────────────────────────

function renderProgressBar(container, value, max, colorClass) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const bar = document.createElement("div");
  bar.className = "consciousness-progress-track";
  const fill = document.createElement("div");
  fill.className = `consciousness-progress-fill ${colorClass}`;
  fill.style.width = `${pct}%`;
  bar.appendChild(fill);
  container.appendChild(bar);
}

export function renderConsciousnessState(data) {
  const state = data?.state;
  if (!state) {
    setOptionalText("consciousnessStateStatus", data?.message || "consciousness 未初始化");
    return;
  }

  const energy = state.energy || {};
  const mood = state.mood || {};
  const desire = state.desire || {};

  // Energy
  setOptionalText("cEnergyValue", `${(energy.value ?? 0).toFixed(0)}/100`);
  setOptionalText("cEnergyStatus", energy.status || "-");
  setOptionalText("cEnergyDesc", energy.description || "");
  const energyBar = document.getElementById("cEnergyBar");
  if (energyBar) {
    energyBar.innerHTML = "";
    renderProgressBar(energyBar, energy.value ?? 0, 100, "energy");
  }

  // Mood
  setOptionalText("cMoodValue", mood.label || "-");
  setOptionalText("cMoodDesc", mood.description || "");
  setOptionalText("cMoodDetail", `V: ${(mood.valence ?? 0).toFixed(2)} / A: ${(mood.arousal ?? 0).toFixed(2)}`);
  const moodBar = document.getElementById("cMoodBar");
  if (moodBar) {
    moodBar.innerHTML = "";
    const normalizedValence = ((mood.valence ?? 0) + 1) / 2 * 100;
    renderProgressBar(moodBar, normalizedValence, 100, "mood");
  }

  // Desire
  setOptionalText("cDesireValue", `${(desire.value ?? 0).toFixed(0)}/100`);
  setOptionalText("cDesireExpress", desire.last_express_at || "从未表达");
  const desireBar = document.getElementById("cDesireBar");
  if (desireBar) {
    desireBar.innerHTML = "";
    renderProgressBar(desireBar, desire.value ?? 0, 100, "desire");
  }

  // World
  const world = state.world || {};
  const weather = world.weather;
  setOptionalText("cWeatherText", weather ? `${weather.text || "-"} (${weather.condition || "?"})` : "暂无天气数据");
  setOptionalText("cWeatherTemp", weather?.temp != null ? `${weather.temp}°C` : "-");
  setOptionalText("cWeatherRain", weather?.rain ? "有雨" : "无雨");

  const topicsBox = document.getElementById("cHotTopics");
  if (topicsBox) {
    topicsBox.innerHTML = "";
    const topics = world.hot_topics || [];
    if (topics.length === 0) {
      topicsBox.textContent = "暂无热搜";
    } else {
      for (const topic of topics) {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = topic;
        topicsBox.appendChild(tag);
      }
    }
  }
  setOptionalText("cWorldTime", world.time_context || "-");
  setOptionalText("cWorldPerception", world.last_perception_at || "-");

  // Last interaction
  const li = state.last_interaction || {};
  setOptionalText("cLastUser", li.user_id || "无");
  setOptionalText("cLastSummary", li.summary || "无");

  // Experiences
  const expBox = document.getElementById("cExperiences");
  if (expBox) {
    expBox.innerHTML = "";
    const exps = state.today_experiences || [];
    if (exps.length === 0) {
      expBox.textContent = "今天没有经历";
    } else {
      for (const exp of exps) {
        const item = document.createElement("div");
        item.className = "consciousness-exp-item";
        item.textContent = `[${exp.time || "?"}] ${exp.content || ""}`;
        expBox.appendChild(item);
      }
    }
  }

  setOptionalText("cRevision", `#${state.revision ?? "-"}`);
  setOptionalText("cUpdatedAt", state.updated_at || "-");
  setOptionalText("consciousnessStateStatus", "");
}

// ── Events rendering ──────────────────────────────────────

function priorityLabel(p) {
  if (p === 0) return "P0 紧急";
  if (p === 1) return "P1 高";
  if (p === 2) return "P2 普通";
  return "P3 低";
}

function priorityClass(p) {
  if (p === 0) return "failed";
  if (p === 1) return "pending";
  if (p === 2) return "dismissed";
  return "info";
}

export function renderConsciousnessEvents(data) {
  const box = document.getElementById("cEventList");
  if (!box) return;

  const events = data?.events || [];
  if (events.length === 0) {
    box.textContent = "暂无事件";
    return;
  }

  clearChildren(box);
  for (const ev of events) {
    const item = document.createElement("div");
    item.className = "check-item";

    const head = document.createElement("div");
    head.style.display = "flex";
    head.style.gap = "6px";
    head.style.alignItems = "center";
    head.style.marginBottom = "4px";

    const priTag = document.createElement("span");
    priTag.className = `tag ${priorityClass(ev.priority)}`;
    priTag.textContent = priorityLabel(ev.priority);
    head.appendChild(priTag);

    const statusTag = document.createElement("span");
    statusTag.className = `tag ${ev.status === "pending" ? "pending" : ev.status === "expressed" ? "sent" : "dismissed"}`;
    statusTag.textContent = ev.status;
    head.appendChild(statusTag);

    const hash = document.createElement("span");
    hash.className = "check-detail";
    hash.textContent = ev.topic_hash;
    head.appendChild(hash);

    const time = document.createElement("span");
    time.className = "check-detail";
    time.textContent = ev.created_at ? ev.created_at.substring(0, 16) : "";
    time.style.marginLeft = "auto";
    head.appendChild(time);

    const content = document.createElement("div");
    content.className = "check-name";
    content.textContent = ev.content || "(空)";

    const meta = document.createElement("div");
    meta.className = "check-detail";
    const tags = (ev.tags || []).join(", ");
    meta.textContent = `mood: ${ev.mood_impact?.toFixed(2) || "0"}${tags ? " · tags: " + tags : ""}`;

    item.append(head, content, meta);
    box.appendChild(item);
  }
}

// ── Think result rendering ────────────────────────────────

function renderStep1(step) {
  if (!step) return "Step 1 未执行";
  const color = step.result === "proceed" ? "#16a34a" : "#94a3b8";
  return `<div style="padding:8px;border-left:3px solid ${color};margin-bottom:6px">
    <b>结果：</b>${step.result} <span style="color:#64748b">(${step.reason || ""})</span>
  </div>`;
}

function escapeForPre(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function renderStep2(step) {
  if (!step) return "Step 2 未执行（Step 1 skip）";
  const r = step.result || {};
  const color = r.should_share ? "#16a34a" : "#94a3b8";
  return `<div style="padding:8px;border-left:3px solid ${color};margin-bottom:6px">
    <b>should_share：</b>${r.should_share ? "是" : "否"}
    ${r.reason ? `<br><b>理由：</b>${escapeHtml(r.reason)}` : ""}
    ${r.target_user_id ? `<br><b>目标：</b>${escapeHtml(r.target_user_id)}` : ""}
    ${r.urgency ? `<br><b>紧急度：</b>${r.urgency}` : ""}
    <br><span style="color:#64748b;font-size:12px">model: ${escapeHtml(step.model || "-")}</span>
    ${step.raw_response ? `<details style="margin-top:4px"><summary style="cursor:pointer;color:#64748b;font-size:12px">原始响应</summary><pre style="font-size:11px;white-space:pre-wrap;margin-top:4px;padding:6px;background:#f8fafc;border-radius:6px">${escapeForPre(step.raw_response)}</pre></details>` : ""}
  </div>`;
}

function renderStep3(step) {
  if (!step) return "Step 3 未执行（judge said no）";
  const color = step.success ? "#16a34a" : "#dc2626";
  return `<div style="padding:8px;border-left:3px solid ${color};margin-bottom:6px">
    <b>生成结果：</b>${step.success ? "成功" : "失败"}
    <br><b>model：</b>${escapeHtml(step.model || "-")}
    ${step.raw_text ? `<br><b>原始文案：</b>${escapeHtml(step.raw_text)}` : ""}
    ${step.fragments_after_split?.length ? `<br><b>碎片化后（不发送）：</b><div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:4px">${step.fragments_after_split.map((f, i) => `<span class="tag sent">${i + 1}. ${escapeHtml(f)}</span>`).join("")}</div>` : ""}
    <br><span style="color:#64748b;font-size:12px;font-style:italic">will_not_send: true — 仅预览，不实际发送</span>
  </div>`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function renderThinkResult(data) {
  const box = document.getElementById("cThinkResult");
  if (!box) return;

  if (!data || !data.success) {
    box.innerHTML = `<div class="check-item" style="border-left-color:#dc2626">
      <div class="check-name" style="color:#991b1b">执行失败</div>
      <div class="check-detail">${escapeHtml(data?.error || "未知错误")}</div>
    </div>`;
    return;
  }

  const steps = data.steps || {};
  const eventsUsed = data.events_used || [];

  let html = `<div style="margin-bottom:8px;color:#64748b;font-size:12px">trace_id: ${escapeHtml(data.trace_id || "-")} · 使用 ${eventsUsed.length} 个事件</div>`;

  html += `<details open><summary style="cursor:pointer;font-weight:700;margin-bottom:6px">Step 1: 规则过滤</summary>${renderStep1(steps.step1_rule_filter)}</details>`;
  html += `<details open><summary style="cursor:pointer;font-weight:700;margin-bottom:6px">Step 2: LLM 判断</summary>${renderStep2(steps.step2_judge)}</details>`;
  html += `<details open><summary style="cursor:pointer;font-weight:700;margin-bottom:6px">Step 3: LLM 生成</summary>${renderStep3(steps.step3_generate)}</details>`;

  box.innerHTML = html;
}

// ── Actions ───────────────────────────────────────────────

export async function loadConsciousnessState() {
  const token = getAdminHeaders()["X-Admin-Token"];
  if (!token) return;

  try {
    const data = await requestJson(
      "/debug/consciousness/state",
      { method: "GET", headers: getAdminHeaders() },
      "加载意识状态失败："
    );
    renderConsciousnessState(data);
  } catch (err) {
    setOptionalText("consciousnessStateStatus", err.message);
  }
}

export async function loadConsciousnessEvents() {
  const token = getAdminHeaders()["X-Admin-Token"];
  if (!token) return;

  try {
    const data = await requestJson(
      "/debug/consciousness/events",
      { method: "GET", headers: getAdminHeaders() },
      "加载事件失败："
    );
    renderConsciousnessEvents(data);
  } catch (err) {
    setOptionalText("cEventStatus", err.message);
  }
}

async function submitInjectEvent(triggerButton) {
  const contentInput = document.getElementById("cInjectContent");
  const priorityInput = document.getElementById("cInjectPriority");
  const status = document.getElementById("cInjectStatus");
  const resetButton = setBusyButton(triggerButton);

  const content = contentInput?.value.trim();
  if (!content) {
    status.textContent = "请输入事件内容";
    resetButton();
    return;
  }

  status.textContent = "注入中...";
  try {
    const data = await requestJson(
      "/debug/consciousness/inject",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({
          content,
          priority: parseInt(priorityInput?.value || "2", 10),
          tags: ["debug"],
          mood_impact: 0.0,
        }),
      },
      "注入失败："
    );
    if (data.success) {
      status.textContent = `注入成功: ${data.event.topic_hash}`;
      contentInput.value = "";
      loadConsciousnessEvents();
    } else {
      status.textContent = "注入失败";
    }
  } catch (err) {
    status.textContent = err.message;
  } finally {
    resetButton();
  }
}

async function submitThinkCycle(triggerButton) {
  const status = document.getElementById("cThinkStatus");
  const resetButton = setBusyButton(triggerButton, "思考中...");

  status.textContent = "正在执行三步决策（可能需要 10-20 秒）...";
  try {
    const data = await requestJson(
      "/debug/consciousness/think",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({}),
      },
      "思考失败："
    );
    renderThinkResult(data);
    status.textContent = data.success ? `思考完成 (${data.trace_id})` : "思考失败";
  } catch (err) {
    status.textContent = err.message;
  } finally {
    resetButton();
  }
}

// ── Auto-refresh ──────────────────────────────────────────

function startDesireRefresh() {
  stopDesireRefresh();
  _desireInterval = setInterval(() => {
    const panel = document.getElementById("consciousnessPanel");
    if (panel && panel.classList.contains("active")) {
      loadConsciousnessState();
    } else {
      stopDesireRefresh();
    }
  }, 1000);
}

function stopDesireRefresh() {
  if (_desireInterval) {
    clearInterval(_desireInterval);
    _desireInterval = null;
  }
}

export function onConsciousnessPanelActive() {
  loadConsciousnessState();
  loadConsciousnessEvents();
  startDesireRefresh();
}

export function onConsciousnessPanelInactive() {
  stopDesireRefresh();
}

// ── Bind ──────────────────────────────────────────────────

export function bindConsciousnessEvents() {
  const injectBtn = document.getElementById("cInjectBtn");
  if (injectBtn) {
    injectBtn.addEventListener("click", () => submitInjectEvent(injectBtn));
  }

  const thinkBtn = document.getElementById("cThinkBtn");
  if (thinkBtn) {
    thinkBtn.addEventListener("click", () => submitThinkCycle(thinkBtn));
  }

  const refreshBtn = document.getElementById("cRefreshStateBtn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      loadConsciousnessState();
      loadConsciousnessEvents();
    });
  }
}
