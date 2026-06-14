import { getAdminHeaders, requestJson } from "./api.js";
import { clearChildren, setBusyButton, setOptionalText } from "./dom.js";
import { mapWorldSnapshot, ROOM_NAME, ROOM_ORDER, actionLabel, OBJECT_SLOTS, objectFx, autoLayout } from "./worldViewAdapter.js";

let _desireInterval = null;
let _worldLiveInterval = null;
let _worldRoomWidth = 0;
let _lastWorldX = null;
let _latestWorldState = null;
// 手动镜头：null=跟着她；"home"/"outside"=手动摇到家内/外面看（点场景按钮触发）
let _worldFocus = null;

// 镜头要居中到哪个房间索引：手动 focus 优先，否则跟随她的真实位置
function focusRoomIndex(state) {
  if (_worldFocus === "outside") {
    const i = ROOM_ORDER.indexOf("cafe");
    return i >= 0 ? i : state.room;
  }
  if (_worldFocus === "home") {
    return state.outside ? ROOM_ORDER.indexOf("living_room") : state.room;
  }
  return state.room;
}

// 点场景按钮：摇镜头到该组；再点同一个 → 回到跟随她
function setWorldFocus(group) {
  _worldFocus = _worldFocus === group ? null : group;
  if (!_latestWorldState) return;
  layoutWorldStage(_latestWorldState, true);
  const showingOutside = _worldFocus ? _worldFocus === "outside" : _latestWorldState.outside;
  document.getElementById("worldSceneHomeBtn")?.classList.toggle("active", !showingOutside);
  document.getElementById("worldSceneOutBtn")?.classList.toggle("active", showingOutside);
}

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
    <b>结果：</b>${step.result} <span style="color:var(--milk-muted)">(${step.reason || ""})</span>
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
    <br><span style="color:var(--milk-muted);font-size:12px">model: ${escapeHtml(step.model || "-")}</span>
    ${step.raw_response ? `<details style="margin-top:4px"><summary style="cursor:pointer;color:var(--milk-muted);font-size:12px">原始响应</summary><pre style="font-size:11px;white-space:pre-wrap;margin-top:4px;padding:6px;background:var(--milk-surface-muted);border-radius:6px">${escapeForPre(step.raw_response)}</pre></details>` : ""}
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
    <br><span style="color:var(--milk-muted);font-size:12px;font-style:italic">will_not_send: true — 仅预览，不实际发送</span>
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
      <div class="check-name" style="color:var(--milk-red-text)">执行失败</div>
      <div class="check-detail">${escapeHtml(data?.error || "未知错误")}</div>
    </div>`;
    return;
  }

  const steps = data.steps || {};
  const eventsUsed = data.events_used || [];

  let html = `<div style="margin-bottom:8px;color:var(--milk-muted);font-size:12px">trace_id: ${escapeHtml(data.trace_id || "-")} · 使用 ${eventsUsed.length} 个事件</div>`;

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

// ── Phase 3b Preflight ────────────────────────────────────

function renderPreflightResult(data) {
  const box = document.getElementById("cPreflightResult");
  if (!box) return;
  box.innerHTML = "";

  if (!data?.success) {
    box.textContent = "预检请求失败";
    return;
  }

  const d = data.decision || {};
  const rules = data.rules || {};
  const intent = data.next_queued_intent;
  const target = data.target_lookup;

  // Decision header
  const statusColor = d.ready_to_send ? "var(--green)" :
    d.status === "disabled" || d.status === "whitelist_empty" ? "var(--milk-muted)" :
    "var(--red)";

  const header = document.createElement("div");
  header.style.fontWeight = "600";
  header.style.color = statusColor;
  header.style.marginBottom = "8px";
  header.textContent = d.ready_to_send
    ? `✓ 就绪 — ${d.reason}`
    : `✗ ${d.status} — ${d.reason}`;
  box.appendChild(header);

  // Config summary
  const configGrid = document.createElement("div");
  configGrid.className = "status-grid";
  configGrid.style.gridTemplateColumns = "1fr 1fr";
  const addMetric = (label, value) => {
    const item = document.createElement("div");
    item.className = "status-item";
    item.innerHTML = `<div class="status-label">${label}</div><div class="status-value">${value}</div>`;
    configGrid.appendChild(item);
  };
  addMetric("consumer_enabled", data.consumer_enabled ? "true" : "false");
  addMetric("whitelist", data.whitelist_users.length > 0 ? data.whitelist_users.join(", ") : "空（子系统关闭）");
  addMetric("whitelist_match", data.whitelist_match ? "✓ 匹配" : "✗ 不匹配");
  addMetric("expected_candidates", d.expected_candidates || 0);
  box.appendChild(configGrid);

  // Intent info
  if (intent) {
    const intentBox = document.createElement("div");
    intentBox.style.marginTop = "8px";
    intentBox.innerHTML = `<div class="status-label">下一条待消费 intent</div>` +
      `<div class="small">id=${intent.id} | user=${intent.user_id} | fragments=${intent.fragments_count} | ${intent.created_at}</div>`;
    box.appendChild(intentBox);

    // fragments preview
    const preview = data.fragments_preview || [];
    if (preview.length > 0) {
      const previewBox = document.createElement("div");
      previewBox.style.marginTop = "4px";
      previewBox.style.paddingLeft = "8px";
      previewBox.style.borderLeft = "2px solid var(--milk-muted)";
      for (const frag of preview) {
        const line = document.createElement("div");
        line.className = "small";
        line.style.color = "var(--milk-muted)";
        line.textContent = `「${frag}」`;
        previewBox.appendChild(line);
      }
      box.appendChild(previewBox);
    }
  }

  // Target info
  if (target) {
    const targetBox = document.createElement("div");
    targetBox.style.marginTop = "6px";
    targetBox.innerHTML = `<div class="status-label">Target 查找</div>` +
      `<div class="small">platform=${target.platform} | session=${target.session_id} | found=${target.found} | real_user_id=${target.real_user_id_masked || "无"}</div>`;
    box.appendChild(targetBox);
  }

  // Rules
  if (Object.keys(rules).length > 0) {
    const rulesBox = document.createElement("div");
    rulesBox.style.marginTop = "6px";
    rulesBox.innerHTML = `<div class="status-label">漏斗规则</div>` +
      `<div class="small">` +
      `cooldown=${rules.hard_cooldown_active} | ` +
      `failure_pause=${rules.failure_pause_active} | ` +
      `active_window=${rules.within_active_window} | ` +
      `sent_today=${rules.today_sent_count}/${rules.daily_limit} | ` +
      `recent_chat=${rules.has_recent_user_message}` +
      `</div>`;
    box.appendChild(rulesBox);
  }
}

async function loadPreflight(btn) {
  const status = document.getElementById("cPreflightStatus");
  if (status) status.textContent = "加载中...";
  try {
    const data = await requestJson(
      "/debug/consciousness/phase3b/preflight",
      { headers: getAdminHeaders() },
      "预检失败："
    );
    renderPreflightResult(data);
    if (status) status.textContent = "预检完成";
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

async function enqueueTestIntent(btn) {
  const status = document.getElementById("cPreflightStatus");
  if (status) status.textContent = "插入中...";
  try {
    const data = await requestJson(
      "/debug/consciousness/phase3b/enqueue_test_intent",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({}),
      },
      "插入失败："
    );
    if (data.success && data.intent) {
      if (status) status.textContent = `已插入 intent #${data.intent.id} (${data.intent.fragments.length} fragments)`;
      await loadPreflight();
    } else {
      if (status) status.textContent = data.error || "插入失败";
    }
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

