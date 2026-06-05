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
    });
  }

  const livingRefreshBtn = document.getElementById("cLivingWorldRefreshBtn");
  if (livingRefreshBtn) {
    livingRefreshBtn.addEventListener("click", () => loadLivingWorld());
  }
}
