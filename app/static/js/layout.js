import { createElement, setOptionalText } from "./dom.js";

export const panelDefinitions = [
  ["overviewPanel", "总览"],
  ["chatPanel", "聊天测试"],
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

export function setActivePanel(panelId) {
  for (const panel of document.querySelectorAll(".console-panel")) {
    panel.classList.toggle("active", panel.id === panelId);
  }
  for (const button of document.querySelectorAll(".console-nav [data-panel-target]")) {
    button.classList.toggle("active", button.dataset.panelTarget === panelId);
  }
  const isChatPanel = panelId === "chatPanel";
  document.body.classList.toggle("chat-panel-active", isChatPanel);
  document.querySelector(".app")?.classList.toggle("chat-panel-active", isChatPanel);
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
  if (sessionCard) {
    chatSide.appendChild(sessionCard);
  }
  if (relationshipCard) {
    chatSide.appendChild(relationshipCard);
  }
  if (chatPreviewCard) {
    chatSide.appendChild(chatPreviewCard);
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