async function dropAllQueuedBrainIntents(btn) {
  const status = document.getElementById("cPreflightStatus");
  if (status) status.textContent = "清理中...";
  try {
    const data = await requestJson(
      "/debug/consciousness/phase3b/drop_all_queued_brain_intents",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({}),
      },
      "清理失败："
    );
    if (data.success) {
      if (status) status.textContent = `已清理 ${data.dropped_count} 条 queued intent`;
      await loadPreflight();
    } else {
      if (status) status.textContent = "清理失败";
    }
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

// ── Auto-refresh ──────────────────────────────────────────

// Phase 4 Living World

function shortTime(value) {
  return value ? String(value).substring(0, 16) : "-";
}

function formatNumber(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return value.toFixed(2);
}

function formatJsonInline(value) {
  if (value == null) return "-";
  if (typeof value === "string") return value || "-";
  try {
    return JSON.stringify(value);
  } catch (err) {
    return "-";
  }
}

function textOrDash(value) {
  if (value == null) return "-";
  const text = String(value).trim();
  return text || "-";
}

function formatTimePhase(value) {
  const labels = {
    early_morning: "清晨",
    forenoon: "上午",
    noon: "中午",
    afternoon: "下午",
    evening: "傍晚",
    night: "晚上",
    late_night: "深夜",
    unknown: "未知",
  };
  return labels[value] || textOrDash(value);
}

function formatPlace(place, environment) {
  const placeLabels = {
    quiet_room: "安静房间",
    home_desk: "桌前",
    bed: "床边",
  };
  const placeText = placeLabels[place] || textOrDash(place);
  const envText = environment?.summary ? ` · ${environment.summary}` : "";
  return `${placeText}${envText}`;
}

function formatResidue(residue) {
  if (!residue || typeof residue !== "object") return "没有明显余波";
  const topic = textOrDash(residue.topic);
  const mood = textOrDash(residue.mood);
  const intensity = formatNumber(residue.intensity);
  if (topic === "-" && mood === "-" && intensity === "0.00") {
    return "没有明显余波";
  }
  return `话题：${topic} · 情绪：${mood} · 强度：${intensity}`;
}

function firstLine(...values) {
  for (const value of values) {
    const text = textOrDash(value);
    if (text !== "-") return text;
  }
  return "-";
}

function formatActivity(label, rawActivity) {
  const labelText = textOrDash(label);
  const rawText = textOrDash(rawActivity);
  if (labelText === "-" && rawText === "-") return "-";
  if (labelText === rawText || rawText === "-") return labelText;
  if (labelText === "-") return rawText;
  return `${labelText} · ${rawText}`;
}

function appendDetail(row, label, value) {
  const detail = document.createElement("div");
  detail.className = "check-detail";
  detail.textContent = `${label}：${textOrDash(value)}`;
  row.appendChild(detail);
}

function renderLivingList(boxId, items, renderItem, emptyText) {
  const box = document.getElementById(boxId);
  if (!box) return;
  clearChildren(box);
  if (!items || items.length === 0) {
    box.textContent = emptyText;
    return;
  }
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "check-item";
    renderItem(row, item);
    box.appendChild(row);
  }
}

