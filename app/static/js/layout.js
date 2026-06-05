import { createElement, setOptionalText } from "./dom.js";

export const panelDefinitions = [
  ["overviewPanel", "总览"],
  ["chatPanel", "聊天测试"],
  ["consciousnessPanel", "意识面板"],
  ["proactivePanel", "主动消息"],
  ["memoryPanel", "记忆库"],
  ["configPanel", "配置"],
  ["debugPanel", "日志 / 调试"],
];

export function getCardByElementId(id) {
  return document.getElementById(id)?.closest(".card") || null;
}

export function createPanel(id, title, subtitle) {
  const panel = createElement("section", "console-panel");
  panel.id = id;

  const header = createElement("div", "panel-header");
  const textBox = createElement("div");
  textBox.append(
    createElement("div", "panel-title", title),
    createElement("div", "panel-subtitle", subtitle)
  );
  header.appendChild(textBox);
  panel.appendChild(header);

  return { panel, header };
}

let _panelActivateCallbacks = {};

export function onPanelActivate(panelId, callback) {
  _panelActivateCallbacks[panelId] = callback;
}

export function setActivePanel(panelId) {
  const prev = document.querySelector(".console-panel.active");
  const prevId = prev?.id;

  for (const panel of document.querySelectorAll(".console-panel")) {
    panel.classList.toggle("active", panel.id === panelId);
  }
  for (const button of document.querySelectorAll(".console-nav [data-panel-target]")) {
    button.classList.toggle("active", button.dataset.panelTarget === panelId);
  }
  const isChatPanel = panelId === "chatPanel";
  document.body.classList.toggle("chat-panel-active", isChatPanel);
  document.querySelector(".app")?.classList.toggle("chat-panel-active", isChatPanel);

  if (prevId && prevId !== panelId && _panelActivateCallbacks[`${prevId}:deactivate`]) {
    _panelActivateCallbacks[`${prevId}:deactivate`]();
  }
  if (_panelActivateCallbacks[`${panelId}:activate`]) {
    _panelActivateCallbacks[`${panelId}:activate`]();
  }
}

export function appendStatusMetric(grid, label, id) {
  const item = createElement("div", "status-item");
  item.append(
    createElement("div", "status-label", label),
    createElement("div", "status-value", "-")
  );
  item.lastChild.id = id;
  grid.appendChild(item);
}

function addButtonClasses(button, ...classes) {
  if (button) {
    button.classList.add(...classes);
  }
}

function createProactiveSectionNav() {
  const nav = createElement("div", "proactive-section-nav");
  for (const label of ["测试区", "自动区", "候选", "目标", "时间线", "配置", "诊断"]) {
    nav.appendChild(createElement("span", "", label));
  }
  return nav;
}

function createPlatformFilter(id) {
  const wrap = createElement("div", "config-field");
  wrap.appendChild(createElement("label", "", "平台筛选"));
  const select = createElement("select");
  select.id = id;
  for (const [value, label] of [["", "全部"], ["qq", "QQ"], ["wx", "WX"]]) {
    const option = createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }
  wrap.appendChild(select);
  return wrap;
}

