import { createElement, setOptionalText } from "./dom.js";

export const panelDefinitions = [
  ["overviewPanel", "总览"],
  ["chatPanel", "聊天测试"],
  ["proactivePanel", "主动消息"],
  ["memoryPanel", "记忆库"],
  ["relationshipPanel", "关系状态"],
  ["sessionPanel", "会话"],
  ["configPanel", "配置"],
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
    "用于手动测试：生成 pending QQ 候选，不受随机概率、最近聊天、时间窗影响，不会自动发送。仍会检查 QQ 目标存在和 QQ 白名单。"
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
    "已有 pending QQ 候选时，自动调度不会继续生成；你仍可手动发送、丢弃，或强制生成测试候选。"
  ));
  grid.appendChild(testCard);

  const statusCard = createElement("div", "card");
  statusCard.appendChild(createElement("h3", "", "自动区"));
  statusCard.appendChild(createElement(
    "div",
    "config-help",
    "这里是后台自动调度规则，不等于手动测试；自动调度仍按 enabled、时间窗、每日上限、最小间隔、最近聊天、随机概率、QQ 白名单和 pending 候选保守运行。"
  ));
  if (autoStatus) {
    statusCard.appendChild(autoStatus);
  }
  const statusGrid = createElement("div", "status-grid");
  appendStatusMetric(statusGrid, "开关", "proactiveStatusEnabled");
  appendStatusMetric(statusGrid, "任务", "proactiveStatusRunning");
  appendStatusMetric(statusGrid, "今日发送", "proactiveStatusToday");
  appendStatusMetric(statusGrid, "自动真实发送", "proactiveStatusAutoSend");
  appendStatusMetric(statusGrid, "自动 dry_run", "proactiveStatusAutoDryRun");
  appendStatusMetric(statusGrid, "自动发送今日", "proactiveStatusAutoSentToday");
  appendStatusMetric(statusGrid, "目标 allowed", "proactiveStatusAutoRequireAllowed");
  appendStatusMetric(statusGrid, "最近发送", "proactiveStatusLastSent");
  appendStatusMetric(statusGrid, "最近检查", "proactiveStatusLastCheck");
  statusCard.appendChild(statusGrid);
  statusCard.appendChild(createElement("div", "small", "上次检查结果：-"));
  statusCard.lastChild.id = "proactiveLastResult";
  statusCard.appendChild(createElement("div", "small", "规则摘要未加载"));
  statusCard.lastChild.id = "proactiveRulesSummary";
  grid.appendChild(statusCard);

  const eventsCard = createElement("div", "card");
  eventsCard.appendChild(createElement("h3", "", "调度时间线"));
  eventsCard.appendChild(createElement("div", "config-help", "最近主动消息调度和手动操作事件；不显示完整 session_id/openid。"));
  if (refreshEventsButton) {
    const eventRow = createElement("div", "row");
    eventRow.appendChild(refreshEventsButton);
    eventsCard.appendChild(eventRow);
  }
  eventsCard.appendChild(createElement("div", "small panel-list", "还没加载"));
  eventsCard.lastChild.id = "proactiveEventList";
  grid.appendChild(eventsCard);

  const targetsCard = createElement("div", "card");
  targetsCard.appendChild(createElement("h3", "", "主动目标"));
  targetsCard.appendChild(createElement("div", "config-help", "最近 QQ 私聊会自动记录为主动目标；页面不显示完整 session_id。allowed 由后端按 QQ 白名单保守标记。"));
  if (refreshTargetsButton) {
    const targetRow = createElement("div", "row");
    targetRow.appendChild(refreshTargetsButton);
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
  pendingCard.appendChild(createElement("div", "config-help", "测试发送 QQ 使用 dry_run；真实发送 QQ 需要二次确认，成功后才写入 messages。"));
  if (pendingList) {
    pendingCard.appendChild(pendingList);
  }
  grid.appendChild(pendingCard);

  const history = createElement("details", "card");
  history.appendChild(createElement("summary", "", "显示历史"));
  history.appendChild(createElement("div", "config-help", "历史记录 sent / dismissed / failed"));
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
  ]) {
    const button = createElement("button", "secondary", label);
    button.type = "button";
    button.dataset.panelTarget = panelId;
    button.addEventListener("click", () => setActivePanel(panelId));
    quickActions.appendChild(button);
  }
  quickCard.appendChild(quickActions);
  overview.panel.appendChild(quickCard);

  const chatPanel = createPanel("chatPanel", "聊天测试", "直接测试 Web 会话，并查看本轮候选记忆和命中记忆。");
  const currentSession = createElement("div", "panel-subtitle", "当前打开 session：-");
  currentSession.id = "currentSessionStatus";
  chatPanel.header.appendChild(currentSession);
  const chatGrid = createElement("div", "console-grid two");
  chat.classList.add("console-chat");
  chatGrid.appendChild(chat);
  const chatSide = createElement("div", "console-grid");
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

  const relationshipPanel = createPanel("relationshipPanel", "关系状态", "查看和调整当前 session 的关系阶段。");
  if (relationshipCard) {
    relationshipPanel.panel.appendChild(relationshipCard);
  }

  const sessionPanel = createPanel("sessionPanel", "会话", "浏览历史 session 并打开到聊天测试。");
  if (sessionCard) {
    sessionPanel.panel.appendChild(sessionCard);
  }

  const configPanel = createPanel("configPanel", "配置", "Admin Token 和模型/上下文配置。");
  if (configCard) {
    configPanel.panel.appendChild(configCard);
  }

  main.append(
    overview.panel,
    chatPanel.panel,
    proactivePanel.panel,
    memoryPanel.panel,
    relationshipPanel.panel,
    sessionPanel.panel,
    configPanel.panel
  );

  side.remove();
  app.classList.add("app-shell");
  app.replaceChildren(sidebar, main);
  setActivePanel("proactivePanel");
}

export function updateCurrentSessionStatus(sessionId, fallbackSessionId) {
  setOptionalText("currentSessionStatus", `当前打开 session：${sessionId || fallbackSessionId || "web-test"}`);
}