export function renderLivingWorld(data) {
  const life = data?.life || data?.state?.life || {};
  const residue = data?.life_residue || life.residue || {};
  const previewLife = data?.loop_preview?.would_update_life || null;

  setOptionalText("cLivingWhere", formatPlace(life.place, life.environment));
  setOptionalText("cLivingActivityLabel", formatActivity(life.activity_label, life.current_activity));
  setOptionalText("cLivingActivityReason", life.activity_reason || "没有新的外部刺激，维持低强度观察");
  setOptionalText("cLivingTimePhase", formatTimePhase(life.time_phase));
  setOptionalText("cLivingLifeMode", `${textOrDash(life.mode)} · ${textOrDash(life.current_activity)}`);
  setOptionalText("cLivingLifeAttention", life.attention || "-");
  setOptionalText("cLivingContinuity", life.continuity_note || "还没有形成连续生活片段");
  setOptionalText("cLivingLifeResidue", formatResidue(residue));

  const previewBox = document.getElementById("cLivingLoopPreview");
  if (previewBox) {
    clearChildren(previewBox);
    if (!data?.loop_preview) {
      previewBox.textContent = "没有请求 dry-run 预览";
    } else if (!data.loop_preview.success) {
      previewBox.textContent = `预览失败：${data.loop_preview.reason || "未知原因"}`;
    } else if (!previewLife) {
      previewBox.textContent = "预览没有返回下一轮生活状态";
    } else {
      const row = document.createElement("div");
      row.className = "check-item";
      const head = document.createElement("div");
      head.className = "check-name";
      head.textContent = `下一轮可能会：${firstLine(previewLife.activity_label, previewLife.current_activity)}`;
      row.appendChild(head);
      appendDetail(row, "地点", formatPlace(previewLife.place, previewLife.environment));
      appendDetail(row, "原因", previewLife.activity_reason);
      appendDetail(row, "连续性", previewLife.continuity_note);
      appendDetail(row, "动作", data.loop_preview.action || "would_update");
      previewBox.appendChild(row);
    }
  }

  renderLivingList("cLivingExperiences", data?.experiences || [], (row, item) => {
    const head = document.createElement("div");
    head.className = "check-name";
    head.textContent = item.content || "(空经历)";
    row.appendChild(head);
    appendDetail(row, "类型", `${item.kind || "-"} / ${item.expression_status || "-"}`);
    appendDetail(row, "来源", `${item.source || "-"} · ${shortTime(item.created_at)}`);
    appendDetail(row, "显著性", formatNumber(item.salience));
  }, "还没有沉淀经历");

  renderLivingList("cLivingReflections", data?.reflection_runs || [], (row, item) => {
    const head = document.createElement("div");
    head.className = "check-name";
    head.textContent = `${item.status || "-"} · ${shortTime(item.created_at)}`;
    row.appendChild(head);
    appendDetail(row, "输入", item.input_summary || "没有输入摘要");
    appendDetail(row, "模型", item.model_name || "deterministic");
    appendDetail(row, "输出", formatJsonInline(item.output));
  }, "还没有梦境总结");

  renderLivingList("cLivingMemories", data?.long_term_memory || [], (row, item) => {
    const head = document.createElement("div");
    head.className = "check-name";
    head.textContent = item.content || "(空记忆)";
    row.appendChild(head);
    appendDetail(row, "主题", item.subject || "-");
    appendDetail(row, "显著性", formatNumber(item.salience));
    appendDetail(row, "标签", (item.tags || []).join(", ") || "-");
  }, "还没有长期记忆影响");

  setOptionalText("cLivingWorldStatus", data?.success ? "已加载（只读）" : "加载失败");
}