export function buildProactivePanel(panel, header) {
  const proactiveCard = getCardByElementId("proactiveCandidateList");
  const statusNode = document.getElementById("proactiveCandidateStatus");
  const refreshButton = document.getElementById("loadProactiveCandidatesBtn");
  const refreshTargetsButton = document.getElementById("loadProactiveTargetsBtn");
  const refreshEventsButton = document.getElementById("loadProactiveEventsBtn");
  const generateButton = document.getElementById("generateProactiveCandidateBtn");
  const generateTestButton = document.getElementById("generateProactiveTestCandidateBtn");
  const forceGenerateTestButton = document.getElementById("forceGenerateProactiveTestCandidateBtn");
  const platformForm = document.getElementById("proactivePlatformSelect")?.closest(".config-form");
  const autoStatus = document.getElementById("proactiveAutoStatus");
  const pendingList = document.getElementById("proactiveCandidateList");
  const configDetails = document.querySelector(".config-panel");

  addButtonClasses(refreshButton, "secondary", "auxiliary");
  addButtonClasses(refreshTargetsButton, "secondary", "auxiliary");
  addButtonClasses(refreshEventsButton, "secondary", "auxiliary");
  addButtonClasses(generateButton, "secondary");
  addButtonClasses(forceGenerateTestButton, "secondary");

  header.appendChild(createProactiveSectionNav());

  if (refreshButton) {
    const actions = createElement("div", "row");
    actions.appendChild(refreshButton);
    header.appendChild(actions);
  }

  if (statusNode) {
    statusNode.classList.add("panel-status");
    panel.appendChild(statusNode);
  }

  const grid = createElement("div", "console-grid");
  panel.appendChild(grid);

  const testCard = createElement("div", "card");
  testCard.appendChild(createElement("h3", "", "测试区"));
  testCard.appendChild(createElement(
    "div",
    "config-help",
    "用于手动测试：生成 pending 候选，不受随机概率、最近聊天、时间窗影响，不会自动发送。QQ 仍检查 allowed/hash；WX 仍检查真实目标与权限。"
  ));
  const testRow = createElement("div", "row");
  if (generateTestButton) {
    testRow.appendChild(generateTestButton);
  }
  if (forceGenerateTestButton) {
    testRow.appendChild(forceGenerateTestButton);
  }
  testCard.appendChild(testRow);
  testCard.appendChild(createElement(
    "div",
    "config-help",
    "已有同平台 pending 候选时，自动调度不会继续生成；你仍可手动发送、丢弃，或强制生成测试候选。"
  ));
  grid.appendChild(testCard);

  const statusCard = createElement("div", "card");
  statusCard.appendChild(createElement("h3", "", "自动区"));
  statusCard.appendChild(createElement(
    "div",
    "config-help",
    "这里是后台自动调度规则，不等于手动测试；自动调度优先按 PROACTIVE_MODE 运行，并受硬冷却、连续失败暂停、时间窗、每日上限、最小间隔、最近聊天、随机概率、平台权限和 pending 候选保护。"
  ));
  if (autoStatus) {
    statusCard.appendChild(autoStatus);
  }
  const statusGrid = createElement("div", "status-grid");
  appendStatusMetric(statusGrid, "当前模式", "proactiveStatusMode");
  appendStatusMetric(statusGrid, "开关", "proactiveStatusEnabled");
  appendStatusMetric(statusGrid, "任务", "proactiveStatusRunning");
  appendStatusMetric(statusGrid, "今日发送", "proactiveStatusToday");
  appendStatusMetric(statusGrid, "自动真实发送", "proactiveStatusAutoSend");
  appendStatusMetric(statusGrid, "自动 dry_run", "proactiveStatusAutoDryRun");
  appendStatusMetric(statusGrid, "自动发送今日", "proactiveStatusAutoSentToday");
  appendStatusMetric(statusGrid, "硬冷却", "proactiveStatusHardCooldown");
  appendStatusMetric(statusGrid, "连续失败", "proactiveStatusFailurePause");
  appendStatusMetric(statusGrid, "目标 allowed", "proactiveStatusAutoRequireAllowed");
  appendStatusMetric(statusGrid, "当前判断平台", "proactiveStatusDecisionPlatform");
  appendStatusMetric(statusGrid, "当前判断目标", "proactiveStatusDecisionTarget");
  appendStatusMetric(statusGrid, "最近目标", "proactiveStatusLatestTargets");
  appendStatusMetric(statusGrid, "最近发送", "proactiveStatusLastSent");
  appendStatusMetric(statusGrid, "最近检查", "proactiveStatusLastCheck");
  statusCard.appendChild(statusGrid);
  statusCard.appendChild(createElement("div", "small", "上次检查结果：-"));
  statusCard.lastChild.id = "proactiveLastResult";
  statusCard.appendChild(createElement("div", "small", "规则摘要未加载"));
  statusCard.lastChild.id = "proactiveRulesSummary";
  grid.appendChild(statusCard);

  const runOnceCard = createElement("div", "card");
  runOnceCard.appendChild(createElement("h3", "", "手动执行自动调度"));
  runOnceCard.appendChild(createElement(
    "div",
    "config-help",
    "这是手动触发自动调度流程，用于测试；默认不会真实发送，可能命中 QQ 或 WX。"
  ));
  const runOnceForm = createElement("div", "config-form");
  for (const option of [
    ["proactiveRunIgnoreRandomInput", "忽略随机概率", true],
    ["proactiveRunIgnoreRecentChatInput", "忽略最近聊天", false],
    ["proactiveRunIgnoreActiveWindowInput", "忽略时间窗", false],
    ["proactiveRunForceInput", "强制生成", false],
    ["proactiveRunDryRunOnlyInput", "只 dry_run，不真实发送", true],
  ]) {
    const label = createElement("label");
    const input = createElement("input");
    input.type = "checkbox";
    input.id = option[0];
    input.checked = option[2];
    label.append(input, ` ${option[1]}`);
    runOnceForm.appendChild(label);
  }
  const runOnceRow = createElement("div", "row");
  runOnceRow.appendChild(createElement("button", "", "执行一轮自动调度"));
  runOnceRow.lastChild.id = "runProactiveOnceBtn";
  runOnceCard.append(runOnceForm, runOnceRow);
  runOnceCard.appendChild(createElement("div", "small", "尚未执行"));
  runOnceCard.lastChild.id = "proactiveRunOnceResult";
  grid.appendChild(runOnceCard);

  const eventsCard = createElement("div", "card");
  eventsCard.appendChild(createElement("h3", "", "调度时间线"));
  eventsCard.appendChild(createElement("div", "config-help", "最近主动消息调度和手动操作事件；不显示完整 session_id/openid。"));
  if (refreshEventsButton) {
    const eventRow = createElement("div", "row");
    eventRow.appendChild(refreshEventsButton);
    eventRow.appendChild(createPlatformFilter("proactiveEventPlatformFilter"));
    eventsCard.appendChild(eventRow);
  }
  eventsCard.appendChild(createElement("div", "small panel-list", "还没加载"));
  eventsCard.lastChild.id = "proactiveEventList";
  grid.appendChild(eventsCard);

  const targetsCard = createElement("div", "card");
  targetsCard.appendChild(createElement("h3", "", "主动目标"));
  targetsCard.appendChild(createElement("div", "config-help", "最近 QQ / WX 私聊会自动记录为主动目标；页面不显示完整 session_id。QQ 会显示 allowed，WX 会显示真实目标是否已保存。"));
  if (refreshTargetsButton) {
    const targetRow = createElement("div", "row");
    targetRow.appendChild(refreshTargetsButton);
    targetRow.appendChild(createPlatformFilter("proactiveTargetPlatformFilter"));
    targetsCard.appendChild(targetRow);
  }
  targetsCard.appendChild(createElement("div", "small panel-list", "还没加载"));
  targetsCard.lastChild.id = "proactiveTargetList";
  grid.appendChild(targetsCard);

  const decisionCard = createElement("div", "card");
  decisionCard.appendChild(createElement("h3", "", "自动调度当前判断"));
  decisionCard.appendChild(createElement("div", "config-help", "check-now 只刷新后台自动调度判断，不会发送消息。"));
  decisionCard.appendChild(createElement("div", "status-value", "-"));
  decisionCard.lastChild.id = "proactiveCanSendNow";
  decisionCard.appendChild(createElement("div", "small", "尚未检查"));
  decisionCard.lastChild.id = "proactiveCanSendReason";
  const checkRow = createElement("div", "row");
  checkRow.appendChild(createElement("button", "", "检查现在会不会发"));
  checkRow.lastChild.id = "checkProactiveNowBtn";
  checkRow.lastChild.classList.add("secondary", "auxiliary");
  if (generateButton) {
    checkRow.appendChild(generateButton);
  }
  decisionCard.appendChild(checkRow);
  if (platformForm) {
    decisionCard.appendChild(platformForm);
  }
  decisionCard.appendChild(createElement("div", "proactive-check-grid", "还没有检查结果"));
  decisionCard.lastChild.id = "proactiveCheckNowChecks";
  grid.appendChild(decisionCard);

  const pendingCard = createElement("div", "card");
  pendingCard.appendChild(createElement("h3", "", "待处理候选 pending"));
  pendingCard.appendChild(createElement("div", "config-help", "候选支持 QQ / WX。dry_run 只验证链路；真实发送需要二次确认，成功后才写入 messages。"));
  pendingCard.appendChild(createPlatformFilter("proactiveCandidatePlatformFilter"));
  if (pendingList) {
    pendingCard.appendChild(pendingList);
  }
  grid.appendChild(pendingCard);

  const history = createElement("details", "card");
  history.appendChild(createElement("summary", "", "显示历史"));
  history.appendChild(createElement("div", "config-help", "历史记录 sent / dismissed / failed，支持 QQ / WX。"));
  history.appendChild(createElement("div", "proactive-history-list", "还没加载"));
  history.lastChild.id = "proactiveHistoryList";
  grid.appendChild(history);

  const configCard = createElement("div", "card");
  configCard.appendChild(createElement("h3", "", "自动配置"));
  if (configDetails) {
    const nodes = Array.from(configDetails.childNodes);
    for (const node of nodes) {
      if (node.nodeType === Node.ELEMENT_NODE && node.tagName === "SUMMARY") {
        node.remove();
        continue;
      }
      configCard.appendChild(node);
    }
    const form = configCard.querySelector(".config-form");
    if (form) {
      form.classList.add("proactive-config-grid");
    }
  }
  grid.appendChild(configCard);

  proactiveCard?.remove();
}