export async function loadLivingWorld() {
  const token = getAdminHeaders()["X-Admin-Token"];
  if (!token) return;

  try {
    setOptionalText("cLivingWorldStatus", "加载中...");
    const data = await requestJson(
      "/debug/consciousness/living-world?dry_run=true",
      { method: "GET", headers: getAdminHeaders() },
      "加载 Living World 失败："
    );
    renderLivingWorld(data);
  } catch (err) {
    setOptionalText("cLivingWorldStatus", err.message);
  }
}

function ensureWorldPanel() {
  const workspace = document.getElementById("worldWorkspace");
  const viewport = document.getElementById("worldViewport");
  const strip = document.getElementById("worldRoomStrip");
  return Boolean(workspace && viewport && strip);
}

function setWorldText(id, value, fallback = "—") {
  const element = document.getElementById(id);
  if (element) element.textContent = value == null || value === "" ? fallback : String(value);
}

const THREAD_ICON = { loss: "💔", goal: "🎯", residue: "🌫️" };

// 「心里还挂着」：把跨天牵挂渲染成带强度条的列表（intensity / 惦记天数 / 心情）
function renderWorldThreads(threads) {
  const list = document.getElementById("worldThreadList");
  if (!list) return;
  const active = (Array.isArray(threads) ? threads : [])
    .filter((t) => t && !t.resolved)
    .sort((a, b) => (Number(b.intensity) || 0) - (Number(a.intensity) || 0))
    .slice(0, 5);
  list.innerHTML = "";
  if (!active.length) {
    const empty = document.createElement("div");
    empty.className = "world-thread-empty";
    empty.textContent = "此刻没有特别惦记的事";
    list.appendChild(empty);
    return;
  }
  for (const t of active) {
    const row = document.createElement("div");
    row.className = `world-thread-item kind-${t.kind || "residue"}`;

    const icon = document.createElement("span");
    icon.className = "thread-icon";
    icon.textContent = THREAD_ICON[t.kind] || "🌫️";
    row.appendChild(icon);

    const topic = document.createElement("span");
    topic.className = "thread-topic";
    topic.textContent = t.topic || "";
    row.appendChild(topic);

    const filled = Math.max(1, Math.min(4, Math.round((Number(t.intensity) || 0) * 4)));
    const bar = document.createElement("span");
    bar.className = "thread-bar";
    bar.textContent = "●".repeat(filled) + "○".repeat(4 - filled);
    bar.title = `惦记强度 ${(Number(t.intensity) || 0).toFixed(2)}`;
    row.appendChild(bar);

    const meta = document.createElement("span");
    meta.className = "thread-meta";
    if (t.kind === "goal" && Number(t.carry) > 0) meta.textContent = `惦记 ${t.carry} 天`;
    else if (t.mood) meta.textContent = t.mood;
    if (meta.textContent) row.appendChild(meta);

    list.appendChild(row);
  }
}

function renderWorldPlan(items) {
  const list = document.getElementById("worldPlan");
  if (!list) return;
  clearChildren(list);
  if (!items.length) {
    const item = document.createElement("li");
    item.textContent = "今天还没有明确计划";
    list.appendChild(item);
    return;
  }
  for (const plan of items) {
    const item = document.createElement("li");
    item.classList.toggle("done", Boolean(plan.done));
    item.textContent = plan.intent || plan.phase || "未命名计划";
    list.appendChild(item);
  }
}

function renderWorldTimeline(state) {
  const timeline = document.getElementById("worldTimeline");
  if (!timeline) return;
  clearChildren(timeline);
  const recent = state.recent.slice(-5);
  for (const activity of recent) {
    const item = document.createElement("div");
    item.className = "world-moment";
    const time = document.createElement("time");
    time.textContent = activity.ago_min != null ? `${activity.ago_min} 分钟前` : "此前";
    item.append(time, document.createTextNode(actionLabel(activity.action)));
    timeline.appendChild(item);
  }
  const current = document.createElement("div");
  current.className = "world-moment current";
  current.id = "worldCurrentMoment";
  const time = document.createElement("time");
  time.textContent = state.time;
  current.append(time, document.createTextNode(state.moment));
  timeline.appendChild(current);
}

function characterBottom(state) {
  if (!state.anchor) return "4.5%";
  const normalized = typeof state.y === "number" && Number.isFinite(state.y) ? state.y : 0.50;
  return `${Math.max(9, Math.min(24, normalized * 34 - 4)).toFixed(2)}%`;
}

function applyWorldLight(state) {
  const viewport = document.getElementById("worldViewport");
  if (viewport && state.daylight) {
    viewport.dataset.dayPhase = state.daylight.phase;
  }

  const daylight = document.getElementById("worldDaylight");
  if (daylight && state.daylight) {
    daylight.style.background = state.daylight.color;
    daylight.style.opacity = String(state.daylight.opacity);
    daylight.style.mixBlendMode = state.daylight.blend;
  }

  const lampGlow = document.getElementById("worldLampGlow");
  if (lampGlow) {
    const hasActiveLight = state.activeLights.includes(state.roomKey);
    lampGlow.classList.toggle("on", hasActiveLight);
  }

  const nightPhases = new Set(["deep_night", "evening", "late_night"]);
  document.getElementById("worldCityLights")?.classList.toggle(
    "on",
    nightPhases.has(state.daylight?.phase)
  );
  document.getElementById("worldAirMotion")?.classList.add("on");
}

function layoutWorldStage(state, animate) {
  const viewport = document.getElementById("worldViewport");
  const strip = document.getElementById("worldRoomStrip");
  const neno = document.getElementById("worldNeno");
  if (!viewport || !strip || !neno) return;

  _worldRoomWidth = Math.max(620, viewport.clientWidth * 0.88);
  const rooms = [...document.querySelectorAll("[data-world-room]")];
  rooms.forEach((room) => {
    room.style.width = `${_worldRoomWidth}px`;
    room.classList.toggle("active", room.dataset.worldRoom === state.roomKey);
  });
  strip.style.width = `${_worldRoomWidth * ROOM_ORDER.length}px`;

  const worldX = state.room * _worldRoomWidth + state.x * _worldRoomWidth;
  neno.className = "world-neno";
  if (_lastWorldX != null && worldX < _lastWorldX) neno.classList.add("face-left");
  if (animate && state.walk) {
    neno.classList.add("walking");
    window.setTimeout(() => neno.classList.remove("walking"), 1750);
  }
  if (state.pose === "reading") neno.classList.add("reading");
  if (state.pose === "sleeping") neno.classList.add("sleeping");
  if (state.anchor) neno.classList.add("anchored");
  neno.style.left = `${worldX}px`;
  neno.style.bottom = characterBottom(state);

  const worldWidth = _worldRoomWidth * ROOM_ORDER.length;
  // 镜头中心：手动 focus 时摇到目标房间，否则跟着她
  const camX = focusRoomIndex(state) * _worldRoomWidth + 0.5 * _worldRoomWidth;
  const camera = Math.max(
    -(worldWidth - viewport.clientWidth),
    Math.min(0, -(camX - viewport.clientWidth / 2))
  );
  strip.style.transform = `translateX(${camera}px)`;
  _lastWorldX = worldX;

  // minimap 高亮：手动 focus 时标在镜头所在房间，否则标她所在
  const mapKey = _worldFocus ? ROOM_ORDER[focusRoomIndex(state)] : state.roomKey;
  document.querySelectorAll("[data-world-map-room]").forEach((cell) => {
    cell.classList.toggle("active", cell.dataset.worldMapRoom === mapKey);
  });
  applyWorldLight(state);
}