export function buildConsciousnessPanel(panel, header) {
  const grid = createElement("div", "console-grid");
  panel.appendChild(grid);

  // ── Phase 1: Body State Card ──
  const bodyCard = createElement("div", "card");
  bodyCard.appendChild(createElement("h3", "", "身体状态 (Phase 1)"));
  bodyCard.appendChild(createElement("div", "config-help", "energy/mood/desire 实时值，desire 每秒自动刷新。"));
  const refreshRow = createElement("div", "row");
  const refreshBtn = createElement("button", "secondary auxiliary", "刷新状态");
  refreshBtn.id = "cRefreshStateBtn";
  refreshRow.appendChild(refreshBtn);
  bodyCard.appendChild(refreshRow);

  const stateGrid = createElement("div", "status-grid");
  stateGrid.style.gridTemplateColumns = "1fr";
  stateGrid.style.gap = "12px";

  // Energy
  const energySection = createElement("div");
  energySection.style.border = "1px solid var(--milk-border-soft)";
  energySection.style.borderRadius = "14px";
  energySection.style.padding = "12px";
  energySection.style.background = "#fffbf7";
  const energyHead = createElement("div");
  energyHead.style.display = "flex";
  energyHead.style.justifyContent = "space-between";
  energyHead.style.alignItems = "center";
  energyHead.style.marginBottom = "6px";
  energyHead.append(
    createElement("div", "status-label", "精力 Energy"),
    createElement("div", "status-value", "-")
  );
  energyHead.lastChild.id = "cEnergyValue";
  const energyMeta = createElement("div");
  energyMeta.style.fontSize = "12px";
  energyMeta.style.color = "var(--milk-muted)";
  energyMeta.style.marginBottom = "6px";
  energyMeta.append(
    createElement("span", "", "状态: "),
    createElement("span", "", "-")
  );
  energyMeta.lastChild.id = "cEnergyStatus";
  const energyDesc = createElement("div");
  energyDesc.style.fontSize = "12px";
  energyDesc.style.color = "var(--milk-muted)";
  energyDesc.id = "cEnergyDesc";
  const energyBar = createElement("div");
  energyBar.id = "cEnergyBar";
  energySection.append(energyHead, energyMeta, energyDesc, energyBar);
  stateGrid.appendChild(energySection);

  // Mood
  const moodSection = createElement("div");
  moodSection.style.border = "1px solid var(--milk-border-soft)";
  moodSection.style.borderRadius = "14px";
  moodSection.style.padding = "12px";
  moodSection.style.background = "#fffbf7";
  const moodHead = createElement("div");
  moodHead.style.display = "flex";
  moodHead.style.justifyContent = "space-between";
  moodHead.style.alignItems = "center";
  moodHead.style.marginBottom = "6px";
  moodHead.append(
    createElement("div", "status-label", "情绪 Mood"),
    createElement("div", "status-value", "-")
  );
  moodHead.lastChild.id = "cMoodValue";
  const moodDetail = createElement("div");
  moodDetail.style.fontSize = "12px";
  moodDetail.style.color = "var(--milk-muted)";
  moodDetail.style.marginBottom = "6px";
  moodDetail.id = "cMoodDetail";
  const moodDesc = createElement("div");
  moodDesc.style.fontSize = "12px";
  moodDesc.style.color = "var(--milk-muted)";
  moodDesc.id = "cMoodDesc";
  const moodBar = createElement("div");
  moodBar.id = "cMoodBar";
  moodSection.append(moodHead, moodDetail, moodDesc, moodBar);
  stateGrid.appendChild(moodSection);

  // Desire
  const desireSection = createElement("div");
  desireSection.style.border = "1px solid var(--milk-border-soft)";
  desireSection.style.borderRadius = "14px";
  desireSection.style.padding = "12px";
  desireSection.style.background = "#fffbf7";
  const desireHead = createElement("div");
  desireHead.style.display = "flex";
  desireHead.style.justifyContent = "space-between";
  desireHead.style.alignItems = "center";
  desireHead.style.marginBottom = "6px";
  desireHead.append(
    createElement("div", "status-label", "表达欲 Desire"),
    createElement("div", "status-value", "-")
  );
  desireHead.lastChild.id = "cDesireValue";
  const desireExpress = createElement("div");
  desireExpress.style.fontSize = "12px";
  desireExpress.style.color = "var(--milk-muted)";
  desireExpress.style.marginBottom = "6px";
  desireExpress.append(
    createElement("span", "", "上次表达: "),
    createElement("span", "", "-")
  );
  desireExpress.lastChild.id = "cDesireExpress";
  const desireBar = createElement("div");
  desireBar.id = "cDesireBar";
  desireSection.append(desireHead, desireExpress, desireBar);
  stateGrid.appendChild(desireSection);

  bodyCard.appendChild(stateGrid);

  // Interaction info
  const interactGrid = createElement("div", "status-grid");
  interactGrid.style.marginTop = "10px";
  appendStatusMetric(interactGrid, "上次互动用户", "cLastUser");
  appendStatusMetric(interactGrid, "互动摘要", "cLastSummary");
  appendStatusMetric(interactGrid, "revision", "cRevision");
  appendStatusMetric(interactGrid, "updated_at", "cUpdatedAt");
  bodyCard.appendChild(interactGrid);

  bodyCard.appendChild(createElement("div", "status", ""));
  bodyCard.lastChild.id = "consciousnessStateStatus";

  // Experiences
  const expCard = createElement("div", "card");
  expCard.appendChild(createElement("h3", "", "今日经历"));
  const expBox = createElement("div", "small panel-list");
  expBox.id = "cExperiences";
  expBox.textContent = "暂无";
  expCard.appendChild(expBox);

  grid.append(bodyCard, expCard);

  // ── Phase 2: World & Events Card ──
  const worldCard = createElement("div", "card");
  worldCard.appendChild(createElement("h3", "", "世界感知 (Phase 2)"));
  worldCard.appendChild(createElement("div", "config-help", "当前天气、热搜和事件池状态。"));

  const weatherGrid = createElement("div", "status-grid");
  weatherGrid.style.gridTemplateColumns = "repeat(3, minmax(0, 1fr))";
  appendStatusMetric(weatherGrid, "天气", "cWeatherText");
  appendStatusMetric(weatherGrid, "温度", "cWeatherTemp");
  appendStatusMetric(weatherGrid, "降雨", "cWeatherRain");
  worldCard.appendChild(weatherGrid);

  const topicsLabel = createElement("div", "status-label");
  topicsLabel.style.marginTop = "10px";
  topicsLabel.textContent = "热搜";
  worldCard.appendChild(topicsLabel);
  const topicsBox = createElement("div");
  topicsBox.id = "cHotTopics";
  topicsBox.style.marginTop = "4px";
  topicsBox.textContent = "暂无";
  worldCard.appendChild(topicsBox);

  const worldMetaGrid = createElement("div", "status-grid");
  worldMetaGrid.style.marginTop = "10px";
  worldMetaGrid.style.gridTemplateColumns = "1fr 1fr";
  appendStatusMetric(worldMetaGrid, "时间感知", "cWorldTime");
  appendStatusMetric(worldMetaGrid, "感知时间", "cWorldPerception");
  worldCard.appendChild(worldMetaGrid);

  const eventsCard = createElement("div", "card");
  eventsCard.appendChild(createElement("h3", "", "事件池"));
  eventsCard.appendChild(createElement("div", "config-help", "event_log 中的 pending/consumed/expressed 事件。"));
  const eventListBox = createElement("div", "small panel-list");
  eventListBox.id = "cEventList";
  eventListBox.textContent = "暂无事件";
  eventsCard.appendChild(eventListBox);
  eventsCard.appendChild(createElement("div", "status", ""));
  eventsCard.lastChild.id = "cEventStatus";

  grid.append(worldCard, eventsCard);

  // ── Phase 3a: Think Card ──
  const thinkCard = createElement("div", "card");
  thinkCard.appendChild(createElement("h3", "", "思考过程 (Phase 3a)"));
  thinkCard.appendChild(createElement("div", "config-help", "手动注入测试事件，触发 Neno 三步决策（规则过滤 → 判断 → 生成），结果仅预览不发送。"));

  // Inject form
  const injectGroup = createElement("div");
  injectGroup.style.marginBottom = "12px";
  injectGroup.appendChild(createElement("div", "status-label", "注入测试事件"));
  const injectRow = createElement("div", "row");
  injectRow.style.gap = "6px";
  injectRow.style.alignItems = "center";

  const contentInput = createElement("input");
  contentInput.id = "cInjectContent";
  contentInput.type = "text";
  contentInput.placeholder = "输入测试事件内容，如：南宁突降暴雨";
  contentInput.style.flex = "1";
  contentInput.style.minWidth = "0";
  injectRow.appendChild(contentInput);

  const prioritySelect = createElement("select");
  prioritySelect.id = "cInjectPriority";
  for (const [val, label] of [["0", "P0 紧急"], ["1", "P1 高"], ["2", "P2 普通"], ["3", "P3 低"]]) {
    const opt = createElement("option", "", label);
    opt.value = val;
    prioritySelect.appendChild(opt);
  }
  prioritySelect.value = "2";
  injectRow.appendChild(prioritySelect);

  const injectBtn = createElement("button", "secondary", "注入");
  injectBtn.id = "cInjectBtn";
  injectRow.appendChild(injectBtn);
  injectGroup.appendChild(injectRow);
  injectGroup.appendChild(createElement("div", "status", ""));
  injectGroup.lastChild.id = "cInjectStatus";
  thinkCard.appendChild(injectGroup);

  // Think button
  const thinkRow = createElement("div", "row");
  const thinkBtn = createElement("button", "", "触发思考");
  thinkBtn.id = "cThinkBtn";
  thinkRow.appendChild(thinkBtn);
  thinkCard.appendChild(thinkRow);
  thinkCard.appendChild(createElement("div", "status", ""));
  thinkCard.lastChild.id = "cThinkStatus";

  // Result area
  const thinkResult = createElement("div");
  thinkResult.id = "cThinkResult";
  thinkResult.style.marginTop = "12px";
  thinkResult.textContent = "点击「触发思考」查看三步决策过程";
  thinkCard.appendChild(thinkResult);

  grid.appendChild(thinkCard);

  // ── Phase 3b: Preflight Card ──
  const preflightCard = createElement("div", "card");
  preflightCard.appendChild(createElement("h3", "", "Phase 3b 预检"));
  preflightCard.appendChild(createElement("div", "config-help", "只读检查 brain intent 发送链路就绪状态。不发送、不创建候选、不改状态。"));

  const preflightRow = createElement("div", "row");
  preflightRow.style.gap = "6px";
  const preflightBtn = createElement("button", "secondary", "刷新预检");
  preflightBtn.id = "cPreflightBtn";
  const enqueueBtn = createElement("button", "secondary", "插入测试 intent");
  enqueueBtn.id = "cEnqueueTestBtn";
  enqueueBtn.title = "往 proactive_intent 写入一条 queued 测试意图，不发送";
  preflightRow.append(preflightBtn, enqueueBtn);
  const dropBtn = createElement("button", "secondary", "清理所有 queued");
  dropBtn.id = "cDropQueuedBtn";
  dropBtn.title = "将所有 queued intent 标记为 dropped（不仅是测试数据）";
  preflightRow.appendChild(dropBtn);
  preflightCard.appendChild(preflightRow);

  const preflightResult = createElement("div");
  preflightResult.id = "cPreflightResult";
  preflightResult.style.marginTop = "12px";
  preflightResult.textContent = "点击「刷新预检」查看当前发送链路状态";
  preflightCard.appendChild(preflightResult);
  preflightCard.appendChild(createElement("div", "status", ""));
  preflightCard.lastChild.id = "cPreflightStatus";

  grid.appendChild(preflightCard);

  // Phase 4: Living World read-only debug view
  const livingCard = createElement("div", "card");
  livingCard.appendChild(createElement("h3", "", "Phase 4 / Living World"));
  livingCard.appendChild(createElement("div", "config-help", "Read-only SQLite view of LifeState, inner experiences, reflection runs, and long-term memories."));
  const livingRow = createElement("div", "row");
  const livingRefreshBtn = createElement("button", "secondary auxiliary", "Refresh Living World");
  livingRefreshBtn.id = "cLivingWorldRefreshBtn";
  livingRow.appendChild(livingRefreshBtn);
  livingCard.appendChild(livingRow);

  const livingStateGrid = createElement("div", "status-grid");
  livingStateGrid.style.gridTemplateColumns = "repeat(2, minmax(0, 1fr))";
  appendStatusMetric(livingStateGrid, "mode", "cLivingLifeMode");
  appendStatusMetric(livingStateGrid, "activity", "cLivingLifeActivity");
  appendStatusMetric(livingStateGrid, "attention", "cLivingLifeAttention");
  appendStatusMetric(livingStateGrid, "needs", "cLivingLifeNeeds");
  livingCard.appendChild(livingStateGrid);

  livingCard.appendChild(createElement("div", "status-label", "life residue"));
  livingCard.appendChild(createElement("div", "small panel-list", "-"));
  livingCard.lastChild.id = "cLivingLifeResidue";
  livingCard.appendChild(createElement("div", "status-label", "recent experiences"));
  livingCard.appendChild(createElement("div", "small panel-list", "Not loaded"));
  livingCard.lastChild.id = "cLivingExperiences";
  livingCard.appendChild(createElement("div", "status-label", "recent reflection runs"));
  livingCard.appendChild(createElement("div", "small panel-list", "Not loaded"));
  livingCard.lastChild.id = "cLivingReflections";
  livingCard.appendChild(createElement("div", "status-label", "recent long-term memory"));
  livingCard.appendChild(createElement("div", "small panel-list", "Not loaded"));
  livingCard.lastChild.id = "cLivingMemories";
  livingCard.appendChild(createElement("div", "status", ""));
  livingCard.lastChild.id = "cLivingWorldStatus";

  grid.appendChild(livingCard);
}