export function renderWorldLive(data) {
  if (!ensureWorldPanel()) return;
  if (!data || data.success === false || !data.world) {
    setWorldText("cWorldLiveStatus", data?.reason || "世界引擎暂无数据。可检查 Admin Token，或点击“走一步”。");
    setWorldText("worldRuntimeStatus", "世界状态不可用");
    return;
  }

  const state = mapWorldSnapshot(data.world);
  _latestWorldState = state;
  layoutWorldStage(state, true);
  setWorldText("worldClock", state.time);
  setWorldText("worldPhase", state.phase || (state.sleeping ? "睡眠中" : "生活进行中"));
  setWorldText("worldStoryTime", `${state.phase || "此刻"} ${state.time} · ${ROOM_NAME[state.roomKey] || state.roomKey}`);
  // 刀③：她在外面时，舞台标题/标签/场景按钮跟着切，别再显示「家」
  setWorldText("worldSceneTitle", state.outside ? (ROOM_NAME[state.roomKey] || state.roomKey) : "Neno 的家");
  setWorldText("worldSceneTag", state.outside ? "场景 · 在外面" : "场景 · Neno 的家");
  // 按钮高亮：手动摇镜头时跟 focus，否则跟她真实所在
  const showingOutside = _worldFocus ? _worldFocus === "outside" : state.outside;
  document.getElementById("worldSceneHomeBtn")?.classList.toggle("active", !showingOutside);
  document.getElementById("worldSceneOutBtn")?.classList.toggle("active", showingOutside);
  setWorldText("worldStoryAction", state.action);
  setWorldText("worldStoryInner", state.inner ? `“${state.inner}”` : "她没有解释，只是继续做手上的事。");
  setWorldText("worldMoodText", `${state.mood} · ${Number(state.moodValence).toFixed(2)}`);
  setWorldText("worldEnergy", state.energy);
  setWorldText("worldMoney", `¥${state.money}`);
  setWorldText("worldEnergyStatus", state.energyStatus);
  setWorldText("worldChange", state.change || "世界暂时没有新的变化。");
  setWorldText("worldPendingThread", state.plan.filter((item) => !item.done).map((item) => item.intent).filter(Boolean).join("；") || "暂无");
  renderWorldThreads(state.threads);
  setWorldText("worldChronicleRange", `今天 · ${state.time}`);
  setWorldText("worldRuntimeStatus", data.loop_enabled ? "世界循环运行中" : "常驻循环关闭 · 可手动推进");
  setWorldText("cWorldLiveStatus", data.loop_enabled ? "每 5 秒读取真实世界状态。" : "常驻循环未开启；当前显示数据库快照，可手动推进。");

  const thought = document.getElementById("worldThought");
  if (thought) {
    thought.textContent = state.wake ? `💭 ${state.thought}` : state.thought;
    thought.classList.toggle("is-thinking", state.wake);
    thought.classList.add("on");
    window.setTimeout(() => thought.classList.remove("on"), 2200);
  }
  // 💭 正在想：wake=true 那一拍点亮她头顶的思考标记 + 压力条
  document.getElementById("worldNeno")?.classList.toggle("is-thinking", state.wake);
  const pBar = document.getElementById("worldPressureFill");
  if (pBar) {
    const pct = Math.max(0, Math.min(100, Number(state.pressure) || 0));
    pBar.style.width = `${pct}%`;
  }
  // 旧的单点厨房蒸汽改由反应式物品层接管（见 renderWorldObjects），这里不再单独开
  document.getElementById("worldSteam")?.classList.remove("on");
  renderWorldObjects(state);
  renderWorldPlan(state.plan);
  renderWorldTimeline(state);
}

// ── 反应式物品层：每个房间按快照里物品的 state 画出/更新物品，状态变了给点手感 ──
const _objPrevState = {};
let _editMode = false;        // 摆放编辑模式：物品可拖、未定位的进托盘、可导出坐标
let _slots = null;            // 工作中的 slot 配置（初始从 OBJECT_SLOTS 克隆，拖动后更新）
let _drag = null;             // 拖动中：{room, key, el}

function ensureSlots() {
  if (!_slots) _slots = JSON.parse(JSON.stringify(OBJECT_SLOTS));
  return _slots;
}

function renderWorldObjects(state) {
  ensureSlots();
  const rooms = state.rooms || {};
  for (const room of Object.keys(rooms)) {
    const roomEl = document.querySelector(`[data-world-room="${room}"]`);
    if (!roomEl) continue;
    let layer = roomEl.querySelector(".world-obj-layer");
    if (!layer) {
      layer = document.createElement("div");
      layer.className = "world-obj-layer";
      roomEl.appendChild(layer);
    }
    layer.classList.toggle("editing", _editMode);
    const objs = rooms[room]?.objects || [];
    const auto = autoLayout(objs);                 // 自动布局打底
    const overrides = _slots[room] || {};          // 手摆/拖动覆盖
    const present = new Set(objs.map((o) => o.key));
    for (const o of objs) {
      const key = o.key;
      const slot = overrides[key] || auto[key] || { x: 50, y: 60, size: 22 };
      const fx = objectFx(key, o.state);
      let el = layer.querySelector(`[data-obj="${key}"]`);
      if (!el) {
        el = document.createElement("div");
        el.className = "world-object";
        el.dataset.obj = key;
        el.dataset.room = room;
        const idleName = slot.idle || "breathe";  // 默认都呼吸，让场景整体"活着"
        const delay = ([...key].reduce((a, c) => a + c.charCodeAt(0), 0) % 24) / 10;  // 错开节奏
        el.innerHTML = `<span class="wo-juice"><span class="wo-idle wo-${idleName}" style="animation-delay:${delay}s"><span class="wo-steam"></span><span class="wo-glyph"></span></span><span class="wo-tag"></span></span>`;
        el.addEventListener("pointerdown", onObjPointerDown);
        layer.appendChild(el);
      }
      el.style.left = `${slot.x}%`;
      el.style.top = `${slot.y}%`;
      el.style.fontSize = `${slot.size || 22}px`;
      const glyph = el.querySelector(".wo-glyph");
      glyph.textContent = fx.emoji || o.emoji || "";
      glyph.style.transform = fx.tip ? "rotate(72deg) translateY(4px)" : "rotate(0)";
      el.style.opacity = fx.dim && !_editMode ? "0.5" : "1";
      el.querySelector(".wo-tag").textContent = _editMode ? key : "";
      el.querySelector(".wo-steam").innerHTML = fx.steam ? "<i></i><i></i><i></i>" : "";
      // 状态变了 → 弹一下（juice），让"她操作了"有反馈
      const pk = `${room}.${key}`;
      if (!_editMode && _objPrevState[pk] !== undefined && _objPrevState[pk] !== o.state) {
        const j = el.querySelector(".wo-juice");
        j.classList.remove("wo-bump");
        void j.offsetWidth;
        j.classList.add("wo-bump");
      }
      _objPrevState[pk] = o.state;
    }
    // 清理已消失（被扔掉）的物品
    layer.querySelectorAll(".world-object").forEach((el) => {
      if (!present.has(el.dataset.obj)) el.remove();
    });
  }
}

// ── 摆放编辑器：拖物品定位 + 导出坐标 ──
function onObjPointerDown(e) {
  if (!_editMode) return;
  e.preventDefault();
  const el = e.currentTarget;
  _drag = { room: el.dataset.room, key: el.dataset.obj, el };
  el.setPointerCapture(e.pointerId);
  el.addEventListener("pointermove", onObjPointerMove);
  el.addEventListener("pointerup", onObjPointerUp);
}
function onObjPointerMove(e) {
  if (!_drag) return;
  const roomEl = _drag.el.closest("[data-world-room]");
  const r = roomEl.getBoundingClientRect();
  const x = Math.max(0, Math.min(100, ((e.clientX - r.left) / r.width) * 100));
  const y = Math.max(0, Math.min(100, ((e.clientY - r.top) / r.height) * 100));
  _slots[_drag.room][_drag.key].x = Math.round(x * 10) / 10;
  _slots[_drag.room][_drag.key].y = Math.round(y * 10) / 10;
  _drag.el.style.left = `${x}%`;
  _drag.el.style.top = `${y}%`;
}
function onObjPointerUp(e) {
  if (!_drag) return;
  _drag.el.removeEventListener("pointermove", onObjPointerMove);
  _drag.el.removeEventListener("pointerup", onObjPointerUp);
  _drag = null;
}
function toggleWorldEdit() {
  _editMode = !_editMode;
  document.getElementById("worldEditBtn")?.classList.toggle("active", _editMode);
  document.getElementById("worldEditExport")?.style.setProperty("display", _editMode ? "inline-flex" : "none");
  if (_latestWorldState) renderWorldObjects(_latestWorldState);
}
function exportWorldSlots() {
  ensureSlots();
  const text = "export const OBJECT_SLOTS = " + JSON.stringify(_slots, null, 2) + ";";
  navigator.clipboard?.writeText(text).then(
    () => setWorldText("cWorldLiveStatus", "已复制 OBJECT_SLOTS 到剪贴板，贴给我即可"),
    () => {}
  );
  console.log(text);
}

export async function loadWorldLive() {
  const token = getAdminHeaders()["X-Admin-Token"];
  if (!token) return;
  try {
    const data = await requestJson(
      "/debug/consciousness/world-live",
      { method: "GET", headers: getAdminHeaders() },
      "加载世界失败："
    );
    renderWorldLive(data);
  } catch (err) {
    setOptionalText("cWorldLiveStatus", `· ${err.message}`);
  }
}