export function buildConsoleLayout() {
  const app = document.querySelector(".app");
  const chat = document.querySelector(".chat");
  const side = document.querySelector(".side");
  if (!app || !chat || !side) {
    return;
  }

  const sessionCard = getCardByElementId("sessionList");
  const configCard = getCardByElementId("configBox");
  const statsCard = getCardByElementId("statsToday");
  const proactiveCard = getCardByElementId("proactiveCandidateList");
  const relationshipCard = getCardByElementId("relationshipStatus");
  const usedMemoryCard = getCardByElementId("usedMemories");
  const chatPreviewCard = getCardByElementId("chatPreviewBox");
  const messageDebugCard = getCardByElementId("messageDebugBox");
  const sessionDebugCard = getCardByElementId("sessionDebugBox");
  const candidateCard = getCardByElementId("candidateBox");
  const memoryCard = getCardByElementId("memoryList");

  const sidebar = createElement("aside", "console-sidebar");
  const brand = createElement("div", "console-brand");
  brand.append(
    createElement("div", "console-brand-title", "Neno 控制台"),
    createElement("div", "console-brand-subtitle", "本地测试与调试")
  );
  const nav = createElement("nav", "console-nav");
  nav.setAttribute("aria-label", "Neno 测试页导航");
  for (const [panelId, label] of panelDefinitions) {
    const button = createElement("button", "", label);
    button.type = "button";
    button.dataset.panelTarget = panelId;
    button.addEventListener("click", () => setActivePanel(panelId));
    nav.appendChild(button);
  }
  sidebar.append(brand, nav);

  const main = createElement("main", "console-main");
  const overview = createPanel("overviewPanel", "总览", "运行状态、快捷入口和当前调试概况。");
  if (statsCard) {
    overview.panel.appendChild(statsCard);
  }
  const quickCard = createElement("div", "card");
  quickCard.appendChild(createElement("h3", "", "快捷入口"));
  const quickActions = createElement("div", "overview-actions");
  for (const [panelId, label] of [
    ["chatPanel", "打开聊天测试"],
    ["consciousnessPanel", "打开意识面板"],
    ["proactivePanel", "打开主动消息"],
    ["memoryPanel", "打开记忆库"],
    ["debugPanel", "打开日志 / 调试"],
  ]) {
    const button = createElement("button", "secondary", label);
    button.type = "button";
    button.dataset.panelTarget = panelId;
    button.addEventListener("click", () => setActivePanel(panelId));
    quickActions.appendChild(button);
  }
  quickCard.appendChild(quickActions);
  overview.panel.appendChild(quickCard);

  const chatPanel = createPanel("chatPanel", "聊天测试", "单页完成会话切换、历史查看、真实输入预览和调试。");
  const currentSession = createElement("div", "panel-subtitle", "当前打开 session：-");
  currentSession.id = "currentSessionStatus";
  chatPanel.header.appendChild(currentSession);
  const chatGrid = createElement("div", "console-grid two");
  chat.classList.add("console-chat");
  chatGrid.appendChild(chat);
  const chatSide = createElement("div", "console-grid chat-side-column");
  const sessionSummaryCard = createElement("div", "card");
  sessionSummaryCard.appendChild(createElement("h3", "", "当前上下文"));
  sessionSummaryCard.appendChild(createElement("div", "config-help", "右键输入消息可查看这条真实输入对应的完整模型预览。"));
  const sessionSummaryGrid = createElement("div", "status-grid session-context-grid");
  appendStatusMetric(sessionSummaryGrid, "当前 session", "currentSessionSidebarId");
  appendStatusMetric(sessionSummaryGrid, "已载入消息", "currentSessionMessageCount");
  appendStatusMetric(sessionSummaryGrid, "预览入口", "currentSessionPreviewMode");
  sessionSummaryCard.appendChild(sessionSummaryGrid);
  chatSide.appendChild(sessionSummaryCard);
  const routingCard = createElement("div", "card");
  routingCard.appendChild(createElement("h3", "", "Session Routing Control"));
  routingCard.appendChild(createElement("div", "config-help", "查询当前平台来源 routing 状态，直接设置 override 到指定 session，或 clear 恢复自动归属。只影响后续入站消息。"));
  const routingForm = createElement("div", "config-form");
  for (const [id, label, type] of [
    ["routingPlatformInput", "platform", "text"],
    ["routingAccountInput", "account_id", "text"],
    ["routingUserInput", "user_id", "text"],
    ["routingChatTypeInput", "chat_type", "text"],
    ["routingGroupInput", "group_id", "text"],
    ["routingOverrideSessionInput", "override session_id", "text"],
  ]) {
    const field = createElement("div", "config-field");
    field.appendChild(createElement("label", "", label));
    const input = createElement("input");
    input.id = id;
    input.type = type;
    if (id === "routingPlatformInput") input.placeholder = "wx";
    if (id === "routingAccountInput") input.placeholder = "default";
    if (id === "routingUserInput") input.placeholder = "通常无需手填，优先自动带入";
    if (id === "routingChatTypeInput") input.placeholder = "private / group";
    if (id === "routingGroupInput") input.placeholder = "group only";
    if (id === "routingOverrideSessionInput") input.placeholder = "wx:private:...";
    field.appendChild(input);
    if (id === "routingUserInput") {
      field.appendChild(createElement("div", "config-help", "user_id 通常不需要手填；系统会优先从当前会话最近一条平台入站消息自动带入。"));
    }
    routingForm.appendChild(field);
  }
  routingCard.appendChild(routingForm);
  const routingActions = createElement("div", "row");
  for (const [id, label, className] of [
    ["routingAutofillBtn", "带入最近平台消息", "secondary"],
    ["routingQueryBtn", "查询状态", "secondary"],
    ["routingSetBtn", "设置 Override", ""],
    ["routingClearBtn", "Clear Override", "danger"],
  ]) {
    const button = createElement("button", className, label);
    button.id = id;
    routingActions.appendChild(button);
  }
  routingCard.appendChild(routingActions);
  routingCard.appendChild(createElement("div", "status", "尚未查询"));
  routingCard.lastChild.id = "routingStatus";
  routingCard.appendChild(createElement("div", "small", "当前来源摘要：-"));
  routingCard.lastChild.id = "routingSourceSummary";
  const routingSummaryGrid = createElement("div", "status-grid session-context-grid");
  appendStatusMetric(routingSummaryGrid, "routing_key", "routingKeyValue");
  appendStatusMetric(routingSummaryGrid, "auto_session_id", "routingAutoSessionValue");
  appendStatusMetric(routingSummaryGrid, "final_session_id", "routingFinalSessionValue");
  appendStatusMetric(routingSummaryGrid, "routing_mode", "routingModeValue");
  appendStatusMetric(routingSummaryGrid, "routing_reason", "routingReasonValue");
  appendStatusMetric(routingSummaryGrid, "override active", "routingOverrideActiveValue");
  routingCard.appendChild(routingSummaryGrid);
  routingCard.appendChild(createElement("div", "small", "自动带入状态：尚未判断"));
  routingCard.lastChild.id = "routingSourceHint";
  routingCard.appendChild(createElement("div", "small", "尚无 explain"));
  routingCard.lastChild.id = "routingExplainBox";
  if (sessionCard) {
    chatSide.appendChild(sessionCard);
  }
  chatSide.appendChild(routingCard);
  if (relationshipCard) {
    chatSide.appendChild(relationshipCard);
  }
  if (chatPreviewCard) {
    chatSide.appendChild(chatPreviewCard);
  }
  if (messageDebugCard) {
    chatSide.appendChild(messageDebugCard);
  }
  if (sessionDebugCard) {
    chatSide.appendChild(sessionDebugCard);
  }
  if (usedMemoryCard) {
    chatSide.appendChild(usedMemoryCard);
  }
  if (candidateCard) {
    chatSide.appendChild(candidateCard);
  }
  chatGrid.appendChild(chatSide);
  chatPanel.panel.appendChild(chatGrid);

  const proactivePanel = createPanel("proactivePanel", "主动消息", "QQ 主动候选、自动状态和主动消息配置。");
  if (proactiveCard) {
    buildProactivePanel(proactivePanel.panel, proactivePanel.header);
  }

  const consciousnessPanel = createPanel("consciousnessPanel", "意识面板", "意识引擎实时状态、世界感知与思考过程预览。");
  buildConsciousnessPanel(consciousnessPanel.panel, consciousnessPanel.header);

  const memoryPanel = createPanel("memoryPanel", "记忆库", "查看、编辑、启用和停用记忆。");
  if (memoryCard) {
    memoryPanel.panel.appendChild(memoryCard);
  }

  const configPanel = createPanel("configPanel", "配置", "Admin Token 和模型/上下文配置。");
  if (configCard) {
    configPanel.panel.appendChild(configCard);
  }

  const debugPanel = createPanel("debugPanel", "日志 / 调试", "查看最近结构化事件、错误和 trace 链路。");
  const debugGrid = createElement("div", "console-grid");

  const diagnosisCard = createElement("div", "card");
  diagnosisCard.appendChild(createElement("h3", "", "当前诊断"));
  const diagnosisActions = createElement("div", "row");
  const refreshDiagnosisButton = createElement("button", "secondary auxiliary", "刷新诊断");
  refreshDiagnosisButton.id = "loadDebugDiagnoseBtn";
  diagnosisActions.appendChild(refreshDiagnosisButton);
  diagnosisCard.appendChild(diagnosisActions);
  diagnosisCard.appendChild(createElement("div", "diagnosis-overall info", "诊断未加载"));
  diagnosisCard.lastChild.id = "debugDiagnosisOverall";
  diagnosisCard.appendChild(createElement("div", "diagnosis-card-grid"));
  diagnosisCard.lastChild.id = "debugDiagnosisCards";
  diagnosisCard.appendChild(createElement("div", "status"));
  diagnosisCard.lastChild.id = "debugDiagnosisStatus";
  debugGrid.appendChild(diagnosisCard);

  const debugSummaryCard = createElement("div", "card");
  debugSummaryCard.appendChild(createElement("h3", "", "事件摘要"));
  const debugSummaryGrid = createElement("div", "status-grid");
  appendStatusMetric(debugSummaryGrid, "最近事件", "debugTotalReturned");
  appendStatusMetric(debugSummaryGrid, "最新时间", "debugLatestEventAt");
  appendStatusMetric(debugSummaryGrid, "错误数", "debugErrorCount");
  appendStatusMetric(debugSummaryGrid, "proactive", "debugProactiveCount");
  appendStatusMetric(debugSummaryGrid, "platform", "debugPlatformCount");
  appendStatusMetric(debugSummaryGrid, "chat", "debugChatCount");
  appendStatusMetric(debugSummaryGrid, "openrouter", "debugOpenrouterCount");
  debugSummaryCard.appendChild(debugSummaryGrid);
  debugGrid.appendChild(debugSummaryCard);

  const debugFilterCard = createElement("div", "card");
  debugFilterCard.appendChild(createElement("h3", "", "筛选"));
  const debugFilterForm = createElement("div", "config-form debug-filter-grid");
  const moduleField = createElement("div", "config-field");
  const moduleLabel = createElement("label", "", "module");
  moduleLabel.setAttribute("for", "debugModuleInput");
  const moduleSelect = createElement("select");
  moduleSelect.id = "debugModuleInput";
  for (const [value, label] of [
    ["", "全部"],
    ["platform", "platform"],
    ["chat", "chat"],
    ["openrouter", "openrouter"],
    ["proactive", "proactive"],
  ]) {
    const option = createElement("option", "", label);
    option.value = value;
    moduleSelect.appendChild(option);
  }
  moduleField.append(moduleLabel, moduleSelect);

  for (const [id, label, type, value] of [
    ["debugEventInput", "event", "text", ""],
    ["debugTraceInput", "trace_id", "text", ""],
    ["debugLimitInput", "limit", "number", "100"],
  ]) {
    const field = createElement("div", "config-field");
    const fieldLabel = createElement("label", "", label);
    fieldLabel.setAttribute("for", id);
    const input = createElement("input");
    input.id = id;
    input.type = type;
    input.value = value;
    if (id === "debugLimitInput") {
      input.min = "1";
      input.max = "300";
    }
    field.append(fieldLabel, input);
    debugFilterForm.appendChild(field);
  }
  debugFilterForm.prepend(moduleField);
  const debugActions = createElement("div", "row");
  const refreshDebugButton = createElement("button", "", "刷新日志");
  refreshDebugButton.id = "loadDebugEventsBtn";
  debugActions.appendChild(refreshDebugButton);
  debugFilterCard.append(debugFilterForm, debugActions, createElement("div", "status"));
  debugFilterCard.lastChild.id = "debugStatus";
  debugGrid.appendChild(debugFilterCard);

  const debugEventsCard = createElement("div", "card");
  debugEventsCard.appendChild(createElement("h3", "", "事件列表"));
  debugEventsCard.appendChild(createElement("div", "debug-event-list", "还没加载"));
  debugEventsCard.lastChild.id = "debugEventList";
  debugGrid.appendChild(debugEventsCard);

  debugPanel.panel.appendChild(debugGrid);

  main.append(
    overview.panel,
    chatPanel.panel,
    consciousnessPanel.panel,
    proactivePanel.panel,
    memoryPanel.panel,
    configPanel.panel,
    debugPanel.panel
  );

  side.remove();
  app.classList.add("app-shell");
  app.replaceChildren(sidebar, main);
  setActivePanel("chatPanel");
}

export function updateCurrentSessionStatus(sessionId, fallbackSessionId) {
  const value = sessionId || fallbackSessionId || "web-test";
  setOptionalText("currentSessionStatus", `当前打开 session：${value}`);
  setOptionalText("currentSessionSidebarId", value);
  setOptionalText("currentSessionPreviewMode", "右键真实消息");
}

export function updateSessionMessageCount(count) {
  setOptionalText("currentSessionMessageCount", count ?? 0);
}