async function worldTickOnce(btn, wake = false) {
  const label = wake ? "叫醒她" : "走一步";
  if (btn) { btn.disabled = true; btn.textContent = wake ? "叫醒中..." : "推进中..."; }
  try {
    const data = await requestJson(
      "/debug/consciousness/world-tick" + (wake ? "?force=wake" : ""),
      { method: "POST", headers: getAdminHeaders() },
      wake ? "叫醒失败：" : "推进世界失败："
    );
    if (data?.world) renderWorldLive({ success: true, world: data.world, loop_enabled: data.loop_enabled });
    else await loadWorldLive();
  } catch (err) {
    setWorldText("cWorldLiveStatus", err.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}

function startWorldLiveRefresh() {
  stopWorldLiveRefresh();
  loadWorldLive();
  _worldLiveInterval = window.setInterval(() => {
    if (!document.getElementById("worldWorkspace")?.classList.contains("workspace-hidden")) {
      loadWorldLive();
    }
  }, 5000);
}

function stopWorldLiveRefresh() {
  if (_worldLiveInterval) {
    window.clearInterval(_worldLiveInterval);
    _worldLiveInterval = null;
  }
}


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
  loadLivingWorld();
  startDesireRefresh();
}

export function onConsciousnessPanelInactive() {
  stopDesireRefresh();
}

// ── Bind ──────────────────────────────────────────────────

// 总览「她此刻」桥接卡：拉 world-live 填一瞥（点击跳世界引擎）
async function loadOverviewBridge() {
  if (!document.getElementById("overviewBridgeCard")) return;
  if (!getAdminHeaders()["X-Admin-Token"]) return;
  try {
    const data = await requestJson(
      "/debug/consciousness/world-live",
      { method: "GET", headers: getAdminHeaders() },
      ""
    );
    const w = data?.world;
    if (!w) return;
    const last = w.last || {};
    const sleeping = last.sleeping || w.energy_status === "sleeping";
    setWorldText("overviewBridgeLine",
      `${ROOM_NAME[w.location] || w.location || "—"} · ${sleeping ? "睡眠中" : "清醒"} · ${w.sim_time || "--:--"}`);
    setWorldText("overviewBridgeEnergy", Math.round(Number(w.energy) || 0));
    setWorldText("overviewBridgeMood", w.mood || "—");
    setWorldText("overviewBridgePressure", last.pressure != null ? last.pressure : "—");
  } catch (err) {
    // 静默：桥接卡非关键
  }
}

export function bindConsciousnessEvents() {
  const injectBtn = document.getElementById("cInjectBtn");
  if (injectBtn) {
    injectBtn.addEventListener("click", () => submitInjectEvent(injectBtn));
  }

  const thinkBtn = document.getElementById("cThinkBtn");
  if (thinkBtn) {
    thinkBtn.addEventListener("click", () => submitThinkCycle(thinkBtn));
  }

  const preflightBtn = document.getElementById("cPreflightBtn");
  if (preflightBtn) {
    preflightBtn.addEventListener("click", () => loadPreflight(preflightBtn));
  }

  const enqueueBtn = document.getElementById("cEnqueueTestBtn");
  if (enqueueBtn) {
    enqueueBtn.addEventListener("click", () => enqueueTestIntent(enqueueBtn));
  }

  const dropBtn = document.getElementById("cDropQueuedBtn");
  if (dropBtn) {
    dropBtn.addEventListener("click", () => dropAllQueuedBrainIntents(dropBtn));
  }

  const refreshBtn = document.getElementById("cRefreshStateBtn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      loadConsciousnessState();
      loadConsciousnessEvents();
      loadLivingWorld();
      loadWorldLive();
    });
  }

  const livingRefreshBtn = document.getElementById("cLivingWorldRefreshBtn");
  if (livingRefreshBtn) {
    livingRefreshBtn.addEventListener("click", () => loadLivingWorld());
  }

  const worldStepBtn = document.getElementById("cWorldStepBtn");
  if (worldStepBtn && !worldStepBtn.dataset.bound) {
    worldStepBtn.dataset.bound = "true";
    worldStepBtn.addEventListener("click", () => worldTickOnce(worldStepBtn));
  }
  const worldWakeBtn = document.getElementById("cWorldWakeBtn");
  if (worldWakeBtn && !worldWakeBtn.dataset.bound) {
    worldWakeBtn.dataset.bound = "true";
    worldWakeBtn.addEventListener("click", () => worldTickOnce(worldWakeBtn, true));
  }

  // 场景按钮：手动把镜头摇到家内 / 外面；再点同一个回到跟随她
  const sceneHomeBtn = document.getElementById("worldSceneHomeBtn");
  if (sceneHomeBtn && !sceneHomeBtn.dataset.bound) {
    sceneHomeBtn.dataset.bound = "true";
    sceneHomeBtn.addEventListener("click", () => setWorldFocus("home"));
  }
  const sceneOutBtn = document.getElementById("worldSceneOutBtn");
  if (sceneOutBtn && !sceneOutBtn.dataset.bound) {
    sceneOutBtn.dataset.bound = "true";
    sceneOutBtn.addEventListener("click", () => setWorldFocus("outside"));
  }

  // 摆放编辑器开关 + 导出
  const editBtn = document.getElementById("worldEditBtn");
  if (editBtn && !editBtn.dataset.bound) {
    editBtn.dataset.bound = "true";
    editBtn.addEventListener("click", () => toggleWorldEdit());
  }
  const exportBtn = document.getElementById("worldEditExport");
  if (exportBtn && !exportBtn.dataset.bound) {
    exportBtn.dataset.bound = "true";
    exportBtn.addEventListener("click", () => exportWorldSlots());
  }

  // 总览桥接卡：载入一次 + 总览激活时每 6s 刷新
  loadOverviewBridge();
  window.setInterval(() => {
    if (document.getElementById("overviewPanel")?.classList.contains("active")) loadOverviewBridge();
  }, 6000);

  window.addEventListener("resize", () => {
    if (_latestWorldState) layoutWorldStage(_latestWorldState, false);
  });
  window.addEventListener("neno:workspace-change", (event) => {
    if (event.detail?.workspace === "world") {
      if (_latestWorldState) layoutWorldStage(_latestWorldState, false);
      startWorldLiveRefresh();
    } else {
      stopWorldLiveRefresh();
    }
  });

  if (ensureWorldPanel()) {
    startWorldLiveRefresh();
  }
}
